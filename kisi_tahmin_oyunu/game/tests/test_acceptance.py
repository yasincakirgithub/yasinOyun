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
class AcceptanceTest(TransactionTestCase):
    """End-to-end scenario over WebSockets.

    Browser A creates the room and picks character A.
    Browser B joins and picks character B.
    A asks a question, B answers.
    B accuses A's character correctly and wins.
    """

    async def _receive_until(self, communicator, message_type, tries=15):
        for _ in range(tries):
            data = await communicator.receive_json_from()
            if data.get('type') == message_type:
                return data
        self.fail(f"'{message_type}' mesajı alınamadı")

    async def test_acceptance_scenario(self):
        room = await GameRoom.objects.acreate(room_code='ABC12', status='WAITING')

        ws_a = WebsocketCommunicator(APPLICATION, f"/ws/game/{room.room_code}/")
        ws_b = WebsocketCommunicator(APPLICATION, f"/ws/game/{room.room_code}/")
        await ws_a.connect()
        await ws_b.connect()
        await self._receive_until(ws_a, 'game_state')
        await self._receive_until(ws_b, 'game_state')

        await ws_a.send_json_to({'type': 'join_player', 'player_identifier': 'browser_a'})
        await self._receive_until(ws_a, 'game_state')
        await self._receive_until(ws_a, 'player_joined')
        await self._receive_until(ws_b, 'player_joined')

        await ws_b.send_json_to({'type': 'join_player', 'player_identifier': 'browser_b'})
        await self._receive_until(ws_b, 'game_state')
        await self._receive_until(ws_b, 'player_joined')
        await self._receive_until(ws_a, 'player_joined')

        char_a = CHARACTERS[0]['id']
        char_b = CHARACTERS[1]['id']

        await ws_a.send_json_to({
            'type': 'choose_character',
            'player_identifier': 'browser_a',
            'character_id': char_a,
        })
        await self._receive_until(ws_a, 'player_ready')
        await self._receive_until(ws_b, 'player_ready')

        await ws_b.send_json_to({
            'type': 'choose_character',
            'player_identifier': 'browser_b',
            'character_id': char_b,
        })
        await self._receive_until(ws_b, 'player_ready')
        await self._receive_until(ws_a, 'player_ready')

        started_a = await self._receive_until(ws_a, 'game_started')
        self.assertEqual(started_a['current_turn_identifier'], 'browser_a')
        await self._receive_until(ws_b, 'game_started')

        await ws_a.send_json_to({
            'type': 'ask_question',
            'player_identifier': 'browser_a',
            'text': 'Şapkalı mı?',
        })
        question = await self._receive_until(ws_a, 'chat_message')
        self.assertEqual(question['message']['text'], 'Şapkalı mı?')
        await self._receive_until(ws_b, 'chat_message')
        await self._receive_until(ws_a, 'turn_changed')
        await self._receive_until(ws_b, 'turn_changed')

        await ws_b.send_json_to({
            'type': 'answer_question',
            'player_identifier': 'browser_b',
            'answer': 'no',
        })
        await self._receive_until(ws_a, 'chat_message')
        await self._receive_until(ws_b, 'chat_message')
        await self._receive_until(ws_a, 'turn_changed')
        await self._receive_until(ws_b, 'turn_changed')

        # Browser B accuses browser A's character correctly.
        await ws_b.send_json_to({
            'type': 'make_accusation',
            'player_identifier': 'browser_b',
            'character_id': char_a,
        })
        result = await self._receive_until(ws_b, 'accusation_result')
        self.assertTrue(result['correct'])
        finished = await self._receive_until(ws_b, 'game_finished')
        self.assertEqual(finished['winner_identifier'], 'browser_b')
        await self._receive_until(ws_a, 'game_finished')

        await ws_a.disconnect()
        await ws_b.disconnect()
