"""101 Okey kuralları.

Bu modül tamamen saf Python fonksiyonlarından oluşur; Django modellerine
dokunmaz. Böylece kurallar hem WebSocket tüketicisinde hem de testlerde
kullanılabilir.

Taş gösterimi::

    {'id': 'r7a', 'color': 'r', 'number': 7, 'fake': False}

Renkler: ``r`` kırmızı, ``y`` sarı, ``b`` mavi, ``k`` siyah.
Sahte okey: ``{'id': 'fake1', 'color': '', 'number': 0, 'fake': True}``.
"""

import itertools
import random

COLORS = ('r', 'y', 'b', 'k')
COLOR_NAMES = {
    'r': 'Kırmızı',
    'y': 'Sarı',
    'b': 'Mavi',
    'k': 'Siyah',
}
COLOR_ORDER = {color: index for index, color in enumerate(COLORS)}

OPENING_POINTS = 101
OPENING_PAIRS = 5
WILD_HAND_VALUE = 101


def team_for_seat(seat):
    """Eşli modda çapraz takım: 0-2 A, 1-3 B."""
    return 'A' if int(seat) % 2 == 0 else 'B'


# ---------------------------------------------------------------------------
# Deste / gösterge / okey
# ---------------------------------------------------------------------------
def build_deck():
    """106 taşlık desteyi üretir (104 sayılı taş + 2 sahte okey)."""
    deck = []
    for color in COLORS:
        for number in range(1, 14):
            for copy in ('a', 'b'):
                deck.append({
                    'id': f'{color}{number}{copy}',
                    'color': color,
                    'number': number,
                    'fake': False,
                })
    deck.append({'id': 'fake1', 'color': '', 'number': 0, 'fake': True})
    deck.append({'id': 'fake2', 'color': '', 'number': 0, 'fake': True})
    return deck


def shuffle_deck():
    deck = build_deck()
    random.shuffle(deck)
    return deck


def okey_for(indicator):
    """Gösterge taşından okeyi hesaplar (13'ün üstü 1'dir)."""
    if not indicator or indicator.get('fake'):
        return None
    number = indicator['number'] % 13 + 1
    return {'color': indicator['color'], 'number': number}


def is_wild(tile, okey):
    """Taş joker (doğal okey veya sahte okey) mi?"""
    if not tile:
        return False
    if tile.get('fake'):
        return True
    if not okey:
        return False
    return tile.get('color') == okey.get('color') and tile.get('number') == okey.get('number')


def real_tiles(tiles, okey):
    return [tile for tile in tiles if not is_wild(tile, okey)]


def wild_tiles(tiles, okey):
    return [tile for tile in tiles if is_wild(tile, okey)]


def tile_number(tile):
    return int(tile.get('number') or 0)


# ---------------------------------------------------------------------------
# Per doğrulama
# ---------------------------------------------------------------------------
def evaluate_meld(tiles, okey):
    """Bir taş grubunu doğrular.

    Döner: ``{'kind', 'score', 'ordered', 'color'? , 'number'?}`` ya da
    geçersizse ``None``. ``ordered`` perin tahtada gösterilecek sırasıdır.
    """
    if not isinstance(tiles, list) or len(tiles) < 2:
        return None
    if len({tile.get('id') for tile in tiles}) != len(tiles):
        return None

    real = real_tiles(tiles, okey)
    wild = wild_tiles(tiles, okey)
    if not real:
        return None

    if len(tiles) == 2:
        return _evaluate_pair(tiles, real, wild)
    if len(tiles) > 13:
        return None

    candidates = []
    group = _evaluate_group(tiles, real, wild)
    if group:
        candidates.append(group)
    run = _evaluate_run(tiles, real, wild)
    if run:
        candidates.append(run)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item['score'])


def _evaluate_pair(tiles, real, wild):
    if len(real) == 2:
        first, second = real
        if (
            first.get('color') != second.get('color')
            or tile_number(first) != tile_number(second)
        ):
            return None
        number = tile_number(first)
        return {
            'kind': 'pair',
            'score': number * 2,
            'ordered': [first, second],
            'color': first.get('color'),
            'number': number,
        }
    if len(real) == 1 and len(wild) == 1:
        number = tile_number(real[0])
        return {
            'kind': 'pair',
            'score': number * 2,
            'ordered': [real[0], wild[0]],
            'color': real[0].get('color'),
            'number': number,
        }
    return None


def _evaluate_group(tiles, real, wild):
    if not 3 <= len(tiles) <= 4:
        return None
    numbers = {tile_number(tile) for tile in real}
    if len(numbers) != 1:
        return None
    colors = {tile.get('color') for tile in real}
    if len(colors) != len(real):
        return None
    if len(colors) + len(wild) < len(tiles):
        return None
    if len(tiles) > 4:
        return None

    number = next(iter(numbers))
    ordered = sorted(real, key=lambda tile: COLOR_ORDER.get(tile.get('color'), 99))
    ordered += wild
    return {
        'kind': 'group',
        'score': number * len(tiles),
        'ordered': ordered,
        'number': number,
    }


def _evaluate_run(tiles, real, wild):
    if not 3 <= len(tiles) <= 13:
        return None
    colors = {tile.get('color') for tile in real}
    if len(colors) != 1:
        return None
    color = next(iter(colors))
    numbers = [tile_number(tile) for tile in real]
    if len(set(numbers)) != len(numbers):
        return None

    best = None
    length = len(tiles)
    for start in range(1, 14 - length + 1):
        window = list(range(start, start + length))
        if any(number not in window for number in numbers):
            continue
        score = sum(window)
        if best is None or score > best['score']:
            by_number = {tile_number(tile): tile for tile in real}
            remaining_wild = list(wild)
            ordered = []
            for number in window:
                if number in by_number:
                    ordered.append(by_number[number])
                elif remaining_wild:
                    ordered.append(remaining_wild.pop(0))
                else:
                    ordered = []
                    break
            if not ordered:
                continue
            best = {
                'kind': 'run',
                'score': score,
                'ordered': ordered,
                'color': color,
                'start': start,
                'end': window[-1],
            }
    return best


def validate_melds(tiles_by_id, meld_id_groups, okey, points_threshold, pairs_threshold):
    """Açılış için verilen perleri doğrular.

    ``tiles_by_id``: taş id -> taş sözlüğü
    ``meld_id_groups``: ``[['r5a', 'r6a', 'r7a'], ...]``
    """
    if not isinstance(meld_id_groups, list) or not meld_id_groups:
        return None, 'En az bir per seçmelisin.'

    seen = set()
    evaluations = []
    pairs = 0
    total = 0

    for group in meld_id_groups:
        if not isinstance(group, list) or len(group) < 2:
            return None, 'Per en az iki taştan oluşmalı.'
        if len({tile_id for tile_id in group}) != len(group):
            return None, 'Aynı taş birden fazla perde kullanılamaz.'
        if any(tile_id not in tiles_by_id for tile_id in group):
            return None, 'Perde elinde olmayan bir taş var.'
        if any(tile_id in seen for tile_id in group):
            return None, 'Aynı taş birden fazla perde kullanılamaz.'

        tiles = [tiles_by_id[tile_id] for tile_id in group]
        evaluation = evaluate_meld(tiles, okey)
        if not evaluation:
            return None, 'Seçilen taşlar geçerli bir seri, grup veya çift oluşturmuyor.'

        seen.update(group)
        evaluations.append(evaluation)
        total += evaluation['score']
        if evaluation['kind'] == 'pair':
            pairs += 1

    has_pair = any(item['kind'] == 'pair' for item in evaluations)
    has_other = any(item['kind'] != 'pair' for item in evaluations)
    if has_pair and has_other:
        return None, 'Aynı açılışta çiftlerle seri/grup karıştırılamaz.'

    if has_pair:
        if len(evaluations) < pairs_threshold:
            return None, f'Çiftle açmak için en az {pairs_threshold} çift gerekir.'
        return {
            'route': 'pairs',
            'total': total,
            'pairs': len(evaluations),
            'evaluations': evaluations,
        }, None

    if total < points_threshold:
        return None, (
            f'Açmak için en az {points_threshold} puan gerekir '
            f'(seçilen toplam: {total}).'
        )
    return {
        'route': 'points',
        'total': total,
        'pairs': 0,
        'evaluations': evaluations,
    }, None


def can_extend_meld(meld_kind, meld_tiles, tile, okey):
    """Taş mevcut bir pere eklenebilir mi? Yeni sıralamayı döndürür."""
    if meld_kind == 'pair':
        return None
    merged = list(meld_tiles) + [tile]
    evaluation = evaluate_meld(merged, okey)
    if not evaluation or evaluation['kind'] != meld_kind:
        return None
    return evaluation


# ---------------------------------------------------------------------------
# Aday perler / otomatik açılış yardımı
# ---------------------------------------------------------------------------
def find_meld_candidates(hand, okey):
    """Eldeki tüm geçerli seri/grup/çift adaylarını üretir.

    Aynı taşların farklı sıralamalarla tekrar üretilmemesi için kimlik
    kümesine göre tekilleştirilir. Bu fonksiyon otomatik açılış ve "alınan
    taş işe yarıyor mu?" kontrollerinde kullanılır.
    """
    hand = list(hand)
    wild = wild_tiles(hand, okey)
    real = real_tiles(hand, okey)
    candidates = []
    seen = set()

    def add(tiles, kind=None):
        evaluation = evaluate_meld(tiles, okey)
        if not evaluation:
            return
        if kind and evaluation['kind'] != kind:
            return
        key = (evaluation['kind'], tuple(sorted(tile['id'] for tile in tiles)))
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            'kind': evaluation['kind'],
            'score': evaluation['score'],
            'tiles': [tile['id'] for tile in evaluation['ordered']],
            'tile_objects': evaluation['ordered'],
            'evaluation': evaluation,
        })

    # Çiftler
    by_identity = {}
    for tile in real:
        key = (tile.get('color'), tile_number(tile))
        by_identity.setdefault(key, []).append(tile)
    for tiles in by_identity.values():
        if len(tiles) >= 2:
            add(tiles[:2], 'pair')
    for tile in real:
        if wild:
            add([tile, wild[0]], 'pair')

    # Gruplar
    by_number = {}
    for tile in real:
        by_number.setdefault(tile_number(tile), {})
        by_number[tile_number(tile)].setdefault(tile.get('color'), tile)
    for number, colors in by_number.items():
        base = list(colors.values())
        if len(base) >= 3:
            for size in range(3, min(4, len(base)) + 1):
                for combo in itertools.combinations(base, size):
                    add(list(combo), 'group')
            if len(base) == 3 and wild:
                add(base + [wild[0]], 'group')
        elif len(base) == 2 and wild:
            add(base + [wild[0]], 'group')
        elif len(base) == 1 and len(wild) >= 2:
            add(base + wild[:2], 'group')

    # Seriler
    by_color_number = {}
    for tile in real:
        by_color_number.setdefault(tile.get('color'), {})
        by_color_number[tile.get('color')].setdefault(tile_number(tile), tile)
    for color, numbers in by_color_number.items():
        for length in range(3, 14):
            for start in range(1, 14 - length + 1):
                window = list(range(start, start + length))
                present = [numbers[number] for number in window if number in numbers]
                missing = length - len(present)
                if not present or missing < 0 or missing > len(wild):
                    continue
                add(present + wild[:missing], 'run')

    candidates.sort(key=lambda item: (item['score'], len(item['tiles'])), reverse=True)
    return candidates


def _greedy_disjoint(candidates):
    used = set()
    chosen = []
    total = 0
    for candidate in candidates:
        ids = set(candidate['tiles'])
        if ids & used:
            continue
        used.update(ids)
        chosen.append(candidate)
        total += candidate['score']
    return chosen, total


def max_disjoint_pairs(hand, okey):
    """Eldeki en fazla çift sayısı (jokerler dahil)."""
    pairs = [
        candidate
        for candidate in find_meld_candidates(hand, okey)
        if candidate['kind'] == 'pair'
    ]
    chosen, _ = _greedy_disjoint(pairs)
    return len(chosen)


def best_opening(
    hand,
    okey,
    points_threshold,
    pairs_threshold,
    attempts=24,
    required_tile_id=None,
):
    """Elden açılabilecek en iyi kombinasyonu arar (greedy + rastgele deneme)."""
    if required_tile_id:
        opening = best_opening(
            hand,
            okey,
            points_threshold,
            pairs_threshold,
            attempts=attempts,
        )
        if opening and any(
            required_tile_id in group for group in opening['melds']
        ):
            return opening

    candidates = find_meld_candidates(hand, okey)
    pairs = [c for c in candidates if c['kind'] == 'pair']
    melds = [c for c in candidates if c['kind'] != 'pair']
    hand_ids = {tile['id'] for tile in hand}

    def leaves_discard(chosen):
        used = {tile_id for candidate in chosen for tile_id in candidate['tiles']}
        return len(used) < len(hand_ids)

    def required_candidates(pool):
        if not required_tile_id:
            return [None]
        return [candidate for candidate in pool if required_tile_id in candidate['tiles']]

    def search(pool, route):
        best = None
        for required in required_candidates(pool):
            for attempt in range(max(1, attempts)):
                order = [candidate for candidate in pool if candidate is not required]
                if attempt:
                    random.shuffle(order)
                    order.sort(
                        key=lambda item: item['score'] * random.uniform(0.7, 1.3),
                        reverse=True,
                    )
                chosen = [required] if required else []
                used = set(required['tiles']) if required else set()
                for candidate in order:
                    ids = set(candidate['tiles'])
                    if ids & used:
                        continue
                    used.update(ids)
                    chosen.append(candidate)
                if not chosen or not leaves_discard(chosen):
                    continue
                total = sum(candidate['score'] for candidate in chosen)
                if route == 'pairs':
                    if len(chosen) < pairs_threshold:
                        continue
                    key = (len(chosen), total)
                    if best is None or key > best[0]:
                        best = (key, chosen)
                elif total >= points_threshold:
                    if best is None or total > best[0][0]:
                        best = ((total,), chosen)
        if best is None:
            return None
        chosen = best[1]
        if route == 'pairs':
            return {
                'route': 'pairs',
                'melds': [c['tiles'] for c in chosen],
                'total': sum(c['score'] for c in chosen),
                'pairs': len(chosen),
            }
        return {
            'route': 'points',
            'melds': [c['tiles'] for c in chosen],
            'total': sum(c['score'] for c in chosen),
            'pairs': 0,
        }

    pair_opening = search(pairs, 'pairs') if pairs else None
    point_opening = search(melds, 'points') if melds else None
    if pair_opening is None:
        return point_opening
    if point_opening and point_opening['total'] > pair_opening['total']:
        return point_opening
    return pair_opening


def tile_can_be_melded(hand, tile, okey):
    """Taş eldeki diğer taşlarla en az bir per oluşturabiliyor mu?"""
    combined = list(hand)
    if not any(existing['id'] == tile['id'] for existing in combined):
        combined.append(tile)
    candidates = find_meld_candidates(combined, okey)
    return any(tile['id'] in candidate['tiles'] for candidate in candidates)


# ---------------------------------------------------------------------------
# Dağıtım
# ---------------------------------------------------------------------------
def deal_round(seats, starter_seat):
    """Yeni el için taşları dağıtır.

    Döner: ``(hands, stock, indicator, okey)``; ``hands`` seat -> taş listesi.
    """
    deck = shuffle_deck()

    indicator_index = next(
        (index for index, tile in enumerate(deck) if not tile.get('fake')),
        0,
    )
    indicator = deck.pop(indicator_index)
    okey = okey_for(indicator)

    seats = list(seats)
    order = []
    if seats:
        if starter_seat not in seats:
            starter_seat = seats[0]
        start_index = seats.index(starter_seat)
        order = seats[start_index:] + seats[:start_index]

    hands = {seat: [] for seat in order}
    for _ in range(21):
        for seat in order:
            if deck:
                hands[seat].append(deck.pop())
    if order and deck:
        hands[order[0]].append(deck.pop())

    for seat in hands:
        hands[seat].sort(key=_tile_sort_key)

    return hands, deck, indicator, okey


def _tile_sort_key(tile):
    if tile.get('fake'):
        return (99, 0, tile.get('id', ''))
    return (
        COLOR_ORDER.get(tile.get('color'), 99),
        tile_number(tile),
        tile.get('id', ''),
    )


def sort_hand(hand):
    """Eldeki taşları renk/sayı sırasına göre dizer (yerinde)."""
    hand.sort(key=_tile_sort_key)
    return hand


def next_seat(seats, current):
    seats = sorted(seats)
    if not seats:
        return None
    if current not in seats:
        return seats[0]
    index = seats.index(current)
    return seats[(index + 1) % len(seats)]


# ---------------------------------------------------------------------------
# Puanlama
# ---------------------------------------------------------------------------
def hand_value(hand, okey=None):
    """Elde kalan taşların ceza değeri (okey/joker 101 sayılır)."""
    total = 0
    for tile in hand:
        if is_wild(tile, okey) or tile.get('fake'):
            total += WILD_HAND_VALUE
        else:
            total += tile_number(tile)
    return total


def round_multiplier(elden=False, okey_discard=False, pairs_finish=False):
    multiplier = 1
    if elden:
        multiplier *= 2
    if okey_discard:
        multiplier *= 2
    if pairs_finish:
        multiplier *= 2
    return multiplier


def score_round(players, winner_seat, multiplier, rules=None):
    """El sonu ceza puanlarını hesaplar.

    ``rules`` ile ceza ve katlama özellikleri kapatılabilir.
    """
    rules = rules or {}
    penalties_enabled = rules.get('penalties_enabled', True)
    multipliers_enabled = rules.get('multipliers_enabled', True)
    if not multipliers_enabled:
        multiplier = 1

    opened_by_anyone = any(player.get('opened') for player in players)
    results = []
    for player in players:
        seat = player['seat']
        penalty = int(player.get('penalty') or 0) if penalties_enabled else 0
        value = hand_value(player.get('hand') or [], player.get('okey'))
        if winner_seat is not None and seat == winner_seat:
            score = -101 * multiplier
        elif not player.get('opened'):
            if winner_seat is None and not opened_by_anyone:
                score = 0
            else:
                score = (202 * multiplier) if penalties_enabled else 0
        else:
            if player.get('route') == 'pairs' and multipliers_enabled:
                value *= 2
            score = value * multiplier
        results.append({
            'seat': seat,
            'name': player.get('name') or f'Oyuncu {seat + 1}',
            'opened': bool(player.get('opened')),
            'route': player.get('route') or '',
            'hand_value': value,
            'penalty': penalty,
            'score': score + penalty,
        })
    return results
