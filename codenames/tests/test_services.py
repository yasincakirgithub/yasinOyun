import json
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from codenames import services
from codenames.models import GamePlayer, GameRoom, GameSession
from codenames.tests.helpers import create_room_with_players, start_room
from codenames.utils import ApiError

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class BoardGenerationTests(TestCase):
    def test_classic_distribution_and_positions(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, starting_team='red')
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        counts = Counter(session.words.values_list('category', flat=True))
        self.assertEqual(counts['red'], 9)
        self.assertEqual(counts['blue'], 8)
        self.assertEqual(counts['neutral'], 7)
        self.assertEqual(counts['assassin'], 1)
        self.assertEqual(session.remaining_agents, {'red': 9, 'blue': 8})
        self.assertEqual(session.current_team, 'red')
        self.assertEqual(sorted(session.words.values_list('position', flat=True)), list(range(25)))
        self.assertEqual(session.words.count(), 25)

    def test_blue_start_reverses_agent_counts(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, starting_team='blue')
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        counts = Counter(session.words.values_list('category', flat=True))
        self.assertEqual(counts['blue'], 9)
        self.assertEqual(counts['red'], 8)
        self.assertEqual(session.remaining_agents, {'blue': 9, 'red': 8})
        self.assertEqual(session.current_team, 'blue')

    def test_switching_starting_team_requires_new_game(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, starting_team='red')
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        self.assertEqual(session.starting_team, 'red')
        with self.assertRaises(ApiError):
            services.update_settings(room.room_code, host, {'starting_team': 'blue'})


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class ClueRuleTests(TestCase):
    def setUp(self):
        self.room, self.host, self.token, self.entries = create_room_with_players(4, language='en')
        self.session = start_room(self.room, self.host)
        self.players = {entry[0].pk: entry[0] for entry in self.entries}
        self.red_spy = GamePlayer.objects.get(pk=self.host.pk)
        self.red_op = GamePlayer.objects.get(pk=self.entries[2][0].pk)
        self.blue_spy = next(p for p in self.players.values() if p.team == 'blue' and p.role == 'spymaster')
        self.blue_op = next(p for p in self.players.values() if p.team == 'blue' and p.role == 'operative')

    def test_only_current_team_spymaster_can_clue(self):
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.red_op, 'zzzzclue', 1)
        self.assertEqual(ctx.exception.code, 'spymaster_only')
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.blue_spy, 'zzzzclue', 1)
        self.assertEqual(ctx.exception.code, 'wrong_team')

    def test_clue_cannot_be_a_board_word(self):
        word = self.session.words.first().word
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.red_spy, word, 1)
        self.assertEqual(ctx.exception.code, 'clue_on_board')

    def test_clue_length_is_bounded(self):
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.red_spy, 'a' * 33, 1)
        self.assertEqual(ctx.exception.code, 'invalid_clue')

    def test_duplicate_clue_is_rejected(self):
        services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 1)
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.red_spy, 'river', 1)
        self.assertEqual(ctx.exception.code, 'clue_already_given')

    def test_zero_clue_toggle(self):
        with self.assertRaises(ApiError) as ctx:
            services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 0)
        self.assertEqual(ctx.exception.code, 'zero_clue_disabled')
        self.room.settings = dict(self.room.settings, allow_zero_clue=True)
        self.room.save(update_fields=['settings'])
        session = services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 0)
        self.assertEqual(session.max_guesses, 1)

    def test_extra_guess_setting_controls_limit(self):
        services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 2)
        self.assertLessEqual(GameSession.objects.get(pk=self.session.pk).max_guesses, 3)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class GuessRuleTests(TestCase):
    def setUp(self):
        self.room, self.host, self.token, self.entries = create_room_with_players(4, language='en')
        self.room.settings = dict(self.room.settings, allow_zero_clue=True)
        self.room.save(update_fields=['settings'])
        self.session = start_room(self.room, self.host)
        self.red_spy = GamePlayer.objects.get(pk=self.host.pk)
        self.red_op = GamePlayer.objects.get(pk=self.entries[2][0].pk)
        self.blue_op = GamePlayer.objects.get(pk=self.entries[3][0].pk)
        services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 2)

    def word(self, category):
        return self.session.words.filter(category=category, revealed=False).first()

    def refresh_session(self):
        self.session.refresh_from_db()
        return self.session

    def test_correct_guess_continues_turn_and_decrements(self):
        target = self.word('red')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertEqual(result['category'], 'red')
        self.assertFalse(result['turn_ended'])
        self.assertEqual(session.current_team, 'red')
        self.assertEqual(session.remaining_agents['red'], 8)
        self.assertEqual(session.guesses_used, 1)

    def test_spymaster_cannot_guess(self):
        target = self.word('red')
        with self.assertRaises(ApiError) as ctx:
            services.guess_word(self.room.room_code, self.red_spy, target.position)
        self.assertEqual(ctx.exception.code, 'operative_only')

    def test_wrong_team_cannot_guess(self):
        target = self.word('red')
        with self.assertRaises(ApiError) as ctx:
            services.guess_word(self.room.room_code, self.blue_op, target.position)
        self.assertEqual(ctx.exception.code, 'wrong_team')

    def test_neutral_guess_ends_turn(self):
        target = self.word('neutral')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertTrue(result['turn_ended'])
        self.assertEqual(session.current_team, 'blue')
        self.assertIsNone(session.clue_number)

    def test_opponent_guess_ends_turn_and_helps_opponent(self):
        target = self.word('blue')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertTrue(result['turn_ended'])
        self.assertEqual(session.current_team, 'blue')
        self.assertEqual(session.remaining_agents['blue'], 7)

    def test_opponent_final_agent_wins_for_opponent(self):
        GameSession.objects.filter(pk=self.session.pk).update(
            remaining_agents={'red': 9, 'blue': 1},
        )
        target = self.word('blue')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertTrue(result['game_ended'])
        self.assertEqual(session.winner, 'blue')
        self.assertEqual(session.end_reason, 'opponent_agents')

    def test_assassin_ends_game_for_opponent(self):
        target = self.word('assassin')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertTrue(result['game_ended'])
        self.assertEqual(session.winner, 'blue')
        self.assertEqual(session.end_reason, 'assassin')
        self.assertEqual(GameRoom.objects.get(pk=self.room.pk).status, 'FINISHED')

    def test_revealing_last_agent_wins(self):
        GameSession.objects.filter(pk=self.session.pk).update(
            remaining_agents={'red': 1, 'blue': 8},
        )
        self.session.refresh_from_db()
        target = self.word('red')
        result = services.guess_word(self.room.room_code, self.red_op, target.position)
        session = self.refresh_session()
        self.assertTrue(result['game_ended'])
        self.assertEqual(session.winner, 'red')
        self.assertEqual(session.remaining_agents['red'], 0)

    def test_guess_limit_ends_turn(self):
        services.end_turn(self.room.room_code, self.red_op)
        self.session.refresh_from_db()
        # Blue's turn; force it back to red with a fresh one-guess clue.
        GameSession.objects.filter(pk=self.session.pk).update(current_team='red')
        services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 0)
        first = self.word('red')
        services.guess_word(self.room.room_code, self.red_op, first.position)
        session = self.refresh_session()
        self.assertEqual(session.current_team, 'blue')
        self.assertIsNone(session.clue_number)

    def test_voluntary_end_turn(self):
        services.end_turn(self.room.room_code, self.red_op)
        session = self.refresh_session()
        self.assertEqual(session.current_team, 'blue')
        self.assertEqual(session.current_turn, 2)

    def test_already_revealed_word_rejected(self):
        target = self.word('red')
        services.guess_word(self.room.room_code, self.red_op, target.position)
        with self.assertRaises(ApiError) as ctx:
            services.guess_word(self.room.room_code, self.red_op, target.position)
        self.assertEqual(ctx.exception.code, 'word_already_revealed')

    def test_game_over_is_idempotent(self):
        target = self.word('assassin')
        services.guess_word(self.room.room_code, self.red_op, target.position)
        room = GameRoom.objects.get(pk=self.room.pk)
        session = GameSession.objects.get(pk=self.session.pk)
        with transaction.atomic():
            changed = services._finish_game_locked(room, session, 'red', 'agents')
        self.assertFalse(changed)
        session.refresh_from_db()
        self.assertEqual(session.winner, 'blue')


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class TimerTests(TestCase):
    def test_timer_runs_before_clue(self):
        room, host, _token, _entries = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, timer_seconds=30)
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        self.assertIsNotNone(session.turn_deadline)
        GameSession.objects.filter(pk=session.pk).update(
            turn_deadline=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(services.expire_turn_if_needed(room.room_code))
        session.refresh_from_db()
        self.assertEqual(session.current_team, 'blue')
        self.assertIsNotNone(session.turn_deadline)

    def test_server_deadline_ends_turn(self):
        room, host, _token, entries = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, timer_seconds=30)
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        services.submit_clue(room.room_code, host, 'zzzzclue', 1)
        session.refresh_from_db()
        self.assertIsNotNone(session.turn_deadline)
        GameSession.objects.filter(pk=session.pk).update(
            turn_deadline=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(services.expire_turn_if_needed(room.room_code))
        session.refresh_from_db()
        self.assertEqual(session.current_team, 'blue')
        self.assertIsNotNone(session.turn_deadline)
        self.assertGreater(session.turn_deadline, timezone.now())

    def test_expire_is_idempotent(self):
        room, host, _token, _entries = create_room_with_players(4, language='en')
        room.settings = dict(room.settings, timer_seconds=30)
        room.save(update_fields=['settings'])
        session = start_room(room, host)
        services.submit_clue(room.room_code, host, 'zzzzclue', 1)
        GameSession.objects.filter(pk=session.pk).update(
            turn_deadline=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(services.expire_turn_if_needed(room.room_code))
        self.assertFalse(services.expire_turn_if_needed(room.room_code))


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class SerializationSecurityTests(TestCase):
    def setUp(self):
        self.room, self.host, self.token, self.entries = create_room_with_players(4, language='en')
        self.session = start_room(self.room, self.host)
        self.red_spy = GamePlayer.objects.get(pk=self.host.pk)
        self.red_op = GamePlayer.objects.get(pk=self.entries[2][0].pk)
        self.blue_op = GamePlayer.objects.get(pk=self.entries[3][0].pk)

    def test_operative_never_receives_unrevealed_categories(self):
        state = services.serialize_state(self.room, self.red_op)
        self.assertEqual(len(state['session']['board']), 25)
        for card in state['session']['board']:
            self.assertFalse(card['revealed'])
            self.assertIsNone(card['category'])
        payload = json.dumps(state)
        for label in ('"category": "red"', '"category": "blue"', '"category": "assassin"', '"category": "neutral"'):
            self.assertNotIn(label, payload)

    def test_spymaster_receives_full_secret_map(self):
        state = services.serialize_state(self.room, self.red_spy)
        categories = [card['category'] for card in state['session']['board']]
        self.assertEqual(Counter(categories)['red'], 9)
        self.assertEqual(Counter(categories)['blue'], 8)
        self.assertEqual(Counter(categories)['neutral'], 7)
        self.assertEqual(Counter(categories)['assassin'], 1)

    def test_finished_game_reveals_full_board_to_everyone(self):
        assassin = self.session.words.get(category='assassin')
        services.submit_clue(self.room.room_code, self.red_spy, 'zzzzclue', 1)
        services.guess_word(self.room.room_code, self.red_op, assassin.position)
        self.room.refresh_from_db()
        state = services.serialize_state(self.room, self.blue_op)
        self.assertTrue(all(card['category'] for card in state['session']['board']))
        self.assertEqual(state['session']['winner'], 'blue')

    def test_token_hash_is_never_serialized(self):
        state = services.serialize_state(self.room, self.red_op)
        self.assertNotIn('session_token', json.dumps(state))
        self.assertNotIn('session_token_hash', json.dumps(state))


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class MembershipTests(TestCase):
    def test_eleventh_player_rejected(self):
        room, host, _token, _players = create_room_with_players(10, language='en')
        with self.assertRaises(ApiError) as ctx:
            services.join_room(room.room_code, 'Eleventh')
        self.assertEqual(ctx.exception.code, 'room_full')

    def test_duplicate_identity_rejected(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        with self.assertRaises(ApiError) as ctx:
            services.join_room(room.room_code, ' player 1 ')
        self.assertEqual(ctx.exception.code, 'name_taken')

    def test_reconnect_with_token_is_idempotent(self):
        room, host, host_token, _players = create_room_with_players(4, language='en')
        same_room, same_player, token, rejoined = services.join_room(
            room.room_code, 'Host', host_token,
        )
        self.assertTrue(rejoined)
        self.assertEqual(same_player.pk, host.pk)
        self.assertEqual(token, host_token)
        self.assertEqual(same_room.players.count(), 4)

    def test_invalid_token_does_not_create_player(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        with self.assertRaises(ApiError):
            services.join_room(room.room_code, 'Someone', 'not-a-real-token')

    def test_host_transfer_on_leave(self):
        room, host, _token, players = create_room_with_players(4, language='en')
        services.leave_room(room.room_code, host)
        room.refresh_from_db()
        self.assertIsNotNone(room.host_id)
        self.assertNotEqual(room.host_id, host.pk)

    def test_spymaster_leave_abandons_game(self):
        room, host, _token, players = create_room_with_players(4, language='en')
        session = start_room(room, host)
        services.leave_room(room.room_code, host)
        room.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(room.status, 'ABANDONED')
        self.assertEqual(session.end_reason, 'spymaster_left')

    def test_last_operative_leave_abandons_game(self):
        room, host, _token, players = create_room_with_players(4, language='en')
        session = start_room(room, host)
        red_operative = players[2][0]
        self.assertEqual(red_operative.role, 'operative')
        services.leave_room(room.room_code, red_operative)
        room.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(room.status, 'ABANDONED')
        self.assertEqual(session.end_reason, 'operative_left')

    def test_new_game_returns_to_lobby(self):
        room, host, _token, _players = create_room_with_players(4, language='en')
        session = start_room(room, host)
        assassin = session.words.get(category='assassin')
        red_op = GamePlayer.objects.get(pk=_players[2][0].pk)
        services.submit_clue(room.room_code, host, 'zzzzclue', 1)
        services.guess_word(room.room_code, red_op, assassin.position)
        room.refresh_from_db()
        services.new_game(room.room_code, host)
        room.refresh_from_db()
        self.assertEqual(room.status, 'WAITING')
        self.assertIsNone(room.current_session_id)
