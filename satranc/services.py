"""Chess rules powered by the ``python-chess`` library.

The server is authoritative: every incoming move is validated against the
current FEN here before it is accepted and persisted.
"""

import chess


def legal_moves(fen):
    """Return the legal moves for the position as UCI strings."""
    board = chess.Board(fen)
    return [move.uci() for move in board.legal_moves]


def turn_color(fen):
    """Whose turn it is ('w' or 'b')."""
    return 'w' if chess.Board(fen).turn == chess.WHITE else 'b'


def is_check(fen):
    board = chess.Board(fen)
    return board.is_check()


def automatic_draw_reason(initial_fen_value, ucis):
    """Üç tekrar ya da 50 hamle kuralı gereği otomatik beraberlik var mı?

    Hamle geçmişi yeniden oynanarak kontrol edilir. Döner: ``'repetition'``,
    ``'fifty'`` ya da ``None``.
    """
    board = chess.Board(initial_fen_value or chess.STARTING_FEN)
    for uci in ucis:
        try:
            board.push(chess.Move.from_uci(uci))
        except ValueError:
            return None
    if board.is_repetition(3):
        return 'repetition'
    if board.is_fifty_moves():
        return 'fifty'
    return None


OUTCOME_TERMINATIONS = {
    'CHECKMATE': 'checkmate',
    'STALEMATE': 'stalemate',
    'INSUFFICIENT_MATERIAL': 'insufficient',
    'SEVENTYFIVE_MOVES': 'fifty',
    'FIVEFOLD_REPETITION': 'repetition',
}


def outcome_termination(outcome):
    """``chess.Outcome`` nesnesini kısa bir neden koduna çevirir."""
    if outcome is None:
        return None
    return OUTCOME_TERMINATIONS.get(outcome.termination.name, outcome.termination.name.lower())


def apply_move(fen, uci):
    """
    Validate and apply a move in UCI notation (e.g. ``e2e4`` or ``e7e8q``).

    Returns a result dict on success or ``{'error': message}`` on failure.
    """
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return {'error': 'Geçersiz hamle biçimi.'}

    if move not in board.legal_moves:
        return {'error': 'Bu hamle oynanamaz.'}

    san = board.san(move)
    board.push(move)
    outcome = board.outcome()

    winner_color = None
    if outcome and outcome.winner is not None:
        winner_color = 'w' if outcome.winner == chess.WHITE else 'b'

    return {
        'uci': uci,
        'san': san,
        'fen': board.fen(),
        'turn': 'w' if board.turn == chess.WHITE else 'b',
        'check': board.is_check(),
        'game_over': outcome is not None,
        'result': outcome.result() if outcome else None,
        'termination': outcome_termination(outcome),
        'winner_color': winner_color,
    }
