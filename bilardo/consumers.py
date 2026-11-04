import json
import logging
import math
import time
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from .engine import (
    CUE_BY_ID,
    DEFAULT_CUE,
    MODES,
    create_initial_state,
    get_mode,
    place_cue_ball,
    sanitize_state,
    validate_cue,
    validate_target,
)
from .models import GamePlayer, GameRoom, Shot

logger = logging.getLogger(__name__)

PENDING_TIMEOUT = 30.0
MAX_EMOTE_LENGTH = 80


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.group_name = f'bilardo_game_{self.room_code}'
        self.player_identifier = None
        self.seat = None

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        summary = await self.room_summary()
        if not summary:
            await self.send_error('Oda bulunamadı.')
            await self.close(code=4004)
            return

        await self.send_json({
            'type': 'connected',
            'room_code': self.room_code,
            'status': summary['status'],
            'mode': summary['mode'],
            'target': summary['target'],
            'players': summary['players'],
        })
        logger.info('Bilardo WebSocket bağlandı: %s', self.room_code)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if self.seat is not None:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'presence',
                    'seat': self.seat,
                    'online': False,
                },
            )
        logger.info('Bilardo WebSocket ayrıldı: %s (%s)', self.room_code, close_code)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            await self.send_error('Geçersiz veri gönderildi.')
            return

        message_type = data.get('type')
        handlers = {
            'join_player': self.handle_join_player,
            'shoot': self.handle_shoot,
            'settle': self.handle_settle,
            'rematch': self.handle_rematch,
            'emote': self.handle_emote,
            'get_state': self.handle_get_state,
            'ping': self.handle_ping,
        }
        handler = handlers.get(message_type)
        if not handler:
            await self.send_error(f'Bilinmeyen mesaj tipi: {message_type}')
            return

        try:
            await handler(data)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception('Bilardo mesajı işlenemedi (%s): %s', message_type, exc)
            await self.send_error('Beklenmeyen bir hata oluştu.')

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def handle_join_player(self, data):
        identifier = (data.get('player_identifier') or self.player_identifier or '').strip()
        if not identifier:
            await self.send_error('Oyuncu kimliği gerekli.')
            return

        result = await self.get_or_create_player(
            identifier,
            data.get('name'),
            data.get('cue'),
        )
        if result.get('error'):
            await self.send_error(result['error'])
            return

        self.player_identifier = result['identifier']
        self.seat = result['seat']

        payload = await self.build_join_payload()
        if not payload:
            await self.send_error('Oda bulunamadı.')
            return

        await self.send_json(payload)

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'players_update',
                'players': payload['players'],
                'status': payload['status'],
            },
        )
        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'presence', 'seat': self.seat, 'online': True},
        )

        if result.get('started'):
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'state_update',
                    'state': payload['state'],
                    'by': None,
                    'status': payload['status'],
                    'winner_seat': None,
                    'result': {'message': 'İki oyuncu hazır. Oyun başladı.'},
                },
            )

    async def handle_shoot(self, data):
        if self.seat is None:
            await self.send_error('Önce odaya katılmalısın.')
            return

        result = await self.begin_shot(self.seat, data.get('params') or {}, data.get('shot_id'))
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'shot_started',
                'state': result['state'],
                'params': result['params'],
                'seat': self.seat,
                'shot_id': result['shot_id'],
            },
        )

    async def handle_settle(self, data):
        if self.seat is None:
            await self.send_error('Önce odaya katılmalısın.')
            return

        result = await self.finish_shot(
            self.seat,
            data.get('shot_id'),
            data.get('state') or {},
            data.get('result') or {},
        )
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'state_update',
                'state': result['state'],
                'by': self.seat,
                'status': result['status'],
                'winner_seat': result['winner_seat'],
                'result': result['result'],
            },
        )

        if result['winner_seat'] is not None:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'game_over',
                    'winner_seat': result['winner_seat'],
                    'state': result['state'],
                },
            )

    async def handle_rematch(self, data):
        if self.seat is None:
            await self.send_error('Önce odaya katılmalısın.')
            return

        result = await self.reset_room(self.seat)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'room_reset',
                'state': result['state'],
                'players': result['players'],
                'status': result['status'],
            },
        )

    async def handle_emote(self, data):
        if self.seat is None:
            return
        text = str(data.get('text') or '').strip()[:MAX_EMOTE_LENGTH]
        if not text:
            return
        name = await self.player_name(self.player_identifier)
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'emote',
                'seat': self.seat,
                'name': name,
                'text': text,
            },
        )

    async def handle_get_state(self, data):
        payload = await self.build_join_payload()
        if not payload:
            await self.send_error('Oda bulunamadı.')
            return
        await self.send_json({
            'type': 'state_update',
            'state': payload['state'],
            'by': None,
            'status': payload['status'],
            'winner_seat': None,
            'result': {},
        })

    async def handle_ping(self, data):
        await self.send_json({'type': 'pong', 'time': data.get('time')})

    # ------------------------------------------------------------------
    # Group message handlers
    # ------------------------------------------------------------------
    async def shot_started(self, event):
        await self.send_json({
            'type': 'shot',
            'state': event['state'],
            'params': event['params'],
            'seat': event['seat'],
            'shot_id': event['shot_id'],
        })

    async def state_update(self, event):
        await self.send_json({
            'type': 'state_update',
            'state': event['state'],
            'by': event.get('by'),
            'status': event.get('status'),
            'winner_seat': event.get('winner_seat'),
            'result': event.get('result') or {},
        })

    async def game_over(self, event):
        await self.send_json({
            'type': 'game_over',
            'winner_seat': event['winner_seat'],
            'state': event['state'],
        })

    async def room_reset(self, event):
        await self.send_json({
            'type': 'room_reset',
            'state': event['state'],
            'players': event['players'],
            'status': event['status'],
        })

    async def players_update(self, event):
        await self.send_json({
            'type': 'players_update',
            'players': event['players'],
            'status': event['status'],
        })

    async def presence(self, event):
        await self.send_json({
            'type': 'presence',
            'seat': event['seat'],
            'online': event['online'],
        })

    async def emote(self, event):
        await self.send_json({
            'type': 'emote',
            'seat': event['seat'],
            'name': event['name'],
            'text': event['text'],
        })

    async def send_error(self, message):
        await self.send_json({'type': 'error', 'message': message})

    async def send_json(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    @database_sync_to_async
    def room_summary(self):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None
        return {
            'status': room.status,
            'mode': room.mode,
            'target': room.target,
            'players': self._serialize_players(room),
        }

    @database_sync_to_async
    def build_join_payload(self):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None
        state = room.state or create_initial_state(room.mode, room.target)
        return {
            'type': 'joined',
            'room_code': room.room_code,
            'seat': self.seat,
            'status': room.status,
            'mode': room.mode,
            'target': room.target,
            'state': state,
            'players': self._serialize_players(room),
            'winner_seat': room.winner_seat,
        }

    def _serialize_players(self, room):
        return [
            {
                'identifier': player.player_identifier,
                'name': player.name or f'Oyuncu {player.seat + 1}',
                'seat': player.seat,
                'cue': player.cue or DEFAULT_CUE,
            }
            for player in room.players.order_by('seat', 'joined_at')
        ]

    @database_sync_to_async
    def player_name(self, identifier):
        player = GamePlayer.objects.filter(player_identifier=identifier).first()
        return player.name if player else 'Oyuncu'

    @database_sync_to_async
    def get_or_create_player(self, identifier, raw_name, raw_cue):
        with transaction.atomic():
            room = GameRoom.objects.select_for_update().filter(room_code=self.room_code).first()
            if not room:
                return {'error': 'Oda bulunamadı.'}

            existing = room.players.filter(player_identifier=identifier).first()
            if existing:
                return {
                    'identifier': existing.player_identifier,
                    'seat': existing.seat,
                    'started': False,
                }

            if room.status == 'FINISHED':
                return {'error': 'Bu oyun bitmiş. Yeni bir oda kur.'}
            if room.players.count() >= 2:
                return {'error': 'Oda dolu.'}

            used_seats = set(room.players.values_list('seat', flat=True))
            seat = 0 if 0 not in used_seats else 1
            name = (raw_name or '').strip()[:30] or f'Oyuncu {seat + 1}'
            cue = validate_cue(raw_cue)

            GamePlayer.objects.create(
                game_room=room,
                player_identifier=identifier,
                name=name,
                seat=seat,
                cue=cue,
            )

            started = False
            if room.players.count() >= 2 and room.status == 'WAITING':
                room.status = 'IN_PROGRESS'
                room.started_at = timezone.now()
                state = room.state or create_initial_state(room.mode, room.target)
                state['message'] = 'İki oyuncu hazır. Oyun başladı.'
                room.state = state
                room.save(update_fields=['status', 'started_at', 'state', 'updated_at'])
                started = True

            return {'identifier': identifier, 'seat': seat, 'started': started}

    @database_sync_to_async
    def begin_shot(self, seat, raw_params, client_shot_id=None):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}

        player = room.players.filter(seat=seat).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}

        state = room.state or {}
        if state.get('winner') is not None:
            return {'error': 'Oyun bitti.'}
        if int(state.get('turn', 0)) != seat:
            return {'error': 'Sıra sende değil.'}

        pending = state.get('pending')
        if isinstance(pending, dict):
            try:
                age = time.time() - float(pending.get('at', 0))
            except (TypeError, ValueError):
                age = PENDING_TIMEOUT + 1
            if age < PENDING_TIMEOUT:
                return {'error': 'Önceki vuruşun tamamlanması bekleniyor.'}

        params, error = self._clean_shot_params(raw_params, player.cue)
        if error:
            return {'error': error}

        if state.get('ball_in_hand'):
            if params.get('cueX') is None or params.get('cueY') is None:
                return {'error': 'İsteka topunu masaya yerleştir.'}
            ok, message = place_cue_ball(state, params['cueX'], params['cueY'])
            if not ok:
                return {'error': message}
            state['ball_in_hand'] = False
        else:
            params.pop('cueX', None)
            params.pop('cueY', None)

        shot_id = self._clean_shot_id(client_shot_id)
        state['pending'] = {'id': shot_id, 'seat': seat, 'at': time.time()}
        room.state = state
        room.save(update_fields=['state', 'updated_at'])

        Shot.objects.create(
            game_room=room,
            player=player,
            angle=params['angle'],
            power=params['power'],
            spin_x=params['spinX'],
            spin_y=params['spinY'],
        )

        return {'state': state, 'params': params, 'shot_id': shot_id}

    def _clean_shot_id(self, raw):
        """İstemcinin gönderdiği vuruş kimliğini güvenli biçimde kabul et."""
        if not isinstance(raw, str):
            return str(uuid.uuid4())
        value = raw.strip()
        if not (8 <= len(value) <= 64):
            return str(uuid.uuid4())
        allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')
        if any(char not in allowed for char in value):
            return str(uuid.uuid4())
        return value

    def _clean_shot_params(self, raw, cue_id):
        if not isinstance(raw, dict):
            return None, 'Vuruş bilgisi geçersiz.'

        def number(key, default=0.0):
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError):
                return None
            if not math.isfinite(value):
                return None
            return value

        angle = number('angle')
        power = number('power', 0)
        spin_x = number('spinX', 0)
        spin_y = number('spinY', 0)
        vx = number('vx', 0)
        vy = number('vy', 0)
        if None in (angle, power, spin_x, spin_y, vx, vy):
            return None, 'Vuruş bilgisi geçersiz.'

        power = min(max(power, 0.02), 1.0)
        spin_x = min(max(spin_x, -1.0), 1.0)
        spin_y = min(max(spin_y, -1.0), 1.0)
        speed = math.hypot(vx, vy)
        if speed > 980:
            scale = 980 / speed
            vx *= scale
            vy *= scale
            speed = 980
        if speed < 8:
            return None, 'Vuruş gücü çok düşük.'

        cue = CUE_BY_ID.get(cue_id) or CUE_BY_ID[DEFAULT_CUE]
        params = {
            'angle': angle,
            'power': power,
            'spinX': spin_x,
            'spinY': spin_y,
            'vx': vx,
            'vy': vy,
            'speed': speed,
            'cueId': cue['id'],
            'cueStats': {
                'power': cue['power'],
                'spin': cue['spin'],
                'control': cue['control'],
            },
        }
        for key in ('cueX', 'cueY'):
            if raw.get(key) is not None:
                value = number(key)
                if value is None:
                    return None, 'İsteka topu konumu geçersiz.'
                params[key] = value
        return params, None

    @database_sync_to_async
    def finish_shot(self, seat, shot_id, incoming_state, result_payload):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}

        player = room.players.filter(seat=seat).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}

        state = room.state or {}
        if int(state.get('turn', 0)) != seat:
            return {'error': 'Sıra sende değil.'}

        pending = state.get('pending')
        if isinstance(pending, dict) and shot_id:
            if pending.get('id') != shot_id:
                try:
                    age = time.time() - float(pending.get('at', 0))
                except (TypeError, ValueError):
                    age = PENDING_TIMEOUT + 1
                if age < PENDING_TIMEOUT:
                    return {'error': 'Vuruş kimliği eşleşmiyor.'}

        clean = sanitize_state(state, incoming_state)
        winner = clean.get('winner')
        status = 'FINISHED' if winner in (0, 1) else 'IN_PROGRESS'
        winner_seat = winner if winner in (0, 1) else None

        room.state = clean
        room.status = status
        room.winner_seat = winner_seat
        update_fields = ['state', 'status', 'winner_seat', 'updated_at']
        if winner_seat is not None:
            room.finished_at = timezone.now()
            update_fields.append('finished_at')
        room.save(update_fields=update_fields)

        shot = Shot.objects.filter(game_room=room, player=player).order_by('-created_at').first()
        if shot:
            shot.pocketed = list(clean.get('last_shot', {}).get('pocketed') or [])
            shot.foul = bool(clean.get('last_shot', {}).get('foul'))
            shot.save(update_fields=['pocketed', 'foul'])

        result = {
            'message': str((result_payload or {}).get('message') or clean.get('message') or '')[:220],
            'foul': bool((result_payload or {}).get('foul')),
            'seat': seat,
        }
        return {
            'state': clean,
            'status': status,
            'winner_seat': winner_seat,
            'result': result,
        }

    @database_sync_to_async
    def reset_room(self, seat):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return {'error': 'Oda bulunamadı.'}
        if not room.players.filter(seat=seat).exists():
            return {'error': 'Oyuncu bulunamadı.'}
        if room.players.count() < 2:
            return {'error': 'Yeniden oynamak için iki oyuncu gerekli.'}

        previous = room.state or {}
        breaker = 1 - int(previous.get('breaker', 0) or 0)
        mode = room.mode if room.mode in MODES else 'three_cushion'
        state = create_initial_state(mode, validate_target(mode, room.target), breaker=breaker)
        state['message'] = 'Yeni oyun başladı.'

        room.state = state
        room.status = 'IN_PROGRESS'
        room.winner_seat = None
        room.finished_at = None
        room.started_at = timezone.now()
        room.save(update_fields=[
            'state', 'status', 'winner_seat', 'finished_at', 'started_at', 'updated_at',
        ])

        return {
            'state': state,
            'players': self._serialize_players(room),
            'status': room.status,
        }
