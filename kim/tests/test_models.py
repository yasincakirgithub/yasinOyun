from django.db import IntegrityError, transaction
from django.test import TestCase

from ..characters import CHARACTERS
from ..models import Accusation, ChatMessage, GamePlayer, GameRoom


class GameRoomModelTest(TestCase):
    def test_create_room(self):
        room = GameRoom.objects.create(room_code='TEST12', status='WAITING')
        self.assertEqual(room.room_code, 'TEST12')
        self.assertEqual(room.status, 'WAITING')
        self.assertFalse(room.awaiting_answer)
        self.assertIsNotNone(room.created_at)

    def test_room_code_unique(self):
        GameRoom.objects.create(room_code='TEST12', status='WAITING')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GameRoom.objects.create(room_code='TEST12', status='WAITING')
        room2 = GameRoom.objects.create(room_code='TEST13', status='WAITING')
        self.assertNotEqual('TEST12', room2.room_code)


class GamePlayerModelTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='CHOOSING')

    def test_create_player(self):
        player = GamePlayer.objects.create(
            game_room=self.room,
            player_identifier='player1',
            character_id=CHARACTERS[0]['id'],
        )
        self.assertEqual(player.game_room, self.room)
        self.assertEqual(player.character_id, CHARACTERS[0]['id'])
        self.assertEqual(player.eliminated, [])
        self.assertFalse(player.ready)


class ChatMessageModelTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='IN_PROGRESS')
        self.player = GamePlayer.objects.create(
            game_room=self.room, player_identifier='player1'
        )

    def test_create_message(self):
        message = ChatMessage.objects.create(
            game_room=self.room,
            game_player=self.player,
            kind='question',
            text='Gözlüklü mü?',
        )
        self.assertEqual(message.kind, 'question')
        self.assertEqual(message.text, 'Gözlüklü mü?')
        self.assertIn(message, self.room.messages.all())


class AccusationModelTest(TestCase):
    def setUp(self):
        self.room = GameRoom.objects.create(room_code='TEST12', status='IN_PROGRESS')
        self.player = GamePlayer.objects.create(
            game_room=self.room, player_identifier='player1'
        )

    def test_create_accusation(self):
        accusation = Accusation.objects.create(
            game_player=self.player,
            character_id=CHARACTERS[0]['id'],
            correct=True,
        )
        self.assertTrue(accusation.correct)
        self.assertEqual(accusation.character_id, CHARACTERS[0]['id'])
