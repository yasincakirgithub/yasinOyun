"""Shared fixtures for the FC Manager test suite."""

from __future__ import annotations

import random

from fcmanager import services
from fcmanager.data import DESIRED_BUCKETS, REQUIRED_LEAGUES, REQUIRED_NATIONS, SLOTS, SLOT_BY_KEY, slot_accepts
from fcmanager.models import MarketPlayer, Player, Room

# Primary position used for each market bucket when seeding a small catalogue.
SEED_POSITIONS = {
    'gk': ('GK', 'GK'),
    'cb': ('CB', 'CB'),
    'lb': ('LB', 'LB'),
    'rb': ('RB', 'RB'),
    'cm': ('CM', 'CM'),
    'cam': ('CAM', 'CAM'),
    'wing': ('LW', 'RW'),
    'st': ('ST', 'ST'),
}


def seed_catalogue() -> int:
    """Create a compact 80-player catalogue so tests never import the CSV.

    Production uses ``manage.py import_fc26``; the tests only need a small,
    deterministic pool that satisfies every market bucket and challenge filter.
    """
    if Player.objects.exists():
        return Player.objects.count()

    rows = []
    player_id = 900000
    for bucket, count in DESIRED_BUCKETS.items():
        positions = SEED_POSITIONS[bucket]
        for index in range(count):
            player_id += 1
            primary = positions[index % len(positions)]
            league = REQUIRED_LEAGUES[player_id % len(REQUIRED_LEAGUES)]
            nationality = REQUIRED_NATIONS[player_id % len(REQUIRED_NATIONS)]
            overall = 74 + (index * 3 + len(bucket)) % 17
            value = (
                5_000_000 + (index % 4) * 8_000_000
                if index % 3
                else 60_000_000 + (index % 3) * 10_000_000
            )
            rows.append(Player(
                player_id=player_id,
                name=f'{bucket.upper()} Oyuncu {index + 1}',
                full_name=f'{bucket.upper()} Test Oyuncu {index + 1}',
                positions=[primary],
                primary_position=primary,
                bucket=bucket,
                overall=min(92, overall),
                potential=min(94, overall + 2),
                value_eur=value,
                wage_eur=100_000,
                age=19 + (index * 2) % 16,
                nationality=nationality,
                league=league,
                club=f'Test Kulüp {player_id}',
                height_cm=175 + index % 20,
                weight_kg=70 + index % 15,
                preferred_foot='Left' if index % 5 == 0 else 'Right',
                weak_foot=3,
                skill_moves=3 + index % 3,
                international_reputation=2,
                pace=70 + overall % 20,
                shooting=70 + overall % 20,
                passing=70 + overall % 20,
                dribbling=70 + overall % 20,
                defending=70 + overall % 20,
                physic=70 + overall % 20,
                gk_diving=75 if bucket == 'gk' else 10,
                gk_handling=75 if bucket == 'gk' else 10,
                gk_kicking=75 if bucket == 'gk' else 10,
                gk_positioning=75 if bucket == 'gk' else 10,
                gk_reflexes=75 if bucket == 'gk' else 10,
                gk_speed=75 if bucket == 'gk' else 10,
                mentality_penalties=70,
                image_url='',
            ))
    Player.objects.bulk_create(rows, batch_size=200)
    return len(rows)


def create_room_with_players(count: int = 2, names: list[str] | None = None):
    """Create a waiting room and return ``(room, host, host_token, entries)``.

    ``entries`` contains ``(participant, token)`` pairs in join order so tests
    can authenticate as either manager.
    """
    seed_catalogue()
    names = names or [f'Player {index + 1}' for index in range(count)]
    room, host, host_token = services.create_room(names[0])
    entries = [(host, host_token)]
    for name in names[1:]:
        room, participant, token, _rejoined = services.join_room(room.room_code, name)
        entries.append((participant, token))
    return room, host, host_token, entries


def start_draft(room: Room, host, budget_eur: int | None = None) -> Room:
    """Start the draft, optionally overriding the random budget."""
    seed_catalogue()
    room = services.start_draft(room.room_code, host)
    if budget_eur is not None:
        Room.objects.filter(pk=room.pk).update(budget_eur=budget_eur)
        room.budget_eur = budget_eur
    return room


def available_candidates(room: Room, slot_key: str, include_picked: bool = False) -> list:
    accepted = SLOT_BY_KEY[slot_key]['accept']
    taken = set()
    if not include_picked:
        taken = set(
            room.market.filter(picked_by__isnull=False).values_list('player_id', flat=True)
        )
    rows = Player.objects.filter(primary_position__in=accepted).order_by('value_eur', 'player_id')
    return [row for row in rows if row.player_id not in taken]


def fill_squad(room: Room, participant, budget_eur: int = 10_000_000_000, lock: bool = True) -> Room:
    """Give a manager a legal 11-player squad using the cheapest valid picks.

    The budget is raised by default so the fixture never fails on price; budget
    limits get their own dedicated tests.
    """
    Room.objects.filter(pk=room.pk).update(budget_eur=budget_eur)
    for slot in SLOTS:
        candidates = available_candidates(room, slot['key'])
        if not candidates:
            raise AssertionError(f'No market candidate for slot {slot["key"]}')
        choice = min(candidates, key=lambda item: int(item.value_eur or 0))
        services.pick_player(room.room_code, participant, choice.player_id, slot['key'])
    if lock:
        return services.lock_squad(room.room_code, participant)
    return Room.objects.get(pk=room.pk)


def make_player(
    player_id: int,
    name: str,
    position: str,
    *,
    nationality: str = 'Spain',
    league: str = 'La Liga',
    club: str | None = None,
    overall: int = 80,
    value_eur: int = 10_000_000,
    age: int = 25,
    **overrides,
) -> dict:
    """Build a compact player dict compatible with the draft/simulation code."""
    player = {
        'player_id': player_id,
        'name': name,
        'full_name': name,
        'positions': [position],
        'primary_position': position,
        'bucket': position.lower(),
        'overall': overall,
        'potential': overall,
        'value_eur': value_eur,
        'wage_eur': 100_000,
        'age': age,
        'nationality': nationality,
        'league': league,
        'club': club or f'Club {player_id}',
        'height_cm': 180,
        'weight_kg': 75,
        'preferred_foot': 'Right',
        'weak_foot': 3,
        'skill_moves': 3,
        'international_reputation': 2,
        'pace': 75,
        'shooting': 75,
        'passing': 75,
        'dribbling': 75,
        'defending': 75,
        'physic': 75,
        'gk_diving': 75,
        'gk_handling': 75,
        'gk_kicking': 75,
        'gk_positioning': 75,
        'gk_reflexes': 75,
        'gk_speed': 75,
        'image_url': '',
    }
    player.update(overrides)
    return player


def synthetic_market(extra_slots: tuple[str, ...] = ()) -> list[dict]:
    """Two players per formation slot, with optional extra Argentine players.

    ``extra_slots`` marks one player in each named slot as Argentine and in the
    Argentine league. Because each slot only yields one player per squad, a
    challenge for two Argentines is impossible with three such players but
    feasible with four.
    """
    market: list[dict] = []
    player_id = 1
    for slot in SLOTS:
        for index in range(2):
            is_argentine = slot['key'] in extra_slots and index == 0
            market.append(make_player(
                player_id,
                f'{slot["key"]}-{index}',
                slot['accept'][0],
                nationality='Argentina' if is_argentine else 'Spain',
                league='Liga Profesional de Fútbol' if is_argentine else 'La Liga',
            ))
            player_id += 1
    return market


def make_squad(market: list[dict], rng: random.Random | None = None, exclude=()) -> dict:
    """Pick one valid player per formation slot from ``market``."""
    rng = rng or random.Random(0)
    used = set(exclude)
    squad = {}
    shuffled = list(market)
    rng.shuffle(shuffled)
    for slot in SLOTS:
        candidates = [
            player for player in shuffled
            if player['player_id'] not in used
            and slot_accepts(slot['key'], player.get('positions', ()))
        ]
        if not candidates:
            raise AssertionError(f'No synthetic candidate for slot {slot["key"]}')
        choice = rng.choice(candidates)
        used.add(choice['player_id'])
        squad[slot['key']] = choice
    return squad
