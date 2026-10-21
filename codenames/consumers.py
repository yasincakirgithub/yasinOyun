import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import services
from .utils import ApiError, allow_rate, clean_chat_text, origin_is_allowed

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 16384


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = (self.scope['url_route']['kwargs'].get('room_code') or '').upper()
        self.room_group_name = ''
        self.player_id = None
        self.session_token = ''
        self._timer_task = None
        self._closed = False
        if not re.fullmatch(r'[A-Z0-9]{1,12}', self.room_code):
            await self.close(code=4404)
            return
        self.room_group_name = f'codenames_room_{self.room_code}'

        headers = dict(self.scope.get('headers') or [])
        origin = headers.get(b'origin', b'').decode('utf-8', errors='ignore')
        request_host = headers.get(b'host', b'').decode('utf-8', errors='ignore')
        if not origin_is_allowed(origin, request_host):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'auth_required'})
        logger.info('Codenames WS connected for room %s', self.room_code)

    async def disconnect(self, close_code):
        self._closed = True
        self._cancel_timer()
        if self.room_group_name:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if self.player_id:
            player = await database_sync_to_async(self._get_player)(self.player_id)
            if player:
                await database_sync_to_async(services.mark_disconnected)(player)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {'type': 'state_changed'},
                )
        logger.info('Codenames WS disconnected for room %s (%s)', self.room_code, close_code)

    def _get_player(self, player_id):
        from .models import GamePlayer
        return GamePlayer.objects.filter(pk=player_id).first()

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
        handlers = {
            'authenticate': self.handle_authenticate,
            'get_state': self.handle_get_state,
            'ping': self.handle_ping,
            'chat': self.handle_chat,
            'clue': self.handle_clue,
            'guess': self.handle_guess,
            'end_turn': self.handle_end_turn,
        }
        handler = handlers.get(message_type)
        if not handler:
            await self.send_error(f'Bilinmeyen mesaj tipi: {message_type}')
            return
        try:
            await handler(data)
        except ApiError as exc:
            await self.send_error(exc.message, exc.code)
        except Exception as exc:  # pragma: no cover - defensive
            if type(exc).__name__ == 'ClientDisconnected':
                self._closed = True
                return
            logger.exception('Codenames WS error handling %s: %s', message_type, exc)
            await self.send_error('Beklenmeyen bir hata oluştu.')

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    async def handle_authenticate(self, data):
        token = str(data.get('session_token') or data.get('token') or '').strip()
        if not token or len(token) > 200:
            await self.send_error('Oturum anahtarı gerekli.', 'auth_required')
            return
        if self.player_id:
            await self.send_json({
                'type': 'auth_ok',
                'player_id': str(self.player_id),
            })
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
        await self.send_json({
            'type': 'auth_ok',
            'player_id': str(player.pk),
        })
        await self.send_room_state()

    async def handle_get_state(self, data):
        if not await self._ensure_authenticated():
            return
        await self.send_room_state()

    async def handle_ping(self, data):
        await self.send_json({'type': 'pong'})

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    async def handle_chat(self, data):
        if not await self._ensure_authenticated():
            return
        try:
            if not await database_sync_to_async(allow_rate)(
                f'chat:{self.player_id}', 5, 5,
            ):
                raise ApiError('Çok hızlı yazıyorsun. Kısa bir mola ver.', 429, 'rate_limited')
            text = clean_chat_text(data.get('text'))
            await database_sync_to_async(self._add_chat)(text)
        except ApiError as exc:
            await self.send_error(exc.message, exc.code)
            return
        await self.broadcast_state()

    async def handle_clue(self, data):
        if not await self._ensure_authenticated():
            return
        try:
            await self._check_action_rate()
            player = await database_sync_to_async(self._get_player)(self.player_id)
            if not player:
                raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
            await database_sync_to_async(services.submit_clue)(
                self.room_code, player, data.get('word'), data.get('number'),
            )
        except ApiError as exc:
            await self.broadcast_state()
            await self.send_error(exc.message, exc.code)
            return
        await self.broadcast_state()

    async def handle_guess(self, data):
        if not await self._ensure_authenticated():
            return
        try:
            await self._check_action_rate()
            player = await database_sync_to_async(self._get_player)(self.player_id)
            if not player:
                raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
            result = await database_sync_to_async(services.guess_word)(
                self.room_code, player, data.get('position'),
            )
            if result.get('expired'):
                await self.broadcast_state()
                await self.send_error(result.get('error') or 'Süre doldu.', 'turn_expired')
                return
        except ApiError as exc:
            await self.broadcast_state()
            await self.send_error(exc.message, exc.code)
            return
        await self.broadcast_state()

    async def handle_end_turn(self, data):
        if not await self._ensure_authenticated():
            return
        try:
            await self._check_action_rate()
            player = await database_sync_to_async(self._get_player)(self.player_id)
            if not player:
                raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
            await database_sync_to_async(services.end_turn)(self.room_code, player)
        except ApiError as exc:
            await self.broadcast_state()
            await self.send_error(exc.message, exc.code)
            return
        await self.broadcast_state()

    async def _ensure_authenticated(self):
        if not self.player_id:
            await self.send_error('Önce oturum açmalısın.', 'auth_required')
            return False
        return True

    async def _check_action_rate(self):
        allowed = await database_sync_to_async(allow_rate)(
            f'action:{self.player_id}', 60, 60,
        )
        if not allowed:
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')

    def _add_chat(self, text):
        from .models import GamePlayer, GameRoom

        room = GameRoom.objects.filter(room_code=self.room_code).first()
        player = GamePlayer.objects.filter(pk=self.player_id, left=False).first()
        if not room or not player:
            raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
        return services.add_chat_message(room, player, text)

    async def broadcast_state(self):
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'state_changed'},
        )

    async def state_changed(self, event):
        if self._closed or not self.player_id:
            return
        await self.send_room_state()

    async def send_room_state(self):
        await database_sync_to_async(services.expire_turn_if_needed)(self.room_code)
        state = await database_sync_to_async(services.build_room_state_for_token)(
            self.room_code, self.session_token,
        )
        if state is None:
            await self.send_error('Oturum sona erdi.', 'invalid_session')
            await self.close(code=4401)
            return
        await self.send_json(state)
        self._schedule_timer(state)

    def _cancel_timer(self):
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

    def _schedule_timer(self, state):
        self._cancel_timer()
        if self._closed:
            return
        session = state.get('session') if isinstance(state, dict) else None
        if not session or session.get('status') != 'IN_PROGRESS':
            return
        timer = session.get('timer') or {}
        remaining = timer.get('remaining_seconds')
        deadline = timer.get('deadline')
        if remaining is None or not deadline:
            return
        try:
            deadline_dt = datetime.fromisoformat(deadline)
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
            delay = max(0.0, (deadline_dt - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            delay = float(remaining)
        self._timer_task = asyncio.create_task(self._timer_after(delay))

    async def _timer_after(self, delay):
        try:
            await asyncio.sleep(max(0.1, delay + 0.2))
            if self._closed:
                return
            changed = await database_sync_to_async(services.expire_turn_if_needed)(
                self.room_code,
            )
            if changed:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {'type': 'state_changed'},
                )
            else:
                await self.send_room_state()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning('Codenames timer task failed: %s', type(exc).__name__)

    # ------------------------------------------------------------------
    # Wire helpers
    # ------------------------------------------------------------------
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
