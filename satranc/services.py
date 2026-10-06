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
        'termination': outcome.termination.name if outcome else None,
        'winner_color': winner_color,
    }
