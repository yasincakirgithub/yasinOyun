"""Game rules for the Guess Who style game."""

from .characters import CHARACTER_MAP


def is_valid_character(character_id):
    return character_id in CHARACTER_MAP


def get_character(character_id):
    return CHARACTER_MAP.get(character_id)


def ordered_players(room):
    """Return the two players ordered by join time."""
    return list(room.players.order_by('joined_at'))


def first_player(room):
    players = ordered_players(room)
    return players[0] if players else None


def opponent_of(room, player):
    return room.players.exclude(id=player.id).first()


def switch_turn(room, current_player):
    """Return the other player in the room."""
    return opponent_of(room, current_player)


def check_accusation(opponent, guessed_character_id):
    """Return True when the guessed character matches the opponent's secret."""
    return bool(opponent and opponent.character_id == guessed_character_id)
