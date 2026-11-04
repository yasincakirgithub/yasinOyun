import json
import logging
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .engine import (
    CUES,
    DEFAULT_CUE,
    DEFAULT_MODE,
    MODES,
    create_initial_state,
    get_mode,
    validate_cue,
    validate_target,
)
from .models import GamePlayer, GameRoom
from .utils import generate_room_code

logger = logging.getLogger(__name__)


def home(request):
    """Bilardo ana sayfası: mod, hedef ve isteka seçimi."""

    return render(request, 'bilardo/home.html', {
        'modes': list(MODES.values()),
        'default_mode': DEFAULT_MODE,
        'cues': CUES,
        'default_cue': DEFAULT_CUE,
    })


def _clean_name(raw, fallback='Oyuncu'):
    name = (raw or '').strip()[:30]
    return name or fallback


@csrf_exempt
@require_http_methods(['POST'])
def create_room(request):
    """Yeni bir online bilardo odası oluşturur."""

    try:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            payload = {}

        mode_id = payload.get('mode') if payload.get('mode') in MODES else DEFAULT_MODE
        mode = get_mode(mode_id)
        target = validate_target(mode_id, payload.get('target'))
        cue = validate_cue(payload.get('cue'))
        name = _clean_name(payload.get('name'), 'Oyuncu 1')

        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()

        room = GameRoom.objects.create(
            room_code=room_code,
            mode=mode_id,
            target=target,
            status='WAITING',
            state=create_initial_state(mode_id, target, breaker=0),
        )

        identifier = str(uuid.uuid4())
        GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            name=name,
            seat=0,
            cue=cue,
        )

        logger.info('Bilardo odası oluşturuldu: %s (%s)', room_code, mode_id)

        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'player_identifier': identifier,
            'seat': 0,
            'mode': mode_id,
            'target': target,
            'mode_name': mode['name'],
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception('Bilardo odası oluşturulamadı: %s', exc)
        return JsonResponse({'success': False, 'error': 'Oda oluşturulamadı.'}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def join_room(request):
    """Oda koduna göre online oyuna katılır."""

    try:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            payload = {}

        room_code = (payload.get('room_code') or '').upper().strip()
        if not room_code:
            return JsonResponse({'success': False, 'error': 'Oda kodu gerekli.'}, status=400)

        room = GameRoom.objects.filter(room_code=room_code).first()
        if not room:
            return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)

        identifier = (payload.get('player_identifier') or '').strip()
        existing = None
        if identifier:
            existing = room.players.filter(player_identifier=identifier).first()
        if existing:
            return JsonResponse({
                'success': True,
                'room_code': room.room_code,
                'player_identifier': existing.player_identifier,
                'seat': existing.seat,
                'mode': room.mode,
                'target': room.target,
                'mode_name': get_mode(room.mode)['name'],
                'reconnected': True,
            })

        if room.status == 'FINISHED':
            return JsonResponse(
                {'success': False, 'error': 'Bu oyun bitmiş. Yeni bir oda kur.'},
                status=400,
            )
        if room.players.count() >= 2:
            return JsonResponse({'success': False, 'error': 'Oda dolu.'}, status=400)

        used_seats = set(room.players.values_list('seat', flat=True))
        seat = 0 if 0 not in used_seats else 1
        cue = validate_cue(payload.get('cue'))
        name = _clean_name(payload.get('name'), f'Oyuncu {seat + 1}')

        identifier = str(uuid.uuid4())
        player = GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            name=name,
            seat=seat,
            cue=cue,
        )

        if room.players.count() >= 2 and room.status == 'WAITING':
            room.status = 'IN_PROGRESS'
            room.started_at = timezone.now()
            state = room.state or create_initial_state(room.mode, room.target)
            state['message'] = 'İki oyuncu hazır. Oyun başladı.'
            room.state = state
            room.save(update_fields=['status', 'started_at', 'state', 'updated_at'])

        logger.info('Oyuncu %s bilardo odasına katıldı: %s', player.seat, room_code)

        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'player_identifier': identifier,
            'seat': seat,
            'mode': room.mode,
            'target': room.target,
            'mode_name': get_mode(room.mode)['name'],
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception('Bilardo odasına katılınamadı: %s', exc)
        return JsonResponse({'success': False, 'error': 'Odaya katılınamadı.'}, status=500)


def game_room(request, room_code):
    """Online bilardo oda ekranı."""

    room = GameRoom.objects.filter(room_code=room_code.upper()).first()
    if not room:
        return render(request, 'bilardo/room_not_found.html', status=404)

    mode = get_mode(room.mode) or MODES[DEFAULT_MODE]
    return render(request, 'bilardo/game_room.html', {
        'room_code': room.room_code,
        'room_mode': mode,
        'room_target': room.target,
        'room_status': room.status,
        'online_mode': True,
        'local_mode': False,
        'bot_mode': False,
        'cues': CUES,
        'default_cue': DEFAULT_CUE,
    })


def local_game(request, mode):
    """Aynı cihazda iki kişilik / bota karşı bilardo ekranı."""

    mode_info = get_mode(mode)
    if not mode_info:
        return render(request, 'bilardo/room_not_found.html', status=404)

    target = validate_target(mode, request.GET.get('target'))
    cue = validate_cue(request.GET.get('cue'))
    bot_mode = request.GET.get('bot') in ('1', 'true', 'yes')
    level = request.GET.get('level') if request.GET.get('level') in ('kolay', 'normal', 'zor') else 'normal'

    return render(request, 'bilardo/game_room.html', {
        'room_code': '',
        'room_mode': mode_info,
        'room_target': target,
        'room_status': 'IN_PROGRESS',
        'online_mode': False,
        'local_mode': True,
        'bot_mode': bot_mode,
        'bot_level': level,
        'cues': CUES,
        'default_cue': cue,
    })
