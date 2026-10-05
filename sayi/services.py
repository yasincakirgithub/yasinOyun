from .validators import validate_four_digit_unique
from django.core.exceptions import ValidationError
from .models import GamePlayer


def validate_number(value):
    """Wrapper for validation that can be used in services."""
    try:
        validate_four_digit_unique(value)
        return True
    except ValidationError:
        return False


def calculate_result(secret: str, guess: str) -> str:
    """
    Calculate the result of a guess against the secret number.
    Returns a string of '+' and '-' symbols where:
    - '+' indicates correct digit in correct position
    - '-' indicates correct digit in wrong position
    - Symbols are only shown for digits that exist in the secret
    - Symbols are in the order of the guess digits.
    
    Example:
    secret=1234, guess=1325 -> '+--'
    secret=1234, guess=1243 -> '++--'
    secret=1234, guess=5678 -> ''
    secret=1234, guess=4321 -> '----'
    """
    if len(secret) != 4 or len(guess) != 4:
        raise ValueError("Secret and guess must be 4 digits")
    
    result = []
    # We need to count how many times each digit appears in secret
    # But since validation ensures unique digits, we can do simple checking
    secret_chars = list(secret)
    
    for i in range(4):
        g_digit = guess[i]
        if g_digit in secret_chars:
            if g_digit == secret_chars[i]:
                result.append('+')
            else:
                result.append('-')
        # else: skip (not in secret)
    
    return ''.join(result)


def is_win(result: str) -> bool:
    """Check if the result indicates a win (all four digits correct position)."""
    # A win means we have four '+' symbols
    return result.count('+') == 4


def switch_turn(current_turn: GamePlayer, players: list[GamePlayer]) -> GamePlayer:
    """Given current turn and list of two players, return the other player."""
    for player in players:
        if player != current_turn:
            return player
    return None  # Should not happen if there are exactly two players