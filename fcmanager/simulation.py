"""Deterministic-once match simulation.

The server generates a complete 90-minute timeline (plus penalties when
needed) and stores it. Clients animate the timeline, so both managers see
exactly the same match.
"""

from __future__ import annotations

import math
import random

from .data import SLOT_BY_KEY

ROLE_WEIGHTS = {
    'GK': {'attack': 0.0, 'midfield': 0.0, 'defense': 1.0, 'gk': 1.0},
    'DEF': {'attack': 0.05, 'midfield': 0.15, 'defense': 0.80, 'gk': 0.0},
    'MID': {'attack': 0.25, 'midfield': 0.50, 'defense': 0.25, 'gk': 0.0},
    'FWD': {'attack': 0.60, 'midfield': 0.25, 'defense': 0.15, 'gk': 0.0},
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _gk_rating(player: dict) -> float:
    values = [
        player.get('gk_diving', 0),
        player.get('gk_handling', 0),
        player.get('gk_positioning', 0),
        player.get('gk_reflexes', 0),
    ]
    values = [v for v in values if v]
    if values:
        return sum(values) / len(values)
    return player.get('overall', 70)


def _attack_rating(player: dict) -> float:
    if 'GK' in player.get('positions', ()):
        return player.get('overall', 70) * 0.25
    return (
        player.get('shooting', 0) * 0.35
        + player.get('pace', 0) * 0.25
        + player.get('dribbling', 0) * 0.25
        + player.get('passing', 0) * 0.15
    )


def _midfield_rating(player: dict) -> float:
    if 'GK' in player.get('positions', ()):
        return player.get('overall', 70) * 0.2
    return (
        player.get('passing', 0) * 0.35
        + player.get('dribbling', 0) * 0.25
        + player.get('physic', 0) * 0.2
        + player.get('overall', 70) * 0.2
    )


def _defense_rating(player: dict) -> float:
    if 'GK' in player.get('positions', ()):
        return player.get('overall', 70) * 0.55 + _gk_rating(player) * 0.45
    return (
        player.get('defending', 0) * 0.45
        + player.get('physic', 0) * 0.25
        + player.get('pace', 0) * 0.2
        + player.get('overall', 70) * 0.1
    )


def compute_profile(squad: dict, challenges: list[dict], home_advantage: float = 0.0) -> dict:
    totals = {'attack': 0.0, 'midfield': 0.0, 'defense': 0.0, 'gk': 0.0}
    weights = {'attack': 0.0, 'midfield': 0.0, 'defense': 0.0, 'gk': 0.0}
    overalls = []
    passing_values = []
    squad_value = 0

    for slot_key, player in (squad or {}).items():
        if not player:
            continue
        slot = SLOT_BY_KEY.get(slot_key)
        role = slot['role'] if slot else 'MID'
        weight = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS['MID'])
        attack = _attack_rating(player)
        midfield = _midfield_rating(player)
        defense = _defense_rating(player)
        gk = _gk_rating(player) if 'GK' in player.get('positions', ()) else 0
        for key, value in (('attack', attack), ('midfield', midfield), ('defense', defense), ('gk', gk)):
            totals[key] += value * weight[key]
            weights[key] += weight[key]
        overalls.append(player.get('overall', 70))
        passing_values.append(player.get('passing', 70))
        squad_value += player.get('value_eur', 0)

    attack = totals['attack'] / weights['attack'] if weights['attack'] else 60
    midfield = totals['midfield'] / weights['midfield'] if weights['midfield'] else 60
    defense = totals['defense'] / weights['defense'] if weights['defense'] else 60
    gk = totals['gk'] / weights['gk'] if weights['gk'] else 60
    overall = sum(overalls) / len(overalls) if overalls else 60
    passing = sum(passing_values) / len(passing_values) if passing_values else 70

    completed = sum(1 for c in challenges if c.get('satisfied'))
    unmet = max(0, len(challenges) - completed)
    challenge_mod = completed * 1.25 - unmet * 2.5

    strength = (
        attack * 0.42
        + midfield * 0.26
        + defense * 0.22
        + gk * 0.10
        + challenge_mod
        + home_advantage
    )

    return {
        'attack': round(attack, 1),
        'midfield': round(midfield, 1),
        'defense': round(defense, 1),
        'goalkeeper': round(gk, 1),
        'overall': round(overall, 1),
        'passing': round(passing, 1),
        'strength': round(strength, 1),
        'challenge_mod': round(challenge_mod, 1),
        'squad_value': squad_value,
        'completed_challenges': completed,
        'unmet_challenges': unmet,
    }


def _expected_goals(attacker: dict, defender: dict) -> float:
    diff = attacker['strength'] - defender['strength']
    return _clamp(1.35 + diff * 0.085, 0.25, 4.1)


def _poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    count = 0
    product = 1.0
    while True:
        count += 1
        product *= rng.random()
        if product <= limit or count > 12:
            return count - 1


def _squad_items(squad: dict) -> list[tuple[str, dict]]:
    return [(slot, player) for slot, player in (squad or {}).items() if player]


def _role_of(slot_key: str) -> str:
    slot = SLOT_BY_KEY.get(slot_key)
    return slot['role'] if slot else 'MID'


def _pick_scorer(items: list[tuple[str, dict]], rng: random.Random) -> tuple[str, dict]:
    weights = []
    for slot, player in items:
        role = _role_of(slot)
        base = {'FWD': 5.0, 'MID': 2.2, 'DEF': 0.65, 'GK': 0.03}.get(role, 1.0)
        weights.append(base + player.get('shooting', 50) / 25)
    return rng.choices(items, weights=weights, k=1)[0]


def _pick_assister(items: list[tuple[str, dict]], scorer_name: str, rng: random.Random):
    candidates = [(slot, p) for slot, p in items if p.get('name') != scorer_name]
    if not candidates or rng.random() > 0.68:
        return None
    weights = []
    for slot, player in candidates:
        role = _role_of(slot)
        base = {'MID': 3.0, 'FWD': 2.2, 'DEF': 1.0, 'GK': 0.05}.get(role, 1.0)
        weights.append(base + player.get('passing', 50) / 30)
    return rng.choices(candidates, weights=weights, k=1)[0]


def _random_player(items: list[tuple[str, dict]], rng: random.Random) -> dict:
    return rng.choice(items)[1]


def _pick_defender(items: list[tuple[str, dict]], rng: random.Random) -> dict | None:
    defenders = [
        player for slot, player in items
        if _role_of(slot) in ('DEF', 'MID') and 'GK' not in player.get('positions', ())
    ]
    if not defenders:
        return _random_player(items, rng) if items else None
    priority = [player for player in defenders if _role_of_player(player) == 'DEF']
    return rng.choice(priority or defenders)


def _role_of_player(player: dict) -> str:
    positions = player.get('positions', ())
    if 'GK' in positions:
        return 'GK'
    if any(position in positions for position in ('CB', 'LB', 'RB', 'LWB', 'RWB')):
        return 'DEF'
    if any(position in positions for position in ('CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM')):
        return 'MID'
    return 'FWD'


def _pick_taker(items: list[tuple[str, dict]], rng: random.Random) -> dict:
    """Corner/free-kick takers: wide midfielders and full-backs."""
    takers = [
        player for slot, player in items
        if _role_of(slot) in ('MID', 'DEF') and 'GK' not in player.get('positions', ())
    ]
    return rng.choice(takers) if takers else _random_player(items, rng)


def _sample_minutes(rng: random.Random, count: int) -> list[int]:
    pool = list(range(1, 45)) + list(range(46, 90))
    return rng.sample(pool, min(count, len(pool)))


def _build_shot_events(
    side: str,
    team_name: str,
    goals: int,
    expected_goals: float,
    items: list[tuple[str, dict]],
    keeper: dict | None,
    defenders: list[tuple[str, dict]],
    rng: random.Random,
) -> list[dict]:
    """Build a shot-by-shot narrative, including exactly ``goals`` goals."""
    if not items:
        return []

    shot_count = int(_clamp(
        max(goals + 4, round(expected_goals * 6 + rng.randint(2, 6))),
        6,
        18,
    ))
    goal_indices = set(rng.sample(range(shot_count), goals))
    minutes = _sample_minutes(rng, shot_count)
    events: list[dict] = []

    for index in range(shot_count):
        _slot, shooter = _pick_scorer(items, rng)
        assist_pair = _pick_assister(items, shooter.get('name', ''), rng)
        assist = assist_pair[1] if assist_pair else None
        minute = minutes[index]
        shot_xg = round(_clamp(
            (expected_goals / shot_count) * rng.uniform(0.45, 1.85),
            0.02,
            0.62,
        ), 2)
        player_name = shooter.get('name', 'Oyuncu')

        if index in goal_indices:
            body = rng.choices(
                ['right_foot', 'left_foot', 'header', 'long_range'],
                weights=[46, 24, 17, 13],
                k=1,
            )[0]
            goal_type = {
                'right_foot': 'open_play',
                'left_foot': 'open_play',
                'header': 'set_piece',
                'long_range': 'long_range',
            }[body]
            if body == 'header':
                text = f'GOOOL! {player_name} kafayla ağları havalandırdı.'
            elif body == 'long_range':
                text = f'GOOOL! {player_name} uzaktan patlattı, top ağlarda!'
            else:
                text = f'GOOOL! {player_name} düzgün bir vuruşla topu ağlara gönderdi.'
            if assist:
                text += f' Asist: {assist.get("name", "Oyuncu")}.'
            events.append({
                'minute': minute,
                'phase': 'match',
                'type': 'goal',
                'side': side,
                'team': team_name,
                'player': player_name,
                'assist': (assist or {}).get('name', ''),
                'body_part': body,
                'goal_type': goal_type,
                'shot_xg': shot_xg,
                'text': text,
                'priority': 0,
            })
            continue

        outcome = rng.choices(
            ['save', 'miss', 'blocked', 'woodwork'],
            weights=[47, 29, 17, 7],
            k=1,
        )[0]
        keeper_name = (keeper or {}).get('name', 'kaleci')
        if outcome == 'save':
            text = f'{player_name} ceza sahası içinde vurdu, {keeper_name} kurtardı!'
        elif outcome == 'miss':
            text = f'{player_name} topu auta gönderdi.'
        elif outcome == 'blocked':
            blocker = _pick_defender(defenders, rng)
            text = f'{player_name} vurdu, savunma son anda blokladı.' if not blocker else (
                f'{player_name} vurdu, {blocker.get("name", "savunmacı")} blokladı.'
            )
        else:
            text = f'{player_name} çok sert vurdu, top direkte!'
        events.append({
            'minute': minute,
            'phase': 'match',
            'type': outcome,
            'side': side,
            'team': team_name,
            'player': player_name,
            'keeper': keeper_name if outcome in ('save', 'woodwork') else '',
            'shot_xg': shot_xg,
            'text': text,
            'priority': 1,
        })

    return events


def _build_other_events(
    side: str,
    team_name: str,
    items: list[tuple[str, dict]],
    rng: random.Random,
) -> list[dict]:
    if not items:
        return []

    events: list[dict] = []
    corner_count = rng.randint(2, 6)
    for _ in range(corner_count):
        taker = _pick_taker(items, rng)
        events.append({
            'minute': _sample_minutes(rng, 1)[0],
            'phase': 'match',
            'type': 'corner',
            'side': side,
            'team': team_name,
            'player': taker.get('name', ''),
            'text': f'{team_name} korner kazanıyor. {taker.get("name", "Oyuncu")} topun başında.',
            'priority': 1,
        })

    for _ in range(rng.randint(0, 3)):
        player = _random_player(items, rng)
        events.append({
            'minute': _sample_minutes(rng, 1)[0],
            'phase': 'match',
            'type': 'offside',
            'side': side,
            'team': team_name,
            'player': player.get('name', ''),
            'text': f'{player.get("name", "Oyuncu")} ofsayta takıldı.',
            'priority': 1,
        })

    foul_count = rng.randint(3, 6)
    cards = 0
    for _ in range(foul_count):
        player = _pick_defender(items, rng) or _random_player(items, rng)
        roll = rng.random()
        if roll < 0.028 and not any(event['type'] == 'red_card' for event in events):
            kind = 'red_card'
            text = f'{player.get("name", "Oyuncu")} kırmızı kartla oyun dışı kaldı!'
        elif roll < 0.16 and cards < 3:
            kind = 'yellow_card'
            cards += 1
            text = f'{player.get("name", "Oyuncu")} sert bir müdahaleden sonra sarı kart gördü.'
        else:
            kind = 'foul'
            text = f'{player.get("name", "Oyuncu")} faul yaptı, hakem serbest vuruş verdi.'
        events.append({
            'minute': _sample_minutes(rng, 1)[0],
            'phase': 'match',
            'type': kind,
            'side': side,
            'team': team_name,
            'player': player.get('name', ''),
            'text': text,
            'priority': 1,
        })

    return events


def _shootout(home_squad: dict, away_squad: dict, home_name: str, away_name: str, rng: random.Random):
    home_items = _squad_items(home_squad)
    away_items = _squad_items(away_squad)
    home_gk = next((p for _, p in home_items if 'GK' in p.get('positions', ())), None)
    away_gk = next((p for _, p in away_items if 'GK' in p.get('positions', ())), None)
    home_kicks = sorted(
        home_items,
        key=lambda item: (item[1].get('mentality_penalties', 0), item[1].get('shooting', 0)),
        reverse=True,
    )
    away_kicks = sorted(
        away_items,
        key=lambda item: (item[1].get('mentality_penalties', 0), item[1].get('shooting', 0)),
        reverse=True,
    )

    def attempt(shooter: dict, keeper: dict | None) -> bool:
        pen_stat = shooter.get('mentality_penalties') or shooter.get('shooting') or 70
        gk_stat = (keeper or {}).get('gk_reflexes') or 70
        probability = _clamp(0.80 + (pen_stat - gk_stat) / 260, 0.58, 0.94)
        return rng.random() < probability

    events = []
    home_pen = away_pen = 0
    order = 0

    def add_event(side, shooter, scored, keeper):
        nonlocal order
        order += 1
        team_name = home_name if side == 'home' else away_name
        if scored:
            text = f'{shooter.get("name", "Oyuncu")} penaltıyı gole çevirdi.'
        else:
            keeper_name = (keeper or {}).get('name', 'kaleci')
            text = f'{shooter.get("name", "Oyuncu")} kaçırdı! {keeper_name} kurtardı.'
        events.append({
            'minute': 91,
            'phase': 'penalties',
            'type': 'penalty_scored' if scored else 'penalty_missed',
            'side': side,
            'team': team_name,
            'player': shooter.get('name', ''),
            'text': text,
            'pen_score': [home_pen, away_pen],
            'order': order,
        })

    for round_index in range(5):
        home_shooter = home_kicks[round_index % len(home_kicks)][1] if home_kicks else None
        away_shooter = away_kicks[round_index % len(away_kicks)][1] if away_kicks else None
        if home_shooter:
            scored = attempt(home_shooter, away_gk)
            if scored:
                home_pen += 1
            add_event('home', home_shooter, scored, away_gk)
        if away_shooter:
            scored = attempt(away_shooter, home_gk)
            if scored:
                away_pen += 1
            add_event('away', away_shooter, scored, home_gk)

    sudden = 0
    while home_pen == away_pen and sudden < 15:
        sudden += 1
        home_shooter = home_kicks[(5 + sudden - 1) % len(home_kicks)][1] if home_kicks else None
        away_shooter = away_kicks[(5 + sudden - 1) % len(away_kicks)][1] if away_kicks else None
        if home_shooter:
            scored = attempt(home_shooter, away_gk)
            if scored:
                home_pen += 1
            add_event('home', home_shooter, scored, away_gk)
        if away_shooter:
            scored = attempt(away_shooter, home_gk)
            if scored:
                away_pen += 1
            add_event('away', away_shooter, scored, home_gk)
        if home_pen != away_pen:
            break

    if home_pen == away_pen:
        if rng.random() < 0.5:
            home_pen += 1
        else:
            away_pen += 1

    return home_pen, away_pen, events


def simulate_match(
    home_squad: dict,
    away_squad: dict,
    home_challenges: list[dict],
    away_challenges: list[dict],
    home_name: str,
    away_name: str,
    rng: random.Random | None = None,
) -> dict:
    rng = rng or random.Random()

    home_challenges = home_challenges or []
    away_challenges = away_challenges or []

    home_profile = compute_profile(home_squad, home_challenges, home_advantage=0.8)
    away_profile = compute_profile(away_squad, away_challenges, home_advantage=0.0)

    home_xg = _expected_goals(home_profile, away_profile) * rng.uniform(0.82, 1.18)
    away_xg = _expected_goals(away_profile, home_profile) * rng.uniform(0.82, 1.18)
    home_xg = _clamp(home_xg, 0.2, 4.3)
    away_xg = _clamp(away_xg, 0.2, 4.3)

    home_goals = min(7, _poisson(home_xg, rng))
    away_goals = min(7, _poisson(away_xg, rng))

    home_items = _squad_items(home_squad)
    away_items = _squad_items(away_squad)
    # A side without players cannot score, even if the xG model produced a
    # number. This keeps the stored score consistent with the goal events.
    if not home_items:
        home_goals = 0
    if not away_items:
        away_goals = 0

    home_gk = next((p for _, p in home_items if 'GK' in p.get('positions', ())), None)
    away_gk = next((p for _, p in away_items if 'GK' in p.get('positions', ())), None)

    shot_events: list[dict] = []
    shot_events.extend(_build_shot_events(
        'home', home_name, home_goals, home_xg, home_items, away_gk, away_items, rng,
    ))
    shot_events.extend(_build_shot_events(
        'away', away_name, away_goals, away_xg, away_items, home_gk, home_items, rng,
    ))

    other_events: list[dict] = []
    other_events.extend(_build_other_events('home', home_name, home_items, rng))
    other_events.extend(_build_other_events('away', away_name, away_items, rng))

    # The team that didn't start the match gets the second-half kick-off.
    opening_side = rng.choice(('home', 'away'))
    second_side = 'away' if opening_side == 'home' else 'home'
    opening_team = home_name if opening_side == 'home' else away_name
    second_team = home_name if second_side == 'home' else away_name

    events: list[dict] = [{
        'minute': 0,
        'phase': 'match',
        'type': 'kickoff',
        'side': opening_side,
        'team': opening_team,
        'text': f'Maç başladı! {opening_team} santrayı kullanıyor.',
        'priority': 0,
    }]
    events.extend(shot_events)
    events.extend(other_events)
    events.append({
        'minute': 45,
        'phase': 'match',
        'type': 'half',
        'side': None,
        'team': None,
        'text': 'İlk yarı sona erdi. Takımlar soyunma odasına gidiyor.',
        'priority': 2,
    })
    events.append({
        'minute': 46,
        'phase': 'match',
        'type': 'kickoff',
        'side': second_side,
        'team': second_team,
        'text': f'İkinci yarı başladı. {second_team} santrayı kullanıyor.',
        'priority': 0,
    })
    events.append({
        'minute': 90,
        'phase': 'match',
        'type': 'full',
        'side': None,
        'team': None,
        'text': '90 dakika sona erdi. Hakem maçı bitirdi.',
        'priority': 2,
    })
    events.sort(key=lambda e: (e['minute'], e.get('priority', 1)))

    # Every goal is followed by a real kick-off from the conceding side. If
    # both teams scored in the same minute the beats are still chained in
    # order because the kick-off is inserted directly after its goal.
    with_kickoffs: list[dict] = []
    for event in events:
        with_kickoffs.append(event)
        if event['type'] != 'goal':
            continue
        conceding_side = 'away' if event['side'] == 'home' else 'home'
        conceding_team = away_name if conceding_side == 'away' else home_name
        with_kickoffs.append({
            'minute': event['minute'],
            'phase': 'match',
            'type': 'kickoff',
            'side': conceding_side,
            'team': conceding_team,
            'text': f'{conceding_team} santrayı kullanıyor.',
            'priority': 0.5,
        })
    events = with_kickoffs

    home_running = away_running = 0
    for event in events:
        if event['type'] == 'goal':
            if event['side'] == 'home':
                home_running += 1
            else:
                away_running += 1
            event['text'] = event['text'].rstrip('.') + f' Skor: {home_running}-{away_running}.'
        event['score'] = [home_running, away_running]

    home_pen = away_pen = None
    if home_goals == away_goals:
        home_pen, away_pen, penalty_events = _shootout(
            home_squad, away_squad, home_name, away_name, rng,
        )
        for event in penalty_events:
            event['score'] = [home_goals, away_goals]
            events.append(event)
        winner_side = 'home' if home_pen > away_pen else 'away'
    else:
        winner_side = 'home' if home_goals > away_goals else 'away'

    possession_home = round(_clamp(
        50 + (home_profile['midfield'] - away_profile['midfield']) * 1.1 + rng.uniform(-4, 4),
        28, 72,
    ))
    possession_away = 100 - possession_home

    shot_types = ('goal', 'save', 'miss', 'blocked', 'woodwork')
    card_types = ('yellow_card', 'red_card')
    foul_types = ('foul',) + card_types

    def side_stats(side: str, profile: dict, possession: int) -> dict:
        side_events = [event for event in events if event.get('side') == side and event.get('phase') == 'match']
        shots = sum(1 for event in side_events if event['type'] in shot_types)
        on_target = sum(1 for event in side_events if event['type'] in ('goal', 'save'))
        xg_total = sum(float(event.get('shot_xg') or 0) for event in side_events)
        corners = sum(1 for event in side_events if event['type'] == 'corner')
        fouls = sum(1 for event in side_events if event['type'] in foul_types)
        yellow_cards = sum(1 for event in side_events if event['type'] in card_types)
        return {
            'possession': possession,
            'shots': shots,
            'on_target': min(shots, on_target),
            'xg': round(_clamp(xg_total, 0.2, 4.3), 2) if shots else 0.0,
            'corners': corners,
            'fouls': fouls,
            'yellow_cards': yellow_cards,
            'pass_accuracy': round(_clamp(72 + (profile['passing'] - 70) * 0.7 + rng.uniform(-3, 3), 60, 94)),
        }

    stats = {
        'home': side_stats('home', home_profile, possession_home),
        'away': side_stats('away', away_profile, possession_away),
    }

    contributions: dict[str, dict] = {}
    by_side: dict[str, dict[str, dict]] = {'home': {}, 'away': {}}

    def contribution(player: dict, side: str) -> dict:
        key = f'{side}:{player.get("player_id", player.get("name"))}'
        item = contributions.setdefault(key, {
            'name': player.get('name', ''),
            'side': side,
            'team': home_name if side == 'home' else away_name,
            'position': player.get('primary_position', ''),
            'overall': player.get('overall', 0),
            'goals': 0,
            'assists': 0,
            'saves': 0,
            'shots': 0,
            'cards': 0,
        })
        return item

    for side, items in (('home', home_items), ('away', away_items)):
        for _slot, player in items:
            by_side[side][player.get('name', '')] = player
            contribution(player, side)

    for event in events:
        if event.get('phase') != 'match':
            continue
        side = event.get('side')
        if side not in ('home', 'away'):
            continue
        player = by_side[side].get(event.get('player', ''))
        if player and event['type'] in shot_types:
            item = contribution(player, side)
            item['shots'] += 1
            if event['type'] == 'goal':
                item['goals'] += 1
                assist_name = event.get('assist', '')
                assist = by_side[side].get(assist_name)
                if assist:
                    contribution(assist, side)['assists'] += 1
            elif event['type'] == 'save' and event.get('keeper'):
                keeper_side = 'away' if side == 'home' else 'home'
                keeper = by_side[keeper_side].get(event['keeper'])
                if keeper:
                    contribution(keeper, keeper_side)['saves'] += 1
        if player and event['type'] in card_types:
            contribution(player, side)['cards'] += 1

    top_players = []
    for key, item in contributions.items():
        rating = (
            6.3
            + (item['overall'] - 75) * 0.03
            + item['goals'] * 1.1
            + item['assists'] * 0.7
            + item['saves'] * 0.16
            + item['shots'] * 0.05
            - item['cards'] * 0.18
            + rng.uniform(-0.25, 0.45)
        )
        item['rating'] = round(_clamp(rating, 5.2, 10.0), 1)
        top_players.append(item)
    top_players.sort(key=lambda item: (item['rating'], item['goals'], item['assists']), reverse=True)

    mvp = top_players[0] if top_players else {}
    winner_name = home_name if winner_side == 'home' else away_name

    return {
        'home_score': home_goals,
        'away_score': away_goals,
        'home_pen': home_pen,
        'away_pen': away_pen,
        'winner_side': winner_side,
        'events': events,
        'stats': stats,
        'profiles': {'home': home_profile, 'away': away_profile},
        'challenges': {'home': home_challenges, 'away': away_challenges},
        'mvp': mvp,
        'top_players': top_players[:5],
        'summary': f'{winner_name} {"penaltılarla " if home_pen is not None else ""}kazandı!',
    }
