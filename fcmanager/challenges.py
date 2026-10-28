"""Shared challenge generation and live progress calculation."""

from __future__ import annotations

import json
import random
from collections import Counter

from .data import (
    SLOTS,
    format_league,
    format_nation,
    slot_accepts,
)


def _make(ctype: str, target, params: dict, label: str, icon: str, kind: str, unit: str = '') -> dict:
    return {
        'id': f'{ctype}:{target}:{json.dumps(params, ensure_ascii=False, sort_keys=True)}',
        'type': ctype,
        'target': target,
        'params': params,
        'label': label,
        'icon': icon,
        'kind': kind,
        'unit': unit,
    }


def _counts(players, key: str) -> Counter:
    return Counter(p.get(key) for p in players if p.get(key))


def _candidate_groups(market: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {'identity': [], 'age': [], 'quality': [], 'shape': []}

    for nationality, count in _counts(market, 'nationality').most_common(12):
        if count < 3:
            continue
        target = 3 if count >= 5 else 2
        groups['identity'].append(_make(
            'nationality_min', target, {'nationality': nationality},
            f'En az {target} {format_nation(nationality)} oyuncu', '🌍', 'identity',
        ))

    for league, count in _counts(market, 'league').most_common(12):
        if not league or count < 3:
            continue
        target = 3 if count >= 5 else 2
        groups['identity'].append(_make(
            'league_min', target, {'league': league},
            f'En az {target} {format_league(league)} oyuncusu', '🏆', 'identity',
        ))

    for threshold in (23, 25, 27):
        count = sum(1 for p in market if p['age'] < threshold)
        if count < 4:
            continue
        target = 4 if threshold == 23 and count >= 7 else 3
        groups['age'].append(_make(
            'age_under', target, {'age': threshold},
            f'En az {target} oyuncu {threshold} yaş altı', '🎂', 'age', 'yaş',
        ))
    for threshold in (30, 32, 34):
        count = sum(1 for p in market if p['age'] >= threshold)
        if count < 2:
            continue
        target = 2 if count >= 4 else 1
        groups['age'].append(_make(
            'age_over', target, {'age': threshold},
            f'En az {target} oyuncu {threshold} yaş üstü', '🎂', 'age', 'yaş',
        ))
    ages = sorted(p['age'] for p in market)
    if len(ages) >= 11:
        youngest_avg = sum(ages[:11]) / 11
        for target in (27.5, 28.5):
            if youngest_avg <= target - 0.3:
                groups['age'].append(_make(
                    'age_avg_max', target, {'max_age': target},
                    f'Kadro yaş ortalaması {str(target).replace(".", ",")} altında',
                    '📉', 'age', 'yaş',
                ))

    for threshold in (82, 84, 86):
        count = sum(1 for p in market if p['overall'] >= threshold)
        if count < 3:
            continue
        target = 3 if threshold == 82 and count >= 5 else 2
        groups['quality'].append(_make(
            'overall_min', target, {'overall': threshold},
            f'En az {target} oyuncu {threshold}+ genel puan', '⭐', 'quality',
        ))

    gk_overall = max((p['overall'] for p in market if 'GK' in p['positions']), default=0)
    for threshold in (80, 82, 84):
        if gk_overall >= threshold:
            groups['quality'].append(_make(
                'gk_overall_min', 1, {'overall': threshold},
                f'Kalecin en az {threshold} genel puan', '🧤', 'quality',
            ))

    for ctype, key, icon, unit, thresholds in (
        ('pace_min', 'pace', '⚡', 'hız', (85, 88)),
        ('passing_min', 'passing', '🎯', 'pas', (85, 88)),
        ('defending_min', 'defending', '🛡️', 'defans', (82, 85)),
    ):
        for threshold in thresholds:
            count = sum(1 for p in market if p.get(key, 0) >= threshold)
            if count >= 4:
                groups['quality'].append(_make(
                    ctype, 2, {'value': threshold},
                    f'En az 2 oyuncu {threshold}+ {unit}', icon, 'quality', unit,
                ))

    left_count = sum(1 for p in market if p.get('preferred_foot', '').lower().startswith('left'))
    if left_count >= 3:
        groups['quality'].append(_make(
            'left_foot', 2, {}, 'En az 2 sol ayaklı oyuncu', '🦶', 'quality',
        ))

    for threshold in (188, 190):
        count = sum(1 for p in market if p.get('height_cm', 0) >= threshold)
        if count >= 3:
            groups['quality'].append(_make(
                'height_min', 2, {'height': threshold},
                f'En az 2 oyuncu {threshold} cm ve üzeri', '📏', 'quality', 'cm',
            ))

    moves_count = sum(1 for p in market if p.get('skill_moves', 0) >= 4)
    if moves_count >= 3:
        groups['quality'].append(_make(
            'skill_moves_min', 2, {'moves': 4},
            'En az 2 oyuncu 4+ skill moves', '✨', 'quality',
        ))

    distinct_leagues = len({p['league'] for p in market if p['league']})
    for target in (5, 6, 7):
        if distinct_leagues >= target:
            groups['shape'].append(_make(
                'distinct_leagues', target, {},
                f'Kadroda en az {target} farklı lig', '🏟️', 'shape',
            ))

    distinct_nations = len({p['nationality'] for p in market if p['nationality']})
    for target in (6, 7, 8):
        if distinct_nations >= target:
            groups['shape'].append(_make(
                'distinct_nations', target, {},
                f'Kadroda en az {target} farklı ülke', '🌐', 'shape',
            ))

    distinct_clubs = len({p['club'] for p in market if p['club']})
    for target in (7, 8):
        if distinct_clubs >= target:
            groups['shape'].append(_make(
                'club_min', target, {},
                f'Kadroda en az {target} farklı kulüp', '🏟️', 'shape',
            ))

    groups['shape'].append(_make(
        'club_max', 2, {}, 'Aynı kulüpten en fazla 2 oyuncu', '🔗', 'shape',
    ))
    groups['shape'].append(_make(
        'nation_max', 3, {}, 'Aynı ülkeden en fazla 3 oyuncu', '🔗', 'shape',
    ))

    return groups


def _contributes(challenge: dict, player: dict, current: list[dict]) -> bool:
    ctype = challenge['type']
    params = challenge.get('params') or {}
    target = challenge['target']
    if ctype == 'nationality_min':
        return player.get('nationality') == params.get('nationality')
    if ctype == 'league_min':
        return player.get('league') == params.get('league')
    if ctype == 'age_under':
        return player.get('age', 99) < params.get('age', 0)
    if ctype == 'age_over':
        return player.get('age', 0) >= params.get('age', 0)
    if ctype == 'overall_min':
        return player.get('overall', 0) >= params.get('overall', 0)
    if ctype == 'gk_overall_min':
        return 'GK' in player.get('positions', ()) and player.get('overall', 0) >= params.get('overall', 0)
    if ctype == 'pace_min':
        return player.get('pace', 0) >= params.get('value', 0)
    if ctype == 'passing_min':
        return player.get('passing', 0) >= params.get('value', 0)
    if ctype == 'defending_min':
        return player.get('defending', 0) >= params.get('value', 0)
    if ctype == 'left_foot':
        return player.get('preferred_foot', '').lower().startswith('left')
    if ctype == 'height_min':
        return player.get('height_cm', 0) >= params.get('height', 0)
    if ctype == 'skill_moves_min':
        return player.get('skill_moves', 0) >= params.get('moves', 0)
    if ctype == 'distinct_leagues':
        return bool(player.get('league')) and player.get('league') not in {p.get('league') for p in current}
    if ctype == 'distinct_nations':
        return bool(player.get('nationality')) and player.get('nationality') not in {p.get('nationality') for p in current}
    if ctype == 'club_min':
        return bool(player.get('club')) and player.get('club') not in {p.get('club') for p in current}
    if ctype == 'age_avg_max':
        return player.get('age', 99) < target
    return False


def challenge_progress(challenge: dict, players: list[dict]) -> dict:
    players = [p for p in (players or []) if p]
    ctype = challenge['type']
    params = challenge.get('params') or {}
    target = challenge['target']
    current = 0

    if ctype == 'nationality_min':
        current = sum(1 for p in players if p.get('nationality') == params.get('nationality'))
    elif ctype == 'league_min':
        current = sum(1 for p in players if p.get('league') == params.get('league'))
    elif ctype == 'age_under':
        current = sum(1 for p in players if p.get('age', 99) < params.get('age', 0))
    elif ctype == 'age_over':
        current = sum(1 for p in players if p.get('age', 0) >= params.get('age', 0))
    elif ctype == 'overall_min':
        current = sum(1 for p in players if p.get('overall', 0) >= params.get('overall', 0))
    elif ctype == 'gk_overall_min':
        current = max((p.get('overall', 0) for p in players if 'GK' in p.get('positions', ())), default=0)
    elif ctype == 'pace_min':
        current = sum(1 for p in players if p.get('pace', 0) >= params.get('value', 0))
    elif ctype == 'passing_min':
        current = sum(1 for p in players if p.get('passing', 0) >= params.get('value', 0))
    elif ctype == 'defending_min':
        current = sum(1 for p in players if p.get('defending', 0) >= params.get('value', 0))
    elif ctype == 'left_foot':
        current = sum(1 for p in players if p.get('preferred_foot', '').lower().startswith('left'))
    elif ctype == 'height_min':
        current = sum(1 for p in players if p.get('height_cm', 0) >= params.get('height', 0))
    elif ctype == 'skill_moves_min':
        current = sum(1 for p in players if p.get('skill_moves', 0) >= params.get('moves', 0))
    elif ctype == 'distinct_leagues':
        current = len({p.get('league') for p in players if p.get('league')})
    elif ctype == 'distinct_nations':
        current = len({p.get('nationality') for p in players if p.get('nationality')})
    elif ctype == 'club_min':
        current = len({p.get('club') for p in players if p.get('club')})
    elif ctype in ('club_max', 'nation_max'):
        key = 'club' if ctype == 'club_max' else 'nationality'
        counts = Counter(p.get(key) for p in players if p.get(key))
        current = max(counts.values(), default=0)
    elif ctype == 'age_avg_max':
        current = round(sum(p.get('age', 0) for p in players) / len(players), 1) if players else 0

    if ctype == 'gk_overall_min':
        # ``target`` is the number of keepers required (always 1); the rating
        # threshold lives in ``params``.
        required = params.get('overall', 0)
        satisfied = current >= required
        detail = f'{current}/{required}'
    elif ctype in ('club_max', 'nation_max', 'age_avg_max'):
        satisfied = bool(players) and current <= target
        if ctype == 'age_avg_max':
            detail = f'{str(current).replace(".", ",")} / {str(target).replace(".", ",")}'
        else:
            detail = f'{current} / {target} sınır'
    else:
        satisfied = current >= target
        detail = f'{current}/{target}'

    return {
        **challenge,
        'current': current,
        'satisfied': satisfied,
        'detail': detail,
    }


def _squad_attempt(
    market: list[dict],
    budget: int,
    challenges: list[dict],
    rng: random.Random,
    reserved: set[int] | None = None,
    *,
    pool_by_slot: dict[str, list[dict]] | None = None,
    with_slots: bool = False,
):
    # Players are unique inside a room, so a second manager must avoid every
    # player already used by the first one.
    used: set[int] = set(reserved or ())
    total = 0
    squad: list[dict] = []
    assignment: list[tuple[dict, dict]] = []
    slots = list(SLOTS)
    rng.shuffle(slots)
    for index, slot in enumerate(slots):
        remaining_slots = len(slots) - index
        remaining_budget = budget - total
        source = pool_by_slot.get(slot['key'], ()) if pool_by_slot is not None else market
        candidates = [
            p for p in source
            if p['player_id'] not in used and slot_accepts(slot['key'], p['positions'])
        ]
        if not candidates:
            return None
        cheapest = min(p['value_eur'] for p in candidates)
        max_price = max(remaining_budget / max(1, remaining_slots) * 1.8, cheapest)
        affordable = [p for p in candidates if p['value_eur'] <= max_price]
        if affordable:
            candidates = affordable
        scored = []
        for player in candidates:
            helps = sum(1 for c in challenges if _contributes(c, player, squad))
            score = helps * 3.0 + rng.random() * 2.0 + (player['overall'] - 70) * 0.05
            score -= player['value_eur'] / max(1, budget) * 2.0
            scored.append((score, player))
        scored.sort(key=lambda item: item[0], reverse=True)
        choice = rng.choice(scored[:5])[1]
        used.add(choice['player_id'])
        total += choice['value_eur']
        squad.append(choice)
        assignment.append((slot, choice))
    if total > budget:
        return None
    if all(challenge_progress(c, squad)['satisfied'] for c in challenges):
        return assignment if with_slots else squad
    return None


def build_pools(
    market: list[dict],
    challenges: list[dict],
    per_slot: int = 90,
) -> dict[str, list[dict]]:
    """Shortlist candidates per formation slot for the auto-squad solver.

    Every slot pool keeps three kinds of players: the strongest overall, the
    cheapest and the ones that help a challenge. That is enough for a good
    squad while keeping the solver fast over the full 15k catalogue.
    """
    helpers = [p for p in market if any(_contributes(c, p, []) for c in challenges)]
    helpers.sort(
        key=lambda p: (p.get('overall', 0), -int(p.get('value_eur') or 0)),
        reverse=True,
    )
    helpers = helpers[: per_slot * 2]

    pools: dict[str, list[dict]] = {}
    for slot in SLOTS:
        candidates = [
            p for p in market
            if slot_accepts(slot['key'], p.get('positions', ()))
        ]
        if not candidates:
            pools[slot['key']] = []
            continue
        stars = sorted(
            candidates,
            key=lambda p: (p.get('overall', 0), -int(p.get('value_eur') or 0)),
            reverse=True,
        )[:per_slot]
        bargains = sorted(
            candidates,
            key=lambda p: (int(p.get('value_eur') or 0), -p.get('overall', 0)),
        )[:per_slot]
        shortlist: dict[int, dict] = {}
        for player in stars + bargains + helpers:
            if slot_accepts(slot['key'], player.get('positions', ())):
                shortlist[player['player_id']] = player
        pools[slot['key']] = list(shortlist.values())
    return pools


def build_squad(
    market: list[dict],
    budget: int,
    challenges: list[dict],
    rng: random.Random,
    *,
    attempts: int = 60,
    reserved: set[int] | None = None,
    pool_by_slot: dict[str, list[dict]] | None = None,
) -> list[tuple[dict, dict]] | None:
    """Return ``[(slot, player), ...]`` satisfying every challenge and the budget.

    Runs several randomised greedy drafts (the same routine used to prove a
    challenge set feasible) and keeps the strongest complete squad. ``None``
    means no attempt produced a legal squad.
    """
    pools = pool_by_slot
    if pools is None and len(market) > 400:
        pools = build_pools(market, challenges)

    best = None
    best_score = -1
    for _ in range(max(1, attempts)):
        squad = _squad_attempt(
            market,
            budget,
            challenges,
            rng,
            reserved=reserved,
            pool_by_slot=pools,
            with_slots=True,
        )
        if not squad:
            continue
        score = sum(player.get('overall', 0) for _slot, player in squad)
        if score > best_score:
            best = squad
            best_score = score
    return best


def cheapest_squad(
    market: list[dict],
    budget: int,
    reserved: set[int] | None = None,
) -> list[tuple[dict, dict]] | None:
    """Last-resort legal squad: the cheapest player for every slot."""
    used: set[int] = set(reserved or ())
    total = 0
    squad: list[tuple[dict, dict]] = []
    for slot in SLOTS:
        candidates = [
            p for p in market
            if p['player_id'] not in used and slot_accepts(slot['key'], p.get('positions', ()))
        ]
        if not candidates:
            return None
        choice = min(candidates, key=lambda p: int(p.get('value_eur') or 0))
        used.add(choice['player_id'])
        total += int(choice.get('value_eur') or 0)
        squad.append((slot, choice))
    return squad if total <= budget else None


def squad_feasible(market: list[dict], budget: int, challenges: list[dict], rng: random.Random, attempts: int = 220) -> bool:
    for _ in range(attempts):
        if _squad_attempt(market, budget, challenges, rng):
            return True
    return False


def two_squads_feasible(
    market: list[dict],
    budget: int,
    challenges: list[dict],
    rng: random.Random,
    attempts: int = 160,
) -> bool:
    """Both managers share one market, so the challenge set must fit twice.

    A challenge can be fine for one squad and still be impossible for the room:
    asking two managers for 2 Argentine-league players needs four such players,
    and each player can only be drafted once. Build two disjoint squads before
    accepting a challenge set.
    """
    for _ in range(attempts):
        first = _squad_attempt(market, budget, challenges, rng)
        if not first:
            continue
        used = {player['player_id'] for player in first}
        if _squad_attempt(market, budget, challenges, rng, reserved=used):
            return True
    return False


def _resolve_conflicts(selected: list[dict], groups: dict[str, list[dict]], rng: random.Random) -> list[dict]:
    """Avoid impossible combinations such as '3 Spanish' + 'max 2 per nation'."""
    nation_max = next((c for c in selected if c['type'] == 'nation_max'), None)
    if nation_max:
        highest_nation_min = max(
            (c['target'] for c in selected if c['type'] == 'nationality_min'),
            default=0,
        )
        if highest_nation_min > nation_max['target']:
            selected.remove(nation_max)
            replacements = [c for c in groups['shape'] if c['type'] in ('distinct_nations', 'distinct_leagues', 'club_min')]
            if replacements:
                selected.append(rng.choice(replacements))
    # Remove duplicate types while keeping one representative.
    seen = set()
    result = []
    for challenge in selected:
        if challenge['type'] in seen:
            continue
        seen.add(challenge['type'])
        result.append(challenge)
    return result


def _fallback(market: list[dict], budget: int, rng: random.Random) -> list[dict]:
    challenges = []
    nations = [n for n, c in _counts(market, 'nationality').most_common(8) if c >= 3]
    leagues = [l for l, c in _counts(market, 'league').most_common(8) if l and c >= 3]
    if nations:
        nation = rng.choice(nations[:5])
        challenges.append(_make(
            'nationality_min', 2, {'nationality': nation},
            f'En az 2 {format_nation(nation)} oyuncu', '🌍', 'identity',
        ))
    if leagues:
        league = rng.choice(leagues[:5])
        challenges.append(_make(
            'league_min', 2, {'league': league},
            f'En az 2 {format_league(league)} oyuncusu', '🏆', 'identity',
        ))
    challenges.append(_make(
        'age_under', 3, {'age': 27},
        'En az 3 oyuncu 27 yaş altı', '🎂', 'age', 'yaş',
    ))
    challenges.append(_make(
        'distinct_nations', 5, {},
        'Kadroda en az 5 farklı ülke', '🌐', 'shape',
    ))
    # Keep trying with progressively smaller sets if the pool is unusual.
    for size in (4, 3, 2):
        subset = challenges[:size]
        if two_squads_feasible(market, budget, subset, rng, attempts=100):
            return subset
    return challenges[:3]


def build_challenges(market: list[dict], budget: int, rng: random.Random) -> list[dict]:
    groups = _candidate_groups(market)
    all_candidates = [c for items in groups.values() for c in items]

    for _ in range(12):
        selected = []
        for group in ('identity', 'age', 'quality', 'shape'):
            pool = groups.get(group) or []
            if pool:
                selected.append(rng.choice(pool))
        if len(selected) < 4:
            remaining = [c for c in all_candidates if c not in selected]
            rng.shuffle(remaining)
            selected.extend(remaining[: 4 - len(selected)])
        selected = _resolve_conflicts(selected, groups, rng)
        if len(selected) < 3:
            continue
        if two_squads_feasible(market, budget, selected, rng):
            return selected

    return _fallback(market, budget, rng)
