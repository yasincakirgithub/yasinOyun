"""Download the FC26 player face photos so the game can serve them itself.

Why this exists
---------------
The dataset stores a CDN link per player (``player_face_url``, e.g.
``https://cdn.sofifa.net/players/209/331/26_120.png``). That CDN only answers
requests that carry a ``https://sofifa.com/`` Referer — a browser loading our
page cannot send that header cross-origin, and ``no-referrer`` requests get a
403. So the images are fetched once here, stored under
``media/player_images/<player_id>.png``, and served by
``/fcmanager/photos/<player_id>.png``.

Usage
-----
    python3 fcmanager/download_player.py                 # all players, missing only
    python3 fcmanager/download_player.py --limit 100     # quick partial run
    python3 fcmanager/download_player.py --workers 12    # more parallel requests
    python3 fcmanager/download_player.py --force         # re-download everything

The run is resumable: existing files are skipped unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import os
import sys
import threading
import time
from pathlib import Path

import requests

BASE_URL = "https://cdn.sofifa.net"

#: Same paths the Django app uses (see ``fcmanager/data.py``).
PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = Path(
    os.environ.get("FCMANAGER_PLAYER_IMAGES")
    or (PROJECT_DIR / "media" / "player_images")
)
DEFAULT_DATASET = Path(
    os.environ.get("FCMANAGER_DATASET")
    or (PROJECT_DIR / "fcmanager" / "datasets" / "FC26_20250921.csv")
)

#: The CDN is picky about headers; these mirror a real browser on sofifa.com.
HEADERS = {
    "Referer": "https://sofifa.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}

RETRY_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}

_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _local.session = session
    return session


def dataset_players(path: Path) -> list[tuple[str, str]]:
    """``[(player_id, face_url), ...]`` for every row of the FC26 CSV."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            player_id = (row.get("player_id") or "").strip()
            if not player_id.isdigit() or player_id in seen:
                continue
            seen.add(player_id)
            url = (row.get("player_face_url") or "").strip()
            rows.append((player_id, url))
    return rows


def image_url(player_id: str, *, version: str = "26", size: int = 120) -> str:
    """Build the CDN URL the same way the dataset does."""
    padded = str(player_id).zfill(6)
    return f"{BASE_URL}/players/{padded[:3]}/{padded[3:]}/{version}_{size}.png"


def download_player_image(
    player_id: str,
    url: str | None = None,
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    version: str = "26",
    size: int = 120,
    attempts: int = 4,
) -> Path:
    """Fetch one photo and store it atomically. Raises on persistent failure."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{player_id}.png"
    source = url or image_url(player_id, version=version, size=size)

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = _session().get(source, timeout=25)
            if response.status_code in RETRY_STATUS:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}", response=response
                )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"Beklenen görsel yerine {content_type} alındı")
            if len(response.content) < 1024:
                raise ValueError("İndirilen dosya çok küçük")
            tmp = target.with_suffix(".png.part")
            tmp.write_bytes(response.content)
            tmp.replace(target)
            return target
        except Exception as error:  # noqa: BLE001 - retried below
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"{player_id}: {last_error}")


def _human_eta(seconds: float) -> str:
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return "--"
    seconds = int(max(0, seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}s {minutes:02d}dk"
    return f"{minutes}dk {secs:02d}sn"


def download_all(
    players: list[tuple[str, str]],
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    workers: int = 8,
    force: bool = False,
    limit: int | None = None,
    size: int | None = None,
    quiet: bool = False,
) -> dict:
    """Download every missing photo. Returns counters."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    todo: list[tuple[str, str]] = []
    skipped = 0
    for player_id, url in players:
        if not force and (output_dir / f"{player_id}.png").is_file():
            skipped += 1
            continue
        if size:
            url = image_url(player_id, size=size)
        todo.append((player_id, url))
        if limit and len(todo) >= limit:
            break

    stats = {"total": len(todo), "downloaded": 0, "failed": 0, "skipped": skipped}
    if not todo:
        if not quiet:
            print(f"İndirilecek görsel yok ({skipped} tanesi zaten var).")
        return stats

    if not quiet:
        print(
            f"{len(todo):,} görsel indirilecek "
            f"({skipped:,} tanesi zaten mevcut) · {workers} paralel istek"
        )

    started = time.time()
    done = 0
    failures: list[str] = []

    def work(item: tuple[str, str]) -> bool:
        player_id, url = item
        try:
            download_player_image(player_id, url, output_dir=output_dir)
            return True
        except Exception as error:  # noqa: BLE001 - reported in the summary
            failures.append(str(error))
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, item) for item in todo]
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if future.result():
                stats["downloaded"] += 1
            else:
                stats["failed"] += 1
            if not quiet and (done % 50 == 0 or done == len(todo)):
                elapsed = time.time() - started
                rate = done / elapsed if elapsed else 0
                eta = (len(todo) - done) / rate if rate else float("inf")
                percent = done / len(todo) * 100
                print(
                    f"\r  {done:,}/{len(todo):,} ({percent:5.1f}%) "
                    f"{rate:4.0f} görsel/sn · kalan {_human_eta(eta)}",
                    end="",
                    flush=True,
                )

    if not quiet:
        elapsed = time.time() - started
        print(
            f"\nBitti: {stats['downloaded']:,} indirildi, "
            f"{stats['failed']:,} hata, {stats['skipped']:,} atlandı "
            f"({elapsed:.0f} sn)."
        )
        if failures:
            print("İlk hatalar:")
            for message in failures[:5]:
                print("  -", message)
    return stats


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FC26 oyuncu fotoğraflarını indirir (cdn.sofifa.net)."
    )
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET,
        help="FC26 CSV yolu (varsayılan: fcmanager/datasets/FC26_20250921.csv)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Görsellerin kaydedileceği klasör (varsayılan: media/player_images)",
    )
    parser.add_argument("--players", nargs="*", help="Sadece bu player_id'leri indir")
    parser.add_argument("--limit", type=int, help="En fazla bu kadar görsel indir")
    parser.add_argument("--workers", type=int, default=8, help="Paralel istek sayısı")
    parser.add_argument("--size", type=int, choices=(120, 240), help="CDN görsel boyutu")
    parser.add_argument("--force", action="store_true", help="Mevcut dosyaların üzerine yaz")
    parser.add_argument("--quiet", action="store_true", help="Sadece özet yazdır")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.players:
        players = [(str(pid).strip(), "") for pid in args.players if str(pid).strip().isdigit()]
    else:
        if not Path(args.dataset).is_file():
            print(f"Dataset bulunamadı: {args.dataset}", file=sys.stderr)
            return 2
        players = dataset_players(args.dataset)

    stats = download_all(
        players,
        output_dir=args.output,
        workers=max(1, args.workers),
        force=args.force,
        limit=args.limit,
        size=args.size,
        quiet=args.quiet,
    )
    print(f"Klasör: {Path(args.output).resolve()}")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())