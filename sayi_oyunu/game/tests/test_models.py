from django.test import TestCase
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from ..models import GameRoom, GamePlayer, Guess
from ..services import validate_number


class GameRoomModelTest(TestCase):
    def test_create_room(self):
        room = GameRoom.objects.create(room_code='TEST12', status='WAITING')
        self.assertEqual(room.room_code, 'TEST12')
        self.assertEqual(room.status, 'WAITING')
        self.assertIsNotNone(room.created_at)

    def test_room_code_unique(self):
        room = GameRoom.objects.create(room_code='TEST12', status='WAITING')
        # A second room with the same code must fail the unique constraint.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GameRoom.objects.create(room_code='TEST12', status='WAITING')
        # A different code is fine
        room2 = GameRoom.objects.create(room_code='TEST13', status='WAITING')
        self.assertNotEqual(room.room_code, room2.room_code)


class GamePlayerModelTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='WAITING')

    def test_create_player(self):
        player = GamePlayer.objects.create(
            game_room=self.room,
            player_identifier='player1',
            secret_number='1234',
            ready=False
        )
        self.assertEqual(player.game_room, self.room)
        self.assertEqual(player.player_identifier, 'player1')
        self.assertEqual(player.secret_number, '1234')
        self.assertFalse(player.ready)


class GuessModelTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='WAITING')
        self.player = GamePlayer.objects.create(
            game_room=self.room,
            player_identifier='player1',
            secret_number='1234',
            ready=True
        )

    def test_create_guess(self):
        guess = Guess.objects.create(
            game_player=self.player,
            value='5678',
            result='--',
            turn_number=1
        )
        self.assertEqual(guess.game_player, self.player)
        self.assertEqual(guess.value, '5678')
        self.assertEqual(guess.result, '--')
        self.assertEqual(guess.turn_number, 1)


class ValidateNumberTest(TestCase):
    def test_valid_numbers(self):
        self.assertTrue(validate_number('1234'))
        self.assertFalse(validate_number('0234'))  # leading zero is invalid
        self.assertTrue(validate_number('1023'))  # Valid: 1,0,2,3 unique, no leading zero
        self.assertTrue(validate_number('9876'))

    def test_invalid_numbers(self):
        self.assertFalse(validate_number('123'))   # Too short
        self.assertFalse(validate_number('12345')) # Too long
        self.assertFalse(validate_number('0123'))  # Leading zero
        self.assertFalse(validate_number('1123'))  # Duplicate digit
        self.assertFalse(validate_number('abcd'))  # Non-digits