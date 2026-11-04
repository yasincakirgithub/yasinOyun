"""Bilardo oyunu için sunucu tarafı yardımcıları.

Fizik istemcide çalışır (canvas üzerinde 60 FPS animasyon için). Sunucu ise
odanın başlangıç dizilimini, mod kurallarını ve oyuncu sırasını tutar. Bu
dosyadaki sabitler istemcideki ``physics.js`` dosyasıyla aynı masa ölçülerini
kullanır; böylece iki taraf da aynı koordinat sisteminde konuşur.
"""

from __future__ import annotations

import math

TABLE_WIDTH = 240.0
TABLE_HEIGHT = 120.0
BALL_RADIUS = 2.7
HEAD_SPOT_X = 60.0
FOOT_SPOT_X = 180.0
CENTER_Y = 60.0
RACK_SPACING = 5.4
RACK_ROW = RACK_SPACING * math.sqrt(3) / 2


MODES = {
    'three_cushion': {
        'id': 'three_cushion',
        'name': '3 Bant',
        'short': '3 Bant',
        'tag': 'Karambol',
        'description': (
            'Topa vurmadan önce en az üç bant kullan, iki hedef topa da dokun '
            've sayı kazan. Sıra sende kalırsa seri yaparsın.'
        ),
        'targets': [5, 10, 15, 20],
        'default_target': 10,
        'pockets': False,
        'ball_count': 3,
    },
    'eight_ball': {
        'id': 'eight_ball',
        'name': '8 Top',
        'short': '8 Top',
        'tag': 'Amerikan',
        'description': (
            'Düz ve çizgili topları paylaş, kendi grubunu temizle ve son '
            'olarak 8 topu deliğe sok. Faul yaparsan rakibin elinde top olur.'
        ),
        'targets': [1],
        'default_target': 1,
        'pockets': True,
        'ball_count': 16,
    },
    'nine_ball': {
        'id': 'nine_ball',
        'name': '9 Top',
        'short': '9 Top',
        'tag': 'Hızlı',
        'description': (
            'Her vuruşta masadaki en küçük numaralı topa ilk önce dokun. '
            '9 topu deliğe sokan oyunu kazanır.'
        ),
        'targets': [1],
        'default_target': 1,
        'pockets': True,
        'ball_count': 10,
    },
    'straight': {
        'id': 'straight',
        'name': 'Düz Bilardo',
        'short': 'Düz',
        'tag': 'Puan',
        'description': (
            'Her delik bir sayı. Hedef puana ilk ulaşan kazanır; delik '
            'yapmaya devam ettiğin sürece masada kalırsın.'
        ),
        'targets': [10, 20, 30, 50],
        'default_target': 20,
        'pockets': True,
        'ball_count': 16,
    },
}

DEFAULT_MODE = 'three_cushion'

CUES = [
    {
        'id': 'klasik',
        'name': 'Klasik Ahşap',
        'subtitle': 'Dengeli başlangıç',
        'description': 'Her oyuna uyum sağlayan, dengeli güç ve falso.',
        'power': 0.55,
        'spin': 0.55,
        'control': 0.60,
        'color': '#b7793f',
        'accent': '#f2c14e',
    },
    {
        'id': 'karbon',
        'name': 'Karbon Pro',
        'subtitle': 'Güç odaklı',
        'description': 'Sert vuruşlarda topa daha fazla hız aktarır.',
        'power': 0.92,
        'spin': 0.48,
        'control': 0.55,
        'color': '#334155',
        'accent': '#67e8f9',
    },
    {
        'id': 'turnuva',
        'name': 'Turnuva Serisi',
        'subtitle': 'Falso ustası',
        'description': 'Yan ve üst-alt falsoyu daha uzun süre korur.',
        'power': 0.62,
        'spin': 0.95,
        'control': 0.68,
        'color': '#7c2d12',
        'accent': '#fb923c',
    },
    {
        'id': 'kontrol',
        'name': 'Kontrol Ustası',
        'subtitle': 'Hassas nişan',
        'description': 'Uzun nişan kılavuzu ve yumuşak hız kontrolü.',
        'power': 0.45,
        'spin': 0.60,
        'control': 0.95,
        'color': '#1e3a5f',
        'accent': '#93c5fd',
    },
    {
        'id': 'efsane',
        'name': 'Efsane',
        'subtitle': 'Her yönüyle güçlü',
        'description': 'Güç, falso ve kontrolü bir arada sunan özel isteka.',
        'power': 0.84,
        'spin': 0.84,
        'control': 0.84,
        'color': '#4c1d95',
        'accent': '#c4b5fd',
    },
]

CUE_BY_ID = {cue['id']: cue for cue in CUES}
DEFAULT_CUE = 'klasik'

BALL_COLORS = {
    1: '#f5c542',
    2: '#2f80ed',
    3: '#eb5757',
    4: '#9b51e0',
    5: '#f2994a',
    6: '#27ae60',
    7: '#8e3b3b',
    8: '#1f2937',
    9: '#f5c542',
    10: '#2f80ed',
    11: '#eb5757',
    12: '#9b51e0',
    13: '#f2994a',
    14: '#27ae60',
    15: '#8e3b3b',
}


def get_mode(mode_id: str):
    return MODES.get(mode_id)


def validate_target(mode_id: str, raw_target) -> int:
    mode = get_mode(mode_id)
    if not mode:
        return MODES[DEFAULT_MODE]['default_target']
    try:
        target = int(raw_target)
    except (TypeError, ValueError):
        return mode['default_target']
    if target not in mode['targets']:
        return mode['default_target']
    return target


def validate_cue(raw_cue) -> str:
    return raw_cue if raw_cue in CUE_BY_ID else DEFAULT_CUE


def _ball(number, x, y, *, stripe=False, kind='object', color=None):
    return {
        'id': number,
        'number': number,
        'x': round(x, 3),
        'y': round(y, 3),
        'color': color or BALL_COLORS.get(number, '#e2e8f0'),
        'stripe': stripe,
        'type': kind,
        'pocketed': False,
    }


def _triangle_balls(numbers):
    balls = []
    index = 0
    for row in range(5):
        count = row + 1
        x = FOOT_SPOT_X + row * RACK_ROW
        for slot in range(count):
            y = CENTER_Y + (slot - (count - 1) / 2) * RACK_SPACING
            number = numbers[index]
            balls.append(_ball(number, x, y, stripe=number > 8))
            index += 1
    return balls


def _diamond_balls(numbers):
    balls = []
    index = 0
    for row, count in enumerate([1, 2, 3, 2, 1]):
        x = FOOT_SPOT_X + row * RACK_ROW
        for slot in range(count):
            y = CENTER_Y + (slot - (count - 1) / 2) * RACK_SPACING
            balls.append(_ball(numbers[index], x, y, stripe=numbers[index] > 8))
            index += 1
    return balls


def initial_balls(mode_id: str):
    cue = _ball(0, HEAD_SPOT_X, CENTER_Y, kind='cue', color='#f8fafc')

    if mode_id == 'three_cushion':
        return [
            cue,
            _ball(1, FOOT_SPOT_X, CENTER_Y, color='#eb5757'),
            _ball(2, TABLE_WIDTH / 2, CENTER_Y, color='#f5c542'),
        ]

    if mode_id == 'nine_ball':
        return [cue] + _diamond_balls([1, 2, 3, 4, 9, 5, 6, 7, 8])

    # 8 top ve düz bilardo aynı üçgen dizilimi kullanır. 8 top üçüncü sıranın
    # ortasında, arka köşelerde ise bir düz bir çizgili top olacak şekilde.
    rack = [1, 9, 2, 3, 8, 10, 11, 4, 12, 5, 6, 13, 7, 14, 15]
    return [cue] + _triangle_balls(rack)


def create_initial_state(mode_id: str, target: int, breaker: int = 0):
    breaker = 0 if breaker not in (0, 1) else breaker
    state = {
        'mode': mode_id,
        'target': target,
        'breaker': breaker,
        'balls': initial_balls(mode_id),
        'scores': [0, 0],
        'turn': breaker,
        'ball_in_hand': False,
        'break': True,
        'groups': [None, None],
        'winner': None,
        'shot_count': 0,
        'message': 'Oyun başladı. İlk vuruşu yap.',
        'last_shot': None,
        'history': [],
        'pending': None,
    }
    return state


def _is_free(balls, x, y, ignore_id=None):
    for ball in balls:
        if ball.get('pocketed'):
            continue
        if ignore_id is not None and ball.get('id') == ignore_id:
            continue
        dx = float(ball.get('x', 0)) - x
        dy = float(ball.get('y', 0)) - y
        if dx * dx + dy * dy < (BALL_RADIUS * 2.05) ** 2:
            return False
    return True


def sanitize_state(previous, incoming):
    """İstemciden gelen son durumu güvenli/geçerli bir şekle sokar.

    Oyun dostane oynandığı için otorite istemcide; yine de koordinatları,
    skorları ve top kimliklerini sunucu tarafında sınırlıyoruz.
    """

    if not isinstance(incoming, dict):
        return previous

    prev_balls = {ball['id']: ball for ball in previous.get('balls', [])}
    incoming_balls = incoming.get('balls')
    if not isinstance(incoming_balls, list):
        incoming_balls = []

    balls = []
    for item in incoming_balls:
        if not isinstance(item, dict):
            continue
        ball_id = item.get('id')
        if ball_id not in prev_balls:
            continue
        base = dict(prev_balls[ball_id])
        try:
            x = float(item.get('x', base['x']))
            y = float(item.get('y', base['y']))
        except (TypeError, ValueError):
            x, y = base['x'], base['y']
        base['x'] = round(min(max(x, BALL_RADIUS), TABLE_WIDTH - BALL_RADIUS), 3)
        base['y'] = round(min(max(y, BALL_RADIUS), TABLE_HEIGHT - BALL_RADIUS), 3)
        base['pocketed'] = bool(item.get('pocketed', base.get('pocketed', False)))
        balls.append(base)

    # Eksik topları önceki halleriyle koru.
    if len(balls) != len(prev_balls):
        seen = {ball['id'] for ball in balls}
        for ball_id, base in prev_balls.items():
            if ball_id not in seen:
                balls.append(dict(base))

    mode = previous.get('mode')
    target = int(previous.get('target') or 1)

    def _clamp_score(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return max(0, min(value, target))

    raw_scores = incoming.get('scores') or [0, 0]
    scores = [_clamp_score(raw_scores[0] if len(raw_scores) > 0 else 0),
              _clamp_score(raw_scores[1] if len(raw_scores) > 1 else 0)]

    turn = incoming.get('turn', previous.get('turn', 0))
    turn = 1 if turn == 1 else 0

    winner = incoming.get('winner')
    winner = winner if winner in (0, 1) else None

    groups = incoming.get('groups') or [None, None]
    clean_groups = []
    for value in groups[:2]:
        clean_groups.append(value if value in ('solids', 'stripes') else None)
    while len(clean_groups) < 2:
        clean_groups.append(None)

    history = incoming.get('history')
    if not isinstance(history, list):
        history = previous.get('history', [])
    clean_history = []
    for entry in history[-30:]:
        if not isinstance(entry, dict):
            continue
        clean_history.append({
            'seat': entry.get('seat') if entry.get('seat') in (0, 1) else 0,
            'message': str(entry.get('message', ''))[:220],
            'foul': bool(entry.get('foul')),
            'pocketed': [int(n) for n in entry.get('pocketed', []) if isinstance(n, int)][:16],
        })

    last_shot = incoming.get('last_shot')
    if not isinstance(last_shot, dict):
        last_shot = None
    else:
        last_shot = {
            'seat': last_shot.get('seat') if last_shot.get('seat') in (0, 1) else 0,
            'message': str(last_shot.get('message', ''))[:220],
            'foul': bool(last_shot.get('foul')),
            'pocketed': [int(n) for n in last_shot.get('pocketed', []) if isinstance(n, int)][:16],
        }

    message = str(incoming.get('message') or previous.get('message') or '')[:220]

    return {
        'mode': mode,
        'target': target,
        'breaker': previous.get('breaker', 0),
        'balls': balls,
        'scores': scores,
        'turn': turn,
        'ball_in_hand': bool(incoming.get('ball_in_hand', False)),
        'break': bool(incoming.get('break', False)),
        'groups': clean_groups,
        'winner': winner,
        'shot_count': int(previous.get('shot_count', 0)) + 1,
        'message': message,
        'last_shot': last_shot,
        'history': clean_history,
        'pending': None,
    }


def cue_ball_in_state(state):
    for ball in state.get('balls', []):
        if ball.get('id') == 0:
            return ball
    return None


def place_cue_ball(state, x, y):
    cue = cue_ball_in_state(state)
    if not cue:
        return False, 'İsteka topu bulunamadı.'
    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return False, 'Geçersiz top konumu.'
    x = min(max(x, BALL_RADIUS), TABLE_WIDTH - BALL_RADIUS)
    y = min(max(y, BALL_RADIUS), TABLE_HEIGHT - BALL_RADIUS)
    if not _is_free(state.get('balls', []), x, y, ignore_id=0):
        return False, 'Bu konumda başka bir top var.'
    cue['x'] = round(x, 3)
    cue['y'] = round(y, 3)
    cue['pocketed'] = False
    return True, ''


def free_spot(balls, preferred_x=FOOT_SPOT_X, preferred_y=CENTER_Y):
    """Bir topu yeniden yerleştirmek için boş nokta bulur."""

    candidates = [(preferred_x, preferred_y)]
    for step in range(1, 30):
        candidates.append((preferred_x - step * RACK_SPACING, preferred_y))
        candidates.append((preferred_x + step * RACK_SPACING, preferred_y))
        candidates.append((preferred_x, preferred_y + step * RACK_SPACING))
        candidates.append((preferred_x, preferred_y - step * RACK_SPACING))
    for x, y in candidates:
        x = min(max(x, BALL_RADIUS), TABLE_WIDTH - BALL_RADIUS)
        y = min(max(y, BALL_RADIUS), TABLE_HEIGHT - BALL_RADIUS)
        if _is_free(balls, x, y):
            return x, y
    return preferred_x, preferred_y
