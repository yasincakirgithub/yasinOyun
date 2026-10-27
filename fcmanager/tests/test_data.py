"""Tests for the FC26 CSV loader and the per-room market snapshot."""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from fcmanager import data
from fcmanager.data import (
    KNOWN_POSITIONS,
    MIN_BUCKETS,
    REQUIRED_LEAGUES,
    REQUIRED_NATIONS,
    SLOTS,
    build_market,
    format_league,
    format_nation,
    load_players,
    slot_accepts,
)


class DatasetTests(SimpleTestCase):
    def test_dataset_loads_clean_unique_rows(self):
        players = load_players()
        self.assertGreater(len(players), 1000)
        self.assertEqual(len(players), len({player['player_id'] for player in players}))

        for player in players[:200]:
            self.assertTrue(player['player_id'])
            self.assertTrue(player['name'])
            self.assertTrue(player['positions'])
            self.assertTrue(set(player['positions']) <= KNOWN_POSITIONS)
            self.assertGreaterEqual(player['overall'], 60)
            self.assertLessEqual(player['overall'], 99)
            self.assertGreater(player['value_eur'], 0)
            self.assertGreaterEqual(player['age'], 15)
            self.assertLessEqual(player['age'], 45)
            self.assertIn(player['primary_position'], player['positions'])
            self.assertIn(player['bucket'], data.DESIRED_BUCKETS)

    def test_missing_dataset_makes_market_unavailable(self):
        data.load_players.cache_clear()
        try:
            with mock.patch.object(data, 'CSV_PATH', Path('/definitely/not/fc26.csv')):
                data.load_players.cache_clear()
                with self.assertRaises(ValueError):
                    build_market(random.Random(0))
        finally:
            data.load_players.cache_clear()

    def test_slot_compatibility(self):
        self.assertTrue(slot_accepts('gk', ['GK']))
        self.assertFalse(slot_accepts('gk', ['CB']))
        self.assertTrue(slot_accepts('lb', ['LWB']))
        self.assertTrue(slot_accepts('cm1', ['CAM']))
        self.assertTrue(slot_accepts('st', ['CF']))
        self.assertTrue(slot_accepts('rw', ['RM']))
        self.assertFalse(slot_accepts('st', ['GK']))
        self.assertFalse(slot_accepts('unknown', ['ST']))
        self.assertFalse(slot_accepts('st', []))

    def test_localized_labels(self):
        self.assertEqual(format_nation('Spain'), 'İspanyol')
        self.assertEqual(format_nation('Türkiye'), 'Türk')
        self.assertEqual(format_nation('Atlantis'), 'Atlantis')
        self.assertEqual(format_league('Liga Profesional de Fútbol'), 'Arjantin Ligi')
        self.assertEqual(format_league('Süper Lig'), 'Süper Lig')
        self.assertEqual(format_league('Unknown League'), 'Unknown League')


class MarketTests(SimpleTestCase):
    def test_market_is_balanced_unique_and_playable(self):
        dataset_ids = {player['player_id'] for player in load_players()}
        for seed in range(3):
            market = build_market(random.Random(seed))
            self.assertEqual(len(market), 80)
            self.assertEqual(len(market), len({player['player_id'] for player in market}))
            self.assertTrue({player['player_id'] for player in market} <= dataset_ids)

            counts = Counter(player['bucket'] for player in market)
            for bucket, minimum in MIN_BUCKETS.items():
                self.assertGreaterEqual(counts[bucket], minimum, f'{bucket} seed {seed}')

            for league in REQUIRED_LEAGUES:
                self.assertGreaterEqual(
                    sum(1 for player in market if player['league'] == league), 2,
                    f'{league} seed {seed}',
                )
            for nation in REQUIRED_NATIONS:
                self.assertGreaterEqual(
                    sum(1 for player in market if player['nationality'] == nation), 2,
                    f'{nation} seed {seed}',
                )

            self.assertGreaterEqual(sum(1 for player in market if player['value_eur'] <= 25_000_000), 14)
            self.assertGreaterEqual(sum(1 for player in market if player['value_eur'] >= 60_000_000), 10)

            # Two managers draft from the same snapshot, so every slot needs at
            # least two valid candidates.
            for slot in SLOTS:
                self.assertGreaterEqual(
                    sum(1 for player in market if slot_accepts(slot['key'], player['positions'])),
                    2,
                    f'{slot["key"]} seed {seed}',
                )

    def test_market_order_is_shuffled(self):
        first = build_market(random.Random(1))
        second = build_market(random.Random(2))
        self.assertNotEqual(
            [player['player_id'] for player in first],
            [player['player_id'] for player in second],
        )
