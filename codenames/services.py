"""Room management, authoritative game rules and role-filtered serialization."""

from __future__ import annotations

import logging
import random
import re
import unicodedata
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .deepseek import generate_words
from .models import (
    BOARD_SIZE,
    MAX_PLAYERS,
    MIN_PLAYERS,
    TIMER_CHOICES,
    ChatMessage,
    GameEvent,
    GamePlayer,
    GameRoom,
    GameSession,
    GameWord,
    default_settings,
)
from .utils import (
    ApiError,
    clean_chat_text,
    clean_display_name,
    generate_room_code,
    hash_token,
    name_key,
    new_session_token,
)
from .words import normalize_word

logger = logging.getLogger(__name__)

CLUE_RE = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşü]+(?:[-'’][A-Za-zÇĞİÖŞÜçğıöşü]+)?$")
ROOM_TTL_HOURS = 12
STARTING_STALE_SECONDS = 120


def _now():
    return timezone.now()


def _new_expiry(hours: int = ROOM_TTL_HOURS):
    return _now() + timedelta(hours=hours)


def broadcast_room(room_code: str):
    """Best-effort channel-layer wakeup; state itself is built per viewer."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(
                f'codenames_room_{room_code}',
                {'type': 'state_changed'},
            )
    except Exception as exc:  # pragma: no cover - Redis optional in dev
        logger.warning('Codenames broadcast failed for %s: %s', room_code, type(exc).__name__)


def _lock_room(room_code: str) -> GameRoom | None:
    # Avoid select_related() here: PostgreSQL refuses FOR UPDATE on the
    # nullable side of an outer join. Related rows are locked separately.
    return (
        GameRoom.objects.select_for_update()
        .filter(room_code=room_code)
        .first()
    )


def _lock_session(room: GameRoom) -> GameSession | None:
    if not room.current_session_id:
        return None
    return (
        GameSession.objects.select_for_update()
        .filter(pk=room.current_session_id)
        .first()
    )


def _validate_settings(raw: dict) -> dict:
    current = default_settings()
    current.update(raw or {})
    timer = current.get('timer_seconds', 0)
    try:
        timer = int(timer)
    except (TypeError, ValueError):
        timer = 0
    if timer not in TIMER_CHOICES:
        timer = 0
    try:
        min_players = int(current.get('min_players', MIN_PLAYERS))
    except (TypeError, ValueError):
        min_players = MIN_PLAYERS
    min_players = max(MIN_PLAYERS, min(MAX_PLAYERS, min_players))
    starting_team = current.get('starting_team', 'random')
    if starting_team not in ('random', 'red', 'blue'):
        starting_team = 'random'
    return {
        'timer_seconds': timer,
        'starting_team': starting_team,
        'min_players': min_players,
        'allow_zero_clue': bool(current.get('allow_zero_clue', False)),
        'extra_guess': bool(current.get('extra_guess', True)),
    }


def _add_event(room, session, player, event_type, message, **data):
    payload = {'message': message}
    payload.update(data)
    return GameEvent.objects.create(
        room=room,
        session=session,
        player=player,
        event_type=event_type,
        event_data=payload,
    )


def _add_system_message(room, text):
    return ChatMessage.objects.create(
        room=room,
        player=None,
        display_name='Sistem',
        kind='system',
        text=text[:400],
    )


def _default_team(room: GameRoom) -> str:
    active = room.players.filter(left=False)
    red = active.filter(team='red').count()
    blue = active.filter(team='blue').count()
    return 'red' if red <= blue else 'blue'


def _default_role(room: GameRoom, team: str) -> str:
    if not room.players.filter(left=False, team=team, role='spymaster').exists():
        return 'spymaster'
    return 'operative'


def create_room(display_name: str) -> tuple[GameRoom, GamePlayer, str]:
    display_name = clean_display_name(display_name)
    with transaction.atomic():
        for _ in range(10):
            code = generate_room_code()
            try:
                with transaction.atomic():
                    room = GameRoom.objects.create(
                        room_code=code,
                        status='WAITING',
                        max_players=MAX_PLAYERS,
                        language='tr',
                        settings=default_settings(),
                        expires_at=_new_expiry(),
                    )
                break
            except IntegrityError:
                continue
        else:  # pragma: no cover - astronomically unlikely
            raise ApiError('Oda kodu üretilemedi.', 503, 'room_code_exhausted')

        token = new_session_token()
        player = GamePlayer.objects.create(
            room=room,
            display_name=display_name,
            name_key=name_key(display_name),
            session_token_hash=hash_token(token),
            team='red',
            role='spymaster',
            connected=True,
            connection_count=0,
        )
        room.host = player
        room.save(update_fields=['host', 'updated_at'])
        _add_event(room, None, player, 'room_created', f'{display_name} odayı kurdu.')
        return room, player, token


def reconnect_player(room: GameRoom, token: str) -> GamePlayer | None:
    if not token:
        return None
    return (
        room.players.filter(
            session_token_hash=hash_token(token),
            left=False,
        ).first()
    )


def join_room(room_code: str, display_name: str, token: str = '') -> tuple[GameRoom, GamePlayer, str, bool]:
    room_code = (room_code or '').upper().strip()
    display_name = clean_display_name(display_name)

    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')

        if token:
            existing = reconnect_player(room, token)
            if not existing:
                raise ApiError('Oturum geçersiz. Lütfen yeniden katıl.', 401, 'invalid_session')
            fields = ['connected', 'last_seen_at']
            existing.connected = True
            existing.last_seen_at = _now()
            if display_name and existing.display_name != display_name:
                if room.players.exclude(pk=existing.pk).filter(name_key=name_key(display_name)).exists():
                    raise ApiError('Bu görünen ad odada kullanılıyor.', 409, 'name_taken')
                existing.display_name = display_name
                existing.name_key = name_key(display_name)
                fields.extend(['display_name', 'name_key'])
            existing.save(update_fields=fields)
            return room, existing, token, True

        if room.status != 'WAITING':
            raise ApiError('Oyun başladı; yeni oyuncu katılamaz.', 400, 'game_already_started')
        active_count = room.players.filter(left=False).count()
        if active_count >= min(room.max_players, MAX_PLAYERS):
            raise ApiError('Oda dolu.', 409, 'room_full')
        if room.players.filter(name_key=name_key(display_name), left=False).exists():
            raise ApiError('Bu görünen ad odada kullanılıyor.', 409, 'name_taken')

        team = _default_team(room)
        role = _default_role(room, team)
        raw_token = new_session_token()
        try:
            player = GamePlayer.objects.create(
                room=room,
                display_name=display_name,
                name_key=name_key(display_name),
                session_token_hash=hash_token(raw_token),
                team=team,
                role=role,
                connected=True,
                connection_count=0,
            )
        except IntegrityError as exc:
            raise ApiError('Bu görünen ad odada kullanılıyor.', 409, 'name_taken') from exc

        if not room.host_id:
            room.host = player
        room.expires_at = _new_expiry()
        room.save(update_fields=['host', 'expires_at', 'updated_at'])
        _add_event(room, None, player, 'player_joined', f'{display_name} odaya katıldı.')
        _add_system_message(room, f'{display_name} odaya katıldı.')
        return room, player, raw_token, False


def authenticate(room_code: str, token: str) -> tuple[GameRoom, GamePlayer] | None:
    room = GameRoom.objects.select_related('host', 'current_session').filter(
        room_code=(room_code or '').upper().strip()
    ).first()
    if not room:
        return None
    player = reconnect_player(room, token)
    if not player:
        return None
    return room, player


def mark_connected(player: GamePlayer):
    GamePlayer.objects.filter(pk=player.pk).update(
        connected=True,
        connection_count=F('connection_count') + 1,
        last_seen_at=_now(),
    )


def mark_disconnected(player: GamePlayer):
    with transaction.atomic():
        member = GamePlayer.objects.select_for_update().filter(pk=player.pk).first()
        if not member:
            return
        member.connection_count = max(0, member.connection_count - 1)
        member.connected = member.connection_count > 0
        member.last_seen_at = _now()
        member.save(update_fields=['connection_count', 'connected', 'last_seen_at'])


def transfer_host(room: GameRoom):
    if room.host_id and room.players.filter(pk=room.host_id, left=False).exists():
        return
    replacement = (
        room.players.filter(left=False, connected=True).order_by('joined_at').first()
        or room.players.filter(left=False).order_by('joined_at').first()
    )
    room.host = replacement
    room.save(update_fields=['host', 'updated_at'])


def leave_room(room_code: str, player: GamePlayer) -> GameRoom | None:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = room.players.filter(pk=player.pk, left=False).first()
        if not member:
            return room
        session = _lock_session(room)

        if room.status == 'WAITING' or not session:
            was_host = room.host_id == member.pk
            member.delete()
            if was_host:
                transfer_host(room)
            room.save(update_fields=['updated_at'])
            return room

        member.left = True
        member.connected = False
        member.connection_count = 0
        member.save(update_fields=['left', 'connected', 'connection_count', 'last_seen_at'])
        _add_system_message(room, f'{member.display_name} odadan ayrıldı.')
        _add_event(room, session, member, 'player_left', f'{member.display_name} odadan ayrıldı.')

        if session.status == 'IN_PROGRESS' and member.role == 'spymaster':
            _abandon_game_locked(room, session, member, 'spymaster_left')
        elif not room.players.filter(left=False).exists():
            if session.status == 'IN_PROGRESS':
                _abandon_game_locked(room, session, member, 'room_empty')
        elif (
            session.status == 'IN_PROGRESS'
            and not room.players.filter(
                left=False, team=member.team, role='operative',
            ).exists()
        ):
            _abandon_game_locked(room, session, member, 'operative_left')

        if room.host_id == member.pk:
            transfer_host(room)
        room.save(update_fields=['updated_at'])
        return room


def update_settings(room_code: str, player: GamePlayer, payload: dict) -> GameRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != player.pk:
            raise ApiError('Bu işlem için oda sahibi olmalısın.', 403, 'host_only')
        if room.status != 'WAITING':
            raise ApiError('Ayarlar yalnızca bekleme odasında değiştirilebilir.', 400, 'game_started')
        merged = dict(room.settings or {})
        merged.update(payload or {})
        room.settings = _validate_settings(merged)
        if 'language' in (payload or {}):
            language = payload.get('language')
            if language not in ('tr', 'en'):
                raise ApiError('Geçersiz dil.', 400, 'invalid_language')
            room.language = language
        room.save(update_fields=['settings', 'language', 'updated_at'])
        return room


def assign_roles(room_code: str, player: GamePlayer, assignments=None, auto: bool = False) -> GameRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != player.pk:
            raise ApiError('Bu işlem için oda sahibi olmalısın.', 403, 'host_only')
        if room.status != 'WAITING':
            raise ApiError('Oyun başladıktan sonra roller değiştirilemez.', 400, 'game_started')

        members = list(room.players.filter(left=False).order_by('joined_at'))

        if auto:
            for index, member in enumerate(members):
                member.team = 'red' if index % 2 == 0 else 'blue'
            first_red = next((m for m in members if m.team == 'red'), None)
            first_blue = next((m for m in members if m.team == 'blue'), None)
            for member in members:
                member.role = 'spymaster' if member in (first_red, first_blue) else 'operative'
                member.save(update_fields=['team', 'role'])
            _add_event(room, None, player, 'roles_assigned', 'Takımlar ve roller otomatik dağıtıldı.')
            room.save(update_fields=['updated_at'])
            return room

        if not isinstance(assignments, list) or not assignments:
            raise ApiError('Rol ataması gerekli.', 400, 'assignments_required')
        by_id = {str(m.pk): m for m in members}
        incoming = {}
        for item in assignments:
            if not isinstance(item, dict):
                raise ApiError('Geçersiz rol ataması.', 400, 'invalid_assignment')
            player_id = str(item.get('player_id') or '')
            member = by_id.get(player_id)
            if not member:
                raise ApiError('Oyuncu bu odada değil.', 400, 'player_not_in_room')
            team = item.get('team', member.team)
            role = item.get('role', member.role)
            if team not in ('red', 'blue'):
                raise ApiError('Geçersiz takım.', 400, 'invalid_team')
            if role not in ('spymaster', 'operative'):
                raise ApiError('Geçersiz rol.', 400, 'invalid_role')
            incoming[player_id] = (member, team, role)

        # Operative changes first so a spymaster can be swapped in one request.
        for member, team, role in incoming.values():
            if role != 'spymaster':
                member.team = team
                member.role = role
                member.save(update_fields=['team', 'role'])
        for member, team, role in incoming.values():
            if role == 'spymaster':
                member.team = team
                member.role = role
                member.save(update_fields=['team', 'role'])

        for team in ('red', 'blue'):
            spies = room.players.filter(left=False, team=team, role='spymaster').count()
            if spies > 1:
                raise ApiError(
                    f'{"Kırmızı" if team == "red" else "Mavi"} takımda en fazla bir spymaster olabilir.',
                    400, 'too_many_spymasters',
                )
        _add_event(room, None, player, 'roles_assigned', 'Takım ve roller güncellendi.')
        room.save(update_fields=['updated_at'])
        return room


def update_player_preference(room_code: str, player: GamePlayer, team=None, role=None) -> GameRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.status != 'WAITING':
            raise ApiError('Oyun başladıktan sonra roller değiştirilemez.', 400, 'game_started')

        member = room.players.filter(pk=player.pk, left=False).first()
        if not member:
            raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')

        team = team or member.team
        role = role or member.role
        if team not in ('red', 'blue'):
            raise ApiError('Geçersiz takım.', 400, 'invalid_team')
        if role not in ('spymaster', 'operative'):
            raise ApiError('Geçersiz rol.', 400, 'invalid_role')

        if role == 'spymaster':
            occupied = (
                room.players.filter(left=False, team=team, role='spymaster')
                .exclude(pk=member.pk)
                .first()
            )
            if occupied:
                team_label = 'Kırmızı' if team == 'red' else 'Mavi'
                raise ApiError(
                    f'{team_label} takımda zaten bir spymaster var: {occupied.display_name}. '
                    'Operative olabilir veya diğer takımı seçebilirsin.',
                    409,
                    'spymaster_taken',
                )

        changed = member.team != team or member.role != role
        member.team = team
        member.role = role
        member.save(update_fields=['team', 'role'])
        if changed:
            team_label = 'Kırmızı' if team == 'red' else 'Mavi'
            role_label = 'spymaster' if role == 'spymaster' else 'operative'
            _add_event(
                room, None, member, 'role_changed',
                f'{member.display_name} {team_label} takımında {role_label} oldu.',
                team=team,
            )
        room.save(update_fields=['updated_at'])
        return room


def start_validation(room: GameRoom) -> list[str]:
    errors = []
    players = list(room.players.filter(left=False))
    settings = _validate_settings(room.settings or {})
    if room.status != 'WAITING':
        errors.append('Oyun şu anda başlatılamaz.')
    if not room.host_id:
        errors.append('Oda sahibi yok.')
    if len(players) < settings['min_players']:
        errors.append(f"En az {settings['min_players']} oyuncu gerekli.")
    if len(players) > MAX_PLAYERS:
        errors.append('Oda kapasitesi aşıldı.')
    for team, label in (('red', 'Kırmızı'), ('blue', 'Mavi')):
        spymasters = [p for p in players if p.team == team and p.role == 'spymaster']
        operatives = [p for p in players if p.team == team and p.role == 'operative']
        if len(spymasters) != 1:
            errors.append(f'{label} takımda tam olarak bir spymaster olmalı.')
        if len(operatives) < 1:
            errors.append(f'{label} takımda en az bir operative olmalı.')
    return errors


def start_game(room_code: str, actor: GamePlayer) -> GameSession:
    room = GameRoom.objects.select_related('current_session').filter(room_code=room_code).first()
    if not room:
        raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
    if room.host_id != actor.pk:
        raise ApiError('Oyunu yalnızca oda sahibi başlatabilir.', 403, 'host_only')

    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != actor.pk:
            raise ApiError('Oyunu yalnızca oda sahibi başlatabilir.', 403, 'host_only')
        if room.status == 'STARTING':
            age = (_now() - room.updated_at).total_seconds()
            if age < STARTING_STALE_SECONDS:
                raise ApiError('Oyun zaten hazırlanıyor.', 409, 'start_in_progress')
            room.status = 'WAITING'
            room.save(update_fields=['status', 'updated_at'])
        if room.status != 'WAITING':
            raise ApiError('Oyun şu anda başlatılamaz.', 400, 'cannot_start')
        errors = start_validation(room)
        if errors:
            raise ApiError(errors[0], 400, 'invalid_start_configuration')
        settings = _validate_settings(room.settings or {})
        room.status = 'STARTING'
        room.save(update_fields=['status', 'updated_at'])
        broadcast_room(room.room_code)
        language = room.language
        settings_snapshot = dict(settings)
        starting_setting = settings['starting_team']

    try:
        words, source = generate_words(language)
        if len(words) != BOARD_SIZE or len({normalize_word(w) for w in words}) != BOARD_SIZE:
            raise ApiError('Kelime listesi geçersiz.', 500, 'invalid_words')

        with transaction.atomic():
            room = _lock_room(room_code)
            if not room or room.status != 'STARTING':
                raise ApiError('Oyun başlatma iptal edildi.', 409, 'start_cancelled')
            if starting_setting in ('red', 'blue'):
                starting_team = starting_setting
            else:
                starting_team = random.choice(['red', 'blue'])
            other_team = 'blue' if starting_team == 'red' else 'red'
            current_team = starting_team
            session = GameSession.objects.create(
                room=room,
                status='IN_PROGRESS',
                starting_team=starting_team,
                current_team=current_team,
                current_turn=1,
                remaining_agents={starting_team: 9, other_team: 8},
                turn_duration=settings_snapshot['timer_seconds'],
                turn_deadline=(
                    _now() + timedelta(seconds=settings_snapshot['timer_seconds'])
                    if settings_snapshot['timer_seconds'] else None
                ),
                word_source=source,
            )
            categories = (
                [starting_team] * 9
                + [other_team] * 8
                + ['neutral'] * 7
                + ['assassin']
            )
            random.shuffle(words)
            random.shuffle(categories)
            GameWord.objects.bulk_create([
                GameWord(
                    session=session,
                    word=word,
                    normalized=normalize_word(word),
                    category=category,
                    position=index,
                )
                for index, (word, category) in enumerate(zip(words, categories))
            ])
            room.status = 'IN_PROGRESS'
            room.current_session = session
            room.started_at = _now()
            room.finished_at = None
            room.expires_at = _new_expiry(24)
            room.save(update_fields=[
                'status', 'current_session', 'started_at', 'finished_at',
                'expires_at', 'updated_at',
            ])
            _add_event(
                room, session, actor, 'game_started',
                f'Oyun başladı. Başlangıç takımı: '
                f'{"Kırmızı" if starting_team == "red" else "Mavi"}.',
                starting_team=starting_team,
            )
            logger.info(
                'Codenames room %s started (language=%s, source=%s, players=%s)',
                room.room_code, language, source,
                room.players.filter(left=False).count(),
            )
            return session
    except Exception:
        with transaction.atomic():
            stale = _lock_room(room_code)
            if stale and stale.status == 'STARTING':
                stale.status = 'WAITING'
                stale.save(update_fields=['status', 'updated_at'])
                broadcast_room(stale.room_code)
        raise


def _expire_deadline(room: GameRoom, session: GameSession) -> bool:
    if (
        session.status == 'IN_PROGRESS'
        and session.turn_deadline
        and session.turn_deadline <= _now()
    ):
        _end_turn_locked(room, session, 'timeout')
        return True
    return False


def expire_turn_if_needed(room_code: str) -> bool:
    room = GameRoom.objects.filter(room_code=room_code).first()
    if not room or not room.current_session_id:
        return False
    session = room.current_session
    if not session or not session.turn_deadline or session.turn_deadline > _now():
        return False
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            return False
        session = _lock_session(room)
        if not session:
            return False
        return _expire_deadline(room, session)


def _end_turn_locked(room: GameRoom, session: GameSession, reason: str) -> bool:
    if session.status != 'IN_PROGRESS':
        return False
    previous = session.current_team
    session.current_team = 'blue' if previous == 'red' else 'red'
    session.current_turn += 1
    session.clue_word = ''
    session.clue_number = None
    session.guesses_used = 0
    session.max_guesses = 1
    session.turn_deadline = (
        _now() + timedelta(seconds=session.turn_duration)
        if session.turn_duration else None
    )
    session.save(update_fields=[
        'current_team', 'current_turn', 'clue_word', 'clue_number',
        'guesses_used', 'max_guesses', 'turn_deadline',
    ])
    reason_label = {
        'timeout': 'Süre doldu',
        'voluntary': 'Takım pas geçti',
        'neutral': 'Nötr kelime açıldı',
        'opponent': 'Rakip ajan açıldı',
        'guess_limit': 'Tahmin hakkı bitti',
    }.get(reason, 'Tur bitti')
    _add_event(
        room, session, None, 'turn_ended',
        f'{reason_label}. Sıra {"Kırmızı" if session.current_team == "red" else "Mavi"} takımda.',
        reason=reason, current_team=session.current_team,
    )
    return True


def _finish_game_locked(room: GameRoom, session: GameSession, winner: str, reason: str, actor=None):
    if session.status != 'IN_PROGRESS':
        return False
    now = _now()
    session.status = 'FINISHED'
    session.winner = winner
    session.end_reason = reason
    session.ended_at = now
    session.turn_deadline = None
    session.save(update_fields=[
        'status', 'winner', 'end_reason', 'ended_at', 'turn_deadline',
    ])
    room.status = 'FINISHED'
    room.finished_at = now
    room.save(update_fields=['status', 'finished_at', 'updated_at'])
    session.words.filter(revealed=False).update(revealed=True, revealed_at=now)
    winner_label = 'Kırmızı' if winner == 'red' else 'Mavi'
    reason_label = {
        'assassin': 'suikastçı açıldı',
        'agents': 'tüm ajanlar açıldı',
        'opponent_agents': 'rakip takımın tüm ajanları açıldı',
    }.get(reason, 'oyun tamamlandı')
    _add_event(
        room, session, actor, 'game_ended',
        f'Oyun bitti: {winner_label} takım kazandı ({reason_label}).',
        winner=winner, reason=reason,
    )
    _add_system_message(room, f'Oyun bitti. Kazanan: {winner_label}.')
    return True


def _abandon_game_locked(room: GameRoom, session: GameSession, actor: GamePlayer | None, reason: str):
    if session.status != 'IN_PROGRESS':
        return False
    session.status = 'ABANDONED'
    session.end_reason = reason
    session.ended_at = _now()
    session.turn_deadline = None
    session.save(update_fields=['status', 'end_reason', 'ended_at', 'turn_deadline'])
    room.status = 'ABANDONED'
    room.finished_at = _now()
    room.save(update_fields=['status', 'finished_at', 'updated_at'])
    session.words.filter(revealed=False).update(revealed=True, revealed_at=_now())
    if reason == 'room_empty':
        message = 'Oyun sona erdi: odada oyuncu kalmadı.'
        system_message = 'Oyun durduruldu: odada oyuncu kalmadı.'
    elif reason == 'operative_left':
        message = 'Oyun sona erdi: bir takımda operative kalmadı.'
        system_message = 'Oyun durduruldu: bir takımda operative kalmadı.'
    else:
        message = 'Oyun sona erdi: bir spymaster odadan ayrıldı.'
        system_message = 'Oyun durduruldu: spymaster ayrıldı.'
    _add_event(room, session, actor, 'game_ended', message, winner='', reason=reason)
    _add_system_message(room, system_message)
    return True


def submit_clue(room_code: str, player: GamePlayer, word, number):
    expired = False
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        session = _lock_session(room)
        if not session or session.status != 'IN_PROGRESS':
            raise ApiError('Oyun şu anda oynanmıyor.', 400, 'game_not_active')
        if _expire_deadline(room, session):
            expired = True
        else:
            member = room.players.filter(pk=player.pk, left=False).first()
            if not member:
                raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
            if session.clue_number is not None:
                raise ApiError('Bu tur için ipucu zaten verildi.', 409, 'clue_already_given')
            if member.team != session.current_team:
                raise ApiError('Sıra senin takımında değil.', 403, 'wrong_team')
            if member.role != 'spymaster':
                raise ApiError('İpucu yalnızca spymaster tarafından verilebilir.', 403, 'spymaster_only')

            clue_word = unicodedata.normalize('NFC', str(word or '')).strip()
            if not CLUE_RE.match(clue_word) or len(clue_word) > 32:
                raise ApiError('İpucu tek kelime olmalı ve rakam içermemeli.', 400, 'invalid_clue')
            try:
                clue_number = int(number)
            except (TypeError, ValueError):
                raise ApiError('İpucu numarası geçersiz.', 400, 'invalid_clue_number')
            if isinstance(number, bool) or not (0 <= clue_number <= 9):
                raise ApiError('İpucu numarası 0 ile 9 arasında olmalı.', 400, 'invalid_clue_number')
            settings = _validate_settings(room.settings or {})
            if clue_number == 0 and not settings['allow_zero_clue']:
                raise ApiError('Sıfır ipucu bu odada kapalı.', 400, 'zero_clue_disabled')

            normalized_clue = normalize_word(clue_word)
            if session.words.filter(normalized=normalized_clue).exists():
                raise ApiError('İpucu tahtadaki bir kelime olamaz.', 400, 'clue_on_board')

            session.clue_word = clue_word
            session.clue_number = clue_number
            session.guesses_used = 0
            session.max_guesses = max(
                1, clue_number + (1 if settings['extra_guess'] else 0)
            )
            session.turn_duration = settings['timer_seconds']
            session.save(update_fields=[
                'clue_word', 'clue_number', 'guesses_used', 'max_guesses',
                'turn_duration',
            ])
            _add_event(
                room, session, member, 'clue_given',
                f'{member.display_name} ipucu verdi: “{clue_word}” ({clue_number})',
                team=member.team, word=clue_word, number=clue_number,
                turn=session.current_turn,
            )
            return session

    if expired:
        raise ApiError('Süre doldu; sıra değişti.', 409, 'turn_expired')
    raise ApiError('İpucu verilemedi.', 400, 'clue_failed')


def guess_word(room_code: str, player: GamePlayer, position):
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        session = _lock_session(room)
        if not session or session.status != 'IN_PROGRESS':
            raise ApiError('Oyun şu anda oynanmıyor.', 400, 'game_not_active')
        if _expire_deadline(room, session):
            return {
                'expired': True,
                'error': 'Süre doldu; sıra değişti.',
                'game_ended': False,
                'turn_ended': True,
            }

        member = room.players.filter(pk=player.pk, left=False).first()
        if not member:
            raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
        if session.clue_number is None:
            raise ApiError('Önce spymaster ipucu vermeli.', 409, 'clue_required')
        if member.team != session.current_team:
            raise ApiError('Sıra senin takımında değil.', 403, 'wrong_team')
        if member.role != 'operative':
            raise ApiError('Spymaster kelime açamaz.', 403, 'operative_only')

        try:
            position = int(position)
        except (TypeError, ValueError):
            raise ApiError('Geçersiz kelime.', 400, 'invalid_word')
        word = session.words.select_for_update().filter(position=position).first()
        if not word:
            raise ApiError('Kelime bulunamadı.', 404, 'word_not_found')
        if word.revealed:
            raise ApiError('Bu kelime zaten açıldı.', 409, 'word_already_revealed')

        now = _now()
        word.revealed = True
        word.revealed_by = member
        word.revealed_at = now
        word.save(update_fields=['revealed', 'revealed_by', 'revealed_at'])
        session.guesses_used += 1
        remaining = dict(session.remaining_agents or {})
        category = word.category
        active = session.current_team
        opponent = 'blue' if active == 'red' else 'red'
        result = {
            'category': category,
            'word': word.word,
            'position': word.position,
            'game_ended': False,
            'turn_ended': False,
            'winner': '',
            'reason': '',
        }
        category_label = {
            'red': 'Kırmızı ajan', 'blue': 'Mavi ajan',
            'neutral': 'Nötr', 'assassin': 'Suikastçı',
        }[category]
        _add_event(
            room, session, member, 'word_revealed',
            f'{member.display_name} “{word.word}” açtı: {category_label}.',
            word=word.word, position=word.position, category=category,
            team=active, turn=session.current_turn,
        )

        if category == 'assassin':
            session.save(update_fields=['guesses_used'])
            result.update(game_ended=True, winner=opponent, reason='assassin')
            _finish_game_locked(room, session, opponent, 'assassin', member)
            return result

        if category in ('red', 'blue'):
            remaining[category] = max(0, int(remaining.get(category, 0)) - 1)
        session.remaining_agents = remaining
        session.save(update_fields=['guesses_used', 'remaining_agents'])

        if category == opponent:
            result.update(turn_ended=True)
            if remaining.get(opponent, 0) == 0:
                result.update(game_ended=True, winner=opponent, reason='opponent_agents')
                _finish_game_locked(room, session, opponent, 'opponent_agents', member)
                return result
            _end_turn_locked(room, session, 'opponent')
            return result

        if category == 'neutral':
            result.update(turn_ended=True)
            _end_turn_locked(room, session, 'neutral')
            return result

        if category == active:
            if remaining.get(active, 0) == 0:
                result.update(game_ended=True, winner=active, reason='agents')
                _finish_game_locked(room, session, active, 'agents', member)
                return result
            if session.guesses_used >= session.max_guesses:
                result.update(turn_ended=True)
                _end_turn_locked(room, session, 'guess_limit')
            return result

        # Unknown category should be impossible; fail closed without leaking.
        raise ApiError('Kelime kategorisi geçersiz.', 500, 'invalid_category')


def end_turn(room_code: str, player: GamePlayer, reason: str = 'voluntary'):
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        session = _lock_session(room)
        if not session or session.status != 'IN_PROGRESS':
            raise ApiError('Oyun şu anda oynanmıyor.', 400, 'game_not_active')
        if _expire_deadline(room, session):
            return session
        member = room.players.filter(pk=player.pk, left=False).first()
        if not member:
            raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
        if member.team != session.current_team:
            raise ApiError('Sıra senin takımında değil.', 403, 'wrong_team')
        if member.role != 'operative':
            raise ApiError('Turu yalnızca operative bitirebilir.', 403, 'operative_only')
        if session.clue_number is None:
            raise ApiError('Tur zaten pas geçilmiş.', 409, 'no_active_clue')
        _end_turn_locked(room, session, reason)
        return session


def new_game(room_code: str, actor: GamePlayer) -> GameRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != actor.pk:
            raise ApiError('Yeni oyunu yalnızca oda sahibi başlatabilir.', 403, 'host_only')
        if room.status not in ('FINISHED', 'ABANDONED'):
            raise ApiError('Yeni oyun için önce mevcut oyun bitmeli.', 400, 'game_not_finished')
        room.players.filter(left=True).delete()
        room.status = 'WAITING'
        room.current_session = None
        room.started_at = None
        room.finished_at = None
        room.expires_at = _new_expiry()
        room.save(update_fields=[
            'status', 'current_session', 'started_at', 'finished_at',
            'expires_at', 'updated_at',
        ])
        if not room.host_id or not room.players.filter(pk=room.host_id, left=False).exists():
            transfer_host(room)
        _add_system_message(room, 'Yeni oyun için lobi hazır. Takımları kontrol edip oyunu başlatın.')
        return room


def add_chat_message(room: GameRoom, player: GamePlayer, text: str) -> ChatMessage:
    text = clean_chat_text(text)
    member = room.players.filter(pk=player.pk, left=False).first()
    if not member:
        raise ApiError('Oyuncu bulunamadı.', 404, 'player_not_found')
    return ChatMessage.objects.create(
        room=room,
        player=member,
        display_name=member.display_name,
        team=member.team,
        role=member.role,
        kind='chat',
        text=text,
    )


def _iso(value):
    return value.isoformat() if value else None


def serialize_event(event: GameEvent):
    data = event.event_data or {}
    payload = {
        'id': str(event.pk),
        'type': event.event_type,
        'message': data.get('message', ''),
        'created_at': _iso(event.created_at),
        'player_id': str(event.player_id) if event.player_id else None,
    }
    for key in (
        'starting_team', 'team', 'word', 'position', 'category',
        'reason', 'winner', 'current_team', 'number', 'turn',
    ):
        if key in data:
            payload[key] = data[key]
    return payload


def serialize_chat(message: ChatMessage):
    return {
        'id': str(message.pk),
        'kind': message.kind,
        'text': message.text,
        'display_name': message.display_name or 'Sistem',
        'team': message.team or '',
        'role': message.role or '',
        'player_id': str(message.player_id) if message.player_id else None,
        'created_at': _iso(message.created_at),
    }


def serialize_player(player: GamePlayer, host_id):
    return {
        'id': str(player.pk),
        'display_name': player.display_name,
        'team': player.team,
        'role': player.role,
        'connected': player.connected and not player.left,
        'left': player.left,
        'is_host': player.pk == host_id,
        'joined_at': _iso(player.joined_at),
    }


def build_guess_history(room: GameRoom, session: GameSession | None) -> list[dict]:
    """Group clues with the words revealed after each one.

    Only revealed words are included, so this is safe for every viewer and
    cannot expose the unrevealed colour map.
    """
    if not session:
        return []
    events = (
        room.events.filter(
            session=session,
            event_type__in=['clue_given', 'word_revealed', 'turn_ended'],
        )
        .select_related('player')
        .order_by('created_at', 'id')
    )
    history = []
    current = None
    group_index = 0
    for event in events:
        data = event.event_data or {}
        if event.event_type == 'clue_given':
            group_index += 1
            current = {
                'turn': int(data.get('turn') or group_index),
                'team': data.get('team') or (event.player.team if event.player else ''),
                'clue': data.get('word') or '',
                'number': data.get('number'),
                'guesses': [],
                'end_reason': '',
            }
            history.append(current)
        elif event.event_type == 'word_revealed' and current is not None:
            current['guesses'].append({
                'word': data.get('word') or '',
                'position': data.get('position'),
                'category': data.get('category') or '',
                'display_name': event.player.display_name if event.player else '',
                'created_at': _iso(event.created_at),
            })
        elif event.event_type == 'turn_ended' and current is not None:
            current['end_reason'] = data.get('reason') or ''
    return history


def serialize_state(room: GameRoom, viewer: GamePlayer | None) -> dict:
    """Build the single source of truth sent to one specific viewer.

    Unrevealed categories are never added to the payload for operatives (and
    are also withheld from anonymous viewers), so CSS/JS cannot leak them.
    """
    players = list(room.players.select_related('room').order_by('joined_at'))
    active_players = [p for p in players if not p.left]
    host_id = room.host_id if room.host_id and any(p.pk == room.host_id and not p.left for p in players) else None
    if host_id is None:
        replacement = next((p for p in active_players if p.connected), None) or (active_players[0] if active_players else None)
        host_id = replacement.pk if replacement else None

    session = room.current_session
    if session:
        session = GameSession.objects.filter(pk=session.pk).first()
    words = list(session.words.order_by('position')) if session else []
    is_spymaster = bool(viewer and not viewer.left and viewer.role == 'spymaster')
    finished = bool(session and session.status in ('FINISHED', 'ABANDONED'))
    reveal_all = is_spymaster or finished
    members = {p.pk: p for p in players}

    board = []
    for word in words:
        show_category = reveal_all or word.revealed
        board.append({
            'position': word.position,
            'word': word.word,
            'revealed': word.revealed,
            'category': word.category if show_category else None,
            'revealed_by': (
                members[word.revealed_by_id].display_name
                if word.revealed_by_id in members else None
            ),
            'revealed_at': _iso(word.revealed_at),
        })

    my = None
    if viewer:
        refreshed = members.get(viewer.pk)
        if refreshed:
            my = serialize_player(refreshed, host_id)
            my['connection_count'] = refreshed.connection_count

    permissions = {
        'is_host': bool(viewer and viewer.pk == host_id and not viewer.left),
        'can_assign': bool(
            viewer and viewer.pk == host_id and room.status == 'WAITING'
        ),
        'can_choose_role': bool(
            viewer and not viewer.left and room.status == 'WAITING'
        ),
        'can_start': False,
        'can_clue': False,
        'can_guess': False,
        'can_end_turn': False,
        'can_new_game': bool(
            viewer and viewer.pk == host_id
            and room.status in ('FINISHED', 'ABANDONED')
        ),
    }
    if viewer and not viewer.left:
        permissions['can_start'] = bool(
            viewer.pk == host_id and not start_validation(room)
        )
        if session and session.status == 'IN_PROGRESS':
            same_team = viewer.team == session.current_team
            permissions['can_clue'] = bool(
                same_team and viewer.role == 'spymaster'
                and session.clue_number is None
            )
            permissions['can_guess'] = bool(
                same_team and viewer.role == 'operative'
                and session.clue_number is not None
            )
            permissions['can_end_turn'] = permissions['can_guess']

    session_payload = None
    if session:
        now = _now()
        remaining = session.remaining_agents or {}
        deadline = session.turn_deadline
        session_payload = {
            'id': str(session.pk),
            'status': session.status,
            'starting_team': session.starting_team,
            'current_team': session.current_team,
            'current_turn': session.current_turn,
            'clue': (
                {'word': session.clue_word, 'number': session.clue_number}
                if session.clue_number is not None else None
            ),
            'guesses_used': session.guesses_used,
            'max_guesses': session.max_guesses,
            'remaining': {
                'red': int(remaining.get('red', 0)),
                'blue': int(remaining.get('blue', 0)),
            },
            'timer': {
                'duration': session.turn_duration,
                'deadline': _iso(deadline),
                'remaining_seconds': (
                    max(0, int((deadline - now).total_seconds())) if deadline else None
                ),
            },
            'board': board,
            'winner': session.winner or '',
            'end_reason': session.end_reason or '',
            'ended_at': _iso(session.ended_at),
            'started_at': _iso(session.started_at),
            'word_source': session.word_source,
        }

    events = [
        serialize_event(e)
        for e in room.events.select_related('player').order_by('-created_at')[:40]
    ]
    events.reverse()
    messages = [
        serialize_chat(m)
        for m in room.messages.order_by('-created_at')[:80]
    ]
    messages.reverse()
    guess_history = build_guess_history(room, session)

    return {
        'type': 'state',
        'room': {
            'code': room.room_code,
            'status': room.status,
            'language': room.language,
            'settings': _validate_settings(room.settings or {}),
            'max_players': min(room.max_players, MAX_PLAYERS),
            'min_players': _validate_settings(room.settings or {})['min_players'],
            'host_id': str(host_id) if host_id else None,
            'player_count': len(active_players),
            'created_at': _iso(room.created_at),
            'started_at': _iso(room.started_at),
            'finished_at': _iso(room.finished_at),
        },
        'me': my,
        'players': [serialize_player(p, host_id) for p in players if not p.left],
        'session': session_payload,
        'permissions': permissions,
        'events': events,
        'messages': messages,
        'guess_history': guess_history,
        'server_time': _iso(_now()),
        'start_errors': start_validation(room) if room.status == 'WAITING' else [],
    }


def build_room_state_for_token(room_code: str, token: str):
    room = GameRoom.objects.select_related('host', 'current_session').filter(
        room_code=(room_code or '').upper().strip()
    ).first()
    if not room:
        return None
    player = reconnect_player(room, token)
    if not player:
        return None
    expire_turn_if_needed(room.room_code)
    room = GameRoom.objects.select_related('host', 'current_session').filter(pk=room.pk).first()
    return serialize_state(room, player)
