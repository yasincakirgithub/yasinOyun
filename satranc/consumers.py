import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from . import services
from .models import GamePlayer, GameRoom, Move, initial_fen

logger = logging.getLogger(__name__)


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'satranc_game_{self.room_code}'
        self.player_identifier = None

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info("WebSocket connected for room %s", self.room_code)
        await self.send_room_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.handle_player_disconnect()
        logger.info("WebSocket disconnected for room %s (%s)", self.room_code, close_code)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("Geçersiz veri gönderildi.")
            return

        message_type = data.get('type')
        handlers = {
            'join_player': self.handle_join_player,
            'move': self.handle_move,
            'restart_game': self.handle_restart_game,
            'get_state': self.handle_get_state,
        }
        handler = handlers.get(message_type)
        if not handler:
            await self.send_error(f"Bilinmeyen mesaj tipi: {message_type}")
            return

        try:
            await handler(data)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Error handling %s: %s", message_type, exc)
            await self.send_error(str(exc))

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def handle_join_player(self, data):
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return

        player, created = await self.get_or_create_player(identifier)
        if not player:
            await self.send_error("Oda dolu veya bulunamadı.")
            return

        self.player_identifier = identifier

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_joined',
                'player_identifier': identifier,
                'color': player['color'],
                'ready': player['ready'],
            },
        )
        await self.broadcast_state()

    async def handle_move(self, data):
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return

        uci = (data.get('uci') or '').strip().lower()
        if not uci:
            await self.send_error("Hamle gerekli.")
            return

        result = await self.make_move(identifier, uci)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.broadcast_state()

    async def handle_restart_game(self, data):
        identifier = self._identifier(data)
        result = await self.reset_room(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_get_state(self, data):
        await self.send_room_state()

    async def handle_player_disconnect(self):
        if not self.player_identifier:
            return
        abandoned = await self.abandon_if_in_progress()
        if abandoned:
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'game_abandoned', 'message': 'Rakip bağlantıyı kesti.'},
            )

    # ------------------------------------------------------------------
    # Group message handlers
    # ------------------------------------------------------------------
    async def push_state(self, event):
        await self.send(text_data=json.dumps(event['state']))

    async def player_joined(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_joined',
            'player_identifier': event['player_identifier'],
            'color': event['color'],
        }))

    async def game_abandoned(self, event):
        await self.send(text_data=json.dumps({
            'type': 'game_abandoned',
            'message': event['message'],
        }))

    async def send_error(self, message):
        await self.send(text_data=json.dumps({'type': 'error', 'message': message}))

    async def send_room_state(self):
        state = await self.build_room_state()
        if state is None:
            await self.send_error("Oda bulunamadı.")
            return
        await self.send(text_data=json.dumps(state))

    async def broadcast_state(self):
        state = await self.build_room_state()
        if state is None:
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'push_state', 'state': state},
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _identifier(self, data):
        return data.get('player_identifier') or self.player_identifier

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------
    @database_sync_to_async
    def get_room(self):
        return (
            GameRoom.objects.select_related('winner')
            .filter(room_code=self.room_code)
            .first()
        )

    @database_sync_to_async
    def get_or_create_player(self, identifier):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None, False

        player = room.players.filter(player_identifier=identifier).first()
        if player:
            return {'id': str(player.id), 'color': player.color, 'ready': True}, False

        if room.players.count() >= 2:
            return None, False

        used_colors = set(room.players.values_list('color', flat=True))
        color = 'w' if 'w' not in used_colors else 'b'

        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            color=color,
        )

        if room.players.count() == 2 and room.status == 'WAITING':
            room.status = 'IN_PROGRESS'
            room.started_at = timezone.now()
            room.save(update_fields=['status', 'started_at', 'updated_at'])

        return {'id': str(player.id), 'color': color, 'ready': True}, True

    @database_sync_to_async
    def make_move(self, identifier, uci):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}

        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}

        if services.turn_color(room.fen) != player.color:
            return {'error': 'Sıra sende değil.'}

        result = services.apply_move(room.fen, uci)
        if result.get('error'):
            return result

        Move.objects.create(
            game_room=room,
            player=player,
            uci=result['uci'],
            san=result['san'],
            fen_after=result['fen'],
        )

        room.fen = result['fen']
        update_fields = ['fen', 'updated_at']

        if result['game_over']:
            room.status = 'FINISHED'
            room.result = result['result'] or ''
            room.finished_at = timezone.now()
            winner_color = result['winner_color']
            room.winner = (
                room.players.filter(color=winner_color).first() if winner_color else None
            )
            update_fields += ['status', 'result', 'finished_at', 'winner']

        room.save(update_fields=update_fields)
        return result

    @database_sync_to_async
    def abandon_if_in_progress(self):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return False
        room.status = 'ABANDONED'
        room.save(update_fields=['status', 'updated_at'])
        return True

    @database_sync_to_async
    def reset_room(self, identifier):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return {'error': 'Oda bulunamadı.'}
        if not room.players.filter(player_identifier=identifier).exists():
            return {'error': 'Oyuncu bulunamadı.'}

        Move.objects.filter(game_room=room).delete()
        room.fen = initial_fen()
        room.status = 'IN_PROGRESS' if room.players.count() == 2 else 'WAITING'
        room.winner = None
        room.result = ''
        room.started_at = timezone.now() if room.status == 'IN_PROGRESS' else None
        room.finished_at = None
        room.save(update_fields=[
            'fen', 'status', 'winner', 'result', 'started_at', 'finished_at', 'updated_at',
        ])
        return {'ok': True}

    @database_sync_to_async
    def build_room_state(self):
        room = (
            GameRoom.objects.select_related('winner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return None

        players = list(room.players.order_by('joined_at'))
        moves = [
            {
                'uci': move.uci,
                'san': move.san,
                'color': move.player.color,
                'player_identifier': move.player.player_identifier,
            }
            for move in room.moves.select_related('player').order_by('created_at')
        ]

        return {
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'fen': room.fen,
            'turn': services.turn_color(room.fen),
            'legal_moves': services.legal_moves(room.fen),
            'check': services.is_check(room.fen),
            'moves': moves,
            'result': room.result or None,
            'winner_color': room.winner.color if room.winner else None,
            'winner_identifier': (
                room.winner.player_identifier if room.winner else None
            ),
            'players': [
                {
                    'id': str(player.id),
                    'player_identifier': player.player_identifier,
                    'color': player.color,
                }
                for player in players
            ],
        }
