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
class GameConsumerTest(TransactionTestCase):
    async def _receive_until(self, communicator, message_type, tries=40):
        for _ in range(tries):
            data = await communicator.receive_json_from()
            if data.get('type') == message_type:
                return data
        self.fail(f"'{message_type}' mesajı alınamadı")

    async def _connect_pair(self, room_code):
        room = await GameRoom.objects.acreate(room_code=room_code, status='WAITING')
        c1 = WebsocketCommunicator(APPLICATION, f"/satranc/ws/game/{room.room_code}/")
        c2 = WebsocketCommunicator(APPLICATION, f"/satranc/ws/game/{room.room_code}/")

        assert (await c1.connect())[0]
        assert (await c2.connect())[0]

        await self._receive_until(c1, 'game_state')
        await self._receive_until(c2, 'game_state')
        return c1, c2

    async def _join(self, c1, c2):
        await c1.send_json_to({'type': 'join_player', 'player_identifier': 'p1'})
        await self._receive_until(c1, 'game_state')
        await self._receive_until(c2, 'game_state')

        await c2.send_json_to({'type': 'join_player', 'player_identifier': 'p2'})
        state = await self._receive_until(c1, 'game_state')
        await self._receive_until(c2, 'game_state')
        return state

    async def test_connect_and_join(self):
        c1, c2 = await self._connect_pair('CHESS1')
        state = await self._join(c1, c2)

        self.assertEqual(state['status'], 'IN_PROGRESS')
        self.assertEqual(state['turn'], 'w')
        colors = {p['player_identifier']: p['color'] for p in state['players']}
        self.assertEqual(colors, {'p1': 'w', 'p2': 'b'})

        await c1.disconnect()
        await c2.disconnect()

    async def test_valid_and_invalid_moves(self):
        c1, c2 = await self._connect_pair('CHESS2')
        await self._join(c1, c2)

        # White plays a legal move.
        await c1.send_json_to({
            'type': 'move', 'player_identifier': 'p1', 'uci': 'e2e4',
        })
        state = await self._receive_until(c1, 'game_state')
        await self._receive_until(c2, 'game_state')
        self.assertEqual(state['turn'], 'b')
        self.assertEqual(len(state['moves']), 1)
        self.assertEqual(state['moves'][0]['san'], 'e4')

        # White tries to move again out of turn -> error to that client only.
        await c1.send_json_to({
            'type': 'move', 'player_identifier': 'p1', 'uci': 'd2d4',
        })
        error = await self._receive_until(c1, 'error')
        self.assertIn('Sıra sende değil', error['message'])

        # Black tries an illegal move.
        await c2.send_json_to({
            'type': 'move', 'player_identifier': 'p2', 'uci': 'e7e5e6',
        })
        error = await self._receive_until(c2, 'error')
        self.assertIn('hamle', error['message'].lower())

        await c1.disconnect()
        await c2.disconnect()

    async def test_checkmate_ends_game(self):
        c1, c2 = await self._connect_pair('CHESS3')
        await self._join(c1, c2)

        sequence = [
            ('p1', c1, 'f2f3'),
            ('p2', c2, 'e7e5'),
            ('p1', c1, 'g2g4'),
            ('p2', c2, 'd8h4'),
        ]
        state = None
        for identifier, communicator, uci in sequence:
            await communicator.send_json_to({
                'type': 'move', 'player_identifier': identifier, 'uci': uci,
            })
            state = await self._receive_until(c1, 'game_state')
            await self._receive_until(c2, 'game_state')

        self.assertEqual(state['status'], 'FINISHED')
        self.assertEqual(state['result'], '0-1')
        self.assertEqual(state['winner_identifier'], 'p2')
        self.assertEqual(state['winner_color'], 'b')

        await c1.disconnect()
        await c2.disconnect()
