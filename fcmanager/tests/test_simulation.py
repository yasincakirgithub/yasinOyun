"""Match simulation tests: profiles, timeline consistency, and randomness."""

from __future__ import annotations

import random

from django.test import SimpleTestCase

from fcmanager.data import SLOTS
from fcmanager.simulation import compute_profile, simulate_match
from fcmanager.tests.helpers import make_player


def build_squad(overall: int, **overrides) -> dict:
    squad = {}
    for index, slot in enumerate(SLOTS):
        position = slot['accept'][0]
        values = {
            'overall': overall,
            'pace': overall,
            'shooting': overall,
            'passing': overall,
            'dribbling': overall,
            'defending': overall,
            'physic': overall,
            'gk_diving': overall,
            'gk_handling': overall,
            'gk_kicking': overall,
            'gk_positioning': overall,
            'gk_reflexes': overall,
            'gk_speed': overall,
        }
        values.update(overrides)
        squad[slot['key']] = make_player(
            1000 + index,
            f'{slot["key"].upper()} {overall}',
            position,
            **values,
        )
    return squad


def challenge(satisfied: bool) -> dict:
    return {'type': 'overall_min', 'target': 1, 'params': {}, 'satisfied': satisfied}


class ProfileTests(SimpleTestCase):
    def test_stronger_squad_has_higher_strength(self):
        strong = compute_profile(build_squad(90), [])
        weak = compute_profile(build_squad(68), [])
        self.assertGreater(strong['strength'], weak['strength'])
        self.assertGreater(strong['attack'], weak['attack'])
        self.assertGreater(strong['defense'], weak['defense'])
        self.assertEqual(strong['overall'], 90.0)
        self.assertEqual(weak['overall'], 68.0)

    def test_completed_challenges_add_strength(self):
        squad = build_squad(80)
        none = compute_profile(squad, [challenge(False), challenge(False)])
        one = compute_profile(squad, [challenge(True), challenge(False)])
        both = compute_profile(squad, [challenge(True), challenge(True)])
        self.assertAlmostEqual(one['strength'] - none['strength'], 3.75, places=1)
        self.assertAlmostEqual(both['strength'] - one['strength'], 3.75, places=1)
        self.assertEqual(none['unmet_challenges'], 2)
        self.assertEqual(both['completed_challenges'], 2)

    def test_home_advantage_is_applied(self):
        squad = build_squad(80)
        neutral = compute_profile(squad, [])
        home = compute_profile(squad, [], home_advantage=0.8)
        self.assertAlmostEqual(home['strength'] - neutral['strength'], 0.8, places=1)


class SimulationTests(SimpleTestCase):
    def setUp(self):
        self.home = build_squad(88)
        self.away = build_squad(78)

    def run_match(self, seed: int = 42, home=None, away=None):
        return simulate_match(
            home or self.home,
            away or self.away,
            [],
            [],
            'Home FC',
            'Away FC',
            rng=random.Random(seed),
        )

    def test_same_seed_produces_identical_match(self):
        first = self.run_match(7)
        second = self.run_match(7)
        self.assertEqual(first, second)
        self.assertNotEqual(first, self.run_match(8))

    def test_score_matches_goal_events(self):
        for seed in range(12):
            result = self.run_match(seed)
            goals = [event for event in result['events'] if event['type'] == 'goal']
            self.assertEqual(
                sum(1 for event in goals if event['side'] == 'home'),
                result['home_score'],
                f'seed {seed}',
            )
            self.assertEqual(
                sum(1 for event in goals if event['side'] == 'away'),
                result['away_score'],
                f'seed {seed}',
            )
            full = next(event for event in result['events'] if event['type'] == 'full')
            self.assertEqual(full['score'], [result['home_score'], result['away_score']])

    def test_timeline_is_busy_enough_for_a_two_minute_replay(self):
        for seed in range(6):
            result = self.run_match(seed)
            chances = [
                event for event in result['events']
                if event['phase'] == 'match' and event['type'] not in ('kickoff', 'half', 'full')
            ]
            self.assertGreaterEqual(len(chances), 20, f'seed {seed}')
            self.assertGreaterEqual(len(result['events']), 27, f'seed {seed}')

    def test_timeline_has_kickoff_half_full_and_is_ordered(self):
        result = self.run_match(3)
        events = result['events']
        self.assertEqual(events[0]['type'], 'kickoff')
        self.assertTrue(any(event['type'] == 'half' for event in events))
        self.assertTrue(any(event['type'] == 'full' for event in events))
        if result['home_pen'] is None:
            self.assertEqual(events[-1]['type'], 'full')
        else:
            self.assertEqual(events[-1]['phase'], 'penalties')
        minutes = [event['minute'] for event in events]
        self.assertEqual(minutes, sorted(minutes))
        for event in events:
            self.assertIn('score', event)
            self.assertIn('text', event)
            self.assertTrue(event['text'])

    def test_every_goal_is_followed_by_a_kickoff_for_the_conceding_side(self):
        for seed in range(12):
            events = self.run_match(seed)['events']
            for index, event in enumerate(events):
                if event['type'] != 'goal':
                    continue
                self.assertLess(index + 1, len(events), f'seed {seed}')
                restart = events[index + 1]
                self.assertEqual(restart['type'], 'kickoff', f'seed {seed}')
                self.assertEqual(restart['minute'], event['minute'], f'seed {seed}')
                conceding = 'away' if event['side'] == 'home' else 'home'
                self.assertEqual(restart['side'], conceding, f'seed {seed}')

    def test_full_time_stops_play_and_penalties_only_follow_it(self):
        for seed in range(40):
            result = self.run_match(seed)
            events = result['events']
            full_index = next(
                index for index, event in enumerate(events) if event['type'] == 'full'
            )
            after_full = events[full_index + 1:]
            self.assertTrue(
                all(event['phase'] == 'penalties' for event in after_full),
                f'seed {seed}',
            )
            if result['home_pen'] is None:
                self.assertEqual(full_index, len(events) - 1, f'seed {seed}')

    def test_non_draw_has_no_penalties(self):
        for seed in range(40):
            result = self.run_match(seed)
            if result['home_score'] == result['away_score']:
                continue
            self.assertIsNone(result['home_pen'])
            self.assertIsNone(result['away_pen'])
            expected = 'home' if result['home_score'] > result['away_score'] else 'away'
            self.assertEqual(result['winner_side'], expected)
            self.assertFalse(any(event['phase'] == 'penalties' for event in result['events']))
            return
        self.fail('No non-draw match found in 40 seeds')

    def test_draw_goes_to_penalties(self):
        for seed in range(120):
            result = self.run_match(seed)
            if result['home_score'] != result['away_score']:
                continue
            self.assertIsNotNone(result['home_pen'])
            self.assertIsNotNone(result['away_pen'])
            self.assertNotEqual(result['home_pen'], result['away_pen'])
            self.assertEqual(
                result['winner_side'],
                'home' if result['home_pen'] > result['away_pen'] else 'away',
            )
            penalties = [event for event in result['events'] if event['phase'] == 'penalties']
            self.assertTrue(penalties)
            self.assertTrue(all(event['minute'] == 91 for event in penalties))
            self.assertTrue(all(event['score'] == [result['home_score'], result['away_score']] for event in penalties))
            return
        self.fail('No draw found in 120 seeds')

    def test_stats_are_internally_consistent(self):
        for seed in range(10):
            result = self.run_match(seed)
            home = result['stats']['home']
            away = result['stats']['away']
            self.assertEqual(home['possession'] + away['possession'], 100)
            for side in (home, away):
                self.assertGreaterEqual(side['shots'], side['on_target'])
                self.assertGreaterEqual(side['on_target'], 0)
                self.assertGreaterEqual(side['xg'], 0.2)
                self.assertLessEqual(side['xg'], 4.3)
                self.assertGreaterEqual(side['pass_accuracy'], 60)
                self.assertLessEqual(side['pass_accuracy'], 94)
                self.assertGreaterEqual(side['yellow_cards'], 0)

    def test_mvp_and_top_players_come_from_the_squads(self):
        result = self.run_match(11)
        names = {player['name'] for player in self.home.values()} | {
            player['name'] for player in self.away.values()
        }
        self.assertIn(result['mvp']['name'], names)
        self.assertTrue(result['top_players'])
        ratings = [player['rating'] for player in result['top_players']]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        for player in result['top_players']:
            self.assertGreaterEqual(player['rating'], 5.2)
            self.assertLessEqual(player['rating'], 10.0)
            self.assertIn(player['side'], ('home', 'away'))
        self.assertIn('kazandı', result['summary'])

    def test_stronger_side_wins_more_often(self):
        strong = build_squad(90)
        weak = build_squad(70)
        wins = 0
        goal_difference = 0
        runs = 60
        for seed in range(runs):
            result = simulate_match(
                strong, weak, [], [], 'Strong', 'Weak', rng=random.Random(seed),
            )
            goal_difference += result['home_score'] - result['away_score']
            if result['winner_side'] == 'home':
                wins += 1
        self.assertGreater(wins, runs * 0.75, f'Strong side only won {wins}/{runs}')
        self.assertGreater(goal_difference / runs, 1.0)

    def test_bigger_rating_gap_means_higher_win_chance(self):
        def win_rate(home_overall: int, away_overall: int, runs: int = 80) -> float:
            wins = 0
            for seed in range(runs):
                result = simulate_match(
                    build_squad(home_overall), build_squad(away_overall),
                    [], [], 'Home', 'Away', rng=random.Random(seed),
                )
                if result['winner_side'] == 'home':
                    wins += 1
            return wins / runs

        big_gap = win_rate(90, 70)
        small_gap = win_rate(85, 75)
        even = win_rate(80, 80)
        self.assertGreater(big_gap, small_gap)
        self.assertGreater(small_gap, even)
        self.assertGreater(big_gap, 0.85)
        self.assertLess(even, 0.62)

    def test_completed_challenges_win_more_matches(self):
        plain = build_squad(78)
        rewarded = build_squad(78)
        completed = [challenge(True), challenge(True), challenge(True)]
        missing = [challenge(False), challenge(False), challenge(False)]
        wins = 0
        runs = 80
        for seed in range(runs):
            result = simulate_match(
                rewarded, plain, completed, missing,
                'Görevli', 'Düz', rng=random.Random(seed),
            )
            if result['winner_side'] == 'home':
                wins += 1
        self.assertGreater(wins, runs * 0.7, f'Challenge squad only won {wins}/{runs}')

    def test_empty_squads_do_not_score_without_events(self):
        result = simulate_match({}, {}, [], [], 'Empty A', 'Empty B', rng=random.Random(1))
        self.assertEqual(result['home_score'], 0)
        self.assertEqual(result['away_score'], 0)
        self.assertFalse(any(event['type'] == 'goal' for event in result['events']))
        self.assertIsNotNone(result['home_pen'])
        self.assertIsNotNone(result['away_pen'])
