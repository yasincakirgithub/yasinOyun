from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from ..characters import CHARACTERS
from ..models import GameRoom
from ..routing import websocket_urlpatterns

IN_MEMORY_LAYER = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
}

APPLICATION = URLRouter(websocket_urlpatterns)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class GameConsumerTest(TransactionTestCase):
    async def _receive_until(self, communicator, message_type, tries=15):
        for _ in range(tries):
            data = await communicator.receive_json_from()
            if data.get('type') == message_type:
                return data
        self.fail(f"'{message_type}' mesajı alınamadı")

    async def test_connect_and_join(self):
        room = await GameRoom.objects.acreate(room_code='TEST12', status='WAITING')
        communicator = WebsocketCommunicator(
            APPLICATION, f"/ws/game/{room.room_code}/"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._receive_until(communicator, 'game_state')
        await communicator.send_json_to({
            'type': 'join_player',
            'player_identifier': 'test_player_123',
        })
        await self._receive_until(communicator, 'game_state')
        joined = await self._receive_until(communicator, 'player_joined')
        self.assertEqual(joined['player_identifier'], 'test_player_123')

        await communicator.disconnect()

    async def test_full_game_flow(self):
        room = await GameRoom.objects.acreate(room_code='GAME12', status='WAITING')

        p1 = WebsocketCommunicator(APPLICATION, f"/ws/game/{room.room_code}/")
        p2 = WebsocketCommunicator(APPLICATION, f"/ws/game/{room.room_code}/")
        await p1.connect()
        await p2.connect()
        await self._receive_until(p1, 'game_state')
        await self._receive_until(p2, 'game_state')

        await p1.send_json_to({'type': 'join_player', 'player_identifier': 'player1'})
        await self._receive_until(p1, 'game_state')
        await self._receive_until(p1, 'player_joined')
        await self._receive_until(p2, 'player_joined')

        await p2.send_json_to({'type': 'join_player', 'player_identifier': 'player2'})
        await self._receive_until(p2, 'game_state')
        await self._receive_until(p2, 'player_joined')
        await self._receive_until(p1, 'player_joined')

        p1_char = CHARACTERS[0]['id']
        p2_char = CHARACTERS[1]['id']

        await p1.send_json_to({
            'type': 'choose_character',
            'player_identifier': 'player1',
            'character_id': p1_char,
        })
        await self._receive_until(p1, 'player_ready')
        await self._receive_until(p2, 'player_ready')

        await p2.send_json_to({
            'type': 'choose_character',
            'player_identifier': 'player2',
            'character_id': p2_char,
        })
        await self._receive_until(p2, 'player_ready')
        await self._receive_until(p1, 'player_ready')

        started = await self._receive_until(p1, 'game_started')
        self.assertEqual(started['current_turn_identifier'], 'player1')
        await self._receive_until(p2, 'game_started')

        # Player 1 asks a question (turn stays with the asker until answered).
        await p1.send_json_to({
            'type': 'ask_question',
            'player_identifier': 'player1',
            'text': 'Gözlüklü mü?',
        })
        q1 = await self._receive_until(p1, 'chat_message')
        self.assertEqual(q1['message']['kind'], 'question')
        await self._receive_until(p2, 'chat_message')
        await self._receive_until(p1, 'turn_changed')
        await self._receive_until(p2, 'turn_changed')

        # Player 2 answers; the turn passes to player 2.
        await p2.send_json_to({
            'type': 'answer_question',
            'player_identifier': 'player2',
            'answer': 'yes',
        })
        answer = await self._receive_until(p2, 'chat_message')
        self.assertEqual(answer['message']['kind'], 'answer')
        await self._receive_until(p1, 'chat_message')
        turn = await self._receive_until(p2, 'turn_changed')
        self.assertEqual(turn['current_turn_identifier'], 'player2')
        await self._receive_until(p1, 'turn_changed')

        # Player 2 accuses player 1's character correctly and wins.
        await p2.send_json_to({
            'type': 'make_accusation',
            'player_identifier': 'player2',
            'character_id': p1_char,
        })
        result = await self._receive_until(p2, 'accusation_result')
        self.assertTrue(result['correct'])
        finished = await self._receive_until(p2, 'game_finished')
        self.assertEqual(finished['winner_identifier'], 'player2')
        await self._receive_until(p1, 'game_finished')

        await p1.disconnect()
        await p2.disconnect()
