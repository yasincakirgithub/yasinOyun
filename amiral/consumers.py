import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import GRID_SIZE, GamePlayer, GameRoom, Shot
from .services import (
    all_sunk,
    is_hit,
    normalize_ships,
    remaining_ships,
    sunk_ship_name,
)

logger = logging.getLogger(__name__)


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'amiral_game_{self.room_code}'
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
            'place_ships': self.handle_place_ships,
            'fire': self.handle_fire,
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
        await self.send_room_state()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_joined',
                'player_id': player['id'],
                'player_identifier': identifier,
                'ready': player['ready'],
            },
        )

    async def handle_place_ships(self, data):
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return

        ships = data.get('ships')
        normalized, error = normalize_ships(ships)
        if error:
            await self.send_error(error)
            return

        saved = await self.save_ships(identifier, normalized)
        if not saved:
            await self.send_error("Gemiler kaydedilemedi.")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_ready',
                'player_identifier': identifier,
            },
        )

        await self.check_game_start()

    async def handle_fire(self, data):
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return

        row = data.get('row')
        col = data.get('col')
        if not isinstance(row, int) or not isinstance(col, int):
            await self.send_error("Geçersiz hedef.")
            return
        if not (0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE):
            await self.send_error("Hedef tahtanın dışında.")
            return

        result = await self.fire(identifier, row, col)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'shot_result',
                'shooter_identifier': identifier,
                'row': row,
                'col': col,
                'hit': result['hit'],
                'sunk': result['sunk'],
                'remaining': result['remaining'],
                'game_over': result['game_over'],
                'winner_identifier': result['winner_identifier'],
            },
        )

        if result['game_over']:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_finished',
                    'winner_identifier': result['winner_identifier'],
                    'reveal': result['reveal'],
                },
            )
        elif result['turn_changed']:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'turn_changed',
                    'current_turn_identifier': result['current_turn_identifier'],
                },
            )

    async def handle_restart_game(self, data):
        identifier = self._identifier(data)
        result = await self.reset_room(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'room_reset',
                'players': result['players'],
            },
        )

    async def handle_get_state(self, data):
        await self.send_room_state()

    # ------------------------------------------------------------------
    # Game flow helpers
    # ------------------------------------------------------------------
    async def check_game_start(self):
        result = await self.start_if_ready()
        if not result:
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'game_started',
                'current_turn_identifier': result['current_turn_identifier'],
            },
        )

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
    async def player_joined(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_joined',
            'player_id': event['player_id'],
            'player_identifier': event['player_identifier'],
            'ready': event['ready'],
        }))

    async def player_ready(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_ready',
            'player_identifier': event['player_identifier'],
        }))

    async def game_started(self, event):
        await self.send(text_data=json.dumps({
            'type': 'game_started',
            'current_turn_identifier': event['current_turn_identifier'],
        }))

    async def turn_changed(self, event):
        await self.send(text_data=json.dumps({
            'type': 'turn_changed',
            'current_turn_identifier': event['current_turn_identifier'],
        }))

    async def shot_result(self, event):
        await self.send(text_data=json.dumps({
            'type': 'shot_result',
            'shooter_identifier': event['shooter_identifier'],
            'row': event['row'],
            'col': event['col'],
            'hit': event['hit'],
            'sunk': event['sunk'],
            'remaining': event['remaining'],
            'game_over': event['game_over'],
            'winner_identifier': event['winner_identifier'],
        }))

    async def game_finished(self, event):
        await self.send(text_data=json.dumps({
            'type': 'game_finished',
            'winner_identifier': event['winner_identifier'],
            'reveal': event.get('reveal', {}),
        }))

    async def room_reset(self, event):
        await self.send(text_data=json.dumps({
            'type': 'room_reset',
            'players': event['players'],
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
            GameRoom.objects.select_related('current_turn', 'winner')
            .filter(room_code=self.room_code)
            .first()
        )

    @database_sync_to_async
    def get_or_create_player(self, identifier):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None, False

        player = GamePlayer.objects.filter(
            game_room=room, player_identifier=identifier
        ).first()
        if player:
            return {'id': str(player.id), 'ready': player.ready}, False

        if room.players.count() >= 2:
            return None, False

        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            ships=[],
            ready=False,
        )
        if room.status == 'WAITING':
            room.status = 'PLACING'
            room.save(update_fields=['status', 'updated_at'])
        return {'id': str(player.id), 'ready': player.ready}, True

    @database_sync_to_async
    def save_ships(self, identifier, ships):
        player = GamePlayer.objects.filter(
            game_room__room_code=self.room_code, player_identifier=identifier
        ).first()
        if not player:
            return None
        player.ships = ships
        player.ready = True
        player.save(update_fields=['ships', 'ready'])
        return {'id': str(player.id)}

    @database_sync_to_async
    def start_if_ready(self):
        room = (
            GameRoom.objects.select_related('current_turn')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room or room.status in ('IN_PROGRESS', 'FINISHED'):
            return None

        players = list(room.players.order_by('joined_at'))
        if len(players) != 2 or not all(p.ready for p in players):
            return None

        first = players[0]
        room.status = 'IN_PROGRESS'
        room.current_turn = first
        if not room.started_at:
            room.started_at = timezone.now()
        room.save(update_fields=['status', 'current_turn', 'started_at', 'updated_at'])
        return {'current_turn_identifier': str(first.player_identifier)}

    @database_sync_to_async
    def fire(self, identifier, row, col):
        room = (
            GameRoom.objects.select_related('current_turn')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}

        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}
        if room.current_turn_id != player.id:
            return {'error': 'Sıra sende değil.'}

        opponent = room.players.exclude(id=player.id).first()
        if not opponent:
            return {'error': 'Rakip bulunamadı.'}

        if Shot.objects.filter(
            game_room=room, shooter=player, row=row, col=col
        ).exists():
            return {'error': 'Bu kareye zaten ateş ettin.'}

        hit = is_hit(opponent.ships, row, col)
        Shot.objects.create(
            game_room=room, shooter=player, row=row, col=col, hit=hit
        )

        shots_against_opponent = [
            (s.row, s.col)
            for s in Shot.objects.filter(game_room=room, shooter=player)
        ]
        sunk = sunk_ship_name(opponent.ships, shots_against_opponent, row, col) if hit else None
        remaining = remaining_ships(opponent.ships, shots_against_opponent)
        game_over = all_sunk(opponent.ships, shots_against_opponent)

        turn_changed = False
        if game_over:
            room.status = 'FINISHED'
            room.winner = player
            room.finished_at = timezone.now()
            room.save(update_fields=['status', 'winner', 'finished_at', 'updated_at'])
        elif not hit:
            room.current_turn = opponent
            room.save(update_fields=['current_turn', 'updated_at'])
            turn_changed = True

        reveal = {}
        if game_over:
            # Identifier -> that player's own ships, so each client can pick
            # the opponent's entry (by excluding its own identifier).
            reveal = {
                str(player.player_identifier): player.ships,
                str(opponent.player_identifier): opponent.ships,
            }

        return {
            'hit': hit,
            'sunk': sunk,
            'remaining': remaining,
            'game_over': game_over,
            'winner_identifier': str(player.player_identifier) if game_over else None,
            'turn_changed': turn_changed,
            'current_turn_identifier': str(room.current_turn.player_identifier) if room.current_turn else None,
            'reveal': reveal,
        }

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
        room = (
            GameRoom.objects.select_related('current_turn')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return {'error': 'Oda bulunamadı.'}
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}

        room.players.update(ships=[], ready=False)
        Shot.objects.filter(game_room=room).delete()

        room.status = 'PLACING'
        room.current_turn = None
        room.winner = None
        room.started_at = None
        room.finished_at = None
        room.save(update_fields=[
            'status', 'current_turn', 'winner', 'started_at', 'finished_at', 'updated_at',
        ])

        players = [
            {'player_identifier': p.player_identifier}
            for p in room.players.order_by('joined_at')
        ]
        return {'players': players}

    @database_sync_to_async
    def build_room_state(self):
        room = (
            GameRoom.objects.select_related('current_turn', 'winner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return None

        players = list(room.players.order_by('joined_at'))
        finished = room.status == 'FINISHED'
        identifier = self.player_identifier

        me = next((p for p in players if p.player_identifier == identifier), None)
        opponent = next((p for p in players if p.player_identifier != identifier), None)

        my_ships = list(me.ships) if me else []
        my_shots = []
        incoming_shots = []
        enemy_ships = []

        if me:
            my_shots = [
                {'row': s.row, 'col': s.col, 'hit': s.hit}
                for s in Shot.objects.filter(game_room=room, shooter=me)
            ]
        if opponent:
            incoming_shots = [
                {'row': s.row, 'col': s.col, 'hit': s.hit}
                for s in Shot.objects.filter(game_room=room, shooter=opponent)
            ]
            if finished:
                enemy_ships = list(opponent.ships)

        return {
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'grid_size': GRID_SIZE,
            'current_turn_identifier': (
                str(room.current_turn.player_identifier) if room.current_turn else None
            ),
            'winner_identifier': (
                str(room.winner.player_identifier) if room.winner else None
            ),
            'players': [
                {
                    'id': str(p.id),
                    'player_identifier': p.player_identifier,
                    'ready': p.ready,
                }
                for p in players
            ],
            'my_ships': my_ships,
            'my_shots': my_shots,
            'incoming_shots': incoming_shots,
            'enemy_ships': enemy_ships,
        }
