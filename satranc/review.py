"""Oyun incelemesi: her hamleyi Stockfish API ile değerlendirir.

Her pozisyon için tek bir analiz yapılır; ardından hamle öncesi/sonrası skorlar
oyuncunun bakış açısına çevrilerek centipawn kaybı, hamle sınıfı ve doğruluk
(accuracy) yüzdesi hesaplanır.
"""

import math
import os
from concurrent.futures import ThreadPoolExecutor

import chess
from django.conf import settings

from . import analyzer

# Sınıflandırma eşikleri (centipawn kaybı).
INACCURACY_LOSS = 80
MISTAKE_LOSS = 150
BLUNDER_LOSS = 300

CLASSIFICATION_LABELS = {
    'best': 'En iyi',
    'excellent': 'Mükemmel',
    'good': 'İyi',
    'inaccuracy': 'Yanlışlık',
    'mistake': 'Hata',
    'blunder': 'Vahim hata',
}


def _review_depth():
    return int(getattr(settings, 'SATRANC_REVIEW_DEPTH', 10))


def _review_thinking_time():
    return int(getattr(settings, 'SATRANC_REVIEW_THINKING_TIME', 50))


def _workers():
    return max(1, int(getattr(settings, 'SATRANC_REVIEW_WORKERS', 2)))


def _clamp(value, low, high):
    return max(low, min(high, value))


def _pov_cp(analysis, color):
    """Analizi verilen rengin bakış açısına göre centipawn'a çevirir."""
    if not analysis:
        return None
    sign = 1 if color == 'w' else -1

    mate = analysis.get('mate')
    if mate is not None:
        value = 10000 - min(abs(mate), 20) * 100
        return sign * (value if mate > 0 else -value)

    cp = analysis.get('cp')
    return None if cp is None else cp * sign


def _win_percent(cp):
    """Lichess formülüyle centipawn'ı kazanma yüzdesine çevirir."""
    if cp is None:
        return None
    cp = _clamp(cp, -1000, 1000)
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _accuracy(win_before, win_after):
    if win_before is None or win_after is None:
        return None
    loss = max(0.0, win_before - win_after)
    value = 103.1668 * math.exp(-0.04354 * loss) - 3.1669
    return round(_clamp(value, 0.0, 100.0), 1)


def classify(loss, is_best=False):
    if loss is None:
        return 'unknown'
    if is_best:
        return 'best'
    if loss <= 10:
        return 'excellent'
    if loss <= 40:
        return 'good'
    if loss <= INACCURACY_LOSS:
        return 'inaccuracy'
    if loss <= MISTAKE_LOSS:
        return 'mistake'
    return 'blunder'


def _san_for_uci(fen, uci):
    if not uci:
        return None
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            return board.san(move)
    except (ValueError, AssertionError):
        pass
    return None


def _summary(moves):
    summary = {}
    for color in ('w', 'b'):
        entries = [m for m in moves if m['color'] == color]
        accuracies = [m['accuracy'] for m in entries if m['accuracy'] is not None]
        summary[color] = {
            'accuracy': round(sum(accuracies) / len(accuracies), 1) if accuracies else None,
            'moves': len(entries),
            'best': sum(1 for m in entries if m['classification'] == 'best'),
            'excellent': sum(1 for m in entries if m['classification'] == 'excellent'),
            'good': sum(1 for m in entries if m['classification'] == 'good'),
            'inaccuracy': sum(1 for m in entries if m['classification'] == 'inaccuracy'),
            'mistake': sum(1 for m in entries if m['classification'] == 'mistake'),
            'blunder': sum(1 for m in entries if m['classification'] == 'blunder'),
        }
    return summary


def review_game(initial_fen, move_rows, bot_color=None):
    """Hamle listesini inceleyip hamle bazlı değerlendirme döndürür.

    ``move_rows``: ``{'uci', 'san', 'color'}`` sözlüklerinden oluşan liste.
    """
    initial_fen = initial_fen or chess.STARTING_FEN

    positions = [initial_fen]
    for row in move_rows:
        positions.append(row.get('fen_after') or initial_fen)

    depth = _review_depth()
    thinking_time = _review_thinking_time()

    def analyze(fen):
        return analyzer.analyze_position(fen, depth=depth, thinking_time=thinking_time)

    with ThreadPoolExecutor(max_workers=_workers()) as executor:
        analyses = list(executor.map(analyze, positions))

    reviewed = []
    for index, row in enumerate(move_rows):
        color = row.get('color') or 'w'
        before = analyses[index] if index < len(analyses) else {}
        after = analyses[index + 1] if index + 1 < len(analyses) else {}

        cp_before = _pov_cp(before, color)
        cp_after = _pov_cp(after, color)

        loss = None
        if cp_before is not None and cp_after is not None:
            loss = max(0, round(cp_before - cp_after))

        is_best = bool(before.get('best')) and before.get('best') == row.get('uci')
        classification = classify(loss, is_best=is_best)

        win_before = _win_percent(cp_before)
        win_after = _win_percent(cp_after)

        reviewed.append({
            'ply': index + 1,
            'move_number': index // 2 + 1,
            'color': color,
            'uci': row.get('uci'),
            'san': row.get('san'),
            'fen_before': positions[index],
            'fen_after': positions[index + 1],
            'eval_before': before.get('cp'),
            'eval_after': after.get('cp'),
            'mate_before': before.get('mate'),
            'mate_after': after.get('mate'),
            'win_chance_before': (
                round(win_before, 1) if win_before is not None else None
            ),
            'win_chance_after': (
                round(win_after, 1) if win_after is not None else None
            ),
            'cp_loss': loss,
            'accuracy': _accuracy(win_before, win_after),
            'classification': classification,
            'classification_label': CLASSIFICATION_LABELS.get(classification, ''),
            'best_uci': before.get('best'),
            'best_san': _san_for_uci(positions[index], before.get('best')),
            'is_bot': bool(bot_color) and color == bot_color,
            'source': before.get('source') or after.get('source'),
        })

    return {
        'moves': reviewed,
        'summary': _summary(reviewed),
        'depth': depth,
    }


def review_enabled():
    return os.environ.get('SATRANC_REVIEW_ENABLED', 'true').lower() == 'true'
