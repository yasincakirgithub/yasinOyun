import json
import logging
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services
from .models import GamePlayer, GameRoom
from .utils import generate_room_code

logger = logging.getLogger(__name__)


def home(request):
    """Render the home page with options to create or join a game."""
    return render(request, 'satranc/home.html')


@csrf_exempt
@require_http_methods(["POST"])
def create_room(request):
    """Create a new game room and return the room code."""
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
    """Join an existing room with a room code. First player gets white."""
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

        if room.status not in ('WAITING', 'IN_PROGRESS'):
            return JsonResponse(
                {'success': False, 'error': 'Bu odaya şu anda katılınamaz.'},
                status=400,
            )

        used_colors = set(room.players.values_list('color', flat=True))
        color = 'w' if 'w' not in used_colors else 'b'

        player_identifier = str(uuid.uuid4())
        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=player_identifier,
            color=color,
        )

        if room.players.count() == 2 and room.status == 'WAITING':
            room.status = 'IN_PROGRESS'
            room.started_at = timezone.now()
            room.save(update_fields=['status', 'started_at', 'updated_at'])

        logger.info("Player %s joined room %s as %s", player_identifier, room_code, color)

        return JsonResponse({
            'success': True,
            'player_id': str(player.id),
            'player_identifier': player_identifier,
            'color': color,
            'room_status': room.status,
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as exc:
        logger.error("Error joining room: %s", exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def game_room(request, room_code):
    """Render the chess game room interface."""
    return render(request, 'satranc/game_room.html', {'room_code': room_code.upper()})


def get_room_state(request, room_code):
    """Get public state of a room (for polling or initial load)."""
    room = (
        GameRoom.objects.select_related('winner')
        .filter(room_code=room_code.upper())
        .first()
    )
    if not room:
        return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

    players = [
        {
            'id': str(player.id),
            'player_identifier': player.player_identifier,
            'color': player.color,
        }
        for player in room.players.order_by('joined_at')
    ]

    return JsonResponse({
        'room_code': room.room_code,
        'status': room.status,
        'fen': room.fen,
        'turn': services.turn_color(room.fen),
        'legal_moves': services.legal_moves(room.fen),
        'check': services.is_check(room.fen),
        'result': room.result or None,
        'winner_color': room.winner.color if room.winner else None,
        'players': players,
    })
