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
from .models import AuctionRoom
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
    themes = services.get_all_themes()
    return render(request, 'auction/home.html', {
        'invite_code': room_code,
        'themes': themes,
    })


def game_room(request, room_code):
    code = (room_code or '').upper().strip()
    room = AuctionRoom.objects.filter(room_code=code).first()
    return render(request, 'auction/game_room.html', {
        'room_code': code,
        'room_exists': bool(room),
    })


def _broadcast_state(room_code: str):
    layer = get_channel_layer()
    if not layer:
        return
    try:
        async_to_sync(layer.group_send)(
            f'auction_room_{room_code.upper()}',
            {'type': 'state_changed'},
        )
    except Exception as exc:
        logger.warning('Could not broadcast Auction room %s: %s', room_code, type(exc).__name__)


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


def _state_payload(room, participant, status: int = 200, **extra):
    state = services.build_room_state(room, participant)
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
            logger.exception('Auction create room failed')
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
        return _state_payload(
            room, player,
            room_code=room.room_code,
            player_id=str(player.pk),
            session_token=token,
            rejoined=rejoined,
        )
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction join room failed')
        return error_response(exc)


@require_http_methods(['GET'])
def api_room_state(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if services.expire_auction_if_needed(room_code.upper()):
            room.refresh_from_db()
            _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction room state failed')
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
            logger.exception('Auction leave room failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_update_settings(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 30, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        data = parse_json_body(request)
        room = services.update_settings(room_code.upper(), player, data.get('settings', {}))
        _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction settings update failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_select_theme(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 30, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        data = parse_json_body(request)
        theme_id = data.get('theme_id', '')
        room = services.select_theme(room_code.upper(), player, theme_id)
        _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction theme select failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_start_auction(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if not allow_rate(f'start:{room_code.upper()}', 6, 60):
            raise ApiError('Çok fazla başlatma isteği.', 429, 'rate_limited')
        room = services.start_auction(room_code.upper(), player)
        _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction start failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_bid(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        if not allow_rate(f'action:{player.pk}', 60, 60):
            raise ApiError('Çok fazla işlem.', 429, 'rate_limited')
        data = parse_json_body(request)
        amount = data.get('amount')
        if amount is None:
            raise ApiError('Teklif tutarı gerekli.', 400, 'amount_required')
        room = services.place_bid(room_code.upper(), player, amount)
        _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction bid failed')
        return error_response(exc)


@csrf_exempt
@require_http_methods(['POST'])
def api_new_game(request, room_code):
    try:
        room, player = _authenticate(request, room_code)
        room = services.new_game(room_code.upper(), player)
        _broadcast_state(room_code.upper())
        return _state_payload(room, player)
    except Exception as exc:
        if not isinstance(exc, ApiError):
            logger.exception('Auction new game failed')
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