from django.test import TestCase

from ..characters import CHARACTERS
from ..models import GameRoom, GamePlayer
from ..services import (
    check_accusation,
    first_player,
    get_character,
    is_valid_character,
    opponent_of,
    switch_turn,
)


class CharactersTest(TestCase):
    def test_characters_loaded(self):
        self.assertGreater(len(CHARACTERS), 0)
        for character in CHARACTERS:
            self.assertIn('id', character)
            self.assertIn('name', character)
            self.assertTrue(character['image'].startswith('kim/characters/'))


class CharacterHelpersTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='CHOOSING')
        self.p1 = GamePlayer.objects.create(
            game_room=self.room,
            player_identifier='p1',
            character_id=CHARACTERS[0]['id'],
        )
        self.p2 = GamePlayer.objects.create(
            game_room=self.room,
            player_identifier='p2',
            character_id=CHARACTERS[1]['id'],
        )

    def test_is_valid_character(self):
        self.assertTrue(is_valid_character(CHARACTERS[0]['id']))
        self.assertFalse(is_valid_character('does-not-exist'))

    def test_get_character(self):
        self.assertEqual(get_character(CHARACTERS[0]['id'])['name'], CHARACTERS[0]['name'])

    def test_first_player_and_opponent(self):
        self.assertEqual(first_player(self.room), self.p1)
        self.assertEqual(opponent_of(self.room, self.p1), self.p2)
        self.assertEqual(opponent_of(self.room, self.p2), self.p1)

    def test_switch_turn(self):
        self.assertEqual(switch_turn(self.room, self.p1), self.p2)
        self.assertEqual(switch_turn(self.room, self.p2), self.p1)

    def test_check_accusation(self):
        self.assertTrue(check_accusation(self.p2, self.p2.character_id))
        self.assertFalse(check_accusation(self.p2, self.p1.character_id))
