import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from . import bot, services
from .models import GamePlayer, GameRoom, Move, initial_fen

logger = logging.getLogger(__name__)

# "Rakibe süre ver" özelliğinde eklenecek saniye.
GIVE_TIME_SECONDS = 15


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'satranc_game_{self.room_code}'
        self.player_identifier = None
        self._bot_lock = asyncio.Lock()

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
            'flag': self.handle_flag,
            'resign': self.handle_resign,
            'draw_offer': self.handle_draw_offer,
            'draw_accept': self.handle_draw_accept,
            'draw_decline': self.handle_draw_decline,
            'give_time': self.handle_give_time,
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
        player, _ = await self.get_or_create_player(identifier, name)
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

        # Bot beyazsa (veya botun sırasıysa) ilk hamleyi bot yapsın.
        await self.maybe_play_bot_move()

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
        await self.maybe_play_bot_move()

    async def handle_restart_game(self, data):
        identifier = self._identifier(data)
        result = await self.reset_room(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()
        await self.maybe_play_bot_move()

    async def handle_get_state(self, data):
        await self.send_room_state()

    async def handle_flag(self, data):
        """İstemci süresi dolduğunu bildirdi; sunucu doğrulayıp bitirir."""
        finished = await self.flag_if_expired()
        if finished:
            await self.broadcast_state()

    async def handle_resign(self, data):
        """Oyuncu pes etti; rakibi kazanır."""
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        result = await self.resign_game(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_draw_offer(self, data):
        """Oyuncu beraberlik teklif etti."""
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        result = await self.offer_draw(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'draw_offered', 'by': identifier},
        )
        await self.broadcast_state()

    async def handle_draw_accept(self, data):
        """Oyuncu beraberlik teklifini kabul etti."""
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        result = await self.respond_draw(identifier, accept=True)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_draw_decline(self, data):
        """Oyuncu beraberlik teklifini reddetti."""
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        result = await self.respond_draw(identifier, accept=False)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'draw_declined', 'by': identifier},
        )
        await self.broadcast_state()

    async def handle_give_time(self, data):
        """Oyuncu rakibinin saatine ek süre verir."""
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        result = await self.give_time(identifier)
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'time_given',
                'by': identifier,
                'seconds': result['seconds'],
                'color': result['color'],
            },
        )
        await self.broadcast_state()

    # ------------------------------------------------------------------
    # Bot hamlesi
    # ------------------------------------------------------------------
    async def maybe_play_bot_move(self):
        """Bot sırasıysa Stockfish API'den hamle alıp oynatır."""
        async with self._bot_lock:
            # Bot art arda oynayabilir (ör. terfi/çift hamle durumları).
            for _ in range(4):
                info = await self.get_bot_turn()
                if not info:
                    return

                move = await sync_to_async(bot.choose_move, thread_sensitive=False)(
                    info['fen'], info['level'],
                )
                if not move:
                    return

                result = await self.make_bot_move(move)
                if result.get('error'):
                    logger.warning('Bot hamlesi uygulanamadı: %s', result['error'])
                    return

                await self.broadcast_state()
                if result.get('game_over'):
                    return

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

    async def draw_offered(self, event):
        await self.send(text_data=json.dumps({
            'type': 'draw_offered',
            'by': event['by'],
        }))

    async def draw_declined(self, event):
        await self.send(text_data=json.dumps({
            'type': 'draw_declined',
            'by': event['by'],
        }))

    async def time_given(self, event):
        await self.send(text_data=json.dumps({
            'type': 'time_given',
            'by': event['by'],
            'seconds': event['seconds'],
            'color': event['color'],
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

        if room.is_bot_game:
            return None, False

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
            now = timezone.now()
            room.status = 'IN_PROGRESS'
            room.started_at = now
            room.begin_clock(now)
            room.save(update_fields=[
                'status', 'started_at', 'updated_at',
                'white_time_left', 'black_time_left', 'turn_started_at',
            ])
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

        if player.player_identifier.startswith('bot:'):
            return {'error': 'Bot adına hamle yapılamaz.'}

        if services.turn_color(room.fen) != player.color:
            return {'error': 'Sıra sende değil.'}

        return self._apply_move(room, player, uci)

    @database_sync_to_async
    def get_bot_turn(self):
        """Bot oynayacaksa gerekli bilgileri döndürür, aksi halde ``None``."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or not room.is_bot_game or room.status != 'IN_PROGRESS':
            return None
        if not room.bot_color or services.turn_color(room.fen) != room.bot_color:
            return None
        return {'fen': room.fen, 'level': room.bot_level or bot.DEFAULT_LEVEL}

    @database_sync_to_async
    def make_bot_move(self, uci):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}

        player = room.players.filter(player_identifier=f'bot:{room.room_code}').first()
        if not player:
            return {'error': 'Bot oyuncu bulunamadı.'}

        if services.turn_color(room.fen) != player.color:
            return {'error': 'Sıra botta değil.'}

        return self._apply_move(room, player, uci)

    @database_sync_to_async
    def flag_if_expired(self):
        """Sırası gelmiş oyuncunun süresi dolmuşsa oyunu bitirir."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS' or not room.time_control:
            return False
        if room.turn_started_at is None:
            return False

        color = services.turn_color(room.fen)
        now = timezone.now()
        if self._consume_clock(room, color, now):
            self._finish_timeout(room, color, now)
            return True
        room.save(update_fields=['white_time_left', 'black_time_left'])
        return False

    @database_sync_to_async
    def resign_game(self, identifier):
        """Oyuncu pes eder; rakibi kazanır."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        player = room.players.filter(player_identifier=identifier).first()
        if not player or player.color not in ('w', 'b'):
            return {'error': 'Oyuncu bulunamadı.'}

        now = timezone.now()
        winner_color = 'b' if player.color == 'w' else 'w'
        room.status = 'FINISHED'
        room.result = '1-0' if winner_color == 'w' else '0-1'
        room.termination = 'resign'
        room.draw_offer_by = ''
        room.finished_at = now
        room.turn_started_at = None
        room.winner = room.players.filter(color=winner_color).first()
        room.save(update_fields=[
            'status', 'result', 'termination', 'draw_offer_by', 'finished_at',
            'turn_started_at', 'winner', 'updated_at',
        ])
        return {'ok': True}

    @database_sync_to_async
    def offer_draw(self, identifier):
        """Bekleyen beraberlik teklifini kaydeder."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        if identifier.startswith('bot:'):
            return {'error': 'Bot beraberlik teklif edemez.'}
        if not room.players.filter(player_identifier=identifier).exists():
            return {'error': 'Oyuncu bulunamadı.'}
        room.draw_offer_by = identifier
        room.save(update_fields=['draw_offer_by', 'updated_at'])
        return {'ok': True}

    @database_sync_to_async
    def respond_draw(self, identifier, accept=True):
        """Bekleyen beraberlik teklifini kabul eder ya da reddeder."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        offer_by = room.draw_offer_by
        if not offer_by:
            return {'error': 'Bekleyen bir beraberlik teklifi yok.'}
        if offer_by == identifier:
            return {'error': 'Kendi teklifini yanıtlayamazsın.'}
        if not room.players.filter(player_identifier=identifier).exists():
            return {'error': 'Oyuncu bulunamadı.'}

        if not accept:
            room.draw_offer_by = ''
            room.save(update_fields=['draw_offer_by', 'updated_at'])
            return {'ok': True}

        now = timezone.now()
        room.status = 'FINISHED'
        room.result = '1/2-1/2'
        room.termination = 'agreement'
        room.draw_offer_by = ''
        room.finished_at = now
        room.turn_started_at = None
        room.winner = None
        room.save(update_fields=[
            'status', 'result', 'termination', 'draw_offer_by', 'finished_at',
            'turn_started_at', 'winner', 'updated_at',
        ])
        return {'ok': True}

    @database_sync_to_async
    def give_time(self, identifier):
        """Oyuncunun rakibinin saatine ``GIVE_TIME_SECONDS`` ekler."""
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        if not room.time_control:
            return {'error': 'Bu oyunda saat kullanılmıyor.'}
        if room.is_bot_game:
            return {'error': 'Bot oyununda rakibe süre verilemez.'}
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}
        if player.player_identifier.startswith('bot:'):
            return {'error': 'Bot adına süre verilemez.'}

        opponent = room.players.exclude(id=player.id).first()
        if not opponent:
            return {'error': 'Rakip bulunamadı.'}

        field = 'white_time_left' if opponent.color == 'w' else 'black_time_left'
        setattr(room, field, float(getattr(room, field) or 0) + GIVE_TIME_SECONDS)
        room.save(update_fields=[field, 'updated_at'])
        return {
            'ok': True,
            'seconds': GIVE_TIME_SECONDS,
            'color': opponent.color,
        }

    def _consume_clock(self, room, color, now):
        """Sırası gelen oyuncunun saatinden geçen süreyi düşer.

        Süre bittiyse ``True`` döner (saat sıfırlanır ve oyun bitirilmelidir).
        """
        if not room.time_control or room.turn_started_at is None:
            return False
        elapsed = (now - room.turn_started_at).total_seconds()
        field = 'white_time_left' if color == 'w' else 'black_time_left'
        remaining = getattr(room, field) - elapsed
        if remaining <= 0:
            setattr(room, field, 0.0)
            room.turn_started_at = None
            return True
        setattr(room, field, remaining)
        return False

    def _finish_timeout(self, room, loser_color, now):
        winner_color = 'b' if loser_color == 'w' else 'w'
        room.status = 'FINISHED'
        room.result = '1-0' if winner_color == 'w' else '0-1'
        room.termination = 'timeout'
        room.draw_offer_by = ''
        room.finished_at = now
        room.turn_started_at = None
        room.winner = room.players.filter(color=winner_color).first()
        room.save(update_fields=[
            'status', 'result', 'termination', 'draw_offer_by', 'finished_at',
            'winner', 'white_time_left', 'black_time_left', 'turn_started_at',
            'updated_at',
        ])
        return {
            'uci': None,
            'san': '',
            'fen': room.fen,
            'fen_after': room.fen,
            'game_over': True,
            'timeout': True,
            'result': room.result,
            'winner_color': winner_color,
            'loser_color': loser_color,
        }

    def _apply_move(self, room, player, uci):
        now = timezone.now()

        # Hamle yapılmadan önce oyuncunun süresi dolduysa kaybeder.
        if self._consume_clock(room, player.color, now):
            return self._finish_timeout(room, player.color, now)

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

        # Üç tekrar / 50 hamle kuralı gereği otomatik beraberlik kontrolü.
        draw_reason = None
        game_over = bool(result.get('game_over'))
        if not game_over:
            ucis = list(room.moves.order_by('created_at').values_list('uci', flat=True))
            draw_reason = services.automatic_draw_reason(initial_fen(), ucis)
            if draw_reason:
                game_over = True

        if game_over:
            room.status = 'FINISHED'
            room.result = '1/2-1/2' if draw_reason else (result['result'] or '')
            room.termination = draw_reason or result.get('termination') or ''
            room.finished_at = now
            winner_color = None if draw_reason else result['winner_color']
            room.winner = (
                room.players.filter(color=winner_color).first() if winner_color else None
            )
            room.turn_started_at = None
            update_fields += [
                'status', 'result', 'termination', 'finished_at', 'winner',
                'turn_started_at',
            ]
        elif room.time_control:
            # Fischer artırımı: hamleyi yapan oyuncunun saatine eklenir.
            if room.increment:
                field = 'white_time_left' if player.color == 'w' else 'black_time_left'
                setattr(room, field, getattr(room, field) + room.increment)
            room.turn_started_at = now
            update_fields.append('turn_started_at')

        # Herhangi bir hamle bekleyen beraberlik teklifini iptal eder.
        if room.draw_offer_by:
            room.draw_offer_by = ''
            update_fields.append('draw_offer_by')

        if room.time_control:
            update_fields += ['white_time_left', 'black_time_left']

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
        room.termination = 'abandon'
        room.turn_started_at = None
        room.save(update_fields=['status', 'termination', 'turn_started_at', 'updated_at'])
        return True

    @database_sync_to_async
    def reset_room(self, identifier):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return {'error': 'Oda bulunamadı.'}
        if not room.players.filter(player_identifier=identifier).exists():
            return {'error': 'Oyuncu bulunamadı.'}

        now = timezone.now()
        Move.objects.filter(game_room=room).delete()
        room.fen = initial_fen()
        room.status = 'IN_PROGRESS' if room.players.count() == 2 else 'WAITING'
        room.winner = None
        room.result = ''
        room.termination = ''
        room.draw_offer_by = ''
        room.started_at = now if room.status == 'IN_PROGRESS' else None
        room.finished_at = None
        room.begin_clock(now)
        room.save(update_fields=[
            'fen', 'status', 'winner', 'result', 'termination', 'draw_offer_by',
            'started_at', 'finished_at', 'white_time_left', 'black_time_left',
            'turn_started_at', 'updated_at',
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
        moves = []
        for move in room.moves.select_related('player').order_by('created_at'):
            moves.append({
                'uci': move.uci,
                'san': move.san,
                'color': move.player.color,
                'player_identifier': move.player.player_identifier,
                'fen_after': move.fen_after,
                'check': services.is_check(move.fen_after),
            })

        return {
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'fen': room.fen,
            'initial_fen': initial_fen(),
            'turn': services.turn_color(room.fen),
            'legal_moves': services.legal_moves(room.fen),
            'check': services.is_check(room.fen),
            'moves': moves,
            'result': room.result or None,
            'winner_color': room.winner.color if room.winner else None,
            'winner_identifier': (
                room.winner.player_identifier if room.winner else None
            ),
            'is_bot_game': room.is_bot_game,
            'bot_level': room.bot_level,
            'bot_color': room.bot_color or None,
            'time_control': room.time_control,
            'increment': room.increment,
            'white_time_left': room.white_time_left,
            'black_time_left': room.black_time_left,
            'turn_started_at': (
                room.turn_started_at.isoformat() if room.turn_started_at else None
            ),
            'draw_offer_by': room.draw_offer_by or None,
            'termination': room.termination or None,
            'server_time': timezone.now().isoformat(),
            'players': [
                {
                    'id': str(player.id),
                    'player_identifier': player.player_identifier,
                    'color': player.color,
                    'name': player.name or '',
                    'is_bot': player.player_identifier.startswith('bot:'),
                }
                for player in players
            ],
        }
