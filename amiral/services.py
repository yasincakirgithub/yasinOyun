"""Game rules for the two-player battleship game."""

import random

from .models import FLEET, GRID_SIZE


def fleet_sizes():
    """Map ship id -> size."""
    return {ship['id']: ship['size'] for ship in FLEET}


def fleet_names():
    return {ship['id']: ship['name'] for ship in FLEET}


def random_board():
    """Build a valid random board (list of ships with cells)."""
    ships = []
    occupied = set()
    for ship in FLEET:
        size = ship['size']
        placed = False
        for _ in range(500):
            horizontal = random.choice([True, False])
            if horizontal:
                row = random.randrange(GRID_SIZE)
                col = random.randrange(GRID_SIZE - size + 1)
                cells = [(row, col + i) for i in range(size)]
            else:
                row = random.randrange(GRID_SIZE - size + 1)
                col = random.randrange(GRID_SIZE)
                cells = [(row + i, col) for i in range(size)]

            if any(cell in occupied for cell in cells):
                continue

            occupied.update(cells)
            ships.append({
                'id': ship['id'],
                'name': ship['name'],
                'size': size,
                'cells': [[r, c] for r, c in cells],
            })
            placed = True
            break

        if not placed:
            # Extremely unlikely; start over to guarantee a valid board.
            return random_board()

    return ships


def normalize_ships(ships):
    """
    Validate a submitted board and return ``(normalized, error)``.

    Enforces: every ship of the fleet present exactly once, correct size,
    straight lines, inside the board and no overlapping cells.
    """
    sizes = fleet_sizes()
    names = fleet_names()

    if not isinstance(ships, list) or len(ships) != len(FLEET):
        return None, 'Gemi listesi geçersiz.'

    seen_ids = set()
    occupied = set()
    normalized = []

    for ship in ships:
        if not isinstance(ship, dict):
            return None, 'Gemi verisi geçersiz.'

        ship_id = ship.get('id')
        if ship_id not in sizes or ship_id in seen_ids:
            return None, 'Gemi kimliği geçersiz veya tekrarlı.'
        seen_ids.add(ship_id)

        size = sizes[ship_id]
        cells = ship.get('cells')
        if not isinstance(cells, list) or len(cells) != size:
            return None, f'{names[ship_id]} gemisinin boyutu yanlış.'

        norm_cells = []
        for cell in cells:
            if not isinstance(cell, (list, tuple)) or len(cell) != 2:
                return None, 'Hücre koordinatı geçersiz.'
            row, col = cell
            if not isinstance(row, int) or not isinstance(col, int):
                return None, 'Hücre koordinatı geçersiz.'
            if not (0 <= row < GRID_SIZE and 0 <= col < GRID_SIZE):
                return None, 'Gemi tahtanın dışına taşıyor.'
            if (row, col) in occupied:
                return None, 'Gemiler üst üste binemez.'
            occupied.add((row, col))
            norm_cells.append([row, col])

        rows = {row for row, _ in norm_cells}
        cols = {col for _, col in norm_cells}
        if len(rows) != 1 and len(cols) != 1:
            return None, 'Gemiler düz (yatay veya dikey) olmalı.'

        norm_cells.sort()
        normalized.append({
            'id': ship_id,
            'name': names[ship_id],
            'size': size,
            'cells': norm_cells,
        })

    if len(seen_ids) != len(FLEET):
        return None, 'Tüm gemiler yerleştirilmeli.'

    return normalized, None


def ship_cells(ship):
    return {(r, c) for r, c in ship.get('cells', [])}


def is_sunk(ship, shots):
    """Return True when every cell of ``ship`` has been shot at."""
    shot_cells = {(s[0], s[1]) for s in shots}
    return ship_cells(ship).issubset(shot_cells)


def all_sunk(ships, shots):
    return bool(ships) and all(is_sunk(ship, shots) for ship in ships)


def is_hit(ships, row, col):
    return any((row, col) in ship_cells(ship) for ship in ships)


def sunk_ship_name(ships, shots, row, col):
    """Return the name of the ship that became fully sunk by this shot, if any."""
    for ship in ships:
        if (row, col) in ship_cells(ship) and is_sunk(ship, shots):
            return ship['name']
    return None


def remaining_ships(ships, shots):
    return sum(1 for ship in ships if not is_sunk(ship, shots))
