"""Room lifecycle, draft actions, match flow, and serialization tests."""

from __future__ import annotations

import json
import random

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from fcmanager import services
from fcmanager.challenges import two_squads_feasible
from fcmanager.data import EUR_TRY_RATE, SLOTS
from fcmanager.models import MarketPlayer, Participant, Room
from fcmanager.tests.helpers import (
    available_candidates,
    create_room_with_players,
    fill_squad,
    start_draft,
)
from fcmanager.utils import ApiError

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
MAX_BUDGET_EUR = 1_000_000_000_000 / EUR_TRY_RATE


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class BudgetTests(SimpleTestCase):
    def test_budget_stays_inside_the_brief(self):
        rng = random.Random(1)
        values = []
        for _ in range(300):
            budget_eur, budget_try = services._random_budget(rng)
            values.append(budget_eur)
            self.assertGreaterEqual(budget_eur, services.MIN_BUDGET_EUR)
            self.assertLessEqual(budget_eur, MAX_BUDGET_EUR)
            self.assertEqual(budget_eur % 1_000_000, 0)
            self.assertEqual(
                budget_try,
                int(round(budget_eur * EUR_TRY_RATE / 10_000_000) * 10_000_000),
            )
        self.assertLess(min(values), 1_000_000_000)
        self.assertGreater(max(values), 2_000_000_000)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class RoomLifecycleTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_create_room_defaults(self):
        room, host, token = services.create_room('Ahmet')
        self.assertRegex(room.room_code, r'^[A-Z0-9]{6}$')
        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.host_id, host.pk)
        self.assertEqual(host.side, 'home')
        self.assertFalse(host.locked)
        self.assertNotEqual(host.session_token_hash, token)
        self.assertIsNotNone(room.expires_at)

    def test_join_assigns_away_and_reconnect_is_idempotent(self):
        room, host, host_token, entries = create_room_with_players()
        away, away_token = entries[1]
        self.assertEqual(away.side, 'away')
        self.assertEqual(room.players.count(), 2)

        same_room, same_player, token, rejoined = services.join_room(
            room.room_code, 'Player 2', away_token,
        )
        self.assertTrue(rejoined)
        self.assertEqual(same_player.pk, away.pk)
        self.assertEqual(token, away_token)
        self.assertEqual(same_room.players.count(), 2)

    def test_third_player_is_rejected(self):
        room, _host, _token, _entries = create_room_with_players()
        with self.assertRaises(ApiError) as ctx:
            services.join_room(room.room_code, 'Third')
        self.assertEqual(ctx.exception.code, 'room_full')

    def test_duplicate_name_is_rejected(self):
        room, _host, _token = services.create_room('Host')
        with self.assertRaises(ApiError) as ctx:
            services.join_room(room.room_code, ' host ')
        self.assertEqual(ctx.exception.code, 'name_taken')

    def test_join_after_draft_is_rejected(self):
        room, host, _token, _entries = create_room_with_players()
        start_draft(room, host)
        with self.assertRaises(ApiError) as ctx:
            services.join_room(room.room_code, 'Late')
        self.assertEqual(ctx.exception.code, 'game_already_started')

    def test_start_draft_requires_host_and_two_managers(self):
        room, host, _token = services.create_room('Solo')
        with self.assertRaises(ApiError) as ctx:
            services.start_draft(room.room_code, host)
        self.assertEqual(ctx.exception.code, 'players_required')

        room, host, _token, entries = create_room_with_players()
        with self.assertRaises(ApiError) as ctx:
            services.start_draft(room.room_code, entries[1][0])
        self.assertEqual(ctx.exception.code, 'host_only')

    def test_start_draft_builds_a_playable_market(self):
        room, host, _token, entries = create_room_with_players()
        room = services.start_draft(room.room_code, host)

        self.assertEqual(room.status, 'DRAFT')
        self.assertEqual(room.market.count(), 80)
        self.assertGreaterEqual(room.budget_eur, services.MIN_BUDGET_EUR)
        self.assertLessEqual(room.budget_eur, MAX_BUDGET_EUR)
        self.assertGreaterEqual(len(room.challenges), 3)
        self.assertLessEqual(len(room.challenges), 4)
        self.assertIsNotNone(room.started_at)
        self.assertFalse(room.players.filter(locked=True).exists())

        with self.assertRaises(ApiError) as ctx:
            services.start_draft(room.room_code, host)
        self.assertEqual(ctx.exception.code, 'game_started')

    def test_authenticate_only_accepts_the_right_room_and_token(self):
        room, host, host_token, entries = create_room_with_players()
        other, _other_host, _other_token = services.create_room('Other')

        auth = services.authenticate(room.room_code, host_token)
        self.assertIsNotNone(auth)
        self.assertEqual(auth[1].pk, host.pk)
        self.assertIsNone(services.authenticate(room.room_code, 'bad-token'))
        self.assertIsNone(services.authenticate(other.room_code, host_token))


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class DraftActionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room, self.host, self.token, self.entries = create_room_with_players()
        self.away = self.entries[1][0]
        self.room = start_draft(self.room, self.host, budget_eur=10_000_000_000)

    def market_player(self, slot_key: str, skip: int = 0):
        candidates = available_candidates(self.room, slot_key)
        self.assertGreater(len(candidates), skip)
        return candidates[skip]

    def test_pick_assigns_player_and_updates_spent(self):
        player = self.market_player('gk')
        services.pick_player(self.room.room_code, self.host, player.pk, 'gk')

        picked = MarketPlayer.objects.get(pk=player.pk)
        self.assertEqual(picked.picked_by_id, self.host.pk)
        self.assertEqual(picked.picked_slot, 'gk')
        state = services.build_room_state(Room.objects.get(pk=self.room.pk), self.host)
        self.assertEqual(state['you']['slots_filled'], 1)
        self.assertEqual(state['you']['spent'], picked.data['value_eur'])
        entry = next(item for item in state['market'] if item['id'] == player.pk)
        self.assertTrue(entry['picked_by_you'])
        self.assertEqual(entry['slot'], 'gk')

    def test_pick_rejects_position_mismatch(self):
        player = self.market_player('gk')
        with self.assertRaises(ApiError) as ctx:
            services.pick_player(self.room.room_code, self.host, player.pk, 'st')
        self.assertEqual(ctx.exception.code, 'position_mismatch')

    def test_pick_rejects_player_taken_by_opponent(self):
        player = self.market_player('gk')
        services.pick_player(self.room.room_code, self.host, player.pk, 'gk')
        with self.assertRaises(ApiError) as ctx:
            services.pick_player(self.room.room_code, self.away, player.pk, 'gk')
        self.assertEqual(ctx.exception.code, 'player_taken')

    def test_pick_respects_budget(self):
        player = self.market_player('gk')
        Room.objects.filter(pk=self.room.pk).update(budget_eur=1)
        with self.assertRaises(ApiError) as ctx:
            services.pick_player(self.room.room_code, self.host, player.pk, 'gk')
        self.assertEqual(ctx.exception.code, 'budget_exceeded')

    def test_replacing_a_slot_releases_the_old_player(self):
        first = self.market_player('gk')
        second = self.market_player('gk', skip=1)
        services.pick_player(self.room.room_code, self.host, first.pk, 'gk')
        services.pick_player(self.room.room_code, self.host, second.pk, 'gk')

        self.assertIsNone(MarketPlayer.objects.get(pk=first.pk).picked_by_id)
        picked = MarketPlayer.objects.get(pk=second.pk)
        self.assertEqual(picked.picked_by_id, self.host.pk)
        self.assertEqual(picked.picked_slot, 'gk')
        self.assertEqual(MarketPlayer.objects.filter(picked_by=self.host).count(), 1)

    def test_remove_pick_and_clear_squad(self):
        gk = self.market_player('gk')
        st = self.market_player('st')
        services.pick_player(self.room.room_code, self.host, gk.pk, 'gk')
        services.pick_player(self.room.room_code, self.host, st.pk, 'st')

        services.remove_pick(self.room.room_code, self.host, 'gk')
        self.assertIsNone(MarketPlayer.objects.get(pk=gk.pk).picked_by_id)
        self.assertEqual(MarketPlayer.objects.filter(picked_by=self.host).count(), 1)

        services.clear_squad(self.room.room_code, self.host)
        self.assertEqual(MarketPlayer.objects.filter(picked_by=self.host).count(), 0)

    def test_swap_to_empty_and_occupied_slots(self):
        first = self.market_player('cm1')
        second = self.market_player('cm1', skip=1)
        services.pick_player(self.room.room_code, self.host, first.pk, 'cm1')

        services.swap_slots(self.room.room_code, self.host, 'cm1', 'cm2')
        self.assertEqual(MarketPlayer.objects.get(pk=first.pk).picked_slot, 'cm2')

        services.pick_player(self.room.room_code, self.host, second.pk, 'cm1')
        services.swap_slots(self.room.room_code, self.host, 'cm1', 'cm2')
        self.assertEqual(MarketPlayer.objects.get(pk=first.pk).picked_slot, 'cm1')
        self.assertEqual(MarketPlayer.objects.get(pk=second.pk).picked_slot, 'cm2')

    def test_swap_rejects_incompatible_position(self):
        gk = self.market_player('gk')
        services.pick_player(self.room.room_code, self.host, gk.pk, 'gk')
        with self.assertRaises(ApiError) as ctx:
            services.swap_slots(self.room.room_code, self.host, 'gk', 'st')
        self.assertEqual(ctx.exception.code, 'position_mismatch')

    def test_lock_requires_a_full_squad(self):
        gk = self.market_player('gk')
        services.pick_player(self.room.room_code, self.host, gk.pk, 'gk')
        with self.assertRaises(ApiError) as ctx:
            services.lock_squad(self.room.room_code, self.host)
        self.assertEqual(ctx.exception.code, 'squad_incomplete')

    def test_locked_squad_blocks_every_draft_action(self):
        fill_squad(self.room, self.host, lock=True)
        for action in (
            lambda: services.pick_player(self.room.room_code, self.host, self.market_player('st').pk, 'st'),
            lambda: services.remove_pick(self.room.room_code, self.host, 'gk'),
            lambda: services.clear_squad(self.room.room_code, self.host),
            lambda: services.swap_slots(self.room.room_code, self.host, 'gk', 'gk'),
        ):
            with self.assertRaises(ApiError) as ctx:
                action()
            self.assertEqual(ctx.exception.code, 'squad_locked')

    def test_unlock_restores_draft_actions(self):
        fill_squad(self.room, self.host, lock=True)
        services.unlock_squad(self.room.room_code, self.host)
        self.assertFalse(Participant.objects.get(pk=self.host.pk).locked)
        services.remove_pick(self.room.room_code, self.host, 'gk')
        self.assertEqual(MarketPlayer.objects.filter(picked_by=self.host).count(), 10)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class MatchFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room, self.host, self.token, self.entries = create_room_with_players()
        self.away = self.entries[1][0]
        self.room = start_draft(self.room, self.host, budget_eur=10_000_000_000)
        fill_squad(self.room, self.host, lock=True)
        fill_squad(self.room, self.away, lock=True)

    def test_start_match_builds_a_complete_result(self):
        match = services.start_match(self.room.room_code, self.host)

        self.assertEqual(match.status, 'FINISHED')
        self.assertEqual(len(match.home_snapshot['squad']), len(SLOTS))
        self.assertEqual(len(match.away_snapshot['squad']), len(SLOTS))
        self.assertTrue(match.events)
        self.assertEqual(match.events[0]['type'], 'kickoff')
        self.assertIn('home', match.stats)
        self.assertIn('away', match.stats)
        self.assertIn('profiles', match.stats)
        self.assertIsInstance(match.mvp, dict)
        self.assertIn(match.winner_side, ('home', 'away'))

        room = Room.objects.select_related('current_match').get(pk=self.room.pk)
        self.assertEqual(room.status, 'FINISHED')
        self.assertEqual(room.current_match_id, match.pk)
        self.assertIsNotNone(room.finished_at)

    def test_start_match_requires_both_squads_locked(self):
        room, host, _token, entries = create_room_with_players(names=['H', 'A'])
        room = start_draft(room, host, budget_eur=10_000_000_000)
        fill_squad(room, host, lock=True)
        fill_squad(room, entries[1][0], lock=False)
        with self.assertRaises(ApiError) as ctx:
            services.start_match(room.room_code, host)
        self.assertEqual(ctx.exception.code, 'squads_not_locked')

    def test_start_match_is_host_only(self):
        with self.assertRaises(ApiError) as ctx:
            services.start_match(self.room.room_code, self.away)
        self.assertEqual(ctx.exception.code, 'host_only')

    def test_unlock_is_closed_after_the_match(self):
        services.start_match(self.room.room_code, self.host)
        with self.assertRaises(ApiError) as ctx:
            services.unlock_squad(self.room.room_code, self.host)
        self.assertEqual(ctx.exception.code, 'draft_closed')

    def test_new_season_resets_the_room(self):
        services.start_match(self.room.room_code, self.host)
        room = services.new_season(self.room.room_code, self.host)

        self.assertEqual(room.status, 'DRAFT')
        self.assertIsNone(room.current_match_id)
        self.assertIsNone(room.finished_at)
        self.assertEqual(room.market.count(), 80)
        self.assertEqual(MarketPlayer.objects.filter(room=room, picked_by__isnull=False).count(), 0)
        self.assertFalse(room.players.filter(locked=True).exists())
        self.assertGreaterEqual(room.budget_eur, services.MIN_BUDGET_EUR)
        self.assertLessEqual(room.budget_eur, MAX_BUDGET_EUR)
        self.assertGreaterEqual(len(room.challenges), 3)
        self.assertTrue(two_squads_feasible(
            [market_player.data for market_player in room.market.all()],
            room.budget_eur,
            room.challenges,
            random.Random(99),
            attempts=300,
        ))

    def test_new_season_is_host_only(self):
        services.start_match(self.room.room_code, self.host)
        with self.assertRaises(ApiError) as ctx:
            services.new_season(self.room.room_code, self.away)
        self.assertEqual(ctx.exception.code, 'host_only')

    def test_new_season_requires_a_finished_match(self):
        with self.assertRaises(ApiError) as ctx:
            services.new_season(self.room.room_code, self.host)
        self.assertEqual(ctx.exception.code, 'invalid_status')

    def test_leave_after_match_resets_to_waiting(self):
        services.start_match(self.room.room_code, self.host)
        room = services.leave_room(self.room.room_code, self.away)
        room.refresh_from_db()

        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.budget_eur, 0)
        self.assertEqual(room.challenges, [])
        self.assertEqual(room.market.count(), 0)
        self.assertEqual(room.host_id, self.host.pk)
        self.assertTrue(Participant.objects.get(pk=self.away.pk).left)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class MembershipTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_waiting_leave_deletes_member(self):
        room, host, _token, entries = create_room_with_players()
        away = entries[1][0]
        services.leave_room(room.room_code, away)
        self.assertFalse(Participant.objects.filter(pk=away.pk).exists())
        self.assertEqual(room.players.count(), 1)

    def test_waiting_host_leave_transfers_host(self):
        room, host, _token, entries = create_room_with_players()
        away = entries[1][0]
        services.leave_room(room.room_code, host)
        room.refresh_from_db()
        self.assertFalse(Participant.objects.filter(pk=host.pk).exists())
        self.assertEqual(room.host_id, away.pk)

    def test_draft_leave_resets_to_waiting(self):
        room, host, _token, entries = create_room_with_players()
        away = entries[1][0]
        start_draft(room, host)
        room = services.leave_room(room.room_code, away)
        room.refresh_from_db()

        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.market.count(), 0)
        self.assertEqual(room.challenges, [])
        self.assertEqual(room.budget_eur, 0)
        self.assertEqual(room.host_id, host.pk)
        self.assertTrue(Participant.objects.get(pk=away.pk).left)
        self.assertFalse(Participant.objects.get(pk=host.pk).locked)

    def test_draft_host_leave_transfers_host_and_resets(self):
        room, host, _token, entries = create_room_with_players()
        away = entries[1][0]
        start_draft(room, host)
        room = services.leave_room(room.room_code, host)
        room.refresh_from_db()

        self.assertEqual(room.status, 'WAITING')
        self.assertEqual(room.host_id, away.pk)
        self.assertTrue(Participant.objects.get(pk=host.pk).left)
        self.assertFalse(Participant.objects.get(pk=away.pk).locked)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class StateSerializationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.room, self.host, self.token, self.entries = create_room_with_players()
        self.away = self.entries[1][0]
        self.room = start_draft(self.room, self.host, budget_eur=10_000_000_000)

    def test_state_contains_everything_the_client_needs(self):
        state = services.build_room_state(self.room, self.host)
        self.assertEqual(state['room']['code'], self.room.room_code)
        self.assertEqual(state['you']['name'], 'Player 1')
        self.assertEqual(state['opponent']['name'], 'Player 2')
        self.assertEqual(len(state['market']), 80)
        self.assertEqual(len(state['slots']), len(SLOTS))
        self.assertIsNone(state['match'])
        self.assertTrue(state['server_time'])
        self.assertNotIn('session_token', json.dumps(state))
        self.assertNotIn('session_token_hash', json.dumps(state))

        market_player = state['market'][0]
        self.assertIn('id', market_player)
        self.assertIn('nation_label', market_player)
        self.assertIn('league_label', market_player)
        self.assertIsNone(market_player['picked_by'])

    def test_viewer_lock_state_is_fresh_after_lock(self):
        stale_host = Participant.objects.get(pk=self.host.pk)
        fill_squad(self.room, self.host, lock=True)
        self.assertFalse(stale_host.locked)

        state = services.build_room_state(Room.objects.get(pk=self.room.pk), stale_host)
        self.assertTrue(state['you']['locked'])

    def test_match_state_is_serialized_after_start(self):
        fill_squad(self.room, self.host, lock=True)
        fill_squad(self.room, self.away, lock=True)
        services.start_match(self.room.room_code, self.host)
        room = Room.objects.select_related('current_match').get(pk=self.room.pk)

        state = services.build_room_state(room, self.host)
        self.assertIsNotNone(state['match'])
        self.assertEqual(state['match']['id'], str(room.current_match_id))
        self.assertTrue(state['match']['events'])
        self.assertIn('home', state['match'])
        self.assertIn('away', state['match'])
        self.assertNotIn('session_token_hash', json.dumps(state))
