import asyncio
import json
import logging
import threading

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from . import analyzer, commentary, services, speech
from .models import GamePlayer, GameRoom, Move, initial_fen

logger = logging.getLogger(__name__)


def _compute_commentary(before_fen, after_fen, uci, mover_color, mover_name,
                        opponent_name, game_over, winner_color):
    """Blocking analiz + yorum seçimi (thread pool içinde çalışır)."""
    before = analyzer.analyze(before_fen)
    after = analyzer.analyze(after_fen)
    flags = commentary.move_flags(before_fen, uci)
    return commentary.pick_comment(
        before, after, mover_color, mover_name, opponent_name,
        game_over=game_over, winner_color=winner_color, flags=flags,
    )


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'satranc_game_{self.room_code}'
        self.player_identifier = None
        self.commentary_cooldown = commentary.CommentCooldown(
            min_interval=getattr(settings, 'SATRANC_AI_COOLDOWN', 10),
            event_interval=getattr(settings, 'SATRANC_AI_EVENT_COOLDOWN', 30),
        )
        self._commentary_lock = asyncio.Lock()

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

        name = (data.get('name') or '').strip()[:30]
        player, created = await self.get_or_create_player(identifier, name)
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

        # İkinci oyuncu gelip oyun başladıysa sesli karşılama yap.
        if created and player.get('started') and getattr(
            settings, 'SATRANC_AI_COMMENTARY_ENABLED', True
        ):
            await self.announce_game_start()

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
        await self.maybe_commentary(result)

    async def handle_restart_game(self, data):
        identifier = self._identifier(data)
        result = await self.reset_room(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        self.commentary_cooldown.reset()
        await self.broadcast_state()

    async def handle_get_state(self, data):
        await self.send_room_state()

    # ------------------------------------------------------------------
    # Sesli AI yorumu (Stockfish + ElevenLabs)
    # ------------------------------------------------------------------
    async def maybe_commentary(self, result):
        """Önemli bir pozisyon değişikliğinde yorum sesi üretip gönderir.

        Yorum yalnızca hamleyi yapan oyuncuya (bu bağlantıya) gönderilir.
        """
        if not getattr(settings, 'SATRANC_AI_COMMENTARY_ENABLED', True):
            return

        try:
            async with self._commentary_lock:
                pick = await sync_to_async(_compute_commentary, thread_sensitive=False)(
                    result.get('fen_before'),
                    result.get('fen_after'),
                    result.get('uci'),
                    result.get('mover_color'),
                    result.get('mover_name') or 'Oyuncu',
                    result.get('opponent_name') or 'Rakip',
                    bool(result.get('game_over')),
                    result.get('winner_color'),
                )
        except Exception as exc:  # pragma: no cover - savunmaci
            logger.warning('Yorum hesaplanamadi: %s', exc)
            return

        if not pick:
            return

        event, text = pick
        if not self.commentary_cooldown.allow(event, text):
            return
        self.commentary_cooldown.mark(event, text)

        await self.send_commentary(text, event)

    async def announce_game_start(self):
        """Oyun başlarken iki oyuncunun adıyla sesli karşılama yapar."""
        state = await self.build_room_state()
        players = (state or {}).get('players', [])
        white = next((p['name'] for p in players if p['color'] == 'w' and p.get('name')), 'Beyaz')
        black = next((p['name'] for p in players if p['color'] == 'b' and p.get('name')), 'Siyah')
        text = commentary.game_start_text(white, black)
        if text:
            await self.send_commentary(text, commentary.EVENT_GAME_START)

    async def send_commentary(self, text, event):
        await self.send(text_data=json.dumps({
            'type': 'commentary',
            'event': event,
            'text': text,
            'sample_rate': getattr(settings, 'SATRANC_TTS_SAMPLE_RATE', 24000),
            'format': 's16le',
            'channels': 1,
        }))

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def produce():
            try:
                for chunk in speech.stream_audio(text):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:  # pragma: no cover - savunmaci
                logger.warning('TTS uretim hatasi: %s', exc)
            finally:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                except Exception:  # pragma: no cover - dongu kapandi
                    pass

        threading.Thread(target=produce, daemon=True).start()

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            try:
                await self.send(bytes_data=chunk)
            except Exception:  # pragma: no cover - baglanti koptu
                return

        try:
            await self.send(text_data=json.dumps({'type': 'commentary_end'}))
        except Exception:  # pragma: no cover - baglanti koptu
            pass

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
    def get_or_create_player(self, identifier, name=''):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None, False

        player = room.players.filter(player_identifier=identifier).first()
        if player:
            if name and player.name != name:
                player.name = name
                player.save(update_fields=['name'])
            return {
                'id': str(player.id),
                'color': player.color,
                'name': player.name,
                'ready': True,
                'started': room.status == 'IN_PROGRESS',
            }, False

        if room.players.count() >= 2:
            return None, False

        used_colors = set(room.players.values_list('color', flat=True))
        color = 'w' if 'w' not in used_colors else 'b'

        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            color=color,
            name=name,
        )

        started = False
        if room.players.count() == 2 and room.status == 'WAITING':
            room.status = 'IN_PROGRESS'
            room.started_at = timezone.now()
            room.save(update_fields=['status', 'started_at', 'updated_at'])
            started = True

        return {
            'id': str(player.id),
            'color': color,
            'name': name,
            'ready': True,
            'started': started,
        }, True

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

        before_fen = room.fen
        result = services.apply_move(before_fen, uci)
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

        opponent = room.players.exclude(id=player.id).first()
        result['fen_before'] = before_fen
        result['fen_after'] = result['fen']
        result['mover_color'] = player.color
        result['mover_name'] = player.name or 'Oyuncu'
        result['opponent_name'] = (opponent.name if opponent and opponent.name else 'Rakip')
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
                    'name': player.name or '',
                }
                for player in players
            ],
        }
