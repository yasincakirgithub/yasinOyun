import json
import logging
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .characters import CHARACTERS
from .models import GameRoom, GamePlayer
from .utils import generate_room_code

logger = logging.getLogger(__name__)


def home(request):
    """Render the home page with options to create or join a game."""
    return render(request, 'kim/home.html')


@csrf_exempt
@require_http_methods(["POST"])
def create_room(request):
    """Create a new game room and return room code."""
    try:
        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()

        room = GameRoom.objects.create(room_code=room_code, status='WAITING')
        logger.info("Created room %s", room_code)

        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'room_id': str(room.id),
        })
    except Exception as exc:
        logger.error("Error creating room: %s", exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def join_room(request):
    """Join an existing room with room code."""
    try:
        data = json.loads(request.body)
        room_code = data.get('room_code', '').upper().strip()

        if not room_code:
            return JsonResponse({'success': False, 'error': 'Oda kodu gerekli.'}, status=400)

        room = GameRoom.objects.filter(room_code=room_code).first()
        if not room:
            return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

        if room.players.count() >= 2:
            return JsonResponse({'success': False, 'error': 'Oda dolu.'}, status=400)

        if room.status not in ('WAITING', 'CHOOSING'):
            return JsonResponse(
                {'success': False, 'error': 'Bu odaya şu anda katılınamaz.'},
                status=400,
            )

        player_identifier = str(uuid.uuid4())
        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=player_identifier,
            character_id='',
            ready=False,
        )

        if room.status == 'WAITING':
            room.status = 'CHOOSING'
            room.save(update_fields=['status', 'updated_at'])

        logger.info("Player %s joined room %s", player_identifier, room_code)

        return JsonResponse({
            'success': True,
            'player_id': str(player.id),
            'player_identifier': player_identifier,
            'room_status': room.status,
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as exc:
        logger.error("Error joining room: %s", exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def game_room(request, room_code):
    """Render the Guess Who game room interface."""
    code = room_code.upper()
    context = {
        'room_code': code,
        'characters': CHARACTERS,
    }
    return render(request, 'kim/game_room.html', context)


def get_room_state(request, room_code):
    """Get public state of a room (for polling or initial load)."""
    room = GameRoom.objects.filter(room_code=room_code.upper()).first()
    if not room:
        return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

    players = [
        {
            'id': str(player.id),
            'player_identifier': player.player_identifier,
            'ready': player.ready,
        }
        for player in room.players.order_by('joined_at')
    ]

    return JsonResponse({
        'room_code': room.room_code,
        'status': room.status,
        'current_turn_identifier': (
            str(room.current_turn.player_identifier) if room.current_turn else None
        ),
        'winner_identifier': (
            str(room.winner.player_identifier) if room.winner else None
        ),
        'awaiting_answer': room.awaiting_answer,
        'players': players,
    })
