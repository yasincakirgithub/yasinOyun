import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import GameRoom, GamePlayer, Guess
from .services import calculate_result, is_win, switch_turn

logger = logging.getLogger(__name__)


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'sayi_game_{self.room_code}'
        self.player_identifier = None
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"WebSocket connected for room {self.room_code}")
        
        # Send initial room state
        await self.send_room_state()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # Handle player disconnection
        await self.handle_player_disconnect()
        
        logger.info(f"WebSocket disconnected for room {self.room_code} with code {close_code}")

    async def receive(self, text_data):
        """Receive message from WebSocket."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'join_player':
                await self.handle_join_player(data)
            elif message_type == 'set_secret':
                await self.handle_set_secret(data)
            elif message_type == 'make_guess':
                await self.handle_make_guess(data)
            elif message_type == 'get_state':
                await self.send_room_state()
            else:
                await self.send_error(f"Bilinmeyen mesaj tipi: {message_type}")
        except json.JSONDecodeError:
            await self.send_error("Geçersiz veri.")
        except Exception as e:
            logger.error(f"Error in receive: {e}")
            await self.send_error(str(e))

    # Handler methods
    async def handle_join_player(self, data):
        """Handle player joining the room via WebSocket."""
        player_identifier = data.get('player_identifier')
        if not player_identifier:
            await self.send_error("Oyuncu kimliği gerekli.")
            return
        
        # Get or create player
        player, created = await self.get_or_create_player(player_identifier)
        if not player:
            await self.send_error("Oda dolu veya bulunamadı.")
            return

        self.player_identifier = player_identifier
        
        # Notify room that player joined
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_joined',
                'player_id': str(player.id),
                'player_identifier': player_identifier,
                'ready': player.ready
            }
        )
        
        # Check if both players are ready to start game
        await self.check_game_start()

        # If the game is already running, bring this (re)connecting client up to speed
        room = await self.get_room()
        if room and room.status == 'IN_PROGRESS' and room.current_turn_id:
            await self.send(text_data=json.dumps({
                'type': 'game_started',
                'current_turn_identifier': str(room.current_turn.player_identifier)
            }))

    async def handle_set_secret(self, data):
        """Handle setting secret number."""
        player_identifier = data.get('player_identifier')
        secret_number = data.get('secret_number', '').strip()
        
        if not player_identifier or not secret_number:
            await self.send_error("Oyuncu kimliği ve gizli sayı gerekli.")
            return
        
        # Validate secret number
        from .validators import validate_four_digit_unique
        try:
            validate_four_digit_unique(secret_number)
        except Exception as e:
            await self.send_error(f"Geçersiz gizli sayı: {str(e)}")
            return
        
        # Update player's secret number
        success = await self.update_player_secret(player_identifier, secret_number)
        if not success:
            await self.send_error("Gizli sayı kaydedilemedi.")
            return
        
        # Notify room that player is ready
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'player_ready',
                'player_identifier': player_identifier,
                'ready': True
            }
        )
        
        # Check if both players are ready to start game
        await self.check_game_start()

    async def handle_make_guess(self, data):
        """Handle making a guess."""
        player_identifier = data.get('player_identifier')
        guess_value = data.get('guess', '').strip()
        
        if not player_identifier or not guess_value:
            await self.send_error("Oyuncu kimliği ve tahmin gerekli.")
            return
        
        # Validate guess
        from .validators import validate_four_digit_unique
        try:
            validate_four_digit_unique(guess_value)
        except Exception as e:
            await self.send_error(f"Geçersiz tahmin: {str(e)}")
            return
        
        # Check if it's player's turn and process guess
        result = await self.process_guess(player_identifier, guess_value)
        if result is None:
            # Error already sent in process_guess
            return
        
        # Send guess result to the player who made the guess
        await self.send(text_data=json.dumps({
            'type': 'guess_result',
            'guess': guess_value,
            'result': result,
            'is_win': result == '++++'
        }))
        
        # Notify room about the guess (without revealing secret)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'opponent_guessed',
                'player_identifier': player_identifier,
                'guess': guess_value,
                'result': result
            }
        )
        
        # If game is over, send finished event
        if result == '++++':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_finished',
                    'winner_identifier': player_identifier
                }
            )

    async def check_game_start(self):
        """Check if both players have set secrets and start the game."""
        room = await self.get_room()
        if not room or room.status in ('IN_PROGRESS', 'FINISHED'):
            return

        players = await self.get_players(room)
        if len(players) == 2 and all(p.ready for p in players):
            # Both players ready: first player (by join order) starts
            first_player = players[0]
            await self.start_game(room, first_player)

            # Notify everyone that the game started
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_started',
                    'current_turn_identifier': str(first_player.player_identifier)
                }
            )

            logger.info(f"Game started in room {self.room_code}")

    async def process_guess(self, player_identifier, guess_value):
        """Process a guess: validate turn, calculate result, update state."""
        room = await self.get_room()
        if not room:
            await self.send_error("Oda bulunamadı.")
            return None
        
        # Get player
        player = await self.get_player_by_identifier(player_identifier)
        if not player:
            await self.send_error("Oyuncu bulunamadı.")
            return None
        
        # Check if it's player's turn
        if room.current_turn != player:
            await self.send_error("Sıra sende değil.")
            return None
        
        # Check if game is in progress
        if room.status != 'IN_PROGRESS':
            await self.send_error("Oyun şu anda oynanmıyor.")
            return None
        
        # Get opponent
        opponent = await self.get_opponent(player)
        if not opponent:
            await self.send_error("Rakip bulunamadı.")
            return None
        
        # Calculate result
        result = calculate_result(opponent.secret_number, guess_value)
        
        # Save guess
        await self.save_guess(player, guess_value, result)
        
        # Check for win
        if is_win(result):
            # End game
            room.status = 'FINISHED'
            room.winner = player
            room.finished_at = timezone.now()
            await self.save_room(room)
            # No turn change
        else:
            # Switch turn
            players = await self.get_players(room)
            next_player = switch_turn(player, players)
            if next_player:
                room.current_turn = next_player
                await self.save_room(room)

                # Notify turn change
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'turn_changed',
                        'new_turn_identifier': str(next_player.player_identifier)
                    }
                )
        
        return result

    async def handle_player_disconnect(self):
        """Handle when a player disconnects."""
        # Only abandon a game that was actually being played. Leaving while
        # waiting / setting numbers should simply free the seat.
        if not self.player_identifier:
            return

        room = await self.get_room()
        if room and room.status == 'IN_PROGRESS':
            room.status = 'ABANDONED'
            await self.save_room(room)

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'game_abandoned',
                    'message': 'Rakip bağlantıyı kesti.'
                }
            )

    # Group message handlers
    async def player_joined(self, event):
        """Send player_joined message to client."""
        await self.send(text_data=json.dumps({
            'type': 'player_joined',
            'player_id': event['player_id'],
            'player_identifier': event['player_identifier'],
            'ready': event['ready']
        }))

    async def player_ready(self, event):
        """Send player_ready message to client."""
        await self.send(text_data=json.dumps({
            'type': 'player_ready',
            'player_identifier': event['player_identifier'],
            'ready': event['ready']
        }))

    async def game_started(self, event):
        """Send game_started message to client."""
        await self.send(text_data=json.dumps({
            'type': 'game_started',
            'current_turn_identifier': event['current_turn_identifier']
        }))

    async def turn_changed(self, event):
        """Send turn_changed message to client."""
        await self.send(text_data=json.dumps({
            'type': 'turn_changed',
            'new_turn_identifier': event['new_turn_identifier']
        }))

    async def opponent_guessed(self, event):
        """Notify that opponent made a guess."""
        await self.send(text_data=json.dumps({
            'type': 'opponent_guessed',
            'player_identifier': event['player_identifier'],
            'guess': event['guess'],
            'result': event['result']
        }))

    async def guess_result(self, event):
        """This is handled by direct send in process_guess"""
        pass  # Already sent directly

    async def game_finished(self, event):
        """Send game_finished message to client."""
        await self.send(text_data=json.dumps({
            'type': 'game_finished',
            'winner_identifier': event['winner_identifier']
        }))

    async def game_abandoned(self, event):
        """Send game_abandoned message to client."""
        await self.send(text_data=json.dumps({
            'type': 'game_abandoned',
            'message': event['message']
        }))

    async def send_error(self, message):
        """Send error message to client."""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))

    async def send_room_state(self):
        """Send current room state to client."""
        room = await self.get_room()
        if not room:
            await self.send_error("Oda bulunamadı.")
            return
        
        players = await self.get_players(room)
        current_turn_id = str(room.current_turn.player_identifier) if room.current_turn else None
        
        await self.send(text_data=json.dumps({
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'current_turn_identifier': current_turn_id,
            'players': [
                {
                    'id': str(p.id),
                    'player_identifier': p.player_identifier,
                    'ready': p.ready
                } for p in players
            ]
        }))

    # Database helper methods
    @database_sync_to_async
    def get_room(self):
        try:
            # select_related so accessing room.current_turn never triggers a
            # lazy query inside the async context.
            return GameRoom.objects.select_related('current_turn').get(
                room_code=self.room_code
            )
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def get_players(self, room):
        return list(room.players.order_by('joined_at'))

    @database_sync_to_async
    def get_player_by_identifier(self, identifier):
        try:
            return GamePlayer.objects.get(game_room__room_code=self.room_code, player_identifier=identifier)
        except GamePlayer.DoesNotExist:
            return None

    @database_sync_to_async
    def get_or_create_player(self, identifier):
        try:
            room = GameRoom.objects.get(room_code=self.room_code)
        except GameRoom.DoesNotExist:
            return None, False

        player = GamePlayer.objects.filter(
            game_room=room, player_identifier=identifier
        ).first()
        if player:
            return player, False

        # Room capacity: at most two players
        if room.players.count() >= 2:
            return None, False

        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            secret_number='0000',
            ready=False,
        )
        return player, True

    @database_sync_to_async
    def update_player_secret(self, identifier, secret_number):
        try:
            player = GamePlayer.objects.get(game_room__room_code=self.room_code, player_identifier=identifier)
            player.secret_number = secret_number
            player.ready = True
            player.save()
            return True
        except GamePlayer.DoesNotExist:
            return False

    @database_sync_to_async
    def save_guess(self, player, value, result):
        turn_number = Guess.objects.filter(
            game_player__game_room_id=player.game_room_id
        ).count() + 1
        Guess.objects.create(
            game_player=player,
            value=value,
            result=result,
            turn_number=turn_number,
        )

    @database_sync_to_async
    def save_room(self, room):
        room.save()

    @database_sync_to_async
    def start_game(self, room, first_player):
        room.status = 'IN_PROGRESS'
        if not room.started_at:
            room.started_at = timezone.now()
        room.current_turn = first_player
        room.save()

    @database_sync_to_async
    def get_opponent(self, player):
        try:
            return player.game_room.players.exclude(id=player.id).first()
        except:
            return None

    @database_sync_to_async
    def get_p1(self, room):
        return room.players.order_by('joined_at').first()

    @database_sync_to_async
    def get_p2(self, room):
        return room.players.order_by('joined_at').last()