import logging
import re

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services
from .models import (
    LANGUAGE_CHOICES,
    MAX_PLAYERS,
    MIN_PLAYERS,
    STARTING_TEAM_CHOICES,
    TIMER_CHOICES,
    GameRoom,
)
from .utils import (
    ApiError,
    allow_rate,
    bearer_token,
    client_ip,
    error_response,
    parse_json_body,
)

logger = logging.getLogger(__name__)


def home(request):
    room_code = (request.GET.get('oda') or request.GET.get('room') or '').upper().strip()
    return render(request, 'codenames/home.html', {
        'max_players': MAX_PLAYERS,
        'min_players': MIN_PLAYERS,
        'timer_choices': TIMER_CHOICES,
        'languages': LANGUAGE_CHOICES,
        'starting_teams': STARTING_TEAM_CHOICES,
        'invite_code': room_code,
    })


def game_room(request, room_code):
    code = (room_code or '').upper().strip()
    room = GameRoom.objects.filter(room_code=code).first()
    return render(request, 'codenames/game_room.html', {
        'room_code': code,
        'room_exists': bool(room),
        'max_players': MAX_PLAYERS,
        'min_players': MIN_PLAYERS,
        'timer_choices': TIMER_CHOICES,
        'languages': LANGUAGE_CHOICES,
        'starting_teams': STARTING_TEAM_CHOICES,
    })


def _broadcast_state(room_code: str):
    layer = get_channel_layer()
    if not layer:
        return
    try:
        services.expire_turn_if_needed(room_code)
        async_to_sync(layer.group_send)(
            f'codenames_room_{room_code}',
            {'type': 'state_changed'},
        )
    except Exception as exc:  # pragma: no cover - Redis optional in dev
        logger.warning('Could not broadcast Codenames room %s: %s', room_code, type(exc).__name__)


def _authenticate(request, room_code: str):
    token = bearer_token(request.headers)
    if not token:
        token = (request.headers.get('X-Player-Token') or '').strip()
    if not token:
        raise ApiError('Bu işlem için oyuncu oturumu gerekli.', 401, 'auth_required')
    auth = services.authenticate(room_code, token)
    if not auth:
        raise ApiError('Oturum geçersiz veya süresi dolmuş.', 401, 'invalid_session')
    return auth


def _state_response(code: str, token: str, status: int = 200, **extra):
    state = services.build_room_state_for_token(code, token)
    if state is None:
        raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
    payload = {'success': True, 'state': state}
    payload.update(extra)
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response


@csrf_exempt
@require_http_methods(['POST'])
def api_create_room(request):
    try:
        if not allow_rate(f'create:{client_ip(request)}', 10, 60):
            raise ApiError('Çok fazla oda oluşturma isteği. Biraz bekle.', 429, 'rate_limited')
        data = parse_json_body(request)
        room, player, token = services.create_room(data.get('name'))
        _broadcast_state(room.room_code)
        response = JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'player_id': str(player.pk),
            'session_token': token,
        }, status=201)
        response['Cache-Control'] = 'no-store'
        return response
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames create room failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_join_room(request):
    try:
        if not allow_rate(f'join:{client_ip(request)}', 30, 60):
            raise ApiError('Çok fazla katılma isteği. Biraz bekle.', 429, 'rate_limited')
        data = parse_json_body(request)
        room_code = (data.get('room_code') or '').upper().strip()
        if not re.fullmatch(r'[A-Z0-9]{6}', room_code):
            raise ApiError('Oda kodu 6 karakter olmalı.', 400, 'invalid_room_code')
        if not allow_rate(f'join-room:{room_code}:{client_ip(request)}', 12, 60):
            raise ApiError('Bu odaya çok fazla katılma denemesi yapıldı.', 429, 'rate_limited')
        room, player, token, rejoined = services.join_room(
            room_code, data.get('name'), data.get('session_token') or data.get('token') or '',
        )
        _broadcast_state(room.room_code)
        return _state_response(
            room.room_code, token,
            room_code=room.room_code,
            player_id=str(player.pk),
            session_token=token,
            rejoined=rejoined,
        )
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames join room failed')
        return error_response(exc)


@require_http_methods(['GET'])
def api_room_state(request, room_code):
    try:
        _, _ = _authenticate(request, room_code)
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames room state failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_leave_room(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        services.leave_room(room_code.upper(), player)
        _broadcast_state(room_code.upper())
        return JsonResponse({'success': True})
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames leave room failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_update_settings(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        data = parse_json_body(request)
        room = services.update_settings(room_code.upper(), player, data)
        _broadcast_state(room.room_code)
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room.room_code, token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames settings update failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_assign_roles(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        data = parse_json_body(request)
        room = services.assign_roles(
            room_code.upper(), player,
            assignments=data.get('assignments'),
            auto=bool(data.get('auto')),
        )
        _broadcast_state(room.room_code)
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room.room_code, token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames role assignment failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_update_preference(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        if not allow_rate(f'preference:{player.pk}', 20, 60):
            raise ApiError('Çok fazla rol değişikliği denedin. Biraz bekle.', 429, 'rate_limited')
        data = parse_json_body(request)
        services.update_player_preference(
            room_code.upper(), player, data.get('team'), data.get('role'),
        )
        _broadcast_state(room_code.upper())
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames player preference failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_start_game(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        if not allow_rate(f'start:{room_code.upper()}', 4, 60):
            raise ApiError('Çok fazla başlatma isteği.', 429, 'rate_limited')
        services.start_game(room_code.upper(), player)
        _broadcast_state(room_code.upper())
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames start game failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_new_game(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        room = services.new_game(room_code.upper(), player)
        _broadcast_state(room.room_code)
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room.room_code, token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames new game failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_submit_clue(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 60, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        data = parse_json_body(request)
        services.submit_clue(room_code.upper(), player, data.get('word'), data.get('number'))
        _broadcast_state(room_code.upper())
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames clue failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_guess(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 60, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        data = parse_json_body(request)
        result = services.guess_word(room_code.upper(), player, data.get('position'))
        _broadcast_state(room_code.upper())
        if result.get('expired'):
            return JsonResponse(
                {'success': False, 'error': result.get('error'), 'code': 'turn_expired'},
                status=409,
            )
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token, result=result)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames guess failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_chat(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if not allow_rate(f'chat:{player.pk}', 5, 5):
            raise ApiError('Çok hızlı yazıyorsun. Kısa bir mola ver.', 429, 'rate_limited')
        data = parse_json_body(request)
        services.add_chat_message(room, player, data.get('text'))
        _broadcast_state(room_code.upper())
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames chat failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_end_turn(request, room_code):
    try:
        _, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 60, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        services.end_turn(room_code.upper(), player)
        _broadcast_state(room_code.upper())
        token = bearer_token(request.headers) or (request.headers.get('X-Player-Token') or '').strip()
        return _state_response(room_code.upper(), token)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames end turn failed')
        return error_response(exc)


@require_http_methods(['GET'])
def api_events(request, room_code):
    try:
        room, _ = _authenticate(request, room_code)
        events = [
            services.serialize_event(event)
            for event in room.events.select_related('player').order_by('-created_at')[:100]
        ]
        events.reverse()
        return JsonResponse({'success': True, 'events': events})
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Codenames events failed')
        return error_response(exc)


@require_http_methods(['GET'])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'error', 'database': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok', 'database': 'ok'})
