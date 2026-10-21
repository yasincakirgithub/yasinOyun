from unittest import mock

from codenames import services
from codenames.words import fallback_words


def create_room_with_players(count=4, language='tr'):
    room, host, host_token = services.create_room('Host')
    room.language = language
    room.settings = dict(room.settings, starting_team='red')
    room.save(update_fields=['language', 'settings'])
    players = [(host, host_token)]
    for index in range(1, count):
        _room, member, token, _rejoined = services.join_room(room.room_code, f'Player {index}')
        players.append((member, token))
    services.assign_roles(room.room_code, host, auto=True)
    room.refresh_from_db()
    return room, host, host_token, players


def start_room(room, host, words=None, source='fallback'):
    words = words or fallback_words(room.language)
    with mock.patch('codenames.services.generate_words', return_value=(words, source)):
        session = services.start_game(room.room_code, host)
    room.refresh_from_db()
    return session


def refresh(player):
    player.refresh_from_db()
    return player
