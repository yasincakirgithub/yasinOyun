from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from codenames.tests.helpers import create_room_with_players, start_room
from config.asgi import application

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY, DEEPSEEK_API_KEY='')
class WebSocketTests(TransactionTestCase):
    def setUp(self):
        self.room, self.host, self.host_token, self.entries = create_room_with_players(4, language='en')
        self.session = start_room(self.room, self.host)
        self.red_op_token = self.entries[2][1]
        self.blue_op_token = self.entries[3][1]

    def path(self, room_code=None):
        return f'/codenames/ws/room/{room_code or self.room.room_code}/'

    async def receive_type(self, communicator, wanted, timeout=3):
        for _ in range(8):
            message = await communicator.receive_json_from(timeout=timeout)
            if message.get('type') == wanted:
                return message
        raise AssertionError(f'Did not receive {wanted}')

    async def connect(self, token, room_code=None):
        communicator = WebsocketCommunicator(application, self.path(room_code))
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        first = await communicator.receive_json_from(timeout=3)
        self.assertEqual(first['type'], 'auth_required')
        await communicator.send_json_to({'type': 'authenticate', 'session_token': token})
        auth = await communicator.receive_json_from(timeout=3)
        self.assertEqual(auth['type'], 'auth_ok')
        state = await self.receive_type(communicator, 'state')
        return communicator, state

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
        other, _other_host, _other_token, _players = await database_sync_to_async(create_room_with_players)(4, language='en')
        communicator = WebsocketCommunicator(application, self.path(other.room_code))
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=3)
        await communicator.send_json_to({'type': 'authenticate', 'session_token': self.host_token})
        error = await communicator.receive_json_from(timeout=3)
        self.assertEqual(error['type'], 'error')
        await communicator.wait()

    def test_role_aware_snapshots_and_guess_broadcast(self):
        async_to_sync(self._role_aware)()

    async def _role_aware(self):
        spy, spy_state = await self.connect(self.host_token)
        op, op_state = await self.connect(self.red_op_token)
        try:
            spy_board = spy_state['session']['board']
            op_board = op_state['session']['board']
            self.assertTrue(all(card['category'] for card in spy_board))
            self.assertTrue(all(card['category'] is None for card in op_board))

            await spy.send_json_to({'type': 'clue', 'word': 'zzzzclue', 'number': 2})
            spy_after = await self.receive_type(spy, 'state')
            op_after = await self.receive_type(op, 'state')
            self.assertEqual(spy_after['session']['clue']['word'], 'zzzzclue')
            self.assertEqual(op_after['session']['clue']['number'], 2)
            self.assertFalse(spy_after['permissions']['can_guess'])
            self.assertTrue(op_after['permissions']['can_guess'])

            target = next(card for card in spy_after['session']['board'] if card['category'] == 'red')
            await op.send_json_to({'type': 'guess', 'position': target['position']})
            spy_revealed = await self.receive_type(spy, 'state')
            op_revealed = await self.receive_type(op, 'state')
            for state in (spy_revealed, op_revealed):
                card = next(c for c in state['session']['board'] if c['position'] == target['position'])
                self.assertTrue(card['revealed'])
                self.assertEqual(card['category'], 'red')
            self.assertEqual(spy_revealed['session']['remaining']['red'], 8)
        finally:
            await spy.disconnect()
            await op.disconnect()

    def test_operative_cannot_submit_clue_or_reveal_as_spymaster(self):
        async_to_sync(self._permissions)()

    async def _permissions(self):
        spy, spy_state = await self.connect(self.host_token)
        op, _op_state = await self.connect(self.red_op_token)
        try:
            await op.send_json_to({'type': 'clue', 'word': 'zzzzclue', 'number': 1})
            error = await self.receive_type(op, 'error')
            self.assertEqual(error['code'], 'spymaster_only')

            await spy.send_json_to({'type': 'clue', 'word': 'zzzzclue', 'number': 1})
            await self.receive_type(spy, 'state')
            await self.receive_type(op, 'state')
            target = next(card for card in spy_state['session']['board'] if card['category'] == 'red')
            await spy.send_json_to({'type': 'guess', 'position': target['position']})
            error = await self.receive_type(spy, 'error')
            self.assertEqual(error['code'], 'operative_only')
        finally:
            await spy.disconnect()
            await op.disconnect()

    def test_chat_is_broadcast_and_sanitized(self):
        async_to_sync(self._chat)()

    async def _chat(self):
        spy, _ = await self.connect(self.host_token)
        op, _ = await self.connect(self.red_op_token)
        try:
            await op.send_json_to({'type': 'chat', 'text': '<script>alert(1)</script> Merhaba'})
            state = await self.receive_type(spy, 'state')
            message = state['messages'][-1]
            self.assertNotIn('<script>', message['text'])
            self.assertIn('Merhaba', message['text'])
            self.assertEqual(message['display_name'], self.entries[2][0].display_name)
        finally:
            await spy.disconnect()
            await op.disconnect()

    def test_same_origin_websocket_is_accepted(self):
        async_to_sync(self._same_origin)()

    async def _same_origin(self):
        communicator = WebsocketCommunicator(
            application,
            self.path(),
            headers=[(b'origin', b'http://testserver'), (b'host', b'testserver')],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        first = await communicator.receive_json_from(timeout=3)
        self.assertEqual(first['type'], 'auth_required')
        await communicator.disconnect()

    def test_cross_origin_websocket_is_rejected(self):
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
