"""WebSocket consumer tests for FC Manager rooms."""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from fcmanager import services
from fcmanager.tests.helpers import available_candidates, create_room_with_players
from config.asgi import application

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class WebSocketTests(TransactionTestCase):
    def setUp(self):
        self.room, self.host, self.host_token, self.entries = create_room_with_players()
        self.away, self.away_token = self.entries[1]
        self.room = services.start_draft(self.room.room_code, self.host)
        self.gk_id = available_candidates(self.room, 'gk')[0].player_id

    def path(self, room_code=None):
        return f'/fcmanager/ws/room/{room_code or self.room.room_code}/'

    async def receive_type(self, communicator, wanted, timeout=3):
        for _ in range(10):
            message = await communicator.receive_json_from(timeout=timeout)
            if message.get('type') == wanted:
                return message
        raise AssertionError(f'Did not receive {wanted}')

    async def receive_state_where(self, communicator, predicate, timeout=3):
        for _ in range(10):
            message = await communicator.receive_json_from(timeout=timeout)
            if message.get('type') == 'state' and predicate(message):
                return message
        raise AssertionError('Did not receive the expected state')

    async def connect(self, token, room_code=None, headers=None):
        communicator = WebsocketCommunicator(
            application,
            self.path(room_code),
            headers=headers if headers is not None else [
                (b'origin', b'http://testserver'),
                (b'host', b'testserver'),
            ],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        first = await communicator.receive_json_from(timeout=3)
        self.assertEqual(first['type'], 'auth_required')
        await communicator.send_json_to({'type': 'authenticate', 'session_token': token})
        auth = await communicator.receive_json_from(timeout=3)
        self.assertEqual(auth['type'], 'auth_ok')
        state = await self.receive_type(communicator, 'state')
        return communicator, state

    def test_connect_authenticate_and_get_state(self):
        async_to_sync(self._connect_authenticate)()

    async def _connect_authenticate(self):
        communicator, state = await self.connect(self.host_token)
        try:
            self.assertEqual(state['room']['code'], self.room.room_code)
            self.assertEqual(state['you']['name'], 'Player 1')
            self.assertEqual(state['market'], [])
            self.assertGreater(state['market_total'], 40)

            await communicator.send_json_to({'type': 'get_state'})
            refreshed = await self.receive_type(communicator, 'state')
            self.assertEqual(refreshed['room']['status'], 'DRAFT')

            await communicator.send_json_to({'type': 'ping'})
            pong = await self.receive_type(communicator, 'pong')
            self.assertEqual(pong['type'], 'pong')
        finally:
            await communicator.disconnect()

    def test_get_state_requires_authentication(self):
        async_to_sync(self._get_state_unauthenticated)()

    async def _get_state_unauthenticated(self):
        communicator = WebsocketCommunicator(application, self.path())
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=3)
        await communicator.send_json_to({'type': 'get_state'})
        error = await communicator.receive_json_from(timeout=3)
        self.assertEqual(error['type'], 'error')
        self.assertEqual(error['code'], 'auth_required')
        await communicator.disconnect()

    def test_invalid_token_is_rejected(self):
        async_to_sync(self._invalid_token)()

    async def _invalid_token(self):
        communicator = WebsocketCommunicator(application, self.path())
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=3)
        await communicator.send_json_to({'type': 'authenticate', 'session_token': 'nope'})
        error = await communicator.receive_json_from(timeout=3)
        self.assertEqual(error['type'], 'error')
        self.assertEqual(error['code'], 'auth_failed')
        await communicator.wait()

    def test_cross_room_token_is_rejected(self):
        async_to_sync(self._cross_room)()

    async def _cross_room(self):
        other, _other_host, _other_token, _entries = await database_sync_to_async(
            create_room_with_players,
        )()
        communicator = WebsocketCommunicator(application, self.path(other.room_code))
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=3)
        await communicator.send_json_to({'type': 'authenticate', 'session_token': self.host_token})
        error = await communicator.receive_json_from(timeout=3)
        self.assertEqual(error['type'], 'error')
        await communicator.wait()

    def test_cross_origin_is_rejected(self):
        async_to_sync(self._cross_origin)()

    async def _cross_origin(self):
        communicator = WebsocketCommunicator(
            application,
            self.path(),
            headers=[(b'origin', b'https://evil.example'), (b'host', b'testserver')],
        )
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4403)

    def test_pick_is_broadcast_to_both_managers(self):
        async_to_sync(self._pick_broadcast)()

    async def _pick_broadcast(self):
        host, _host_state = await self.connect(self.host_token)
        away, _away_state = await self.connect(self.away_token)
        try:
            await database_sync_to_async(services.pick_player)(
                self.room.room_code, self.host, self.gk_id, 'gk',
            )
            await database_sync_to_async(services.broadcast_room)(self.room.room_code)

            host_state = await self.receive_state_where(
                host, lambda state: state['you']['slots_filled'] == 1,
            )
            away_state = await self.receive_state_where(
                away, lambda state: state['opponent']['slots_filled'] == 1,
            )
            self.assertEqual(host_state['you']['spent'], host_state['you']['squad']['gk']['value_eur'])
            self.assertTrue(away_state['opponent']['locked'] is False)
        finally:
            await host.disconnect()
            await away.disconnect()
