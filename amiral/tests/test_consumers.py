from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from ..models import GameRoom
from ..routing import websocket_urlpatterns

IN_MEMORY_LAYER = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
}

APPLICATION = URLRouter(websocket_urlpatterns)


def board(offset):
    return [
        {'id': 'amiral', 'cells': [[offset, c] for c in range(5)]},
        {'id': 'kruvazor', 'cells': [[offset + 1, c] for c in range(4)]},
        {'id': 'denizalti1', 'cells': [[offset + 2, c] for c in range(3)]},
        {'id': 'denizalti2', 'cells': [[offset + 2, c] for c in range(3, 6)]},
        {'id': 'hucumbot1', 'cells': [[offset + 3, 0], [offset + 3, 1]]},
        {'id': 'hucumbot2', 'cells': [[offset + 3, 2], [offset + 3, 3]]},
        {'id': 'hucumbot3', 'cells': [[offset + 3, 4], [offset + 3, 5]]},
        {'id': 'kesif1', 'cells': [[offset + 4, 0]]},
        {'id': 'kesif2', 'cells': [[offset + 4, 1]]},
        {'id': 'kesif3', 'cells': [[offset + 4, 2]]},
    ]


# All cells occupied by the fleet placed at offset 9 (rows 9-13).
FLEET_CELLS = (
    [(9, c) for c in range(5)]
    + [(10, c) for c in range(4)]
    + [(11, c) for c in range(3)]
    + [(11, c) for c in range(3, 6)]
    + [(12, 0), (12, 1)]
    + [(12, 2), (12, 3)]
    + [(12, 4), (12, 5)]
    + [(13, 0), (13, 1), (13, 2)]
)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class GameConsumerTest(TransactionTestCase):
    async def _receive_until(self, communicator, message_type, tries=40):
        for _ in range(tries):
            data = await communicator.receive_json_from()
            if data.get('type') == message_type:
                return data
        self.fail(f"'{message_type}' mesajı alınamadı")

    async def _start_game(self, room_code):
        room = await GameRoom.objects.acreate(room_code=room_code, status='WAITING')
        c1 = WebsocketCommunicator(APPLICATION, f"/amiral/ws/game/{room.room_code}/")
        c2 = WebsocketCommunicator(APPLICATION, f"/amiral/ws/game/{room.room_code}/")

        assert (await c1.connect())[0]
        assert (await c2.connect())[0]

        await self._receive_until(c1, 'game_state')
        await self._receive_until(c2, 'game_state')

        await c1.send_json_to({'type': 'join_player', 'player_identifier': 'player1'})
        await self._receive_until(c1, 'player_joined')
        await self._receive_until(c2, 'player_joined')

        await c2.send_json_to({'type': 'join_player', 'player_identifier': 'player2'})
        await self._receive_until(c1, 'player_joined')
        await self._receive_until(c2, 'player_joined')

        await c1.send_json_to({
            'type': 'place_ships',
            'player_identifier': 'player1',
            'ships': board(0),
        })
        await self._receive_until(c1, 'player_ready')
        await self._receive_until(c2, 'player_ready')

        await c2.send_json_to({
            'type': 'place_ships',
            'player_identifier': 'player2',
            'ships': board(9),
        })
        await self._receive_until(c1, 'player_ready')
        await self._receive_until(c2, 'player_ready')

        start = await self._receive_until(c1, 'game_started')
        await self._receive_until(c2, 'game_started')
        self.assertEqual(start['current_turn_identifier'], 'player1')

        return c1, c2

    async def test_connect_join_place_and_start(self):
        room = await GameRoom.objects.acreate(room_code='TEST12', status='WAITING')
        communicator = WebsocketCommunicator(
            APPLICATION, f"/amiral/ws/game/{room.room_code}/"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        state = await self._receive_until(communicator, 'game_state')
        self.assertEqual(state['status'], 'WAITING')

        await communicator.send_json_to({
            'type': 'join_player',
            'player_identifier': 'solo',
        })
        joined = await self._receive_until(communicator, 'player_joined')
        self.assertEqual(joined['player_identifier'], 'solo')

        await communicator.disconnect()

    async def test_miss_switches_turn_and_hit_keeps_turn(self):
        c1, c2 = await self._start_game('MISS12')

        # player1 fires at an empty cell -> miss, turn passes to player2.
        await c1.send_json_to({
            'type': 'fire',
            'player_identifier': 'player1',
            'row': 0,
            'col': 0,
        })
        shot = await self._receive_until(c1, 'shot_result')
        self.assertFalse(shot['hit'])
        turn = await self._receive_until(c1, 'turn_changed')
        self.assertEqual(turn['current_turn_identifier'], 'player2')
        await self._receive_until(c2, 'shot_result')
        await self._receive_until(c2, 'turn_changed')

        # player2 fires at an empty cell -> miss, turn passes back to player1.
        await c2.send_json_to({
            'type': 'fire',
            'player_identifier': 'player2',
            'row': 7,
            'col': 7,
        })
        await self._receive_until(c2, 'shot_result')
        turn = await self._receive_until(c2, 'turn_changed')
        self.assertEqual(turn['current_turn_identifier'], 'player1')
        await self._receive_until(c1, 'shot_result')
        turn = await self._receive_until(c1, 'turn_changed')
        self.assertEqual(turn['current_turn_identifier'], 'player1')

        # player1 scores a hit and keeps the turn.
        await c1.send_json_to({
            'type': 'fire',
            'player_identifier': 'player1',
            'row': 9,
            'col': 0,
        })
        hit = await self._receive_until(c1, 'shot_result')
        self.assertTrue(hit['hit'])
        self.assertFalse(hit['game_over'])
        await self._receive_until(c2, 'shot_result')

        await c1.disconnect()
        await c2.disconnect()

    async def test_full_win_flow(self):
        c1, c2 = await self._start_game('WIN123')

        for index, (row, col) in enumerate(FLEET_CELLS):
            await c1.send_json_to({
                'type': 'fire',
                'player_identifier': 'player1',
                'row': row,
                'col': col,
            })
            shot = await self._receive_until(c1, 'shot_result')
            self.assertTrue(shot['hit'])
            last = index == len(FLEET_CELLS) - 1
            self.assertEqual(shot['game_over'], last)

        finished = await self._receive_until(c1, 'game_finished')
        self.assertEqual(finished['winner_identifier'], 'player1')

        # reveal maps each identifier to that player's own ships.
        def cells_by_ship(ships):
            return {s['id']: s['cells'] for s in ships}

        reveal = finished['reveal']
        self.assertEqual(cells_by_ship(reveal['player1']), cells_by_ship(board(0)))
        self.assertEqual(cells_by_ship(reveal['player2']), cells_by_ship(board(9)))

        finished_b = await self._receive_until(c2, 'game_finished')
        self.assertEqual(finished_b['winner_identifier'], 'player1')
        self.assertEqual(cells_by_ship(finished_b['reveal']['player2']), cells_by_ship(board(9)))

        await c1.disconnect()
        await c2.disconnect()
