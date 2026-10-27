"""Challenge generation, progress, and joint-feasibility tests."""

from __future__ import annotations

import random

from django.test import SimpleTestCase

from fcmanager.challenges import (
    _candidate_groups,
    _fallback,
    _make,
    _resolve_conflicts,
    build_challenges,
    challenge_progress,
    squad_feasible,
    two_squads_feasible,
)
from fcmanager.data import build_market
from fcmanager.tests.helpers import make_player, synthetic_market


def challenge(ctype: str, target, params: dict | None = None) -> dict:
    return _make(ctype, target, params or {}, f'{ctype} {target}', '⭐', 'quality')


class ChallengeProgressTests(SimpleTestCase):
    def test_identity_counts(self):
        players = [
            make_player(1, 'A', 'ST', nationality='Spain', league='La Liga'),
            make_player(2, 'B', 'ST', nationality='Spain', league='La Liga'),
            make_player(3, 'C', 'ST', nationality='Brazil', league='Série A'),
        ]
        nation = challenge_progress(challenge('nationality_min', 2, {'nationality': 'Spain'}), players)
        self.assertEqual(nation['current'], 2)
        self.assertTrue(nation['satisfied'])
        self.assertEqual(nation['detail'], '2/2')

        league = challenge_progress(challenge('league_min', 3, {'league': 'La Liga'}), players)
        self.assertEqual(league['current'], 2)
        self.assertFalse(league['satisfied'])

    def test_age_and_overall_limits(self):
        players = [
            make_player(1, 'Young', 'ST', age=20, overall=86),
            make_player(2, 'Mid', 'ST', age=24, overall=84),
            make_player(3, 'Old', 'ST', age=31, overall=80),
        ]
        self.assertEqual(challenge_progress(challenge('age_under', 3, {'age': 25}), players)['current'], 2)
        self.assertEqual(challenge_progress(challenge('age_over', 2, {'age': 30}), players)['current'], 1)
        self.assertEqual(challenge_progress(challenge('overall_min', 2, {'overall': 85}), players)['current'], 1)
        self.assertEqual(challenge_progress(challenge('overall_min', 2, {'overall': 85}), players)['detail'], '1/2')

    def test_goalkeeper_challenge_uses_best_keeper(self):
        players = [
            make_player(1, 'Keeper', 'GK', overall=84),
            make_player(2, 'Backup', 'GK', overall=78),
            make_player(3, 'Striker', 'ST', overall=90),
        ]
        met = challenge_progress(challenge('gk_overall_min', 1, {'overall': 80}), players)
        self.assertEqual(met['current'], 84)
        self.assertEqual(met['detail'], '84/80')
        self.assertTrue(met['satisfied'])
        unmet = challenge_progress(challenge('gk_overall_min', 1, {'overall': 85}), players)
        self.assertFalse(unmet['satisfied'])
        self.assertEqual(unmet['detail'], '84/85')

    def test_attribute_challenges(self):
        players = [
            make_player(1, 'Fast', 'ST', pace=90, passing=86, defending=84),
            make_player(2, 'Technical', 'ST', pace=70, passing=90, defending=70),
        ]
        self.assertEqual(challenge_progress(challenge('pace_min', 2, {'value': 85}), players)['current'], 1)
        self.assertEqual(challenge_progress(challenge('passing_min', 2, {'value': 85}), players)['current'], 2)
        self.assertEqual(challenge_progress(challenge('defending_min', 2, {'value': 80}), players)['current'], 1)

    def test_physical_and_foot_challenges(self):
        players = [
            make_player(1, 'Left', 'ST', preferred_foot='Left', height_cm=191, skill_moves=4),
            make_player(2, 'Right', 'ST', preferred_foot='Right', height_cm=180, skill_moves=5),
        ]
        self.assertEqual(challenge_progress(challenge('left_foot', 2), players)['current'], 1)
        self.assertEqual(challenge_progress(challenge('height_min', 2, {'height': 190}), players)['current'], 1)
        self.assertEqual(challenge_progress(challenge('skill_moves_min', 2, {'moves': 4}), players)['current'], 2)

    def test_distinct_shape_challenges(self):
        players = [
            make_player(1, 'A', 'ST', nationality='Spain', league='La Liga', club='A'),
            make_player(2, 'B', 'ST', nationality='Spain', league='Premier League', club='B'),
            make_player(3, 'C', 'ST', nationality='Brazil', league='La Liga', club='A'),
        ]
        self.assertEqual(challenge_progress(challenge('distinct_leagues', 3), players)['current'], 2)
        self.assertEqual(challenge_progress(challenge('distinct_nations', 2), players)['current'], 2)
        self.assertEqual(challenge_progress(challenge('club_min', 2), players)['current'], 2)

    def test_max_challenges_are_upper_bounds(self):
        players = [
            make_player(1, 'A', 'ST', nationality='Spain', club='A'),
            make_player(2, 'B', 'ST', nationality='Spain', club='A'),
            make_player(3, 'C', 'ST', nationality='Spain', club='B'),
        ]
        club_max = challenge_progress(challenge('club_max', 2), players)
        self.assertEqual(club_max['current'], 2)
        self.assertTrue(club_max['satisfied'])
        self.assertEqual(club_max['detail'], '2 / 2 sınır')

        nation_max = challenge_progress(challenge('nation_max', 2), players)
        self.assertEqual(nation_max['current'], 3)
        self.assertFalse(nation_max['satisfied'])

        # An empty squad must not accidentally satisfy an upper bound.
        self.assertFalse(challenge_progress(challenge('club_max', 2), [])['satisfied'])

    def test_age_average_challenge(self):
        players = [
            make_player(1, 'A', 'ST', age=24),
            make_player(2, 'B', 'ST', age=26),
        ]
        average = challenge_progress(challenge('age_avg_max', 27.5, {'max_age': 27.5}), players)
        self.assertEqual(average['current'], 25.0)
        self.assertTrue(average['satisfied'])
        self.assertEqual(average['detail'], '25,0 / 27,5')

        older = [make_player(3, 'C', 'ST', age=31), make_player(4, 'D', 'ST', age=32)]
        self.assertFalse(challenge_progress(challenge('age_avg_max', 27.5), older)['satisfied'])


class ChallengeGenerationTests(SimpleTestCase):
    def test_conflicting_nation_cap_is_replaced(self):
        selected = [
            _make('nationality_min', 3, {'nationality': 'Spain'}, '3 İspanyol', '🌍', 'identity'),
            _make('nation_max', 2, {}, 'Aynı ülkeden en fazla 2', '🔗', 'shape'),
            _make('distinct_nations', 5, {}, '5 farklı ülke', '🌐', 'shape'),
        ]
        resolved = _resolve_conflicts(selected, _candidate_groups(synthetic_market()), random.Random(1))
        self.assertNotIn('nation_max', {item['type'] for item in resolved})
        self.assertIn('nationality_min', {item['type'] for item in resolved})

    def test_duplicate_types_are_removed(self):
        selected = [
            _make('age_under', 3, {'age': 25}, 'U25', '🎂', 'age'),
            _make('age_under', 4, {'age': 23}, 'U23', '🎂', 'age'),
            _make('overall_min', 2, {'overall': 85}, '85+', '⭐', 'quality'),
        ]
        resolved = _resolve_conflicts(selected, {'shape': []}, random.Random(1))
        self.assertEqual([item['type'] for item in resolved], ['age_under', 'overall_min'])

    def test_generated_challenges_are_jointly_feasible(self):
        # Regression: a set can be fine for one manager but impossible for the
        # room when both squads share a single unique-player market.
        for seed in range(6):
            rng = random.Random(seed)
            market = build_market(rng)
            budget = 1_000_000_000
            challenges = build_challenges(market, budget, rng)

            self.assertGreaterEqual(len(challenges), 3, f'seed {seed}')
            self.assertLessEqual(len(challenges), 4, f'seed {seed}')
            self.assertEqual(len(challenges), len({item['type'] for item in challenges}))
            for item in challenges:
                self.assertTrue(item['label'])
                self.assertTrue(item['icon'])
                self.assertIn(item['type'], {
                    'nationality_min', 'league_min', 'age_under', 'age_over',
                    'overall_min', 'gk_overall_min', 'pace_min', 'passing_min',
                    'defending_min', 'left_foot', 'height_min', 'skill_moves_min',
                    'distinct_leagues', 'distinct_nations', 'club_min', 'club_max',
                    'nation_max', 'age_avg_max',
                })

            self.assertTrue(
                two_squads_feasible(
                    market, budget, challenges, random.Random(seed + 1000), attempts=300,
                ),
                f'seed {seed} produced a jointly infeasible set',
            )

    def test_three_argentines_cannot_satisfy_two_squads(self):
        challenge_set = [
            _make(
                'nationality_min', 2, {'nationality': 'Argentina'},
                'En az 2 Arjantinli oyuncu', '🌍', 'identity',
            ),
        ]
        three = synthetic_market(extra_slots=('gk', 'cb1', 'cb2'))
        four = synthetic_market(extra_slots=('gk', 'cb1', 'cb2', 'cm1'))

        # One manager can satisfy the challenge from a three-player pool...
        self.assertTrue(squad_feasible(three, 2_000_000_000, challenge_set, random.Random(7), attempts=120))
        # ...but the second manager cannot, because each player is unique.
        self.assertFalse(two_squads_feasible(three, 2_000_000_000, challenge_set, random.Random(7), attempts=120))
        self.assertTrue(two_squads_feasible(four, 2_000_000_000, challenge_set, random.Random(7), attempts=160))

    def test_fallback_returns_a_playable_set(self):
        rng = random.Random(3)
        market = build_market(rng)
        fallback = _fallback(market, 1_000_000_000, rng)
        self.assertTrue(fallback)
        self.assertTrue(two_squads_feasible(market, 1_000_000_000, fallback, random.Random(0), attempts=2000))
