import json
import logging
import re

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import services
from .utils import origin_is_allowed

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 8192


class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = (self.scope['url_route']['kwargs'].get('room_code') or '').upper()
        self.room_group_name = ''
        self.player_id = None
        self.session_token = ''
        self._closed = False
        if not re.fullmatch(r'[A-Z0-9]{1,12}', self.room_code):
            await self.close(code=4404)
            return
        self.room_group_name = f'fcmanager_room_{self.room_code}'

        headers = dict(self.scope.get('headers') or [])
        origin = headers.get(b'origin', b'').decode('utf-8', errors='ignore')
        request_host = headers.get(b'host', b'').decode('utf-8', errors='ignore')
        if not origin_is_allowed(origin, request_host):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'auth_required'})
        logger.info('FC Manager WS connected for room %s', self.room_code)

    async def disconnect(self, close_code):
        self._closed = True
        if self.room_group_name:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if self.player_id:
            player = await database_sync_to_async(self._get_player)(self.player_id)
            if player:
                await database_sync_to_async(services.mark_disconnected)(player)
                if self.room_group_name:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {'type': 'state_changed'},
                    )
        logger.info('FC Manager WS disconnected for room %s (%s)', self.room_code, close_code)

    def _get_player(self, player_id):
        from .models import Participant

        return Participant.objects.filter(pk=player_id).first()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data or not text_data:
            await self.send_error('Geçersiz veri gönderildi.')
            return
        if len(text_data.encode('utf-8')) > MAX_MESSAGE_BYTES:
            await self.send_error('Mesaj çok büyük.')
            return
        try:
            data = json.loads(text_data)
        except (TypeError, ValueError):
            await self.send_error('Geçersiz veri gönderildi.')
            return
        if not isinstance(data, dict):
            await self.send_error('Geçersiz veri gönderildi.')
            return

        message_type = data.get('type')
        if message_type == 'authenticate':
            await self.handle_authenticate(data)
        elif message_type == 'get_state':
            await self.handle_get_state(data)
        elif message_type == 'ping':
            await self.send_json({'type': 'pong'})
        else:
            await self.send_error(f'Bilinmeyen mesaj tipi: {message_type}')

    async def handle_authenticate(self, data):
        token = str(data.get('session_token') or data.get('token') or '').strip()
        if not token or len(token) > 200:
            await self.send_error('Oturum anahtarı gerekli.', 'auth_required')
            return
        if self.player_id:
            await self.send_json({'type': 'auth_ok', 'player_id': str(self.player_id)})
            await self.send_room_state()
            return
        auth = await database_sync_to_async(services.authenticate)(self.room_code, token)
        if not auth:
            await self.send_error('Oda veya oturum geçersiz.', 'auth_failed')
            await self.close(code=4401)
            return
        _, player = auth
        self.session_token = token
        self.player_id = player.pk
        await database_sync_to_async(services.mark_connected)(player)
        await self.send_json({'type': 'auth_ok', 'player_id': str(player.pk)})
        await self.send_room_state()
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'state_changed'},
        )

    async def handle_get_state(self, data):
        if not self.player_id:
            await self.send_error('Önce oturum açmalısın.', 'auth_required')
            return
        await self.send_room_state()

    async def state_changed(self, event):
        if self._closed or not self.player_id:
            return
        await self.send_room_state()

    async def send_room_state(self):
        state = await database_sync_to_async(services.build_room_state_for_token)(
            self.room_code, self.session_token,
        )
        if state is None:
            await self.send_error('Oturum sona erdi.', 'invalid_session')
            await self.close(code=4401)
            return
        state = dict(state)
        state['type'] = 'state'
        await self.send_json(state)

    async def send_error(self, message, code='error'):
        await self.send_json({'type': 'error', 'message': message, 'code': code})

    async def send_json(self, payload):
        if self._closed:
            return
        try:
            await self.send(text_data=json.dumps(payload, default=str))
        except Exception as exc:
            if type(exc).__name__ == 'ClientDisconnected':
                self._closed = True
                return
            raise
