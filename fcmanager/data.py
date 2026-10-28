"""FC26 dataset loading, database import and market sampling.

The dataset ships as a CSV under ``fcmanager/datasets/``. ``manage.py
import_fc26`` loads every row into the :class:`fcmanager.models.Player` table;
the draft screen then searches that table instead of using a fixed 80-player
snapshot. The CSV stays the source of truth for re-imports.
"""

from __future__ import annotations

import csv
import logging
import os
import random
import threading
from collections import Counter
from functools import lru_cache
from pathlib import Path

from django.db.models import Count, Max

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).resolve().parent / 'datasets'
CSV_PATH = Path(
    os.environ.get('FCMANAGER_DATASET') or (DATASET_DIR / 'FC26_20250921.csv')
).expanduser()

PROJECT_DIR = Path(__file__).resolve().parent.parent
#: Local copies of the FC26 face photos. The CDN only answers when the request
#: carries a ``sofifa.com`` Referer, which a browser cannot send cross-origin,
#: so ``fcmanager/download_player.py`` fetches the images once and the app
#: serves them itself.
PLAYER_IMAGE_DIR = Path(
    os.environ.get('FCMANAGER_PLAYER_IMAGES')
    or (PROJECT_DIR / 'media' / 'player_images')
).expanduser()
PLAYER_IMAGE_URL = '/fcmanager/photos/{player_id}.png'

# The dataset stores values in EUR. The game displays a TRY equivalent so the
# budget range from the brief (400M EUR -> 1T TRY) can be shown honestly.
EUR_TRY_RATE = 47.0

SLOTS = (
    {'key': 'gk', 'label': 'GK', 'role': 'GK', 'full': 'Kaleci', 'accept': ('GK',), 'x': 50, 'y': 88},
    {'key': 'lb', 'label': 'LB', 'role': 'DEF', 'full': 'Sol bek', 'accept': ('LB', 'LWB'), 'x': 13, 'y': 69},
    {'key': 'cb1', 'label': 'CB', 'role': 'DEF', 'full': 'Stoper', 'accept': ('CB',), 'x': 36, 'y': 73},
    {'key': 'cb2', 'label': 'CB', 'role': 'DEF', 'full': 'Stoper', 'accept': ('CB',), 'x': 64, 'y': 73},
    {'key': 'rb', 'label': 'RB', 'role': 'DEF', 'full': 'Sağ bek', 'accept': ('RB', 'RWB'), 'x': 87, 'y': 69},
    {'key': 'cm1', 'label': 'CM', 'role': 'MID', 'full': 'Orta saha', 'accept': ('CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'), 'x': 24, 'y': 48},
    {'key': 'cm2', 'label': 'CM', 'role': 'MID', 'full': 'Orta saha', 'accept': ('CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'), 'x': 50, 'y': 53},
    {'key': 'cm3', 'label': 'CM', 'role': 'MID', 'full': 'Orta saha', 'accept': ('CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'), 'x': 76, 'y': 48},
    {'key': 'lw', 'label': 'LW', 'role': 'FWD', 'full': 'Sol kanat', 'accept': ('LW', 'LM', 'LF'), 'x': 17, 'y': 22},
    {'key': 'st', 'label': 'ST', 'role': 'FWD', 'full': 'Santrfor', 'accept': ('ST', 'CF', 'LS', 'RS'), 'x': 50, 'y': 14},
    {'key': 'rw', 'label': 'RW', 'role': 'FWD', 'full': 'Sağ kanat', 'accept': ('RW', 'RM', 'RF'), 'x': 83, 'y': 22},
)
SLOT_BY_KEY = {slot['key']: slot for slot in SLOTS}
SLOT_KEYS = tuple(slot['key'] for slot in SLOTS)

POSITION_BUCKETS = {
    'GK': 'gk',
    'CB': 'cb',
    'LB': 'lb', 'LWB': 'lb',
    'RB': 'rb', 'RWB': 'rb',
    'CM': 'cm', 'CDM': 'cm', 'LCM': 'cm', 'RCM': 'cm', 'LDM': 'cm', 'RDM': 'cm',
    'CAM': 'cam', 'LAM': 'cam', 'RAM': 'cam',
    'LM': 'wing', 'RM': 'wing', 'LW': 'wing', 'RW': 'wing', 'LF': 'wing', 'RF': 'wing',
    'ST': 'st', 'CF': 'st', 'LS': 'st', 'RS': 'st',
}
KNOWN_POSITIONS = set(POSITION_BUCKETS)

# 80 players, balanced enough that every formation slot has choices.
DESIRED_BUCKETS = {
    'gk': 7,
    'cb': 12,
    'lb': 7,
    'rb': 7,
    'cm': 15,
    'cam': 7,
    'wing': 12,
    'st': 13,
}
MIN_BUCKETS = {'gk': 3, 'cb': 6, 'lb': 3, 'rb': 3, 'cm': 8, 'cam': 3, 'wing': 6, 'st': 7}

REQUIRED_LEAGUES = ('Süper Lig', 'La Liga', 'Premier League', 'Serie A', 'Bundesliga', 'Ligue 1')
REQUIRED_NATIONS = ('Spain', 'Türkiye', 'Brazil', 'France', 'England', 'Argentina')

NATION_TR = {
    'Spain': 'İspanyol',
    'Türkiye': 'Türk',
    'Turkey': 'Türk',
    'Brazil': 'Brezilyalı',
    'France': 'Fransız',
    'England': 'İngiliz',
    'Argentina': 'Arjantinli',
    'Germany': 'Alman',
    'Portugal': 'Portekizli',
    'Italy': 'İtalyan',
    'Netherlands': 'Hollandalı',
    'Belgium': 'Belçikalı',
    'Uruguay': 'Uruguaylı',
    'Denmark': 'Danimarkalı',
    'Sweden': 'İsveçli',
    'Norway': 'Norveçli',
    'Croatia': 'Hırvat',
    'Morocco': 'Faslı',
    'Senegal': 'Senegalli',
    'Nigeria': 'Nijeryalı',
    'Japan': 'Japon',
    'United States': 'Amerikalı',
    'Colombia': 'Kolombiyalı',
    'Serbia': 'Sırp',
    'Switzerland': 'İsviçreli',
    'Austria': 'Avusturyalı',
    'Poland': 'Polonyalı',
    'Greece': 'Yunan',
    'Scotland': 'İskoç',
    'Ghana': 'Ganalı',
    'Algeria': 'Cezayirli',
    'Egypt': 'Mısırlı',
    'Korea Republic': 'Koreli',
    'Mexico': 'Meksikalı',
    'Canada': 'Kanadalı',
    'Australia': 'Avustralyalı',
    'Ivory Coast': "Fildişi Sahilli",
    "Côte d'Ivoire": 'Fildişi Sahilli',
}

LEAGUE_TR = {
    'Süper Lig': 'Süper Lig',
    'La Liga': 'La Liga',
    'Premier League': 'Premier League',
    'Serie A': 'Serie A',
    'Bundesliga': 'Bundesliga',
    'Ligue 1': 'Ligue 1',
    'Eredivisie': 'Eredivisie',
    'Primeira Liga': 'Primeira Liga',
    'Championship': 'Championship',
    'Pro League': 'Pro League',
    'Super League': 'Super League',
    'Liga Profesional de Fútbol': 'Arjantin Ligi',
    'Major League Soccer': 'MLS',
    'Série A': 'Brezilya Serie A',
}


def _int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _num(value, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _positions(raw: str) -> list[str]:
    items = []
    for part in str(raw or '').split(','):
        code = part.strip().upper()
        if code in KNOWN_POSITIONS and code not in items:
            items.append(code)
    return items


@lru_cache(maxsize=1)
def load_players() -> tuple[dict, ...]:
    """Load the FC26 CSV once into a compact, immutable tuple of dicts."""
    return _read_csv(CSV_PATH)


def _read_csv(path: Path) -> tuple[dict, ...]:
    if not Path(path).exists():
        logger.error('FC26 dataset not found at %s', path)
        return ()

    players: list[dict] = []
    seen: set[int] = set()
    try:
        with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                player_id = _int(row.get('player_id'))
                name = (row.get('short_name') or '').strip()
                positions = _positions(row.get('player_positions'))
                overall = _int(row.get('overall'))
                value = _int(row.get('value_eur'))
                age = _int(row.get('age'))
                if (
                    not player_id or player_id in seen or not name or not positions
                    or overall < 60 or value <= 0 or age < 15 or age > 45
                ):
                    continue
                seen.add(player_id)
                primary = positions[0]
                bucket = POSITION_BUCKETS.get(primary)
                if not bucket:
                    continue
                players.append({
                    'player_id': player_id,
                    'name': name,
                    'full_name': (row.get('long_name') or name).strip(),
                    'positions': positions,
                    'primary_position': primary,
                    'bucket': bucket,
                    'overall': overall,
                    'potential': _int(row.get('potential'), overall),
                    'value_eur': value,
                    'wage_eur': _int(row.get('wage_eur')),
                    'age': age,
                    'nationality': (row.get('nationality_name') or '').strip(),
                    'league': (row.get('league_name') or '').strip(),
                    'club': (row.get('club_name') or '').strip(),
                    'height_cm': _int(row.get('height_cm')),
                    'weight_kg': _int(row.get('weight_kg')),
                    'preferred_foot': (row.get('preferred_foot') or '').strip(),
                    'weak_foot': _int(row.get('weak_foot')),
                    'skill_moves': _int(row.get('skill_moves')),
                    'international_reputation': _int(row.get('international_reputation')),
                    'pace': _int(row.get('pace')),
                    'shooting': _int(row.get('shooting')),
                    'passing': _int(row.get('passing')),
                    'dribbling': _int(row.get('dribbling')),
                    'defending': _int(row.get('defending')),
                    'physic': _int(row.get('physic')),
                    'gk_diving': _int(row.get('goalkeeping_diving')),
                    'gk_handling': _int(row.get('goalkeeping_handling')),
                    'gk_kicking': _int(row.get('goalkeeping_kicking')),
                    'gk_positioning': _int(row.get('goalkeeping_positioning')),
                    'gk_reflexes': _int(row.get('goalkeeping_reflexes')),
                    'gk_speed': _int(row.get('goalkeeping_speed')),
                    'mentality_penalties': _int(row.get('mentality_penalties')),
                    'image_url': (row.get('player_face_url') or '').strip(),
                })
    except OSError:
        logger.exception('Could not read FC26 dataset')
        return ()

    logger.info('Loaded %s FC26 players from CSV', len(players))
    return tuple(players)


#: Model columns copied from the CSV dict, in the order used by bulk import.
PLAYER_FIELDS = (
    'player_id', 'name', 'full_name', 'positions', 'primary_position', 'bucket',
    'overall', 'potential', 'value_eur', 'wage_eur', 'age', 'nationality',
    'league', 'club', 'height_cm', 'weight_kg', 'preferred_foot', 'weak_foot',
    'skill_moves', 'international_reputation', 'pace', 'shooting', 'passing',
    'dribbling', 'defending', 'physic', 'gk_diving', 'gk_handling', 'gk_kicking',
    'gk_positioning', 'gk_reflexes', 'gk_speed', 'mentality_penalties', 'image_url',
)
# ``updated_at`` is auto-managed, so it is excluded from bulk upserts.
PLAYER_UPDATE_FIELDS = tuple(
    field for field in PLAYER_FIELDS if field not in ('player_id',)
) + ('updated_at',)

_PHOTO_CACHE: dict[str, object] = {'stamp': None, 'ids': frozenset()}
_PHOTO_LOCK = threading.Lock()


def downloaded_photo_ids() -> frozenset[str]:
    """Player ids that already have a photo on disk.

    The listing is cached and refreshed whenever the directory changes, so the
    hot paths (market cards, match squads) never hit the filesystem per player.
    """
    try:
        stamp = PLAYER_IMAGE_DIR.stat().st_mtime_ns
    except OSError:
        return frozenset()
    with _PHOTO_LOCK:
        if _PHOTO_CACHE['stamp'] == stamp:
            return _PHOTO_CACHE['ids']  # type: ignore[return-value]
    try:
        ids = frozenset(path.stem for path in PLAYER_IMAGE_DIR.glob('*.png'))
    except OSError:
        ids = frozenset()
    with _PHOTO_LOCK:
        _PHOTO_CACHE['stamp'] = stamp
        _PHOTO_CACHE['ids'] = ids
    return ids


def clear_photo_cache() -> None:
    """Forget the downloaded-photo listing (used after a bulk download)."""
    with _PHOTO_LOCK:
        _PHOTO_CACHE['stamp'] = None
        _PHOTO_CACHE['ids'] = frozenset()


def photo_url(player_id, fallback: str = '') -> str:
    """Local photo path when it exists, otherwise the dataset's CDN link."""
    key = str(player_id or '')
    if key and key in downloaded_photo_ids():
        return PLAYER_IMAGE_URL.format(player_id=key)
    return (fallback or '').strip()


def with_photo(player: dict) -> dict:
    """Copy of ``player`` whose ``image_url`` prefers the local photo."""
    url = photo_url(player.get('player_id'), player.get('image_url'))
    if not url or url == player.get('image_url'):
        return player
    updated = dict(player)
    updated['image_url'] = url
    return updated


_CATALOGUE_CACHE: dict[str, object] = {'signature': None, 'players': ()}
_CATALOGUE_LOCK = threading.Lock()


def _catalogue_signature() -> dict:
    """Cheap fingerprint of the catalogue table (one aggregate query)."""
    from .models import Player

    return Player.objects.aggregate(count=Count('pk'), latest=Max('updated_at'))


def clear_catalogue_cache() -> None:
    with _CATALOGUE_LOCK:
        _CATALOGUE_CACHE['signature'] = None
        _CATALOGUE_CACHE['players'] = ()


def catalogue_players() -> tuple[dict, ...]:
    """All catalogue players as dicts, cached until the table changes.

    Auto-fill and challenge generation both need the whole pool, so loading it
    once per process (instead of once per click) keeps drafting snappy. The
    cache is keyed by ``(row count, latest update)`` and cleared by imports.
    """
    from .models import Player

    try:
        signature = _catalogue_signature()
    except Exception:  # pragma: no cover - database unavailable in some tests
        return ()
    if not signature.get('count'):
        return ()
    with _CATALOGUE_LOCK:
        if _CATALOGUE_CACHE['signature'] == signature:
            return _CATALOGUE_CACHE['players']  # type: ignore[return-value]
    players = tuple(dict(row) for row in Player.objects.values(*PLAYER_FIELDS))
    with _CATALOGUE_LOCK:
        _CATALOGUE_CACHE['signature'] = signature
        _CATALOGUE_CACHE['players'] = players
    return players


def import_catalogue(path: Path | str | None = None, *, replace: bool = False) -> int:
    """Load every CSV row into the ``Player`` table.

    Existing rows are updated by ``player_id`` so the command is safe to run
    again after a dataset refresh.
    """
    from .models import Player

    players = _read_csv(Path(path or CSV_PATH))
    if replace:
        Player.objects.all().delete()
    if not players:
        return 0

    objects = [Player(**{field: player[field] for field in PLAYER_FIELDS}) for player in players]
    batch_size = 500
    for start in range(0, len(objects), batch_size):
        Player.objects.bulk_create(
            objects[start:start + batch_size],
            batch_size=batch_size,
            update_conflicts=True,
            unique_fields=['player_id'],
            update_fields=list(PLAYER_UPDATE_FIELDS),
        )
    logger.info('Imported %s FC26 players into the database', len(objects))
    clear_catalogue_cache()
    return len(objects)


def catalogue_size() -> int:
    from .models import Player

    try:
        return Player.objects.count()
    except Exception:  # pragma: no cover - database unavailable in some tests
        return 0


def ensure_catalogue(path: Path | str | None = None) -> int:
    """Import the dataset on first use; return the number of stored players."""
    size = catalogue_size()
    if size:
        return size
    if not Path(path or CSV_PATH).exists():
        return 0
    import_catalogue(path)
    return catalogue_size()


def _catalogue_players(max_overall: bool = False) -> list[dict]:
    """Read the player pool from the database, or ``[]`` when unavailable."""
    try:
        players = catalogue_players()
    except Exception:  # pragma: no cover - DB unavailable (SimpleTestCase)
        return []
    if max_overall:
        return [player for player in players if player['overall'] >= 73]
    return list(players)



def slot_accepts(slot_key: str, positions) -> bool:
    slot = SLOT_BY_KEY.get(slot_key)
    if not slot:
        return False
    return bool(set(positions or ()) & set(slot['accept']))


def format_nation(nationality: str) -> str:
    return NATION_TR.get(nationality, nationality)


def format_league(league: str) -> str:
    return LEAGUE_TR.get(league, league)


def _take(pool: list[dict], count: int, rng: random.Random, used: set[int]) -> list[dict]:
    available = [p for p in pool if p['player_id'] not in used]
    if count <= 0:
        return []
    if count >= len(available):
        return list(available)
    return rng.sample(available, count)


def _replace_one(chosen: list[dict], new_player: dict, rng: random.Random, protected: set[int]) -> bool:
    """Replace a surplus player with a targeted one, keeping the pool balanced."""
    counts = Counter(p['bucket'] for p in chosen)
    removable = [
        p for p in chosen
        if p['player_id'] not in protected
        and counts[p['bucket']] > MIN_BUCKETS.get(p['bucket'], 1)
        and p['player_id'] != new_player['player_id']
    ]
    if not removable:
        return False
    # Prefer removing from the most over-represented bucket.
    removable.sort(key=lambda p: counts[p['bucket']] - MIN_BUCKETS.get(p['bucket'], 1), reverse=True)
    victim = rng.choice(removable[:max(1, len(removable) // 3)])
    chosen.remove(victim)
    chosen.append(new_player)
    return True


def build_market(rng: random.Random, size: int = 80) -> list[dict]:
    """Create a balanced sample used to design and verify challenges.

    The playable market itself is the whole ``Player`` table; this balanced
    sample keeps challenge generation honest (every proposed goal is proven
    twice over a realistic pool) without scanning 15k rows per attempt.
    """
    all_players = _catalogue_players(max_overall=True)
    if not all_players:
        all_players = list(load_players())
    return select_market(all_players, rng, size)


def select_market(all_players: list[dict], rng: random.Random, size: int = 80) -> list[dict]:
    if len(all_players) < 50:
        raise ValueError('FC26 dataset is unavailable or too small.')

    eligible = [p for p in all_players if p['overall'] >= 73]
    by_bucket: dict[str, list[dict]] = {key: [] for key in DESIRED_BUCKETS}
    for player in eligible:
        bucket = player['bucket']
        if bucket in by_bucket:
            by_bucket[bucket].append(player)

    chosen: list[dict] = []
    used: set[int] = set()
    for bucket, count in DESIRED_BUCKETS.items():
        pool = by_bucket.get(bucket, [])
        if not pool:
            continue
        pool = sorted(pool, key=lambda p: p['overall'], reverse=True)
        elite = [p for p in pool if p['overall'] >= 82]
        value = [p for p in pool if p['overall'] < 82]
        elite_count = min(len(elite), max(1, int(round(count * 0.55))))
        value_count = count - elite_count
        picks = _take(elite, elite_count, rng, used)
        used.update(p['player_id'] for p in picks)
        picks += _take(value, value_count, rng, used)
        used.update(p['player_id'] for p in picks)
        if len(picks) < count:
            picks += _take(pool, count - len(picks), rng, used)
            used.update(p['player_id'] for p in picks)
        chosen.extend(picks)

    # Fill any shortfall (e.g. a position bucket is unexpectedly thin).
    if len(chosen) < size:
        rest = [p for p in eligible if p['player_id'] not in used]
        chosen.extend(_take(rest, size - len(chosen), rng, used))
    chosen = chosen[:size]

    protected: set[int] = set()

    def ensure(predicate, minimum: int, pool=None):
        pool = pool or eligible
        current = [p for p in chosen if predicate(p)]
        if len(current) >= minimum:
            return
        candidates = [p for p in pool if predicate(p) and p['player_id'] not in {x['player_id'] for x in chosen}]
        rng.shuffle(candidates)
        for candidate in candidates[: minimum - len(current)]:
            if _replace_one(chosen, candidate, rng, protected):
                protected.add(candidate['player_id'])

    # Flavour quotas make the example challenges (Spain, Süper Lig, U25...)
    # appear naturally in most rooms while keeping the pool random.
    for league in REQUIRED_LEAGUES:
        ensure(lambda p, league=league: p['league'] == league, 2)
    for nation in REQUIRED_NATIONS:
        ensure(lambda p, nation=nation: p['nationality'] == nation, 2)

    # Keep the budget meaningful: enough bargains and enough stars.
    ensure(lambda p: p['value_eur'] <= 25_000_000, 14)
    ensure(lambda p: p['value_eur'] >= 60_000_000, 10)

    rng.shuffle(chosen)
    return chosen
