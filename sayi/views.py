from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import json
import logging

from .models import GameRoom, GamePlayer, Guess
from .services import validate_number
from .utils import generate_room_code

logger = logging.getLogger(__name__)


def home(request):
    """Render the home page with options to create or join a game."""
    return render(request, 'sayi/home.html')


@csrf_exempt
@require_http_methods(["POST"])
def create_room(request):
    """Create a new game room and return room code."""
    try:
        # Generate a unique room code
        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()
        
        room = GameRoom.objects.create(room_code=room_code, status='WAITING')
        logger.info(f"Created room {room_code}")
        
        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'room_id': str(room.id)
        })
    except Exception as e:
        logger.error(f"Error creating room: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def join_room(request):
    """Join an existing room with room code."""
    try:
        data = json.loads(request.body)
        room_code = data.get('room_code', '').upper().strip()
        
        if not room_code:
            return JsonResponse({'success': False, 'error': 'Oda kodu gerekli.'}, status=400)
        
        try:
            room = GameRoom.objects.get(room_code=room_code)
        except GameRoom.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)
        
        # Check if room is full (max 2 players)
        player_count = room.players.count()
        if player_count >= 2:
            return JsonResponse({'success': False, 'error': 'Oda dolu.'}, status=400)
        
        # Check room status: only WAITING or SETTING_NUMBERS allow joining
        if room.status not in ['WAITING', 'SETTING_NUMBERS']:
            return JsonResponse({'success': False, 'error': 'Bu odaya şu anda katılınamaz.'}, status=400)
        
        # Create player identifier (in real app, this would come from session or auth)
        # For now, we'll generate a temporary ID; in WebSocket we'll authenticate properly
        import uuid
        player_identifier = str(uuid.uuid4())
        
        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=player_identifier,
            secret_number='0000',  # Placeholder; will be set via set_secret
            ready=False
        )
        
        # As soon as at least one player is in the room, move it to
        # SETTING_NUMBERS (players can set their secret and wait for the other).
        if room.status == 'WAITING':
            room.status = 'SETTING_NUMBERS'
            room.save()
        
        logger.info(f"Player {player_identifier} joined room {room_code}")
        
        return JsonResponse({
            'success': True,
            'player_id': str(player.id),
            'player_identifier': player_identifier,
            'room_status': room.status
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as e:
        logger.error(f"Error joining room: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def set_secret(request):
    """Set the secret number for a player."""
    try:
        data = json.loads(request.body)
        player_id = data.get('player_id')
        secret_number = data.get('secret_number', '').strip()
        
        if not player_id or not secret_number:
            return JsonResponse({'success': False, 'error': 'Oyuncu kimliği ve gizli sayı gerekli.'}, status=400)
        
        # Validate secret number
        if not validate_number(secret_number):
            return JsonResponse({'success': False, 'error': 'Geçersiz gizli sayı. 4 farklı rakam olmalı ve 0 ile başlamamalı.'}, status=400)
        
        try:
            player = GamePlayer.objects.get(id=player_id)
        except GamePlayer.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Oyuncu bulunamadı.'}, status=404)
        
        # Update secret number and mark player as ready
        player.secret_number = secret_number
        player.ready = True
        player.save()
        
        # Check if both players are ready
        room = player.game_room
        if room.players.filter(ready=True).count() == 2:
            room.status = 'IN_PROGRESS'
            # Determine who goes first: room creator (first player) starts
            room.current_turn = room.players.order_by('joined_at').first()
            room.save()
            
            # In a real app, we would trigger WebSocket event here
            # For now, the WebSocket consumer will handle state propagation
        
        logger.info(f"Player {player.player_identifier} set secret in room {room.room_code}")
        
        return JsonResponse({
            'success': True,
            'room_status': room.status,
            'current_turn': str(room.current_turn.id) if room.current_turn else None
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as e:
        logger.error(f"Error setting secret: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def make_guess(request):
    """Make a guess in the game."""
    try:
        data = json.loads(request.body)
        player_id = data.get('player_id')
        guess_value = data.get('guess', '').strip()
        
        if not player_id or not guess_value:
            return JsonResponse({'success': False, 'error': 'Oyuncu kimliği ve tahmin gerekli.'}, status=400)
        
        # Validate guess
        if not validate_number(guess_value):
            return JsonResponse({'success': False, 'error': 'Geçersiz tahmin. 4 farklı rakam olmalı ve 0 ile başlamamalı.'}, status=400)
        
        try:
            player = GamePlayer.objects.get(id=player_id)
        except GamePlayer.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Oyuncu bulunamadı.'}, status=404)
        
        room = player.game_room
        
        # Check if it's the player's turn
        if room.current_turn != player:
            return JsonResponse({'success': False, 'error': 'Sıra sende değil.'}, status=400)
        
        # Check if game is in progress
        if room.status != 'IN_PROGRESS':
            return JsonResponse({'success': False, 'error': 'Oyun şu anda oynanmıyor.'}, status=400)
        
        # Get opponent player
        opponent = room.players.exclude(id=player.id).first()
        if not opponent:
            return JsonResponse({'success': False, 'error': 'Rakip bulunamadı.'}, status=400)
        
        # Calculate result
        from .services import calculate_result, is_win
        result = calculate_result(opponent.secret_number, guess_value)
        
        # Determine turn number
        turn_number = Guess.objects.filter(game_player__game_room=room).count() + 1
        
        # Save guess
        guess = Guess.objects.create(
            game_player=player,
            value=guess_value,
            result=result,
            turn_number=turn_number
        )
        
        # Check for win
        if is_win(result):
            room.status = 'FINISHED'
            room.winner = player
            room.finished_at = timezone.now()
            room.save()
            # Game over; no turn change
        else:
            # Switch turn
            from .services import switch_turn
            next_player = switch_turn(player, list(room.players.all()))
            room.current_turn = next_player
            room.save()
        
        logger.info(f"Player {player.player_identifier} guessed {guess_value} with result {result} in room {room.room_code}")
        
        response_data = {
            'success': True,
            'guess': guess_value,
            'result': result,
            'is_win': is_win(result),
            'turn_number': turn_number
        }
        
        if not is_win(result):
            response_data['next_turn_player_id'] = str(next_player.id) if next_player else None
        
        return JsonResponse(response_data)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as e:
        logger.error(f"Error making guess: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_room_state(request, room_code):
    """Get current state of a room (for polling or initial load)."""
    try:
        room = GameRoom.objects.get(room_code=room_code.upper())
        
        # Get current player from request (in real app, from session/auth)
        # For simplicity, we'll return public state
        players_data = []
        for player in room.players.all():
            players_data.append({
                'id': str(player.id),
                'ready': player.ready,
                # Do not expose secret_number
            })
        
        data = {
            'room_code': room.room_code,
            'status': room.status,
            'current_turn': str(room.current_turn.id) if room.current_turn else None,
            'winner': str(room.winner.id) if room.winner else None,
            'players': players_data,
            'guesses': []  # We'll omit guess history for brevity; in real app, filter by player
        }
        
        return JsonResponse(data)
    except GameRoom.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def game_room(request, room_code):
    """Render the game room interface."""
    try:
        room = GameRoom.objects.get(room_code=room_code.upper())
        context = {
            'room_code': room.room_code
        }
        return render(request, 'sayi/game_room.html', context)
    except GameRoom.DoesNotExist:
        # Room not found, could redirect to error page
        return render(request, 'sayi/game_room.html', {'room_code': room_code.upper()})