"""Shared fixtures for the Character Auction test suite."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from auction import services
from auction.models import AuctionRoom


def make_room(names=('Host', 'Guest'), *, settings=None):
    """Create a room and join every name in ``names``.

    Returns ``(room, players)`` where ``players`` is a list of
    ``(player, session_token)`` tuples in join order.
    """
    room, host, host_token = services.create_room(names[0])
    players = [(host, host_token)]
    for name in names[1:]:
        room, member, token, _rejoined = services.join_room(room.room_code, name)
        players.append((member, token))
    if settings:
        room = services.update_settings(room.room_code, host, settings)
    return room, players


def select_theme(room, host, theme_id='marvel'):
    return services.select_theme(room.room_code, host, theme_id)


def started_room(
    theme='marvel',
    *,
    character_ids=None,
    count=None,
    names=('Host', 'Guest'),
    settings=None,
):
    """Create, configure and start a room.

    ``character_ids`` pins the auction order so scoring/synergy assertions are
    deterministic instead of depending on ``random.sample``.
    """
    if count is None:
        count = len(character_ids) if character_ids else 2

    config = {'character_count': count}
    config.update(settings or {})
    room, players = make_room(names=names, settings=config)
    select_theme(room, players[0][0], theme)
    room = services.start_auction(room.room_code, players[0][0])

    if character_ids is not None:
        room = AuctionRoom.objects.get(pk=room.pk)
        room.auction_characters = list(character_ids)
        room.current_character_index = 0
        room.current_highest_bid = room.starting_bid
        room.current_highest_bidder = None
        room.current_auction_extensions = 0
        room.auction_deadline = timezone.now() + timedelta(seconds=room.auction_duration)
        room.save()
    return room, players


def reload(room):
    room.refresh_from_db()
    return room


def reload_player(player):
    player.refresh_from_db()
    return player


def timeout_current(room):
    """Force the current auction deadline into the past and process it."""
    AuctionRoom.objects.filter(pk=room.pk).update(
        auction_deadline=timezone.now() - timedelta(seconds=1)
    )
    changed = services.expire_auction_if_needed(room.room_code)
    room.refresh_from_db()
    return changed, room


def win_current(room, player, amount=None):
    """Make ``player`` the highest bidder for the current character, then end it."""
    room.refresh_from_db()
    if room.current_highest_bidder_id != player.pk:
        target = amount if amount is not None else room.current_highest_bid + 100
        services.place_bid(room.room_code, player, target)
    _, room = timeout_current(room)
    return room


def record_bid(room, player, amount):
    return services.place_bid(room.room_code, player, amount)


def set_deadline(room, seconds):
    room.auction_deadline = timezone.now() + timedelta(seconds=seconds)
    room.save(update_fields=['auction_deadline'])
    return room
