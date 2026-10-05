from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from ..models import GameRoom
from ..routing import websocket_urlpatterns

IN_MEMORY_LAYER = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
}

APPLICATION = URLRouter(websocket_urlpatterns)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class AcceptanceTest(TransactionTestCase):
    """Browser A and Browser B play a full number-guessing round."""

    async def _receive_until(self, communicator, message_type, tries=20):
        for _ in range(tries):
            data = await communicator.receive_json_from()
            if data.get('type') == message_type:
                return data
        self.fail(f"'{message_type}' mesajı alınamadı")

    async def test_acceptance_scenario(self):
        room = await GameRoom.objects.acreate(room_code='ABC12', status='WAITING')

        ws_a = WebsocketCommunicator(APPLICATION, f"/sayi/ws/game/{room.room_code}/")
        ws_b = WebsocketCommunicator(APPLICATION, f"/sayi/ws/game/{room.room_code}/")

        connected_a, _ = await ws_a.connect()
        connected_b, _ = await ws_b.connect()
        self.assertTrue(connected_a)
        self.assertTrue(connected_b)

        await self._receive_until(ws_a, 'game_state')
        await self._receive_until(ws_b, 'game_state')

        await ws_a.send_json_to({'type': 'join_player', 'player_identifier': 'browser_a'})
        await self._receive_until(ws_a, 'player_joined')
        await self._receive_until(ws_b, 'player_joined')

        await ws_b.send_json_to({'type': 'join_player', 'player_identifier': 'browser_b'})
        await self._receive_until(ws_a, 'player_joined')
        await self._receive_until(ws_b, 'player_joined')

        await ws_a.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'browser_a',
            'secret_number': '1234',
        })
        await self._receive_until(ws_a, 'player_ready')
        await self._receive_until(ws_b, 'player_ready')

        await ws_b.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'browser_b',
            'secret_number': '7521',
        })
        await self._receive_until(ws_a, 'player_ready')
        await self._receive_until(ws_b, 'player_ready')

        start = await self._receive_until(ws_a, 'game_started')
        await self._receive_until(ws_b, 'game_started')
        self.assertEqual(start['current_turn_identifier'], 'browser_a')

        # Browser A guesses 5723 against Browser B's secret 7521 -> --+
        await ws_a.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'browser_a',
            'guess': '5723',
        })
        result_a = await self._receive_until(ws_a, 'guess_result')
        self.assertEqual(result_a['result'], '--+')
        self.assertFalse(result_a['is_win'])

        notif_b = await self._receive_until(ws_b, 'opponent_guessed')
        self.assertEqual(notif_b['guess'], '5723')
        self.assertEqual(notif_b['result'], '--+')

        # Browser B guesses 1234 against Browser A's secret 1234 -> ++++
        await ws_b.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'browser_b',
            'guess': '1234',
        })
        result_b = await self._receive_until(ws_b, 'guess_result')
        self.assertEqual(result_b['result'], '++++')
        self.assertTrue(result_b['is_win'])

        finished = await self._receive_until(ws_a, 'game_finished')
        self.assertEqual(finished['winner_identifier'], 'browser_b')

        await ws_a.disconnect()
        await ws_b.disconnect()
