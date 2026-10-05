import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .characters import CHARACTER_MAP
from .models import Accusation, ChatMessage, GamePlayer, GameRoom
from .services import check_accusation, is_valid_character

logger = logging.getLogger(__name__)


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'kim_game_{self.room_code}'
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
            'choose_character': self.handle_choose_character,
            'send_chat': self.handle_send_chat,
            'ask_question': self.handle_ask_question,
            'answer_question': self.handle_answer_question,
            'make_accusation': self.handle_make_accusation,
            'set_eliminated': self.handle_set_eliminated,
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
                'player_id': str(player['id']),
                'player_identifier': identifier,
                'ready': player['ready'],
            },
        )

    async def handle_choose_character(self, data):
        identifier = self._identifier(data)
        character_id = (data.get('character_id') or '').strip()
        if not is_valid_character(character_id):
            await self.send_error("Geçersiz karakter seçimi.")
            return

        player = await self.set_character(identifier, character_id)
        if not player:
            await self.send_error("Oyuncu bulunamadı.")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_ready',
                'player_identifier': identifier,
                'character_id': character_id,
            },
        )

        await self.check_game_start()

    async def handle_send_chat(self, data):
        identifier = self._identifier(data)
        text = (data.get('text') or '').strip()
        if not text:
            return

        message = await self.create_message(identifier, 'chat', text)
        if not message:
            await self.send_error("Mesaj gönderilemedi.")
            return
        await self.broadcast_message(message)

    async def handle_ask_question(self, data):
        identifier = self._identifier(data)
        text = (data.get('text') or '').strip()
        if not text:
            await self.send_error("Soru boş olamaz.")
            return

        result = await self.ask_question(identifier, text)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.broadcast_message(result['message'])
        await self.broadcast_turn()

    async def handle_answer_question(self, data):
        identifier = self._identifier(data)
        answer = (data.get('answer') or '').strip().lower()
        if answer not in ('yes', 'no'):
            await self.send_error("Cevap 'yes' veya 'no' olmalı.")
            return

        result = await self.answer_question(identifier, answer)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.broadcast_message(result['message'])
        await self.broadcast_turn()

    async def handle_make_accusation(self, data):
        identifier = self._identifier(data)
        character_id = (data.get('character_id') or '').strip()
        if not is_valid_character(character_id):
            await self.send_error("Geçersiz karakter tahmini.")
            return

        result = await self.make_accusation(identifier, character_id)

        if result.get('error'):
            await self.send_error(result['error'])
            return

        await self.send(text_data=json.dumps({
            'type': 'accusation_result',
            'correct': result['correct'],
            'character_id': character_id,
        }))

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'game_finished',
                'winner_identifier': result['winner_identifier'],
                'loser_identifier': result['loser_identifier'],
                'reason': result['reason'],
                'reveal': result['reveal'],
            },
        )

    async def handle_set_eliminated(self, data):
        identifier = self._identifier(data)
        eliminated = data.get('eliminated') or []
        if not isinstance(eliminated, list):
            return
        eliminated = [cid for cid in eliminated if cid in CHARACTER_MAP]
        await self.save_eliminated(identifier, eliminated)

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
        abandoned = await self.abandon_if_in_progress(self.player_identifier)
        if abandoned:
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'game_abandoned', 'message': 'Rakip bağlantıyı kesti.'},
            )

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------
    async def broadcast_message(self, message):
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'chat_message', 'message': message},
        )

    async def broadcast_turn(self):
        state = await self.get_turn_state()
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'turn_changed',
                'current_turn_identifier': state['current_turn_identifier'],
                'awaiting_answer': state['awaiting_answer'],
                'question_owner_identifier': state['question_owner_identifier'],
            },
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
            'character_id': event['character_id'],
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
            'awaiting_answer': event['awaiting_answer'],
            'question_owner_identifier': event['question_owner_identifier'],
        }))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
        }))

    async def game_finished(self, event):
        await self.send(text_data=json.dumps({
            'type': 'game_finished',
            'winner_identifier': event['winner_identifier'],
            'loser_identifier': event['loser_identifier'],
            'reason': event['reason'],
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
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )

    @database_sync_to_async
    def get_or_create_player(self, identifier):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return None, False

        player = GamePlayer.objects.filter(game_room=room, player_identifier=identifier).first()
        if player:
            return {'id': player.id, 'ready': player.ready}, False

        if room.players.count() >= 2:
            return None, False

        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            character_id='',
            ready=False,
        )
        if room.status == 'WAITING':
            room.status = 'CHOOSING'
            room.save(update_fields=['status', 'updated_at'])
        return {'id': player.id, 'ready': player.ready}, True

    @database_sync_to_async
    def set_character(self, identifier, character_id):
        player = (
            GamePlayer.objects.select_related('game_room')
            .filter(game_room__room_code=self.room_code, player_identifier=identifier)
            .first()
        )
        if not player:
            return None
        player.character_id = character_id
        player.ready = True
        player.save(update_fields=['character_id', 'ready'])
        return {'id': player.id}

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
        room.awaiting_answer = False
        room.question_owner = None
        if not room.started_at:
            room.started_at = timezone.now()
        room.save(update_fields=[
            'status', 'current_turn', 'awaiting_answer',
            'question_owner', 'started_at', 'updated_at',
        ])
        return {'current_turn_identifier': str(first.player_identifier)}

    @database_sync_to_async
    def create_message(self, identifier, kind, text, answer='', reply_to=None):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room:
            return None
        player = GamePlayer.objects.filter(
            game_room=room, player_identifier=identifier
        ).first()
        if not player:
            return None
        message = ChatMessage.objects.create(
            game_room=room,
            game_player=player,
            kind=kind,
            text=text,
            answer=answer,
            reply_to=reply_to,
        )
        return self._serialize_message(message)

    @database_sync_to_async
    def ask_question(self, identifier, text):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}
        if room.awaiting_answer:
            return {'error': 'Rakibin cevap vermesi bekleniyor.'}
        if room.current_turn_id != player.id:
            return {'error': 'Sıra sende değil.'}

        message = ChatMessage.objects.create(
            game_room=room,
            game_player=player,
            kind='question',
            text=text,
        )
        room.awaiting_answer = True
        room.question_owner = player
        room.save(update_fields=['awaiting_answer', 'question_owner', 'updated_at'])
        return {'message': self._serialize_message(message)}

    @database_sync_to_async
    def answer_question(self, identifier, answer):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.'}
        if not room.awaiting_answer or not room.question_owner_id:
            return {'error': 'Cevaplanacak bir soru yok.'}

        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}
        if player.id == room.question_owner_id:
            return {'error': 'Kendi sorunu cevaplayamazsın.'}

        question = (
            ChatMessage.objects.filter(game_room=room, kind='question')
            .order_by('-created_at')
            .first()
        )
        message = ChatMessage.objects.create(
            game_room=room,
            game_player=player,
            kind='answer',
            text='Evet' if answer == 'yes' else 'Hayır',
            answer=answer,
            reply_to=question.id if question else None,
        )

        room.awaiting_answer = False
        room.question_owner = None
        room.current_turn = player
        room.save(update_fields=[
            'awaiting_answer', 'question_owner', 'current_turn', 'updated_at',
        ])
        return {'message': self._serialize_message(message)}

    @database_sync_to_async
    def make_accusation(self, identifier, character_id):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room or room.status != 'IN_PROGRESS':
            return {'error': 'Oyun şu anda oynanmıyor.', 'correct': False}
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.', 'correct': False}
        if room.awaiting_answer:
            return {'error': 'Rakibin cevabı bekleniyor.', 'correct': False}
        if room.current_turn_id != player.id:
            return {'error': 'Sıra sende değil.', 'correct': False}

        opponent = room.players.exclude(id=player.id).first()
        correct = check_accusation(opponent, character_id)
        Accusation.objects.create(
            game_player=player,
            character_id=character_id,
            correct=correct,
        )

        winner = player if correct else opponent
        loser = opponent if correct else player
        room.status = 'FINISHED'
        room.winner = winner
        room.awaiting_answer = False
        room.question_owner = None
        room.finished_at = timezone.now()
        room.save(update_fields=[
            'status', 'winner', 'awaiting_answer', 'question_owner',
            'finished_at', 'updated_at',
        ])

        reveal = {
            str(winner.player_identifier): winner.character_id,
            str(loser.player_identifier): loser.character_id,
        }
        return {
            'correct': correct,
            'winner_identifier': str(winner.player_identifier),
            'loser_identifier': str(loser.player_identifier),
            'reason': 'correct' if correct else 'wrong',
            'reveal': reveal,
        }

    @database_sync_to_async
    def save_eliminated(self, identifier, eliminated):
        GamePlayer.objects.filter(
            game_room__room_code=self.room_code,
            player_identifier=identifier,
        ).update(eliminated=eliminated)

    @database_sync_to_async
    def get_turn_state(self):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return {
                'current_turn_identifier': None,
                'awaiting_answer': False,
                'question_owner_identifier': None,
            }
        return {
            'current_turn_identifier': (
                str(room.current_turn.player_identifier) if room.current_turn else None
            ),
            'awaiting_answer': room.awaiting_answer,
            'question_owner_identifier': (
                str(room.question_owner.player_identifier) if room.question_owner else None
            ),
        }

    @database_sync_to_async
    def abandon_if_in_progress(self, identifier):
        room = GameRoom.objects.filter(room_code=self.room_code).first()
        if not room or room.status != 'IN_PROGRESS':
            return False
        room.status = 'ABANDONED'
        room.save(update_fields=['status', 'updated_at'])
        return True

    @database_sync_to_async
    def reset_room(self, identifier):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return {'error': 'Oda bulunamadı.'}
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return {'error': 'Oyuncu bulunamadı.'}

        room.players.update(character_id='', ready=False, eliminated=[])
        room.messages.all().delete()
        Accusation.objects.filter(game_player__game_room=room).delete()

        room.status = 'CHOOSING'
        room.current_turn = None
        room.winner = None
        room.question_owner = None
        room.awaiting_answer = False
        room.started_at = None
        room.finished_at = None
        room.save(update_fields=[
            'status', 'current_turn', 'winner', 'question_owner',
            'awaiting_answer', 'started_at', 'finished_at', 'updated_at',
        ])

        players = [
            {'player_identifier': p.player_identifier}
            for p in room.players.order_by('joined_at')
        ]
        return {'players': players}

    @database_sync_to_async
    def build_room_state(self):
        room = (
            GameRoom.objects.select_related('current_turn', 'question_owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return None

        players = list(room.players.order_by('joined_at'))
        messages = [
            self._serialize_message(m)
            for m in room.messages.select_related('game_player').order_by('created_at')
        ]
        finished = room.status == 'FINISHED'

        players_payload = []
        for player in players:
            item = {
                'id': str(player.id),
                'player_identifier': player.player_identifier,
                'ready': player.ready,
                'eliminated': player.eliminated or [],
            }
            if finished or player.player_identifier == self.player_identifier:
                item['character_id'] = player.character_id
            players_payload.append(item)

        return {
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'current_turn_identifier': (
                str(room.current_turn.player_identifier) if room.current_turn else None
            ),
            'awaiting_answer': room.awaiting_answer,
            'question_owner_identifier': (
                str(room.question_owner.player_identifier) if room.question_owner else None
            ),
            'winner_identifier': (
                str(room.winner.player_identifier) if room.winner else None
            ),
            'players': players_payload,
            'messages': messages,
        }

    @staticmethod
    def _serialize_message(message):
        return {
            'id': str(message.id),
            'kind': message.kind,
            'text': message.text,
            'answer': message.answer,
            'reply_to': str(message.reply_to) if message.reply_to else None,
            'sender_identifier': (
                str(message.game_player.player_identifier) if message.game_player else None
            ),
            'created_at': message.created_at.isoformat(),
        }
