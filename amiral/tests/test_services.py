from django.test import TestCase

from ..models import FLEET, GRID_SIZE
from ..services import (
    all_sunk,
    is_hit,
    is_sunk,
    normalize_ships,
    random_board,
    remaining_ships,
    sunk_ship_name,
)


def board_a():
    return [
        {'id': 'amiral', 'cells': [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4]]},
        {'id': 'kruvazor', 'cells': [[1, 0], [1, 1], [1, 2], [1, 3]]},
        {'id': 'denizalti1', 'cells': [[2, 0], [2, 1], [2, 2]]},
        {'id': 'denizalti2', 'cells': [[2, 3], [2, 4], [2, 5]]},
        {'id': 'hucumbot1', 'cells': [[3, 0], [3, 1]]},
        {'id': 'hucumbot2', 'cells': [[3, 2], [3, 3]]},
        {'id': 'hucumbot3', 'cells': [[3, 4], [3, 5]]},
        {'id': 'kesif1', 'cells': [[4, 0]]},
        {'id': 'kesif2', 'cells': [[4, 1]]},
        {'id': 'kesif3', 'cells': [[4, 2]]},
    ]


class NormalizeShipsTest(TestCase):
    def test_valid_board(self):
        normalized, error = normalize_ships(board_a())
        self.assertIsNone(error)
        self.assertEqual(len(normalized), len(FLEET))
        self.assertEqual({s['id'] for s in normalized}, {s['id'] for s in FLEET})

    def test_random_board_is_valid(self):
        for _ in range(20):
            normalized, error = normalize_ships(random_board())
            self.assertIsNone(error)
            self.assertEqual(len(normalized), len(FLEET))

    def test_missing_ship(self):
        ships = board_a()[:-1]
        normalized, error = normalize_ships(ships)
        self.assertIsNone(normalized)
        self.assertIsNotNone(error)

    def test_wrong_size(self):
        ships = board_a()
        ships[0]['cells'] = ships[0]['cells'][:4]
        normalized, error = normalize_ships(ships)
        self.assertIsNotNone(error)

    def test_overlap(self):
        ships = board_a()
        ships[1]['cells'] = [[0, 0], [0, 1], [0, 2], [0, 3]]
        normalized, error = normalize_ships(ships)
        self.assertIsNotNone(error)

    def test_out_of_bounds(self):
        ships = board_a()
        ships[0]['cells'] = [[0, 10], [0, 11], [0, 12], [0, 13], [0, 14]]
        normalized, error = normalize_ships(ships)
        self.assertIsNotNone(error)

    def test_diagonal(self):
        ships = board_a()
        ships[0]['cells'] = [[0, 0], [1, 1], [2, 2], [3, 3], [4, 4]]
        normalized, error = normalize_ships(ships)
        self.assertIsNotNone(error)

    def test_unknown_ship_id(self):
        ships = board_a()
        ships[0]['id'] = 'yok'
        normalized, error = normalize_ships(ships)
        self.assertIsNotNone(error)


class RulesTest(TestCase):
    def setUp(self):
        self.ships, _ = normalize_ships(board_a())

    def test_is_hit(self):
        self.assertTrue(is_hit(self.ships, 0, 0))
        self.assertTrue(is_hit(self.ships, 3, 5))
        self.assertTrue(is_hit(self.ships, 4, 2))
        self.assertFalse(is_hit(self.ships, 13, 13))

    def test_is_sunk(self):
        amiral = next(s for s in self.ships if s['id'] == 'amiral')
        self.assertFalse(is_sunk(amiral, [(0, 0), (0, 1)]))
        self.assertTrue(
            is_sunk(amiral, [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)])
        )

    def test_sunk_ship_name(self):
        shots = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        self.assertEqual(sunk_ship_name(self.ships, shots, 0, 4), 'Amiral')
        # A partially hit ship is not reported as sunk.
        self.assertIsNone(sunk_ship_name(self.ships, [(0, 0)], 0, 0))

    def test_all_sunk_and_remaining(self):
        all_cells = [tuple(c) for s in self.ships for c in s['cells']]
        self.assertEqual(remaining_ships(self.ships, []), len(FLEET))
        self.assertFalse(all_sunk(self.ships, all_cells[:-1]))
        self.assertTrue(all_sunk(self.ships, all_cells))
        self.assertEqual(remaining_ships(self.ships, all_cells), 0)

    def test_fleet_shape(self):
        sizes = sorted(s['size'] for s in FLEET)
        self.assertEqual(sizes, [1, 1, 1, 2, 2, 2, 3, 3, 4, 5])
        self.assertEqual(GRID_SIZE, 14)
