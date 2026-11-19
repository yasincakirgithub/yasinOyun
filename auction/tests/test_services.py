"""Service-level tests for the Character Auction game."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from auction import services
from auction.models import AuctionBid, AuctionRoom
from auction.themes.loader import (
    THEME_METADATA,
    calculate_synergy_bonus,
    get_all_themes,
    get_character_by_id,
    get_theme_characters,
    get_theme_synergies,
)
from auction.utils import ApiError

from .helpers import (
    make_room,
    record_bid,
    reload,
    reload_player,
    set_deadline,
    started_room,
    timeout_current,
    win_current,
)


class RoomLifecycleTests(TestCase):
    def test_create_room_defaults_and_authentication(self):
        room, host, token = services.create_room('  Alice  ')

        self.assertRegex(room.room_code, r'^[A-Z0-9]{6}$')
        self.assertEqual(room.host_id, host.pk)
        self.assertEqual(host.display_name, 'Alice')
        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.starting_budget, 2000)
        self.assertEqual(room.starting_bid, 100)
        self.assertIsNotNone(room.expires_at)

        authenticated = services.authenticate(room.room_code, token)
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated[1].pk, host.pk)
        self.assertIsNone(services.authenticate(room.room_code, 'not-a-real-token'))

    def test_join_rejoin_and_duplicate_names(self):
        room, host, host_token = services.create_room('Host')

        room, guest, guest_token, rejoined = services.join_room(room.room_code, 'Guest')
        self.assertFalse(rejoined)
        self.assertEqual(room.players.filter(left=False).count(), 2)
        self.assertEqual(guest.budget, room.starting_budget)

        room, again, token_again, rejoined_again = services.join_room(
            room.room_code, 'Guest', guest_token
        )
        self.assertTrue(rejoined_again)
        self.assertEqual(again.pk, guest.pk)
        self.assertEqual(token_again, guest_token)

        with self.assertRaises(ApiError) as raised:
            services.join_room(room.room_code, '  guest  ')
        self.assertEqual(raised.exception.code, 'name_taken')

        with self.assertRaises(ApiError) as raised:
            services.join_room(room.room_code, 'Other', 'bogus-token')
        self.assertEqual(raised.exception.code, 'invalid_session')

    def test_join_allowed_until_auction_starts(self):
        room, host, _ = services.create_room('Host')
        room = services.update_settings(room.room_code, host, {'character_count': 2})
        self.assertEqual(room.status, 'CONFIGURING')

        # Configuring and theme selection are still lobby states.
        room, guest, guest_token, _ = services.join_room(room.room_code, 'Guest')
        services.select_theme(room.room_code, host, 'marvel')
        room, late, _, _ = services.join_room(room.room_code, 'Late')
        self.assertEqual(room.players.filter(left=False).count(), 3)

        services.start_auction(room.room_code, host)
        with self.assertRaises(ApiError) as raised:
            services.join_room(room.room_code, 'TooLate')
        self.assertEqual(raised.exception.code, 'game_already_started')

        # Reconnecting with an existing token is always allowed.
        room, reconnect, token, rejoined = services.join_room(
            room.room_code, 'Guest', guest_token
        )
        self.assertTrue(rejoined)
        self.assertEqual(reconnect.pk, guest.pk)

    def test_room_full_and_host_only_configuration(self):
        room, host, _ = services.create_room('Host')
        room.max_players = 2
        room.save(update_fields=['max_players'])
        room, guest, _, _ = services.join_room(room.room_code, 'Guest')

        with self.assertRaises(ApiError) as raised:
            services.join_room(room.room_code, 'Third')
        self.assertEqual(raised.exception.code, 'room_full')

        with self.assertRaises(ApiError) as raised:
            services.update_settings(room.room_code, guest, {'starting_budget': 5000})
        self.assertEqual(raised.exception.code, 'host_only')

        with self.assertRaises(ApiError) as raised:
            services.select_theme(room.room_code, guest, 'dc')
        self.assertEqual(raised.exception.code, 'host_only')

    def test_host_only_start_and_reset(self):
        room, host, _ = services.create_room('Host')
        room, guest, _, _ = services.join_room(room.room_code, 'Guest')

        with self.assertRaises(ApiError) as raised:
            services.start_auction(room.room_code, guest)
        self.assertEqual(raised.exception.code, 'host_only')

        with self.assertRaises(ApiError) as raised:
            services.start_auction(room.room_code, host)
        self.assertEqual(raised.exception.code, 'theme_not_selected')

        services.select_theme(room.room_code, host, 'marvel')
        with self.assertRaises(ApiError) as raised:
            services.start_auction(room.room_code, guest)
        self.assertEqual(raised.exception.code, 'host_only')

    def test_start_requires_two_players(self):
        room, host, _ = services.create_room('Solo')
        services.select_theme(room.room_code, host, 'marvel')

        with self.assertRaises(ApiError) as raised:
            services.start_auction(room.room_code, host)
        self.assertEqual(raised.exception.code, 'players_required')

    def test_leave_in_lobby_deletes_player_and_transfers_host(self):
        room, host, host_token = services.create_room('Host')
        room, guest, guest_token, _ = services.join_room(room.room_code, 'Guest')
        services.select_theme(room.room_code, host, 'marvel')

        room = services.leave_room(room.room_code, host)

        self.assertEqual(room.players.filter(left=False).count(), 1)
        self.assertFalse(room.players.filter(pk=host.pk).exists())
        self.assertEqual(room.host_id, guest.pk)
        self.assertIsNone(services.authenticate(room.room_code, host_token))
        # The remaining guest can still use their token.
        self.assertEqual(
            services.authenticate(room.room_code, guest_token)[1].pk, guest.pk
        )

    def test_leave_during_auction_marks_left_and_abandons(self):
        room, players = started_room()
        host, guest = players[0][0], players[1][0]

        room = services.leave_room(room.room_code, host)

        host.refresh_from_db()
        self.assertTrue(host.left)
        self.assertFalse(host.connected)
        self.assertEqual(room.status, 'ABANDONED')
        self.assertEqual(room.host_id, guest.pk)
        self.assertEqual(room.players.filter(left=False).count(), 1)
        self.assertIsNone(services.authenticate(room.room_code, players[0][1]))

    def test_reconnection_and_disconnect_tracking(self):
        room, players = started_room()
        host, guest = players[0][0], players[1][0]

        services.mark_connected(guest)
        services.mark_connected(guest)
        guest.refresh_from_db()
        self.assertEqual(guest.connection_count, 2)
        self.assertTrue(guest.connected)

        services.mark_disconnected(guest)
        guest.refresh_from_db()
        self.assertTrue(guest.connected)
        self.assertEqual(guest.connection_count, 1)

        services.mark_disconnected(guest)
        services.mark_disconnected(guest)
        guest.refresh_from_db()
        self.assertFalse(guest.connected)
        self.assertEqual(guest.connection_count, 0)

        room, rejoined, token, was_rejoin = services.join_room(
            room.room_code, 'Guest', players[1][1]
        )
        self.assertTrue(was_rejoin)
        self.assertEqual(rejoined.pk, guest.pk)
        self.assertEqual(token, players[1][1])

    def test_settings_are_clamped(self):
        room, host, _ = services.create_room('Host')

        room = services.update_settings(room.room_code, host, {
            'starting_budget': 1,
            'starting_bid': 0,
            'character_count': 999,
            'auction_duration': 1,
            'max_players': 99,
            'extension_threshold': 99,
            'extension_duration': 99,
        })

        self.assertEqual(room.starting_budget, 100)
        self.assertEqual(room.starting_bid, 1)
        self.assertEqual(room.character_count, 50)
        self.assertEqual(room.auction_duration, 5)
        self.assertEqual(room.max_players, 8)
        self.assertEqual(room.extension_threshold, 10)
        self.assertEqual(room.extension_duration, 30)

    def test_theme_can_be_changed_while_configuring(self):
        room, host, _ = services.create_room('Host')
        room, guest, _, _ = services.join_room(room.room_code, 'Guest')

        services.select_theme(room.room_code, host, 'marvel')
        room = services.select_theme(room.room_code, host, 'naruto')
        self.assertEqual(room.theme_id, 'naruto')
        self.assertEqual(room.status, 'THEME_SELECT')

        with self.assertRaises(ApiError) as raised:
            services.select_theme(room.room_code, host, 'not-a-theme')
        self.assertEqual(raised.exception.code, 'invalid_theme')


class ThemeRegistryTests(TestCase):
    def test_ten_themes_with_complete_metadata(self):
        themes = get_all_themes()
        self.assertGreaterEqual(len(themes), 10)
        self.assertEqual({theme['id'] for theme in themes}, set(THEME_METADATA))

        for theme in themes:
            with self.subTest(theme=theme['id']):
                self.assertTrue(theme['name'])
                self.assertTrue(theme['description'])
                self.assertRegex(theme['accent'], r'^#[0-9a-fA-F]{6}$')
                self.assertRegex(theme['accent_2'], r'^#[0-9a-fA-F]{6}$')
                self.assertTrue(theme['icon'])
                self.assertGreaterEqual(theme['character_count'], 20)

    def test_characters_and_synergies_are_valid(self):
        for theme_id in THEME_METADATA:
            with self.subTest(theme=theme_id):
                characters = get_theme_characters(theme_id)
                self.assertGreaterEqual(len(characters), 20)
                character_ids = [char['id'] for char in characters]
                self.assertEqual(len(character_ids), len(set(character_ids)))

                for char in characters:
                    self.assertRegex(char['id'], r'^[a-z0-9_]+$')
                    self.assertTrue(char['name'])
                    self.assertIsInstance(char['power'], int)
                    self.assertGreater(char['power'], 0)
                    self.assertTrue(char['image'])

                synergies = get_theme_synergies(theme_id)
                self.assertGreaterEqual(len(synergies), 5)
                synergy_ids = [synergy['id'] for synergy in synergies]
                self.assertEqual(len(synergy_ids), len(set(synergy_ids)))

                for synergy in synergies:
                    self.assertTrue(synergy['name'])
                    required = synergy['required_character_ids']
                    self.assertGreaterEqual(len(required), 2)
                    self.assertTrue(set(required).issubset(set(character_ids)))
                    self.assertIn(synergy['bonus']['type'], ('fixed', 'percentage'))
                    self.assertGreater(synergy['bonus']['value'], 0)

    def test_synergy_bonus_fixed_and_percentage(self):
        fixed = {
            'id': 'test_fixed',
            'name': 'Fixed',
            'required_character_ids': ['marvel_iron_man', 'marvel_thor'],
            'bonus': {'type': 'fixed', 'value': 15},
        }
        percentage = {
            'id': 'test_percentage',
            'name': 'Percentage',
            'required_character_ids': ['marvel_iron_man', 'marvel_thor'],
            'bonus': {'type': 'percentage', 'value': 10},
        }

        with mock.patch(
            'auction.themes.loader.get_theme_synergies', return_value=[fixed]
        ):
            bonus, active = calculate_synergy_bonus(
                'marvel', {'marvel_iron_man', 'marvel_thor'}
            )
        self.assertEqual(bonus, 15)
        self.assertEqual(active[0]['bonus_type'], 'fixed')

        with mock.patch(
            'auction.themes.loader.get_theme_synergies', return_value=[percentage]
        ):
            bonus, active = calculate_synergy_bonus(
                'marvel', {'marvel_iron_man', 'marvel_thor'}
            )
        # Iron Man 92 + Thor 95 = 187 base power; 10% = 18.7 -> 19.
        self.assertEqual(bonus, 19)
        self.assertEqual(active[0]['bonus_type'], 'percentage')

        with mock.patch(
            'auction.themes.loader.get_theme_synergies',
            return_value=[fixed, percentage],
        ):
            bonus, active = calculate_synergy_bonus(
                'marvel', {'marvel_iron_man', 'marvel_thor'}
            )
        self.assertEqual(bonus, 34)
        self.assertEqual(len(active), 2)


class BiddingTests(TestCase):
    def test_valid_bid_updates_room_and_audit_trail(self):
        room, players = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        host, guest = players[0][0], players[1][0]

        room = record_bid(room, guest, 150)

        self.assertEqual(room.current_highest_bid, 150)
        self.assertEqual(room.current_highest_bidder_id, guest.pk)
        self.assertEqual(
            AuctionBid.objects.filter(room=room, is_winning=True).count(), 1
        )

        room = record_bid(room, host, 250)
        self.assertEqual(room.current_highest_bid, 250)
        self.assertEqual(room.current_highest_bidder_id, host.pk)
        winning = AuctionBid.objects.filter(room=room, is_winning=True)
        self.assertEqual(winning.count(), 1)
        self.assertEqual(winning.first().player_id, host.pk)

    def test_invalid_bids_are_rejected(self):
        room, players = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        host, guest = players[0][0], players[1][0]

        cases = [
            (guest, room.starting_bid, 'bid_too_low'),
            (guest, 0, 'bid_too_low'),
            (guest, -100, 'bid_too_low'),
            (guest, room.starting_budget + 100, 'insufficient_budget'),
        ]
        for player, amount, code in cases:
            with self.subTest(amount=amount):
                with self.assertRaises(ApiError) as raised:
                    services.place_bid(room.room_code, player, amount)
                self.assertEqual(raised.exception.code, code)

        # Guest takes the lead, then cannot outbid themselves.
        record_bid(room, guest, 150)
        with self.assertRaises(ApiError) as raised:
            services.place_bid(room.room_code, guest, 200)
        self.assertEqual(raised.exception.code, 'bid_against_self')

        # A bid exactly equal to the remaining budget is allowed.
        rich = reload_player(guest)
        rich.budget = 500
        rich.save(update_fields=['budget'])
        room = record_bid(room, host, 300)
        room = record_bid(room, guest, 500)
        self.assertEqual(room.current_highest_bid, 500)

    def test_bidding_outside_auction_is_rejected(self):
        room, players = make_room(settings={'character_count': 2})
        host = players[0][0]

        with self.assertRaises(ApiError) as raised:
            services.place_bid(room.room_code, host, 150)
        self.assertEqual(raised.exception.code, 'not_in_auction')

    def test_bidding_after_deadline_advances_auction(self):
        room, players = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        guest = players[1][0]

        AuctionRoom.objects.filter(pk=room.pk).update(
            auction_deadline=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(ApiError) as raised:
            services.place_bid(room.room_code, guest, 150)
        self.assertEqual(raised.exception.code, 'auction_ended')

        # The timeout handling must survive the rejected bid (no rollback).
        room.refresh_from_db()
        self.assertEqual(room.current_character_index, 1)
        self.assertEqual(room.status, 'AUCTION')
        self.assertEqual(room.current_highest_bidder_id, None)


class AntiSnipeTests(TestCase):
    def test_valid_late_bid_extends_and_repeats(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor'],
            settings={
                'extension_threshold': 3,
                'extension_duration': 5,
                'auction_duration': 20,
            },
        )
        host, guest = players[0][0], players[1][0]

        set_deadline(room, 2)
        room = reload(room)
        original_deadline = room.auction_deadline
        room = record_bid(room, guest, 150)
        self.assertEqual(room.current_auction_extensions, 1)
        self.assertAlmostEqual(
            (room.auction_deadline - original_deadline).total_seconds(), 5, places=1
        )

        set_deadline(room, 1)
        room = reload(room)
        second_original = room.auction_deadline
        room = record_bid(room, host, 250)
        self.assertEqual(room.current_auction_extensions, 2)
        self.assertAlmostEqual(
            (room.auction_deadline - second_original).total_seconds(), 5, places=1
        )

    def test_early_bid_does_not_extend(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor'],
            settings={'extension_threshold': 3, 'extension_duration': 5},
        )
        guest = players[1][0]

        set_deadline(room, 10)
        room = reload(room)
        original_deadline = room.auction_deadline
        room = record_bid(room, guest, 150)
        self.assertEqual(room.current_auction_extensions, 0)
        self.assertEqual(room.auction_deadline, original_deadline)

    def test_invalid_late_bid_does_not_extend(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor'],
            settings={'extension_threshold': 3, 'extension_duration': 5},
        )
        guest = players[1][0]

        set_deadline(room, 2)
        room = reload(room)
        original_deadline = room.auction_deadline
        with self.assertRaises(ApiError) as raised:
            services.place_bid(room.room_code, guest, room.starting_bid)
        self.assertEqual(raised.exception.code, 'bid_too_low')

        room.refresh_from_db()
        self.assertEqual(room.current_auction_extensions, 0)
        self.assertEqual(room.auction_deadline, original_deadline)


class AuctionProgressionTests(TestCase):
    def test_timeout_without_bids_advances_to_next_character(self):
        room, _ = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor', 'marvel_hulk']
        )
        self.assertEqual(room.current_character_index, 0)

        changed, room = timeout_current(room)
        self.assertTrue(changed)
        self.assertEqual(room.status, 'AUCTION')
        self.assertEqual(room.current_character_index, 1)
        self.assertEqual(room.current_highest_bidder_id, None)
        self.assertGreater(room.auction_deadline, timezone.now())

    def test_winner_receives_character_and_budget_is_deducted(self):
        room, players = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        guest = players[1][0]

        room = win_current(room, guest, amount=300)
        guest = reload_player(guest)

        self.assertEqual(guest.owned_characters, ['marvel_iron_man'])
        self.assertEqual(guest.budget, room.starting_budget - 300)
        # Iron Man power was rebalanced from 92 to 96
        self.assertEqual(guest.total_power, 96)
        self.assertEqual(room.current_character_index, 1)

    def test_all_characters_finish_the_game_and_persist_results(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor']
        )
        guest = players[1][0]

        room = win_current(room, guest, amount=200)
        self.assertEqual(room.status, 'AUCTION')

        room = win_current(room, guest, amount=200)
        self.assertEqual(room.status, 'FINISHED')
        self.assertIsNotNone(room.finished_at)
        self.assertTrue(hasattr(room, 'result'))
        self.assertEqual(room.result.rankings[0]['name'], 'Guest')
        self.assertEqual(room.result.rankings[0]['character_count'], 2)
        self.assertEqual(
            room.result.character_ownership,
            {'marvel_iron_man': str(guest.pk), 'marvel_thor': str(guest.pk)},
        )

    def test_new_game_resets_state_and_keeps_players(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor']
        )
        host, guest = players[0][0], players[1][0]
        win_current(room, guest, amount=200)
        room = win_current(room, guest, amount=200)
        self.assertEqual(room.status, 'FINISHED')

        with self.assertRaises(ApiError) as raised:
            services.new_game(room.room_code, guest)
        self.assertEqual(raised.exception.code, 'host_only')

        room = services.new_game(room.room_code, host)
        host = reload_player(host)
        guest = reload_player(guest)

        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.theme_id, '')
        self.assertEqual(room.auction_characters, [])
        self.assertEqual(room.current_character_index, 0)
        self.assertIsNone(room.auction_deadline)
        self.assertEqual(host.budget, room.starting_budget)
        self.assertEqual(guest.budget, room.starting_budget)
        self.assertEqual(host.owned_characters, [])
        self.assertEqual(host.total_power, 0)
        self.assertFalse(hasattr(room, 'result'))
        self.assertEqual(room.players.filter(left=False).count(), 2)


class ScoringTests(TestCase):
    def test_synergy_bonus_is_added_once_and_included_in_state(self):
        character_ids = [
            'marvel_iron_man',
            'marvel_thor',
            'marvel_captain_america',
            'marvel_hulk',
        ]
        room, players = started_room(
            character_ids=character_ids, count=len(character_ids)
        )
        host, guest = players[0][0], players[1][0]

        for _ in character_ids:
            room = win_current(room, host)

        host = reload_player(host)
        base_power = (
            get_character_by_id('marvel', 'marvel_iron_man')['power']
            + get_character_by_id('marvel', 'marvel_thor')['power']
            + get_character_by_id('marvel', 'marvel_captain_america')['power']
            + get_character_by_id('marvel', 'marvel_hulk')['power']
        )
        self.assertEqual(host.owned_characters, character_ids)
        self.assertEqual(host.synergy_bonus, 40)
        self.assertEqual(host.total_power, base_power + 40)
        # Each winning bid is starting_bid + $1.00 = 200 cents.
        self.assertEqual(host.budget, room.starting_budget - 4 * 200)

        state = services.build_room_state(room, host)
        self.assertEqual(state['me']['synergy_bonus'], 40)
        self.assertEqual(
            [synergy['name'] for synergy in state['me']['active_synergies']],
            ['Avengers Assemble'],
        )

        if room.status == 'FINISHED':
            self.assertIn(str(host.pk), room.result.activated_synergies)

    def test_ranking_uses_power_then_characters_then_budget(self):
        room, players = started_room(
            character_ids=['marvel_iron_man'], names=('Alpha', 'Bravo', 'Charlie')
        )
        alpha, bravo, charlie = (player for player, _ in players)

        # Equal power, different collections and budgets.
        alpha.total_power, alpha.owned_characters, alpha.budget = 100, ['x'], 1000
        bravo.total_power, bravo.owned_characters, bravo.budget = 100, ['x', 'y'], 500
        charlie.total_power, charlie.owned_characters, charlie.budget = 100, ['x', 'y'], 800
        alpha.save()
        bravo.save()
        charlie.save()

        AuctionRoom.objects.filter(pk=room.pk).update(
            status='AUCTION',
            current_character_index=len(room.get_auction_characters()),
            current_highest_bidder=None,
            auction_deadline=timezone.now() - timedelta(seconds=1),
        )
        _, room = timeout_current(room)

        self.assertEqual(room.status, 'FINISHED')
        rankings = room.result.rankings
        self.assertEqual(
            [entry['name'] for entry in rankings],
            ['Charlie', 'Bravo', 'Alpha'],
        )
        self.assertEqual([entry['rank'] for entry in rankings], [1, 2, 3])
        self.assertFalse(any(entry['is_draw'] for entry in rankings))

    def test_equal_scores_share_rank_as_draw(self):
        room, players = started_room(
            character_ids=['marvel_iron_man'], names=('Alpha', 'Bravo', 'Charlie')
        )
        alpha, bravo, charlie = (player for player, _ in players)

        alpha.total_power, alpha.owned_characters, alpha.budget = 120, ['x'], 400
        bravo.total_power, bravo.owned_characters, bravo.budget = 120, ['x'], 400
        charlie.total_power, charlie.owned_characters, charlie.budget = 50, [], 1800
        alpha.save()
        bravo.save()
        charlie.save()

        AuctionRoom.objects.filter(pk=room.pk).update(
            status='AUCTION',
            current_character_index=len(room.get_auction_characters()),
            current_highest_bidder=None,
            auction_deadline=timezone.now() - timedelta(seconds=1),
        )
        _, room = timeout_current(room)

        rankings = room.result.rankings
        self.assertEqual([entry['rank'] for entry in rankings], [1, 1, 3])
        self.assertTrue(rankings[0]['is_draw'])
        self.assertTrue(rankings[1]['is_draw'])
        self.assertFalse(rankings[2]['is_draw'])

    def test_every_theme_can_run_an_auction(self):
        for theme_id in THEME_METADATA:
            with self.subTest(theme=theme_id):
                room, players = started_room(theme=theme_id, count=5)

                self.assertEqual(room.status, 'AUCTION')
                self.assertEqual(room.theme_id, theme_id)
                self.assertEqual(len(room.auction_characters), 5)
                self.assertEqual(len(set(room.auction_characters)), 5)

                valid_ids = {
                    char['id'] for char in get_theme_characters(theme_id)
                }
                self.assertTrue(set(room.auction_characters).issubset(valid_ids))

                state = services.build_room_state(room, players[0][0])
                self.assertIsNotNone(state['current_auction'])
                self.assertIsNotNone(state['theme_info']['selected_theme'])
                self.assertEqual(
                    len(state['theme_info']['selected_theme']['characters']),
                    len(valid_ids),
                )
                self.assertGreaterEqual(len(state['theme_info']['themes']), 10)


class SerializationTests(TestCase):
    def test_state_contains_progress_timer_and_permissions(self):
        room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor', 'marvel_hulk'],
            settings={'extension_threshold': 3, 'extension_duration': 5},
        )
        host, guest = players[0][0], players[1][0]

        state = services.build_room_state(room, host)
        self.assertEqual(state['room']['status'], 'AUCTION')
        self.assertEqual(state['room']['current_character_index'], 0)
        self.assertEqual(state['current_auction']['auction_number'], 1)
        self.assertEqual(state['current_auction']['total_auctions'], 3)
        self.assertFalse(state['current_auction']['timer']['extended'])
        self.assertEqual(state['current_auction']['timer']['extension_count'], 0)
        self.assertTrue(state['permissions']['is_host'])
        self.assertTrue(state['permissions']['can_bid'])
        self.assertFalse(state['permissions']['can_configure'])
        self.assertEqual(len(state['players']), 2)

        # A late bid is reflected in the serialized timer.
        set_deadline(room, 2)
        record_bid(room, guest, 150)
        room = reload(room)
        state = services.build_room_state(room, guest)
        self.assertTrue(state['current_auction']['timer']['extended'])
        self.assertEqual(state['current_auction']['timer']['extension_count'], 1)
        self.assertEqual(
            state['current_auction']['current_bidder']['id'], str(guest.pk)
        )

    def test_build_room_state_for_token_authenticates_and_expires(self):
        room, players = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        guest, guest_token = players[1]

        state = services.build_room_state_for_token(room.room_code, guest_token)
        self.assertIsNotNone(state)
        self.assertEqual(state['me']['id'], str(guest.pk))
        self.assertIsNone(services.build_room_state_for_token(room.room_code, 'nope'))

        AuctionRoom.objects.filter(pk=room.pk).update(
            auction_deadline=timezone.now() - timedelta(seconds=1)
        )
        state = services.build_room_state_for_token(room.room_code, guest_token)
        self.assertEqual(state['room']['current_character_index'], 1)
