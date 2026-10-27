"""Room lifecycle, draft actions, and role-aware serialization for FC Manager."""

from __future__ import annotations

import logging
import random
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .challenges import build_challenges, challenge_progress
from .data import (
    EUR_TRY_RATE,
    SLOTS,
    SLOT_BY_KEY,
    build_market,
    format_league,
    format_nation,
    slot_accepts,
)
from .models import MarketPlayer, Match, Participant, Room
from .simulation import simulate_match
from .utils import (
    ApiError,
    clean_display_name,
    generate_room_code,
    hash_token,
    name_key,
    new_session_token,
)

logger = logging.getLogger(__name__)

MAX_PLAYERS = 2
ROOM_TTL_HOURS = 12
MIN_BUDGET_EUR = 400_000_000
MAX_BUDGET_TRY = 1_000_000_000_000


def _now():
    return timezone.now()


def _new_expiry(hours: int = ROOM_TTL_HOURS):
    return _now() + timedelta(hours=hours)


def _lock_room(room_code: str) -> Room | None:
    return Room.objects.select_for_update().filter(
        room_code=(room_code or '').upper().strip()
    ).first()


def _random_budget(rng: random.Random) -> tuple[int, int]:
    """Pick a budget between €400M and the € equivalent of ₺1T.

    A squared uniform distribution keeps the low end common (a real transfer
    budget) while still allowing the occasional billionaire season.
    """
    max_eur = MAX_BUDGET_TRY / EUR_TRY_RATE
    factor = (max_eur / MIN_BUDGET_EUR) ** (rng.random() ** 2)
    budget_eur = int(round(MIN_BUDGET_EUR * factor / 1_000_000) * 1_000_000)
    budget_eur = max(MIN_BUDGET_EUR, min(int(max_eur), budget_eur))
    budget_try = int(round(budget_eur * EUR_TRY_RATE / 10_000_000) * 10_000_000)
    return budget_eur, budget_try


def _squad_picks(room: Room, participant: Participant):
    return list(
        room.market.filter(picked_by=participant)
        .select_related('picked_by')
        .order_by('picked_slot')
    )


def _squad_players(room: Room, participant: Participant) -> list[dict]:
    return [mp.data for mp in _squad_picks(room, participant)]


def _squad_value(room: Room, participant: Participant) -> int:
    return sum(int(mp.data.get('value_eur', 0) or 0) for mp in _squad_picks(room, participant))


def _build_snapshot(participant: Participant, room: Room) -> dict:
    picks = _squad_picks(room, participant)
    squad = {mp.picked_slot: dict(mp.data) for mp in picks}
    players = [mp.data for mp in picks]
    challenges = [challenge_progress(c, players) for c in (room.challenges or [])]
    return {
        'id': str(participant.pk),
        'name': participant.display_name,
        'side': participant.side,
        'squad': squad,
        'spent': sum(int(mp.data.get('value_eur', 0) or 0) for mp in picks),
        'challenges': challenges,
        'slots_filled': len(picks),
    }


def create_room(display_name: str) -> tuple[Room, Participant, str]:
    display_name = clean_display_name(display_name)
    with transaction.atomic():
        for _ in range(10):
            code = generate_room_code()
            try:
                with transaction.atomic():
                    room = Room.objects.create(
                        room_code=code,
                        status='WAITING',
                        expires_at=_new_expiry(),
                    )
                break
            except IntegrityError:
                continue
        else:  # pragma: no cover - astronomically unlikely
            raise ApiError('Oda kodu üretilemedi.', 503, 'room_code_exhausted')

        token = new_session_token()
        participant = Participant.objects.create(
            room=room,
            display_name=display_name,
            name_key=name_key(display_name),
            session_token_hash=hash_token(token),
            side='home',
            connected=True,
        )
        room.host = participant
        room.save(update_fields=['host', 'updated_at'])
        return room, participant, token


def reconnect_player(room: Room, token: str) -> Participant | None:
    if not token:
        return None
    return room.players.filter(
        session_token_hash=hash_token(token),
        left=False,
    ).first()


def join_room(room_code: str, display_name: str, token: str = '') -> tuple[Room, Participant, str, bool]:
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
        active = room.players.filter(left=False)
        if active.count() >= MAX_PLAYERS:
            raise ApiError('Oda dolu. İki menajerlik yer var.', 409, 'room_full')
        if room.players.filter(name_key=name_key(display_name), left=False).exists():
            raise ApiError('Bu görünen ad odada kullanılıyor.', 409, 'name_taken')

        used_sides = set(active.values_list('side', flat=True))
        side = 'away' if 'away' not in used_sides else 'home'
        raw_token = new_session_token()
        try:
            participant = Participant.objects.create(
                room=room,
                display_name=display_name,
                name_key=name_key(display_name),
                session_token_hash=hash_token(raw_token),
                side=side,
                connected=True,
            )
        except IntegrityError as exc:
            raise ApiError('Bu görünen ad odada kullanılıyor.', 409, 'name_taken') from exc

        if not room.host_id:
            room.host = participant
        room.expires_at = _new_expiry()
        room.save(update_fields=['host', 'expires_at', 'updated_at'])
        return room, participant, raw_token, False


def authenticate(room_code: str, token: str) -> tuple[Room, Participant] | None:
    room = Room.objects.select_related('current_match').filter(
        room_code=(room_code or '').upper().strip()
    ).first()
    if not room:
        return None
    participant = reconnect_player(room, token)
    if not participant:
        return None
    return room, participant


def mark_connected(participant: Participant):
    Participant.objects.filter(pk=participant.pk).update(
        connected=True,
        connection_count=F('connection_count') + 1,
        last_seen_at=_now(),
    )


def mark_disconnected(participant: Participant):
    with transaction.atomic():
        member = Participant.objects.select_for_update().filter(pk=participant.pk).first()
        if not member:
            return
        member.connection_count = max(0, member.connection_count - 1)
        member.connected = member.connection_count > 0
        member.last_seen_at = _now()
        member.save(update_fields=['connection_count', 'connected', 'last_seen_at'])


def transfer_host(room: Room):
    if room.host_id and room.players.filter(pk=room.host_id, left=False).exists():
        return
    replacement = (
        room.players.filter(left=False, connected=True).order_by('joined_at').first()
        or room.players.filter(left=False).order_by('joined_at').first()
    )
    room.host = replacement
    room.save(update_fields=['host', 'updated_at'])


def _reset_to_waiting(room: Room):
    room.status = 'WAITING'
    room.budget_eur = 0
    room.budget_try = 0
    room.challenges = []
    room.current_match = None
    room.started_at = None
    room.finished_at = None
    room.market.all().delete()
    room.players.filter(left=False).update(locked=False)
    room.save(update_fields=[
        'status', 'budget_eur', 'budget_try', 'challenges', 'current_match',
        'started_at', 'finished_at', 'updated_at',
    ])


def leave_room(room_code: str, participant: Participant) -> Room | None:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = room.players.filter(pk=participant.pk, left=False).first()
        if not member:
            return room
        was_host = room.host_id == member.pk

        if room.status == 'WAITING':
            member.delete()
            if was_host:
                transfer_host(room)
            room.save(update_fields=['updated_at'])
            return room

        member.left = True
        member.connected = False
        member.connection_count = 0
        member.locked = False
        member.save(update_fields=['left', 'connected', 'connection_count', 'locked', 'last_seen_at'])

        active_count = room.players.filter(left=False).count()
        if active_count < 2 and room.status in ('DRAFT', 'FINISHED'):
            _reset_to_waiting(room)

        if was_host:
            transfer_host(room)
        room.save(update_fields=['updated_at'])
        return room


def _generate_draft(room: Room):
    rng = random.Random(secrets.randbits(64))
    try:
        market = build_market(rng)
    except ValueError as exc:
        raise ApiError('FC26 oyuncu verisi yüklenemedi.', 503, 'dataset_unavailable') from exc
    if len(market) < 40:
        raise ApiError('FC26 oyuncu verisi yetersiz.', 503, 'dataset_unavailable')

    budget_eur, budget_try = _random_budget(rng)
    challenges = build_challenges(market, budget_eur, rng)

    room.market.all().delete()
    MarketPlayer.objects.bulk_create([
        MarketPlayer(room=room, player_id=player['player_id'], data=player)
        for player in market
    ])
    room.budget_eur = budget_eur
    room.budget_try = budget_try
    room.challenges = challenges
    room.status = 'DRAFT'
    room.started_at = _now()
    room.finished_at = None
    room.current_match = None
    room.expires_at = _new_expiry()
    room.players.filter(left=False).update(locked=False)
    room.save(update_fields=[
        'budget_eur', 'budget_try', 'challenges', 'status', 'started_at',
        'finished_at', 'current_match', 'expires_at', 'updated_at',
    ])


def start_draft(room_code: str, participant: Participant) -> Room:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != participant.pk:
            raise ApiError('Oyunu yalnızca oda sahibi başlatabilir.', 403, 'host_only')
        if room.status != 'WAITING':
            raise ApiError('Oyun zaten başlamış.', 400, 'game_started')
        active = room.players.filter(left=False)
        if active.count() < MAX_PLAYERS:
            raise ApiError('Oyunu başlatmak için 2 menajer gerekli.', 400, 'players_required')
        _generate_draft(room)
        return room


def _get_member(room: Room, participant: Participant) -> Participant:
    member = room.players.select_for_update().filter(pk=participant.pk, left=False).first()
    if not member:
        raise ApiError('Oyuncu bu odada değil.', 404, 'player_not_found')
    return member


def pick_player(room_code: str, participant: Participant, market_player_id, slot_key: str) -> Room:
    slot_key = str(slot_key or '').strip()
    slot = SLOT_BY_KEY.get(slot_key)
    if not slot:
        raise ApiError('Geçersiz mevki.', 400, 'invalid_slot')
    try:
        market_player_id = int(market_player_id)
    except (TypeError, ValueError) as exc:
        raise ApiError('Geçersiz oyuncu.', 400, 'invalid_player') from exc

    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Kadro kurma aşaması kapalı.', 400, 'draft_closed')
        if member.locked:
            raise ApiError('Kadron kilitli. Önce kilidi aç.', 400, 'squad_locked')

        market_player = room.market.select_for_update().filter(pk=market_player_id).first()
        if not market_player:
            raise ApiError('Oyuncu bu odada bulunamadı.', 404, 'player_not_found')
        if not slot_accepts(slot_key, market_player.data.get('positions', ())):
            raise ApiError(
                f'{market_player.data.get("name", "Oyuncu")} bu mevkide oynayamaz.',
                400, 'position_mismatch',
            )
        if market_player.picked_by_id and market_player.picked_by_id != member.pk:
            raise ApiError('Bu oyuncu rakibin tarafından seçildi.', 409, 'player_taken')

        existing = room.market.select_for_update().filter(
            picked_by=member, picked_slot=slot_key,
        ).first()
        if existing and existing.pk == market_player.pk:
            return room

        spent = _squad_value(room, member)
        delta = int(market_player.data.get('value_eur', 0) or 0)
        if existing:
            delta -= int(existing.data.get('value_eur', 0) or 0)
        if market_player.picked_by_id == member.pk:
            delta -= int(market_player.data.get('value_eur', 0) or 0)
        if spent + delta > room.budget_eur:
            raise ApiError('Bu transfer bütçeni aşıyor.', 400, 'budget_exceeded')

        if existing and existing.pk != market_player.pk:
            existing.picked_by = None
            existing.picked_slot = ''
            existing.save(update_fields=['picked_by', 'picked_slot'])

        market_player.picked_by = member
        market_player.picked_slot = slot_key
        market_player.save(update_fields=['picked_by', 'picked_slot'])
        member.last_seen_at = _now()
        member.save(update_fields=['last_seen_at'])
        room.save(update_fields=['updated_at'])
        return room


def remove_pick(room_code: str, participant: Participant, slot_key: str) -> Room:
    slot_key = str(slot_key or '').strip()
    if slot_key not in SLOT_BY_KEY:
        raise ApiError('Geçersiz mevki.', 400, 'invalid_slot')
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Kadro kurma aşaması kapalı.', 400, 'draft_closed')
        if member.locked:
            raise ApiError('Kadron kilitli. Önce kilidi aç.', 400, 'squad_locked')
        market_player = room.market.select_for_update().filter(
            picked_by=member, picked_slot=slot_key,
        ).first()
        if market_player:
            market_player.picked_by = None
            market_player.picked_slot = ''
            market_player.save(update_fields=['picked_by', 'picked_slot'])
        room.save(update_fields=['updated_at'])
        return room


def clear_squad(room_code: str, participant: Participant) -> Room:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Kadro kurma aşaması kapalı.', 400, 'draft_closed')
        if member.locked:
            raise ApiError('Kadron kilitli. Önce kilidi aç.', 400, 'squad_locked')
        room.market.filter(picked_by=member).update(picked_by=None, picked_slot='')
        member.last_seen_at = _now()
        member.save(update_fields=['last_seen_at'])
        room.save(update_fields=['updated_at'])
        return room


def swap_slots(room_code: str, participant: Participant, from_slot: str, to_slot: str) -> Room:
    from_slot = str(from_slot or '').strip()
    to_slot = str(to_slot or '').strip()
    if from_slot not in SLOT_BY_KEY or to_slot not in SLOT_BY_KEY:
        raise ApiError('Geçersiz mevki.', 400, 'invalid_slot')

    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Kadro kurma aşaması kapalı.', 400, 'draft_closed')
        if member.locked:
            raise ApiError('Kadron kilitli. Önce kilidi aç.', 400, 'squad_locked')
        if from_slot == to_slot:
            return room

        first = room.market.select_for_update().filter(picked_by=member, picked_slot=from_slot).first()
        second = room.market.select_for_update().filter(picked_by=member, picked_slot=to_slot).first()
        if not first:
            raise ApiError('Taşınacak oyuncu bulunamadı.', 400, 'slots_not_filled')

        if not slot_accepts(to_slot, first.data.get('positions', ())):
            raise ApiError(
                f'{first.data.get("name", "Oyuncu")} {to_slot.upper()} mevkisinde oynayamaz.',
                400, 'position_mismatch',
            )

        if not second:
            # Move into an empty slot: a single row update is enough.
            first.picked_slot = to_slot
            first.save(update_fields=['picked_slot'])
            room.save(update_fields=['updated_at'])
            return room

        if not slot_accepts(from_slot, second.data.get('positions', ())):
            raise ApiError(
                f'{second.data.get("name", "Oyuncu")} {from_slot.upper()} mevkisinde oynayamaz.',
                400, 'position_mismatch',
            )

        # Both slots are occupied. Park the first row on a temporary slot so the
        # (room, picked_by, picked_slot) unique constraint never sees two empty
        # picks from the same manager.
        temporary_slot = '__swap__'
        first.picked_slot = temporary_slot
        first.save(update_fields=['picked_slot'])
        second.picked_slot = from_slot
        second.save(update_fields=['picked_slot'])
        first.picked_slot = to_slot
        first.save(update_fields=['picked_slot'])
        room.save(update_fields=['updated_at'])
        return room


def lock_squad(room_code: str, participant: Participant) -> Room:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Kadro kurma aşaması kapalı.', 400, 'draft_closed')
        picks = _squad_picks(room, member)
        if len(picks) < len(SLOTS):
            raise ApiError('Kilitlemek için 11 mevkinin tamamını doldur.', 400, 'squad_incomplete')
        if _squad_value(room, member) > room.budget_eur:
            raise ApiError('Kadro bütçeyi aşıyor.', 400, 'budget_exceeded')
        member.locked = True
        member.save(update_fields=['locked', 'last_seen_at'])
        room.save(update_fields=['updated_at'])
        return room


def unlock_squad(room_code: str, participant: Participant) -> Room:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        member = _get_member(room, participant)
        if room.status != 'DRAFT':
            raise ApiError('Maç başladıktan sonra kadro değiştirilemez.', 400, 'draft_closed')
        member.locked = False
        member.save(update_fields=['locked', 'last_seen_at'])
        room.save(update_fields=['updated_at'])
        return room


def start_match(room_code: str, participant: Participant) -> Match:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != participant.pk:
            raise ApiError('Maçı yalnızca oda sahibi başlatabilir.', 403, 'host_only')
        if room.status != 'DRAFT':
            raise ApiError('Maç bu aşamada başlatılamaz.', 400, 'invalid_status')
        active = list(room.players.select_for_update().filter(left=False).order_by('joined_at'))
        if len(active) < MAX_PLAYERS:
            raise ApiError('Maç için 2 menajer gerekli.', 400, 'players_required')
        if not all(member.locked for member in active):
            raise ApiError('İki menajer de kadrosunu kilitlemeli.', 400, 'squads_not_locked')
        for member in active:
            if len(_squad_picks(room, member)) < len(SLOTS):
                raise ApiError(f'{member.display_name} kadrosunu tamamlamadı.', 400, 'squad_incomplete')

        home = next((m for m in active if m.side == 'home'), None)
        away = next((m for m in active if m.side == 'away'), None)
        if not home or not away:
            raise ApiError('Ev sahibi ve deplasman menajeri bulunamadı.', 400, 'sides_missing')

        home_snapshot = _build_snapshot(home, room)
        away_snapshot = _build_snapshot(away, room)
        home_squad = home_snapshot['squad']
        away_squad = away_snapshot['squad']

        result = simulate_match(
            home_squad,
            away_squad,
            home_snapshot['challenges'],
            away_snapshot['challenges'],
            home.display_name,
            away.display_name,
        )

        home_snapshot['challenges'] = result['challenges']['home']
        away_snapshot['challenges'] = result['challenges']['away']
        stats = {
            'home': result['stats']['home'],
            'away': result['stats']['away'],
            'profiles': result['profiles'],
            'top_players': result['top_players'],
            'summary': result['summary'],
        }

        match = Match.objects.create(
            room=room,
            home=home,
            away=away,
            status='FINISHED',
            home_score=result['home_score'],
            away_score=result['away_score'],
            home_pen=result['home_pen'],
            away_pen=result['away_pen'],
            winner_side=result['winner_side'],
            home_snapshot=home_snapshot,
            away_snapshot=away_snapshot,
            stats=stats,
            events=result['events'],
            mvp=result['mvp'],
        )
        room.current_match = match
        room.status = 'FINISHED'
        room.finished_at = _now()
        room.save(update_fields=['current_match', 'status', 'finished_at', 'updated_at'])
        return match


def new_season(room_code: str, participant: Participant) -> Room:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError('Oda bulunamadı.', 404, 'room_not_found')
        if room.host_id != participant.pk:
            raise ApiError('Yeni sezonu yalnızca oda sahibi başlatabilir.', 403, 'host_only')
        if room.status != 'FINISHED':
            raise ApiError('Yeni sezon için maçın bitmesi gerekli.', 400, 'invalid_status')
        active = room.players.filter(left=False)
        if active.count() < MAX_PLAYERS:
            raise ApiError('Yeni sezon için 2 menajer gerekli.', 400, 'players_required')
        room.current_match = None
        room.finished_at = None
        room.save(update_fields=['current_match', 'finished_at', 'updated_at'])
        _generate_draft(room)
        return room


def _iso(value):
    return value.isoformat() if value else None


def serialize_market_player(market_player: MarketPlayer, viewer: Participant | None = None) -> dict:
    payload = dict(market_player.data or {})
    payload['id'] = market_player.pk
    payload['picked_by'] = market_player.picked_by.side if market_player.picked_by else None
    payload['picked_by_name'] = market_player.picked_by.display_name if market_player.picked_by else ''
    payload['picked_by_you'] = bool(viewer and market_player.picked_by_id == viewer.pk)
    payload['slot'] = market_player.picked_slot or None
    payload['nation_label'] = format_nation(payload.get('nationality', ''))
    payload['league_label'] = format_league(payload.get('league', ''))
    return payload


def serialize_participant(
    room: Room,
    participant: Participant,
    viewer: Participant | None = None,
    picks: list[MarketPlayer] | None = None,
) -> dict:
    if picks is None:
        picks = _squad_picks(room, participant)
    squad = {mp.picked_slot: serialize_market_player(mp, viewer) for mp in picks}
    players = [mp.data for mp in picks]
    challenges = [challenge_progress(c, players) for c in (room.challenges or [])]
    spent = sum(int(mp.data.get('value_eur', 0) or 0) for mp in picks)
    return {
        'id': str(participant.pk),
        'name': participant.display_name,
        'side': participant.side,
        'connected': participant.connected,
        'locked': participant.locked,
        'left': participant.left,
        'is_host': room.host_id == participant.pk,
        'squad': squad,
        'slots_filled': len(picks),
        'spent': spent,
        'remaining': max(0, room.budget_eur - spent),
        'valid': len(picks) == len(SLOTS) and spent <= room.budget_eur,
        'challenges': challenges,
    }


def serialize_match(match: Match, viewer: Participant | None = None) -> dict:
    return {
        'id': str(match.pk),
        'status': match.status,
        'home_score': match.home_score,
        'away_score': match.away_score,
        'home_pen': match.home_pen,
        'away_pen': match.away_pen,
        'winner_side': match.winner_side,
        'home': match.home_snapshot,
        'away': match.away_snapshot,
        'stats': match.stats,
        'events': match.events,
        'mvp': match.mvp,
        'started_at': _iso(match.started_at),
        'finished_at': _iso(match.finished_at),
    }


def build_room_state(room: Room, viewer: Participant) -> dict:
    participants = list(room.players.filter(left=False).order_by('joined_at'))
    # Actions such as lock/unlock update a different Participant instance, so
    # use the freshly loaded row for the viewer instead of the auth copy.
    viewer = next((p for p in participants if p.pk == viewer.pk), viewer)
    opponent = next((p for p in participants if p.pk != viewer.pk), None)
    market = list(room.market.select_related('picked_by').all())
    match = room.current_match

    # Reuse the market rows already in memory instead of issuing one query per
    # manager. The database may be remote, so each round trip is noticeable.
    picks_by_manager: dict = {}
    for market_player in market:
        if market_player.picked_by_id:
            picks_by_manager.setdefault(market_player.picked_by_id, []).append(market_player)

    return {
        'room': {
            'code': room.room_code,
            'status': room.status,
            'host_id': str(room.host_id) if room.host_id else None,
            'budget_eur': room.budget_eur,
            'budget_try': room.budget_try,
            'challenges': room.challenges or [],
            'max_players': MAX_PLAYERS,
            'created_at': _iso(room.created_at),
            'started_at': _iso(room.started_at),
            'finished_at': _iso(room.finished_at),
            'expires_at': _iso(room.expires_at),
        },
        'you': serialize_participant(
            room, viewer, viewer, picks_by_manager.get(viewer.pk, []),
        ),
        'opponent': serialize_participant(
            room, opponent, viewer, picks_by_manager.get(opponent.pk, []),
        ) if opponent else None,
        'players': [
            {
                'id': str(p.pk),
                'name': p.display_name,
                'side': p.side,
                'connected': p.connected,
                'locked': p.locked,
                'is_host': room.host_id == p.pk,
            }
            for p in participants
        ],
        'market': [serialize_market_player(mp, viewer) for mp in market],
        'slots': [
            {**slot, 'accept': list(slot['accept'])}
            for slot in SLOTS
        ],
        'match': serialize_match(match, viewer) if match else None,
        'server_time': _now().isoformat(),
    }


def build_room_state_for_token(room_code: str, token: str) -> dict | None:
    auth = authenticate(room_code, token)
    if not auth:
        return None
    room, participant = auth
    return build_room_state(room, participant)


def broadcast_room(room_code: str):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)(
                f'fcmanager_room_{room_code.upper()}',
                {'type': 'state_changed'},
            )
    except Exception as exc:  # pragma: no cover - Redis optional in dev
        logger.warning('FC Manager broadcast failed for %s: %s', room_code, type(exc).__name__)
