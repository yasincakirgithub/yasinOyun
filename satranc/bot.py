"""Stockfish (chess-api.com) destekli bot oyuncular.

Seviyeler, uzak Stockfish API'sinin ``depth`` parametresi ve düşük seviyelerde
devreye giren rastgelelik oranı ile tanımlanır. Böylece gerçek Stockfish
değerlendirmesi kullanılırken seviyeler arasında belirgin güç farkı oluşur.
"""

import logging
import random

import chess

from . import analyzer

logger = logging.getLogger('satranc')

# level: (görünen ad, yaklaşık ELO, arama derinliği, rastgele hamle olasılığı)
LEVELS = [
    {'level': 1, 'name': 'Acemi', 'elo': '~600', 'depth': 1, 'randomness': 0.70},
    {'level': 2, 'name': 'Çaylak', 'elo': '~900', 'depth': 2, 'randomness': 0.55},
    {'level': 3, 'name': 'Kulüp', 'elo': '~1200', 'depth': 4, 'randomness': 0.38},
    {'level': 4, 'name': 'Orta', 'elo': '~1500', 'depth': 6, 'randomness': 0.24},
    {'level': 5, 'name': 'İyi', 'elo': '~1800', 'depth': 9, 'randomness': 0.13},
    {'level': 6, 'name': 'Uzman', 'elo': '~2100', 'depth': 12, 'randomness': 0.06},
    {'level': 7, 'name': 'Usta', 'elo': '~2400', 'depth': 15, 'randomness': 0.02},
    {'level': 8, 'name': 'Stockfish', 'elo': '~2700+', 'depth': 18, 'randomness': 0.0},
]

LEVEL_MAP = {item['level']: item for item in LEVELS}
DEFAULT_LEVEL = 4
MAX_LEVEL = max(LEVEL_MAP)


def level_config(level):
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = DEFAULT_LEVEL
    level = min(max(level, 1), MAX_LEVEL)
    return LEVEL_MAP[level]


def bot_name(level):
    config = level_config(level)
    return f"Stockfish {config['name']} (Sv.{config['level']})"


def choose_move(fen, level):
    """Verilen pozisyon için botun oynayacağı UCI hamlesini döndürür."""
    try:
        board = chess.Board(fen)
    except ValueError:
        return None

    legal = list(board.legal_moves)
    if not legal:
        return None

    config = level_config(level)

    if config['randomness'] and random.random() < config['randomness']:
        return random.choice(legal).uci()

    analysis = analyzer.analyze_position(
        fen,
        depth=config['depth'],
        thinking_time=50,
    )
    best = analysis.get('best')
    if best:
        try:
            move = chess.Move.from_uci(best)
        except ValueError:
            move = None
        if move in board.legal_moves:
            return best

    logger.warning('Bot en iyi hamleyi alamadı (seviye %s), rastgele oynuyor.', level)
    return random.choice(legal).uci()
