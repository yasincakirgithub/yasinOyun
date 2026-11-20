"""Room lifecycle, auction logic, and state serialization for the Auction game."""

from __future__ import annotations

import logging
import random
import secrets
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import AuctionBid, AuctionPlayer, AuctionResult, AuctionRoom
from .themes.loader import (
    calculate_synergy_bonus,
    get_all_themes,
    get_character_by_id,
    get_theme,
    get_theme_characters,
    get_theme_synergies,
)
from .utils import (
    ApiError,
    clean_display_name,
    generate_room_code,
    hash_token,
    name_key,
    new_session_token,
)

logger = logging.getLogger(__name__)

MAX_PLAYERS = 8
MIN_PLAYERS = 2
ROOM_TTL_HOURS = 12

DEFAULT_STARTING_BUDGET = 2000  # $20.00 in cents
DEFAULT_STARTING_BID = 0  # $0.00 in cents (first bid starts from 1 cent)
DEFAULT_CHARACTER_COUNT = 10
DEFAULT_AUCTION_DURATION = 20  # seconds
DEFAULT_EXTENSION_THRESHOLD = 3
DEFAULT_EXTENSION_DURATION = 5
DEFAULT_MAX_CHARACTERS_PER_PLAYER = 0  # 0 = unlimited


def _now():
    return timezone.now()


def _new_expiry(hours: int = ROOM_TTL_HOURS):
    return _now() + timedelta(hours=hours)


def _lock_room(room_code: str) -> AuctionRoom | None:
    return (
        AuctionRoom.objects.select_for_update()
        .filter(room_code=(room_code or "").upper().strip())
        .first()
    )


def create_room(display_name: str) -> tuple[AuctionRoom, AuctionPlayer, str]:
    display_name = clean_display_name(display_name)
    with transaction.atomic():
        for _ in range(10):
            code = generate_room_code()
            try:
                with transaction.atomic():
                    room = AuctionRoom.objects.create(
                        room_code=code,
                        status="WAITING",
                        expires_at=_new_expiry(),
                        starting_budget=DEFAULT_STARTING_BUDGET,
                        starting_bid=DEFAULT_STARTING_BID,
                        character_count=DEFAULT_CHARACTER_COUNT,
                        auction_duration=DEFAULT_AUCTION_DURATION,
                        max_characters_per_player=DEFAULT_MAX_CHARACTERS_PER_PLAYER,
                        extension_threshold=DEFAULT_EXTENSION_THRESHOLD,
                        extension_duration=DEFAULT_EXTENSION_DURATION,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise ApiError("Oda kodu üretilemedi.", 503, "room_code_exhausted")

        token = new_session_token()
        player = AuctionPlayer.objects.create(
            room=room,
            display_name=display_name,
            name_key=name_key(display_name),
            session_token_hash=hash_token(token),
            connected=True,
            budget=DEFAULT_STARTING_BUDGET,
        )
        room.host = player
        room.save(update_fields=["host", "updated_at"])
        return room, player, token


def reconnect_player(room: AuctionRoom, token: str) -> AuctionPlayer | None:
    if not token:
        return None
    return room.players.filter(
        session_token_hash=hash_token(token),
        left=False,
    ).first()


def join_room(
    room_code: str, display_name: str, token: str = ""
) -> tuple[AuctionRoom, AuctionPlayer, str, bool]:
    room_code = (room_code or "").upper().strip()
    display_name = clean_display_name(display_name)

    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")

        if token:
            existing = reconnect_player(room, token)
            if not existing:
                raise ApiError(
                    "Oturum geçersiz. Lütfen yeniden katıl.", 401, "invalid_session"
                )
            fields = ["connected", "last_seen_at"]
            existing.connected = True
            existing.last_seen_at = _now()
            if display_name and existing.display_name != display_name:
                if (
                    room.players.exclude(pk=existing.pk)
                    .filter(name_key=name_key(display_name))
                    .exists()
                ):
                    raise ApiError(
                        "Bu görünen ad odada kullanılıyor.", 409, "name_taken"
                    )
                existing.display_name = display_name
                existing.name_key = name_key(display_name)
                fields.extend(["display_name", "name_key"])
            existing.save(update_fields=fields)
            return room, existing, token, True

        if room.status not in ("WAITING", "CONFIGURING", "THEME_SELECT"):
            raise ApiError(
                "Oyun başladı; yeni oyuncu katılamaz.", 400, "game_already_started"
            )
        active = room.players.filter(left=False)
        if active.count() >= room.max_players:
            raise ApiError(
                f"Oda dolu. Maksimum {room.max_players} oyuncu.", 409, "room_full"
            )
        if room.players.filter(name_key=name_key(display_name), left=False).exists():
            raise ApiError("Bu görünen ad odada kullanılıyor.", 409, "name_taken")

        raw_token = new_session_token()
        try:
            player = AuctionPlayer.objects.create(
                room=room,
                display_name=display_name,
                name_key=name_key(display_name),
                session_token_hash=hash_token(raw_token),
                connected=True,
                budget=room.starting_budget,
            )
        except IntegrityError as exc:
            raise ApiError(
                "Bu görünen ad odada kullanılıyor.", 409, "name_taken"
            ) from exc

        if not room.host_id:
            room.host = player
        room.expires_at = _new_expiry()
        room.save(update_fields=["host", "expires_at", "updated_at"])
        return room, player, raw_token, False


def authenticate(
    room_code: str, token: str
) -> tuple[AuctionRoom, AuctionPlayer] | None:
    room = (
        AuctionRoom.objects.select_related("host")
        .filter(room_code=(room_code or "").upper().strip())
        .first()
    )
    if not room:
        return None
    participant = reconnect_player(room, token)
    if not participant:
        return None
    return room, participant


def mark_connected(player: AuctionPlayer):
    AuctionPlayer.objects.filter(pk=player.pk).update(
        connected=True,
        connection_count=F("connection_count") + 1,
        last_seen_at=_now(),
    )


def mark_disconnected(player: AuctionPlayer):
    with transaction.atomic():
        member = AuctionPlayer.objects.select_for_update().filter(pk=player.pk).first()
        if not member:
            return
        member.connection_count = max(0, member.connection_count - 1)
        member.connected = member.connection_count > 0
        member.last_seen_at = _now()
        member.save(update_fields=["connection_count", "connected", "last_seen_at"])


def transfer_host(room: AuctionRoom):
    if room.host_id and room.players.filter(pk=room.host_id, left=False).exists():
        return
    replacement = (
        room.players.filter(left=False, connected=True).order_by("joined_at").first()
        or room.players.filter(left=False).order_by("joined_at").first()
    )
    room.host = replacement
    room.save(update_fields=["host", "updated_at"])


def leave_room(room_code: str, player: AuctionPlayer) -> AuctionRoom | None:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        member = room.players.filter(pk=player.pk, left=False).first()
        if not member:
            return room
        was_host = room.host_id == member.pk

        if room.status in ("WAITING", "CONFIGURING", "THEME_SELECT"):
            member.delete()
            if was_host:
                transfer_host(room)
            room.save(update_fields=["updated_at"])
            return room

        member.left = True
        member.connected = False
        member.connection_count = 0
        member.save(
            update_fields=["left", "connected", "connection_count", "last_seen_at"]
        )

        active_count = room.players.filter(left=False).count()
        if active_count < MIN_PLAYERS and room.status in ("AUCTION", "RESULTS"):
            _abandon_game(room)

        if was_host:
            transfer_host(room)
        room.save(update_fields=["updated_at"])
        return room


def _abandon_game(room: AuctionRoom):
    room.status = "ABANDONED"
    room.finished_at = _now()
    room.save(update_fields=["status", "finished_at", "updated_at"])


def update_settings(
    room_code: str, player: AuctionPlayer, payload: dict
) -> AuctionRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        if room.host_id != player.pk:
            raise ApiError("Bu işlem için oda sahibi olmalısın.", 403, "host_only")
        if room.status not in ("WAITING", "CONFIGURING", "THEME_SELECT"):
            raise ApiError(
                "Ayarlar yalnızca bekleme odasında değiştirilebilir.",
                400,
                "game_started",
            )

        if room.status != "THEME_SELECT":
            room.status = "CONFIGURING"
        if "starting_budget" in payload:
            room.starting_budget = max(100, int(payload["starting_budget"]))  # min $1
        if "starting_bid" in payload:
            room.starting_bid = max(0, int(payload["starting_bid"]))
        if "character_count" in payload:
            room.character_count = max(1, min(50, int(payload["character_count"])))
        if "auction_duration" in payload:
            room.auction_duration = max(5, min(300, int(payload["auction_duration"])))
        if "max_players" in payload:
            room.max_players = max(
                MIN_PLAYERS, min(MAX_PLAYERS, int(payload["max_players"]))
            )
        if "extension_threshold" in payload:
            room.extension_threshold = max(
                1, min(10, int(payload["extension_threshold"]))
            )
        if "extension_duration" in payload:
            room.extension_duration = max(
                1, min(30, int(payload["extension_duration"]))
            )
        if "max_characters_per_player" in payload:
            # 0 = unlimited, otherwise 1 to character_count
            val = int(payload["max_characters_per_player"])
            room.max_characters_per_player = max(
                0, min(room.character_count if room.character_count > 0 else 50, val)
            )

        room.save(
            update_fields=[
                "status",
                "starting_budget",
                "starting_bid",
                "character_count",
                "auction_duration",
                "max_players",
                "max_characters_per_player",
                "extension_threshold",
                "extension_duration",
                "updated_at",
            ]
        )
        return room


def select_theme(room_code: str, player: AuctionPlayer, theme_id: str) -> AuctionRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        if room.host_id != player.pk:
            raise ApiError(
                "Tema seçimi yalnızca oda sahibi yapabilir.", 403, "host_only"
            )
        if room.status not in ("WAITING", "CONFIGURING", "THEME_SELECT"):
            raise ApiError("Tema seçimi bu aşamada yapılamaz.", 400, "invalid_status")

        theme = get_theme(theme_id)
        if not theme:
            raise ApiError("Geçersiz tema.", 400, "invalid_theme")

        # Check if theme has enough characters
        chars = get_theme_characters(theme_id)
        if len(chars) < room.character_count:
            raise ApiError(
                f"Bu temada yeterli karakter yok ({len(chars)}/{room.character_count}).",
                400,
                "insufficient_characters",
            )

        room.theme_id = theme_id
        room.status = "THEME_SELECT"
        room.save(update_fields=["theme_id", "status", "updated_at"])
        return room


def _generate_auction_characters(room: AuctionRoom) -> list[str]:
    """Select random characters for the auction."""
    theme_id = room.theme_id
    count = room.character_count
    all_chars = get_theme_characters(theme_id)
    selected = random.sample(all_chars, min(count, len(all_chars)))
    return [c["id"] for c in selected]


def start_auction(room_code: str, player: AuctionPlayer) -> AuctionRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        if room.host_id != player.pk:
            raise ApiError(
                "Açık artırmayı yalnızca oda sahibi başlatabilir.", 403, "host_only"
            )
        if room.status != "THEME_SELECT":
            raise ApiError("Önce bir tema seçilmeli.", 400, "theme_not_selected")

        active = room.players.filter(left=False)
        if active.count() < MIN_PLAYERS:
            raise ApiError(
                f"Oyunu başlatmak için en az {MIN_PLAYERS} oyuncu gerekli.",
                400,
                "players_required",
            )

        # Generate auction character pool
        auction_chars = _generate_auction_characters(room)
        room.auction_characters = auction_chars
        room.current_character_index = 0

        # Initialize all players' budgets
        room.players.filter(left=False).update(budget=room.starting_budget)

        # Start first auction
        _start_next_auction_locked(room)

        room.status = "AUCTION"
        room.started_at = _now()
        room.save(
            update_fields=[
                "auction_characters",
                "current_character_index",
                "status",
                "started_at",
                "current_highest_bid",
                "current_highest_bidder",
                "auction_deadline",
                "updated_at",
            ]
        )
        return room


def _start_next_auction_locked(room: AuctionRoom):
    """Start the next character auction."""
    chars = room.get_auction_characters()
    if room.current_character_index >= len(chars):
        _finish_game_locked(room)
        return

    character_id = chars[room.current_character_index]
    room.current_highest_bid = room.starting_bid
    room.current_highest_bidder = None
    room.current_auction_extensions = 0
    deadline = _now() + timedelta(seconds=room.auction_duration)
    room.auction_deadline = deadline
    room.save(
        update_fields=[
            "current_highest_bid",
            "current_highest_bidder",
            "current_auction_extensions",
            "auction_deadline",
            "updated_at",
        ]
    )


def place_bid(room_code: str, player: AuctionPlayer, amount: int) -> AuctionRoom:
    """Place a bid on the current character."""
    amount = int(amount)
    # Process an expired auction *before* opening the atomic block. Calling
    # _process_auction_end_locked() and then raising inside a transaction would
    # roll the timeout handling back again.
    if expire_auction_if_needed(room_code):
        # The bid belonged to the character whose timer just ran out; never
        # silently apply it to the next character.
        raise ApiError("Açık artırma süresi doldu.", 409, "auction_ended")
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        if room.status != "AUCTION":
            raise ApiError("Açık artırma şu anda aktif değil.", 400, "not_in_auction")

        member = (
            room.players.select_for_update().filter(pk=player.pk, left=False).first()
        )
        if not member:
            raise ApiError("Oyuncu bu odada değil.", 404, "player_not_found")

        # Re-check the deadline inside the lock. expire_auction_if_needed()
        # already advanced normal timeouts; this only guards a tight race.
        if room.auction_deadline and _now() >= room.auction_deadline:
            raise ApiError("Açık artırma süresi doldu.", 409, "auction_ended")

        # Validate bid
        if amount > member.budget:
            raise ApiError("Yetersiz bütçe.", 400, "insufficient_budget")
        if amount <= room.current_highest_bid:
            raise ApiError(
                "Teklif mevcut en yüksek tekliften yüksek olmalı.", 400, "bid_too_low"
            )
        if room.current_highest_bidder_id == member.pk:
            raise ApiError(
                "Kendi teklifiniz üzerine teklif veremezsiniz.", 400, "bid_against_self"
            )
        # Check character limit per player
        if room.max_characters_per_player > 0:
            owned_count = len(member.owned_characters or [])
            if owned_count >= room.max_characters_per_player:
                raise ApiError(
                    f"Maksimum karakter sayısına ulaştınız ({room.max_characters_per_player}).",
                    400,
                    "max_characters_reached",
                )

        # Record bid. Only the newest bid for this character is the winning one.
        char_id = room.get_current_character_id()
        AuctionBid.objects.filter(
            room=room, character_id=char_id, is_winning=True
        ).update(is_winning=False)
        AuctionBid.objects.create(
            room=room,
            player=member,
            character_id=char_id or "",
            amount=amount,
            is_winning=True,
        )

        # Update room state
        room.current_highest_bid = amount
        room.current_highest_bidder = member
        fields = ["current_highest_bid", "current_highest_bidder", "updated_at"]

        # Check for anti-snipe extension. Only a valid bid can trigger this.
        if room.auction_deadline:
            remaining = (room.auction_deadline - _now()).total_seconds()
            if remaining <= room.extension_threshold:
                room.auction_deadline = room.auction_deadline + timedelta(
                    seconds=room.extension_duration
                )
                room.current_auction_extensions = (
                    room.current_auction_extensions or 0
                ) + 1
                fields.extend(["auction_deadline", "current_auction_extensions"])

        room.save(update_fields=fields)
        return room


def _process_auction_end_locked(room: AuctionRoom):
    """Process the end of current auction and start next or finish game."""
    char_id = room.get_current_character_id()
    winner = room.current_highest_bidder
    winning_bid = room.current_highest_bid

    if winner and char_id:
        # Award character to winner
        winner.owned_characters = list(winner.owned_characters) + [char_id]
        winner.budget = max(0, winner.budget - winning_bid)

        # Recompute the whole score from scratch so synergy bonuses are never
        # counted twice when a player acquires multiple characters.
        base_power = 0
        for owned_id in winner.owned_characters:
            owned = get_character_by_id(room.theme_id, owned_id)
            if owned:
                base_power += owned.get("power", 0)

        synergy_bonus, _ = calculate_synergy_bonus(
            room.theme_id, set(winner.owned_characters)
        )
        winner.synergy_bonus = synergy_bonus
        winner.total_power = base_power + synergy_bonus

        winner.save(
            update_fields=["owned_characters", "budget", "total_power", "synergy_bonus"]
        )

        # Record winning bid
        AuctionBid.objects.filter(
            room=room, character_id=char_id, player=winner, amount=winning_bid
        ).update(is_winning=True)

    # Move to next character
    room.current_character_index += 1
    room.current_highest_bid = room.starting_bid
    room.current_highest_bidder = None
    room.current_auction_extensions = 0

    # Check if game is over
    chars = room.get_auction_characters()
    if room.current_character_index >= len(chars):
        _finish_game_locked(room)
    else:
        # Start next auction
        deadline = _now() + timedelta(seconds=room.auction_duration)
        room.auction_deadline = deadline
        room.save(
            update_fields=[
                "current_character_index",
                "current_highest_bid",
                "current_highest_bidder",
                "current_auction_extensions",
                "auction_deadline",
                "updated_at",
            ]
        )


def _finish_game_locked(room: AuctionRoom):
    """Calculate final results and end the game."""
    room.status = "FINISHED"
    room.finished_at = _now()

    # Build rankings: total power -> character count -> remaining budget.
    # If all three are equal the players share the same rank (draw).
    players = list(room.players.filter(left=False))
    players.sort(
        key=lambda p: (
            -p.total_power,
            -len(p.owned_characters),
            -p.budget,
            p.display_name.lower(),
        )
    )
    rankings = []
    previous_key = None
    rank = 0
    for index, player in enumerate(players, 1):
        key = (player.total_power, len(player.owned_characters), player.budget)
        if key != previous_key:
            rank = index
            previous_key = key
        rankings.append(
            {
                "player_id": str(player.pk),
                "name": player.display_name,
                "total_power": player.total_power,
                "character_count": len(player.owned_characters),
                "budget": player.budget,
                "rank": rank,
                "is_draw": sum(
                    1
                    for other in players
                    if (other.total_power, len(other.owned_characters), other.budget)
                    == key
                )
                > 1,
                "owned_characters": player.owned_characters,
            }
        )

    # Character ownership
    ownership = {}
    for player in players:
        for char_id in player.owned_characters:
            ownership[char_id] = str(player.pk)

    # Activated synergies
    activated_synergies = {}
    for player in players:
        owned_ids = set(player.owned_characters)
        _, synergies = calculate_synergy_bonus(room.theme_id, owned_ids)
        if synergies:
            activated_synergies[str(player.pk)] = synergies

    AuctionResult.objects.create(
        room=room,
        rankings=rankings,
        character_ownership=ownership,
        activated_synergies=activated_synergies,
    )

    room.save(update_fields=["status", "finished_at", "updated_at"])


def expire_auction_if_needed(room_code: str) -> bool:
    """Check and process auction timeout. Returns True if state changed."""
    room = AuctionRoom.objects.filter(room_code=room_code).first()
    if not room or room.status != "AUCTION":
        return False
    if not room.auction_deadline or room.auction_deadline > _now():
        return False
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room or room.status != "AUCTION":
            return False
        if not room.auction_deadline or room.auction_deadline > _now():
            return False
        _process_auction_end_locked(room)
        return True


def new_game(room_code: str, player: AuctionPlayer) -> AuctionRoom:
    with transaction.atomic():
        room = _lock_room(room_code)
        if not room:
            raise ApiError("Oda bulunamadı.", 404, "room_not_found")
        if room.host_id != player.pk:
            raise ApiError(
                "Yeni oyun yalnızca oda sahibi başlatabilir.", 403, "host_only"
            )
        if room.status not in ("FINISHED", "ABANDONED"):
            raise ApiError(
                "Yeni oyun için önce mevcut oyun bitmeli.", 400, "game_not_finished"
            )

        room.players.filter(left=True).delete()
        room.players.filter(left=False).update(
            budget=room.starting_budget,
            owned_characters=[],
            total_power=0,
            synergy_bonus=0,
            ready=False,
        )
        # A room only keeps its latest result; remove the previous one so the
        # next season can store a fresh ranking.
        AuctionResult.objects.filter(room=room).delete()
        room.status = "WAITING"
        room.theme_id = ""
        room.auction_characters = []
        room.current_character_index = 0
        room.current_highest_bid = 0
        room.current_highest_bidder = None
        room.current_auction_extensions = 0
        room.auction_deadline = None
        room.started_at = None
        room.finished_at = None
        room.expires_at = _new_expiry()
        room.save(
            update_fields=[
                "status",
                "theme_id",
                "auction_characters",
                "current_character_index",
                "current_highest_bid",
                "current_highest_bidder",
                "current_auction_extensions",
                "auction_deadline",
                "started_at",
                "finished_at",
                "expires_at",
                "updated_at",
            ]
        )
        if (
            not room.host_id
            or not room.players.filter(pk=room.host_id, left=False).exists()
        ):
            transfer_host(room)
        return room


def _iso(value):
    return value.isoformat() if value else None


def serialize_player(player: AuctionPlayer, host_id, theme_id: str = "") -> dict:
    owned_details = []
    if player.owned_characters:
        for char_id in player.owned_characters:
            char = get_character_by_id(theme_id, char_id)
            if char:
                owned_details.append(
                    {
                        "id": char_id,
                        "name": char["name"],
                        "power": char["power"],
                        "image": char["image"],
                    }
                )

    # Active synergies
    owned_ids = set(player.owned_characters)
    _, active_synergies = calculate_synergy_bonus(theme_id, owned_ids)

    # Incomplete synergies (for UI hints)
    all_synergies = get_theme_synergies(theme_id)
    incomplete_synergies = []
    for synergy in all_synergies:
        required = set(synergy.get("required_character_ids", []))
        missing = required - owned_ids
        if missing and not required.issubset(owned_ids):
            incomplete_synergies.append(
                {
                    "id": synergy["id"],
                    "name": synergy["name"],
                    "description": synergy.get("description", ""),
                    "bonus": synergy.get("bonus", {}).get("value", 0),
                    "bonus_type": synergy.get("bonus", {}).get("type", "fixed"),
                    "missing": list(missing),
                    "required": list(required),
                }
            )

    return {
        "id": str(player.pk),
        "display_name": player.display_name,
        "connected": player.connected and not player.left,
        "left": player.left,
        "ready": player.ready,
        "is_host": player.pk == host_id,
        "budget": player.budget,
        "owned_characters": player.owned_characters,
        "owned_details": owned_details,
        "total_power": player.total_power,
        "synergy_bonus": player.synergy_bonus,
        "active_synergies": active_synergies,
        "incomplete_synergies": incomplete_synergies,
        "joined_at": _iso(player.joined_at),
    }


def serialize_current_auction(room: AuctionRoom) -> dict | None:
    if room.status != "AUCTION":
        return None
    char_id = room.get_current_character_id()
    if not char_id:
        return None
    char = get_character_by_id(room.theme_id, char_id)
    if not char:
        return None

    # Current bidder info
    current_bidder = None
    if room.current_highest_bidder:
        current_bidder = {
            "id": str(room.current_highest_bidder.pk),
            "name": room.current_highest_bidder.display_name,
        }

    now = _now()
    remaining_seconds = None
    if room.auction_deadline:
        remaining_seconds = max(0, round((room.auction_deadline - now).total_seconds()))
    extensions = room.current_auction_extensions or 0

    return {
        "character": {
            "id": char_id,
            "name": char["name"],
            "power": char["power"],
            "image": char["image"],
            "description": char["description"],
        },
        "current_bid": room.current_highest_bid,
        "current_bidder": current_bidder,
        "auction_number": room.current_character_index + 1,
        "total_auctions": len(room.get_auction_characters()),
        "timer": {
            "duration": room.auction_duration,
            "deadline": _iso(room.auction_deadline),
            "remaining_seconds": remaining_seconds,
            "extended": extensions > 0,
            "extension_count": extensions,
            "extension_threshold": room.extension_threshold,
            "extension_duration": room.extension_duration,
        },
    }


def serialize_theme_info(room: AuctionRoom) -> dict:
    themes = get_all_themes()
    selected_theme = get_theme(room.theme_id) if room.theme_id else None
    if selected_theme:
        # Lightweight roster used by the UI to resolve synergy character names.
        selected_theme["characters"] = [
            {
                "id": char["id"],
                "name": char["name"],
                "power": char.get("power", 0),
            }
            for char in get_theme_characters(room.theme_id)
        ]
    return {
        "themes": themes,
        "selected_theme": selected_theme,
    }


def build_room_state(room: AuctionRoom, viewer: AuctionPlayer) -> dict:
    participants = list(room.players.filter(left=False).order_by("joined_at"))
    viewer = next((p for p in participants if p.pk == viewer.pk), viewer)
    host_id = (
        room.host_id
        if room.host_id
        and any(p.pk == room.host_id and not p.left for p in participants)
        else None
    )
    if host_id is None:
        replacement = next((p for p in participants if p.connected), None) or (
            participants[0] if participants else None
        )
        host_id = replacement.pk if replacement else None

    theme_id = room.theme_id
    result = room.result if hasattr(room, "result") else None

    # Permissions
    permissions = {
        "is_host": bool(viewer and viewer.pk == host_id and not viewer.left),
        "can_configure": bool(
            viewer
            and viewer.pk == host_id
            and room.status in ("WAITING", "CONFIGURING")
        ),
        "can_select_theme": bool(
            viewer
            and viewer.pk == host_id
            and room.status in ("WAITING", "CONFIGURING", "THEME_SELECT")
        ),
        "can_start_auction": bool(
            viewer and viewer.pk == host_id and room.status == "THEME_SELECT"
        ),
        "can_bid": bool(viewer and not viewer.left and room.status == "AUCTION"),
        "can_new_game": bool(
            viewer and viewer.pk == host_id and room.status in ("FINISHED", "ABANDONED")
        ),
    }

    players_data = [serialize_player(p, host_id, theme_id) for p in participants]
    current_auction = serialize_current_auction(room)
    theme_info = serialize_theme_info(room)

    result_data = None
    if result:
        result_data = {
            "rankings": result.rankings,
            "character_ownership": result.character_ownership,
            "activated_synergies": result.activated_synergies,
        }

    return {
        "type": "state",
        "room": {
            "code": room.room_code,
            "status": room.status,
            "host_id": str(host_id) if host_id else None,
            "theme_id": room.theme_id,
            "character_count": room.character_count,
            "current_character_index": room.current_character_index,
            "starting_budget": room.starting_budget,
            "starting_bid": room.starting_bid,
            "auction_duration": room.auction_duration,
            "max_players": room.max_players,
            "max_characters_per_player": room.max_characters_per_player,
            "extension_threshold": room.extension_threshold,
            "extension_duration": room.extension_duration,
            "created_at": _iso(room.created_at),
            "started_at": _iso(room.started_at),
            "finished_at": _iso(room.finished_at),
            "expires_at": _iso(room.expires_at),
        },
        "me": serialize_player(viewer, host_id, theme_id),
        "players": players_data,
        "current_auction": current_auction,
        "theme_info": theme_info,
        "permissions": permissions,
        "result": result_data,
        "server_time": _iso(_now()),
    }


def build_room_state_for_token(room_code: str, token: str) -> dict | None:
    room = (
        AuctionRoom.objects.select_related("host")
        .filter(room_code=(room_code or "").upper().strip())
        .first()
    )
    if not room:
        return None
    player = reconnect_player(room, token)
    if not player:
        return None
    expire_auction_if_needed(room.room_code)
    room = AuctionRoom.objects.select_related("host").filter(pk=room.pk).first()
    return build_room_state(room, player)
