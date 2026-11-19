#!/usr/bin/env python3
"""
Auction teması için TÜM karakterleri Google Görseller'de tek tek yeni sekmede açar.
Sen elinle indirirsin (sağ tık → "Görseli farklı kaydet..."), script sadece tarayıcıyı hazırlar.

Script bittiğinde sekmeler KAPANMAZ: Chrome ayrı bir süreç olarak başlatılır,
script çıktıktan sonra da açık kalır. Sekmeleri kapatmak istediğinde Chrome'u
kendin kapatman yeterli.

Kullanım:
    python auction/tools/open_images.py --theme kurtlar_vadisi
    python auction/tools/open_images.py --theme kurtlar_vadisi --chars kv_polat kv_cakir
    python auction/tools/open_images.py --theme marvel --delay 1.5
    python auction/tools/open_images.py --theme marvel --headless  # görünmez, iş bitince kapanır
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Playwright yok: pip install playwright && playwright install chrome")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
THEME_DATA_DIR = BASE_DIR / "auction" / "themes" / "data"
PROFILE_DIR = BASE_DIR / ".chrome_profile_auction"

# Harici Chrome'a bağlanacağımız sabit port (tekrar çalıştırınca aynı Chrome'a bağlanır)
CDP_PORT = 9333
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

SEARCH_PREFIX = {
    "kurtlar_vadisi": "Kurtlar Vadisi",
    "lotr": "Lord of the Rings",
    "marvel": "Marvel",
    "dc": "DC Comics",
    "harry_potter": "Harry Potter",
    "game_of_thrones": "Game of Thrones",
    "naruto": "Naruto",
    "dragon_ball": "Dragon Ball",
    "one_piece": "One Piece",
    "star_wars": "Star Wars",
    "video_games": "Video Game",
}

CONSENT_SELECTORS = (
    'button:has-text("Accept all")',
    'button:has-text("I agree")',
    'button:has-text("Kabul et")',
    'button:has-text("Tümünü kabul et")',
    'button:has-text("Alle akzeptieren")',
)


def load_characters(theme: str) -> list[tuple[str, str]]:
    path = THEME_DATA_DIR / f"{theme}.json"
    if not path.exists():
        sys.exit(f"Tema dosyası yok: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(c["id"], c["name"]) for c in data.get("characters", [])]


def find_chrome() -> str:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit(
        "Chrome bulunamadı. macOS için Google Chrome kurulu olmalı "
        "(/Applications/Google Chrome.app)."
    )


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cdp_ready(url: str = CDP_URL) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/json/version", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_cdp(timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cdp_ready():
            return True
        time.sleep(0.25)
    return False


def ensure_chrome(headless: bool) -> bool:
    """Chrome'u script'ten bağımsız (ayrı süreç) başlatır.

    Dönen değer: Chrome bu script tarafından mı başlatıldı?
    """
    if cdp_ready():
        print(f"♻️  Açık Chrome bulundu, ona bağlanılıyor (port {CDP_PORT}).")
        return False

    if port_in_use(CDP_PORT):
        sys.exit(
            f"Port {CDP_PORT} başka bir uygulama tarafından kullanılıyor. "
            "Lütfen o uygulamayı kapatıp tekrar dene."
        )

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()

    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1400,900",
        "--lang=tr-TR",
    ]
    if headless:
        args.append("--headless=new")
    args.append("about:blank")

    print("🚀 Chrome başlatılıyor…")
    # start_new_session=True → terminal/script kapansa bile Chrome yaşamaya devam eder
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    if not wait_for_cdp():
        sys.exit(
            "Chrome debug portu açılmadı. Muhtemelen bu profil "
            f"({PROFILE_DIR.name}) başka bir Chrome tarafından kullanılıyor.\n"
            "Açık olan auction Chrome penceresini kapatıp tekrar dene."
        )
    return True


def image_search_url(prefix: str, name: str) -> str:
    query = urllib.parse.quote_plus(f"{prefix} {name}")
    return f"https://www.google.com/search?tbm=isch&hl=tr&q={query}"


async def dismiss_consent(page) -> None:
    for selector in CONSENT_SELECTORS:
        try:
            button = await page.wait_for_selector(selector, timeout=500)
            if button and await button.is_visible():
                await button.click(timeout=2000)
                await page.wait_for_timeout(600)
                return
        except Exception:
            pass


async def open_tabs(theme: str, characters: list[tuple[str, str]], delay: float) -> None:
    prefix = SEARCH_PREFIX.get(theme, theme.replace("_", " ").title())

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        # İlk karakter için boş about:blank sekmesini kullan (fazladan boş sekme kalmasın)
        reusable = next(
            (page for page in context.pages if page.url in ("about:blank", "")),
            None,
        )

        print(f"\n{'=' * 60}")
        print(f"  {theme.upper()}  —  {len(characters)} karakter")
        print(f"{'=' * 60}\n")

        for index, (char_id, char_name) in enumerate(characters, 1):
            print(f"[{index:>2}/{len(characters)}] {char_id}  →  {char_name}", flush=True)

            if index == 1 and reusable is not None:
                page = reusable
            else:
                page = await context.new_page()

            try:
                await page.goto(
                    image_search_url(prefix, char_name),
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
            except Exception as exc:
                print(f"    ⚠️  Sayfa yüklenemedi: {exc}", flush=True)
                continue

            # Her karakterin sekmesi sırayla öne gelsin (tek tek açılıyor gibi görünsün)
            try:
                await page.bring_to_front()
            except Exception:
                pass

            await page.wait_for_timeout(1200)
            await dismiss_consent(page)

            # Sekme başlığına karakter adını yaz (kolay ayırt için)
            try:
                await page.evaluate(
                    "(title) => { document.title = title; }",
                    f"{char_name} — Google Görseller",
                )
            except Exception:
                pass

            if delay > 0:
                await asyncio.sleep(delay)

        # Bağlantıyı kapat ama tarayıcıyı KAPATMA.
        # (connect_over_cdp ile bağlı olduğumuz Chrome bizim sürecimizin çocuğu değil.)
        try:
            await browser.close()  # CDP bağlantısı için sadece disconnect yapar
        except Exception:
            pass


async def open_tabs_managed(theme: str, characters: list[tuple[str, str]], delay: float) -> None:
    """Headless mod: Playwright'ın yönettiği tarayıcı (iş bitince kapanır)."""
    prefix = SEARCH_PREFIX.get(theme, theme.replace("_", " ").title())
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=True,
            args=["--no-first-run", "--no-default-browser-check"],
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        for index, (char_id, char_name) in enumerate(characters, 1):
            print(f"[{index:>2}/{len(characters)}] {char_id}  →  {char_name}", flush=True)
            try:
                await page.goto(
                    image_search_url(prefix, char_name),
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await page.wait_for_timeout(1000)
            except Exception as exc:
                print(f"    ⚠️  Sayfa yüklenemedi: {exc}", flush=True)
            if delay > 0:
                await asyncio.sleep(delay)

        await context.close()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tüm karakterleri Google Görseller'de tek tek yeni sekmelerde açar."
    )
    parser.add_argument("--theme", default="kurtlar_vadisi", choices=sorted(SEARCH_PREFIX))
    parser.add_argument("--chars", nargs="+", metavar="ID", help="Sadece bu id'ler")
    parser.add_argument("--headless", action="store_true",
                        help="Görünmez çalıştır (iş bitince tarayıcı kapanır)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Sekme açma arası bekleme (sn, varsayılan 1.0)")
    parser.add_argument("--list", action="store_true", help="Temaları listele")
    args = parser.parse_args()

    if args.list:
        for theme in sorted(SEARCH_PREFIX):
            chars = load_characters(theme)
            print(f"{theme:<20} {len(chars):>3} karakter")
        return 0

    characters = load_characters(args.theme)
    if args.chars:
        wanted = set(args.chars)
        characters = [c for c in characters if c[0] in wanted]
        if not characters:
            sys.exit(f"Karakter bulunamadı: {args.chars}")
        missing = wanted - {c[0] for c in characters}
        if missing:
            print(f"⚠️  Bulunamadı: {', '.join(sorted(missing))}")

    if args.headless:
        await open_tabs_managed(args.theme, characters, args.delay)
        return 0

    launched = ensure_chrome(headless=False)
    await open_tabs(args.theme, characters, args.delay)

    print(f"\n✅ {len(characters)} sekme açıldı.")
    print("   Script bitti, ama Chrome ve sekmeler AÇIK kalacak.")
    print("   Sağ tık → 'Görseli farklı kaydet...' ile indirebilirsin.")
    if launched:
        print("   Bitirince Chrome penceresini kendin kapat (Cmd+Q).\n")
    else:
        print("   Zaten açık olan Chrome penceresini kullanıyorsun.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
