import json
import logging
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import bot, review, services
from .models import GamePlayer, GameRoom, initial_fen
from .utils import generate_room_code

logger = logging.getLogger(__name__)

# Süre seçenekleri: ``value`` başlangıç saniyesi, ``increment`` hamle başına
# eklenen artırım (Fischer). İlk değer varsayılandır.
TIME_CONTROLS = [
    {'value': 300, 'increment': 0, 'label': '5 dk'},
    {'value': 300, 'increment': 3, 'label': '5+3'},
    {'value': 600, 'increment': 0, 'label': '10 dk'},
    {'value': 600, 'increment': 5, 'label': '10+5'},
]
DEFAULT_TIME_CONTROL = 600
DEFAULT_INCREMENT = 0


def _parse_time_control(raw, raw_increment=None):
    """(başlangıç, artırım) döndürür; geçersizse varsayılana düşer."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIME_CONTROL, DEFAULT_INCREMENT
    try:
        increment = int(raw_increment) if raw_increment is not None else None
    except (TypeError, ValueError):
        increment = None
    for option in TIME_CONTROLS:
        if option['value'] == value and (
            increment is None or option['increment'] == increment
        ):
            return option['value'], option['increment']
    return DEFAULT_TIME_CONTROL, DEFAULT_INCREMENT


def home(request):
    """Render the home page with options to create or join a game."""
    return render(request, 'satranc/home.html', {
        'bot_levels': bot.LEVELS,
        'default_bot_level': bot.DEFAULT_LEVEL,
        'time_controls': TIME_CONTROLS,
        'default_time_control': DEFAULT_TIME_CONTROL,
        'default_increment': DEFAULT_INCREMENT,
    })


@csrf_exempt
@require_http_methods(["POST"])
def create_room(request):
    """Create a new game room and return the room code."""
    try:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            payload = {}
        time_control, increment = _parse_time_control(
            payload.get('time_control'), payload.get('increment')
        )

        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()

        room = GameRoom.objects.create(
            room_code=room_code,
            status='WAITING',
            time_control=time_control,
            increment=increment,
            white_time_left=float(time_control),
            black_time_left=float(time_control),
        )
        logger.info("Created room %s (%s+%s sn)", room_code, time_control, increment)

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
def create_bot_game(request):
    """Create a room where a Stockfish bot plays one side."""
    try:
        data = json.loads(request.body or '{}')
        name = (data.get('name') or '').strip()[:30]

        try:
            level = int(data.get('level') or bot.DEFAULT_LEVEL)
        except (TypeError, ValueError):
            level = bot.DEFAULT_LEVEL
        level = min(max(level, 1), bot.MAX_LEVEL)

        color = data.get('color')
        if color not in ('w', 'b', 'random'):
            color = 'w'
        if color == 'random':
            color = 'w' if uuid.uuid4().int % 2 == 0 else 'b'
        bot_color = 'b' if color == 'w' else 'w'

        time_control, increment = _parse_time_control(
            data.get('time_control'), data.get('increment')
        )

        room_code = generate_room_code()
        while GameRoom.objects.filter(room_code=room_code).exists():
            room_code = generate_room_code()

        now = timezone.now()
        room = GameRoom.objects.create(
            room_code=room_code,
            status='IN_PROGRESS',
            is_bot_game=True,
            bot_level=level,
            bot_color=bot_color,
            time_control=time_control,
            increment=increment,
            started_at=now,
        )
        room.begin_clock(now)
        room.save(update_fields=[
            'white_time_left', 'black_time_left', 'turn_started_at',
        ])

        identifier = str(uuid.uuid4())
        GamePlayer.objects.create(
            game_room=room,
            player_identifier=identifier,
            color=color,
            name=name,
        )
        GamePlayer.objects.create(
            game_room=room,
            player_identifier=f'bot:{room.room_code}',
            color=bot_color,
            name=bot.bot_name(level),
        )

        logger.info("Created bot room %s (level %s)", room_code, level)

        return JsonResponse({
            'success': True,
            'room_code': room.room_code,
            'player_identifier': identifier,
            'color': color,
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Geçersiz veri.'}, status=400)
    except Exception as exc:
        logger.error("Error creating bot game: %s", exc)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def join_room(request):
    """Join an existing room with a room code. First player gets white."""
    try:
        data = json.loads(request.body)
        room_code = data.get('room_code', '').upper().strip()
        name = (data.get('name') or '').strip()[:30]

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
            name=name,
        )

        if room.players.count() == 2 and room.status == 'WAITING':
            now = timezone.now()
            room.status = 'IN_PROGRESS'
            room.started_at = now
            room.begin_clock(now)
            room.save(update_fields=[
                'status', 'started_at', 'updated_at',
                'white_time_left', 'black_time_left', 'turn_started_at',
            ])

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
            'name': player.name or '',
            'is_bot': player.player_identifier.startswith('bot:'),
        }
        for player in room.players.order_by('joined_at')
    ]

    return JsonResponse({
        'room_code': room.room_code,
        'status': room.status,
        'fen': room.fen,
        'turn': services.turn_color(room.fen),
        'legal_moves': services.legal_moves(room.fen),
        'premove_moves': {
            'w': services.premove_moves_for_color(room.fen, 'w'),
            'b': services.premove_moves_for_color(room.fen, 'b'),
        },
        'check': services.is_check(room.fen),
        'result': room.result or None,
        'winner_color': room.winner.color if room.winner else None,
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
        'players': players,
    })


def review_game(request, room_code):
    """Review every move of a finished game with Stockfish."""
    if not review.review_enabled():
        return JsonResponse(
            {'success': False, 'error': 'Oyun incelemesi devre dışı.'},
            status=403,
        )

    room = (
        GameRoom.objects.select_related('winner')
        .filter(room_code=room_code.upper())
        .first()
    )
    if not room:
        return JsonResponse({'success': False, 'error': 'Oda bulunamadı.'}, status=404)
    if room.status != 'FINISHED':
        return JsonResponse(
            {
                'success': False,
                'error': 'Oyun bitmeden inceleme yapılamaz.',
            },
            status=409,
        )

    move_rows = [
        {
            'uci': move.uci,
            'san': move.san,
            'color': move.player.color,
            'fen_after': move.fen_after,
        }
        for move in room.moves.select_related('player').order_by('created_at')
    ]
    if not move_rows:
        return JsonResponse(
            {'success': False, 'error': 'İncelenecek hamle yok.'},
            status=400,
        )

    data = review.review_game(
        initial_fen(),
        move_rows,
        bot_color=room.bot_color if room.is_bot_game else None,
    )
    data.update({
        'success': True,
        'room_code': room.room_code,
        'result': room.result or None,
        'status': room.status,
        'bot_color': room.bot_color or None,
    })
    return JsonResponse(data)
