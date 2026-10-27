"""FC26 CSV loading and draft-market generation.

The dataset is a single CSV shipped with the game. Rows are loaded once and
kept in memory; each room receives a frozen, balanced snapshot of 80 players.
"""

from __future__ import annotations

import csv
import logging
import random
from collections import Counter
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).with_name('FC26_20250921.csv')

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
    if not CSV_PATH.exists():
        logger.error('FC26 dataset not found at %s', CSV_PATH)
        return ()

    players: list[dict] = []
    seen: set[int] = set()
    try:
        with CSV_PATH.open('r', encoding='utf-8-sig', newline='') as handle:
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
                    'image_url': (row.get('player_face_url') or '').strip(),
                })
    except OSError:
        logger.exception('Could not read FC26 dataset')
        return ()

    logger.info('Loaded %s FC26 players from CSV', len(players))
    return tuple(players)


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
    """Create a balanced 80-player market from the FC26 dataset."""
    all_players = list(load_players())
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
