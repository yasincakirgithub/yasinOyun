import json
import logging
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    DEFAULT_ROUNDS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ROUND_CHOICES,
    GamePlayer,
    GameRoom,
)
from .utils import generate_room_code

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'okey101/home.html', {
        'round_choices': ROUND_CHOICES,
        'default_rounds': DEFAULT_ROUNDS,
        'max_players': MAX_PLAYERS,
        'min_players': MIN_PLAYERS,
    })


def _rounds_from_payload(value):
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ROUNDS
    return rounds if rounds in ROUND_CHOICES else DEFAULT_ROUNDS


def _mode_from_payload(value):
    return value if value in ('solo', 'pairs') else 'solo'


def _bool_from_payload(value, default=True):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ('0', 'false', 'off', 'no', '')
    return bool(value)


def _broadcast_room_state(room_code):
    layer = get_channel_layer()
    if not layer:
        return
    try:
        async_to_sync(layer.group_send)(
            f'okey101_game_{room_code}',
            {'type': 'state_changed'},
        )
    except Exception as exc:  # pragma: no cover - Redis opsiyonel
        logger.warning('Could not broadcast 101 Okey room %s: %s', room_code, exc)


@csrf_exempt
@require_http_methods(['POST'])
def create_room(request):
    try:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            payload = {}

        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()

        room = GameRoom.objects.create(
            room_code=room_code,
            status='WAITING',
            total_rounds=_rounds_from_payload(payload.get('total_rounds')),
            mode=_mode_from_payload(payload.get('mode')),
            penalties_enabled=_bool_from_payload(payload.get('penalties_enabled')),
            multipliers_enabled=_bool_from_payload(payload.get('multipliers_enabled')),
        )
        logger.info('Created 101 Okey room %s', room_code)
        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'room_id': str(room.id),
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Error creating 101 Okey room: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def join_room(request):
    try:
        data = json.loads(request.body or '{}')
        room_code = (data.get('room_code') or '').upper().strip()
        name = (data.get('name') or '').strip()[:30]
        identifier = (data.get('player_identifier') or '').strip()

        if not room_code:
            return JsonResponse({'success': False, 'error': 'Oda kodu gerekli.'}, status=400)

        room = GameRoom.objects.filter(room_code=room_code).first()
        if not room:
            return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

        existing = None
        if identifier:
            existing = room.players.filter(player_identifier=identifier).first()
        if existing:
            existing.connected = True
            fields = ['connected']
            if name and existing.name != name:
                existing.name = name
                fields.append('name')
            existing.save(update_fields=fields)
            _broadcast_room_state(room.room_code)
            return JsonResponse({
                'success': True,
                'player_id': str(existing.id),
                'player_identifier': existing.player_identifier,
                'seat': existing.seat,
                'room_status': room.status,
            })

        if identifier and GamePlayer.objects.filter(player_identifier=identifier).exists():
            return JsonResponse(
                {'success': False, 'error': 'Bu oyuncu kimliği başka bir odada kullanılıyor.'},
                status=409,
            )

        if room.status not in ('WAITING',):
            return JsonResponse(
                {'success': False, 'error': 'Bu oyun başladı, yeni oyuncu katılamaz.'},
                status=400,
            )
        if room.players.count() >= MAX_PLAYERS:
            return JsonResponse({'success': False, 'error': 'Oda dolu.'}, status=400)

        used_seats = set(room.players.values_list('seat', flat=True))
        seat = next(seat for seat in range(MAX_PLAYERS) if seat not in used_seats)

        player_identifier = identifier or str(uuid.uuid4())
        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=player_identifier,
            name=name,
            seat=seat,
            hand=[],
        )
        if not room.creator_identifier:
            GameRoom.objects.filter(
                pk=room.pk,
                creator_identifier='',
            ).update(creator_identifier=player_identifier)
        logger.info('Player %s joined 101 Okey room %s (seat %s)', player_identifier, room_code, seat)
        _broadcast_room_state(room.room_code)
        return JsonResponse({
            'success': True,
            'player_id': str(player.id),
            'player_identifier': player.player_identifier,
            'seat': player.seat,
            'room_status': room.status,
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except StopIteration:
        return JsonResponse({'success': False, 'error': 'Oda dolu.'}, status=400)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Error joining 101 Okey room: %s', exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def game_room(request, room_code):
    return render(request, 'okey101/game_room.html', {
        'room_code': room_code.upper(),
        'max_players': MAX_PLAYERS,
    })


def get_room_state(request, room_code):
    """Herkese açık oda özeti (eller gizlidir)."""
    room = GameRoom.objects.filter(room_code=room_code.upper()).first()
    if not room:
        return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

    return JsonResponse({
        'success': True,
        'room_code': room.room_code,
        'status': room.status,
        'mode': room.mode,
        'penalties_enabled': room.penalties_enabled,
        'multipliers_enabled': room.multipliers_enabled,
        'round_number': room.round_number,
        'total_rounds': room.total_rounds,
        'current_seat': room.current_seat,
        'stock_count': len(room.stock or []),
        'players': [
            {
                'player_identifier': player.player_identifier,
                'name': player.name or '',
                'seat': player.seat,
                'opened': player.opened,
                'tile_count': len(player.hand or []),
                'total_score': player.total_score,
                'connected': player.connected,
            }
            for player in room.players.order_by('seat')
        ],
        'server_time': timezone.now().isoformat(),
    })
