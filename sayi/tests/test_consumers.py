from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from ..models import GameRoom, GamePlayer
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

    async def test_connect_and_disconnect(self):
        """Test that a player can connect, join and disconnect."""
        room = await GameRoom.objects.acreate(room_code='TEST12', status='WAITING')

        communicator = WebsocketCommunicator(
            APPLICATION, f"/sayi/ws/game/{room.room_code}/"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await self._receive_until(communicator, 'game_state')

        await communicator.send_json_to({
            'type': 'join_player',
            'player_identifier': 'test_player_123',
        })

        response = await self._receive_until(communicator, 'player_joined')
        self.assertEqual(response['player_identifier'], 'test_player_123')

        await communicator.disconnect()

    async def test_full_game_flow(self):
        """Test a complete game flow via WebSocket."""
        room = await GameRoom.objects.acreate(room_code='GAME12', status='WAITING')

        p1 = WebsocketCommunicator(APPLICATION, f"/sayi/ws/game/{room.room_code}/")
        p2 = WebsocketCommunicator(APPLICATION, f"/sayi/ws/game/{room.room_code}/")

        p1_connected, _ = await p1.connect()
        p2_connected, _ = await p2.connect()
        self.assertTrue(p1_connected)
        self.assertTrue(p2_connected)

        await self._receive_until(p1, 'game_state')
        await self._receive_until(p2, 'game_state')

        # Player 1 joins
        await p1.send_json_to({'type': 'join_player', 'player_identifier': 'player1'})
        await self._receive_until(p1, 'player_joined')
        await self._receive_until(p2, 'player_joined')

        # Player 2 joins
        await p2.send_json_to({'type': 'join_player', 'player_identifier': 'player2'})
        await self._receive_until(p1, 'player_joined')
        await self._receive_until(p2, 'player_joined')

        # Set secrets
        await p1.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'player1',
            'secret_number': '1234',
        })
        await self._receive_until(p1, 'player_ready')
        await self._receive_until(p2, 'player_ready')

        await p2.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'player2',
            'secret_number': '5678',
        })
        await self._receive_until(p1, 'player_ready')
        await self._receive_until(p2, 'player_ready')

        start = await self._receive_until(p1, 'game_started')
        await self._receive_until(p2, 'game_started')
        self.assertEqual(start['current_turn_identifier'], 'player1')

        # Player 1 guesses Player 2's number correctly
        await p1.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'player1',
            'guess': '5678',
        })
        result = await self._receive_until(p1, 'guess_result')
        self.assertEqual(result['guess'], '5678')
        self.assertEqual(result['result'], '++++')
        self.assertTrue(result['is_win'])

        finished = await self._receive_until(p1, 'game_finished')
        self.assertEqual(finished['winner_identifier'], 'player1')

        await p1.disconnect()
        await p2.disconnect()
