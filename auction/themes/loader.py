"""Theme data loader and registry."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from django.conf import settings

THEME_DIR = Path(__file__).parent / 'data'

# Theme metadata registry
THEME_METADATA = {
    'lotr': {
        'id': 'lotr',
        'name': 'The Lord of the Rings',
        'description': 'Characters from J.R.R. Tolkien\'s Middle-earth',
        'cover_image': '/static/auction/themes/lotr/cover.webp',
        'character_count': 25,
        'accent': '#d4a843',
        'accent_2': '#6b4a1f',
        'icon': '🗡️',
    },
    'marvel': {
        'id': 'marvel',
        'name': 'Marvel Universe',
        'description': 'Superheroes and villains from Marvel Comics',
        'cover_image': '/static/auction/themes/marvel/cover.webp',
        'character_count': 30,
        'accent': '#ef4444',
        'accent_2': '#3b82f6',
        'icon': '🦸',
    },
    'dc': {
        'id': 'dc',
        'name': 'DC Universe',
        'description': 'Iconic heroes and villains from DC Comics',
        'cover_image': '/static/auction/themes/dc/cover.webp',
        'character_count': 28,
        'accent': '#3b82f6',
        'accent_2': '#facc15',
        'icon': '🦇',
    },
    'harry_potter': {
        'id': 'harry_potter',
        'name': 'Harry Potter',
        'description': 'Wizards, witches, and magical beings from the Wizarding World',
        'cover_image': '/static/auction/themes/harry_potter/cover.webp',
        'character_count': 25,
        'accent': '#a855f7',
        'accent_2': '#f59e0b',
        'icon': '⚡',
    },
    'game_of_thrones': {
        'id': 'game_of_thrones',
        'name': 'Game of Thrones',
        'description': 'Characters from George R.R. Martin\'s A Song of Ice and Fire',
        'cover_image': '/static/auction/themes/game_of_thrones/cover.webp',
        'character_count': 25,
        'accent': '#94a3b8',
        'accent_2': '#7f1d1d',
        'icon': '🐺',
    },
    'naruto': {
        'id': 'naruto',
        'name': 'Naruto',
        'description': 'Shinobi from the Hidden Leaf and beyond',
        'cover_image': '/static/auction/themes/naruto/cover.webp',
        'character_count': 28,
        'accent': '#f97316',
        'accent_2': '#2563eb',
        'icon': '🍥',
    },
    'dragon_ball': {
        'id': 'dragon_ball',
        'name': 'Dragon Ball',
        'description': 'Warriors from Akira Toriyama\'s Dragon Ball universe',
        'cover_image': '/static/auction/themes/dragon_ball/cover.webp',
        'character_count': 25,
        'accent': '#f59e0b',
        'accent_2': '#ef4444',
        'icon': '🐉',
    },
    'one_piece': {
        'id': 'one_piece',
        'name': 'One Piece',
        'description': 'Pirates and marines from Eiichiro Oda\'s One Piece',
        'cover_image': '/static/auction/themes/one_piece/cover.webp',
        'character_count': 28,
        'accent': '#ef4444',
        'accent_2': '#facc15',
        'icon': '🏴‍☠️',
    },
    'star_wars': {
        'id': 'star_wars',
        'name': 'Star Wars',
        'description': 'Jedi, Sith, and characters from a galaxy far, far away',
        'cover_image': '/static/auction/themes/star_wars/cover.webp',
        'character_count': 25,
        'accent': '#facc15',
        'accent_2': '#3b82f6',
        'icon': '⭐',
    },
    'video_games': {
        'id': 'video_games',
        'name': 'Video Game Characters',
        'description': 'Iconic protagonists from gaming history',
        'cover_image': '/static/auction/themes/video_games/cover.webp',
        'character_count': 25,
        'accent': '#22d3ee',
        'accent_2': '#a855f7',
        'icon': '🎮',
    },
    'kurtlar_vadisi': {
        'id': 'kurtlar_vadisi',
        'name': 'Kurtlar Vadisi',
        'description': 'Efsanevi Türk dizisi Kurtlar Vadisi karakterleri',
        'cover_image': '/static/auction/themes/kurtlar_vadisi/cover.webp',
        'character_count': 25,
        'accent': '#dc2626',
        'accent_2': '#fbbf24',
        'icon': '🐺',
    },
}


def _load_theme_data(theme_id: str) -> dict[str, Any] | None:
    """Load character data for a specific theme."""
    data_file = THEME_DIR / f'{theme_id}.json'
    if not data_file.exists():
        return None
    try:
        with data_file.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def get_all_themes() -> list[dict[str, Any]]:
    """Get all available themes with metadata."""
    themes = []
    for theme_id, meta in THEME_METADATA.items():
        data = _load_theme_data(theme_id)
        if data and 'characters' in data:
            meta_copy = meta.copy()
            meta_copy['character_count'] = len(data['characters'])
            themes.append(meta_copy)
    return themes


def get_theme(theme_id: str) -> dict[str, Any] | None:
    """Get theme metadata by ID."""
    if theme_id not in THEME_METADATA:
        return None
    data = _load_theme_data(theme_id)
    if not data:
        return None
    meta = THEME_METADATA[theme_id].copy()
    meta['character_count'] = len(data.get('characters', []))
    meta['synergies'] = data.get('synergies', [])
    return meta


def get_theme_characters(theme_id: str, count: int | None = None) -> list[dict[str, Any]]:
    """Get characters for a theme, optionally limited to a specific count."""
    data = _load_theme_data(theme_id)
    if not data or 'characters' not in data:
        return []
    characters = data['characters']
    if count is not None and count < len(characters):
        return random.sample(characters, count)
    return characters


def get_character_by_id(theme_id: str, character_id: str) -> dict[str, Any] | None:
    """Get a specific character by ID."""
    data = _load_theme_data(theme_id)
    if not data or 'characters' not in data:
        return None
    for char in data['characters']:
        if char.get('id') == character_id:
            return char
    return None


def get_theme_synergies(theme_id: str) -> list[dict[str, Any]]:
    """Get synergy definitions for a theme."""
    data = _load_theme_data(theme_id)
    if not data:
        return []
    return data.get('synergies', [])


def calculate_synergy_bonus(theme_id: str, owned_character_ids: set[str]) -> tuple[int, list[dict]]:
    """Calculate total synergy bonus for a player's collection.

    ``fixed`` bonuses add a flat amount. ``percentage`` bonuses are a
    percentage of the player's raw character power (the same base power the
    engine adds to the score), never of the bonus itself, so the result stays
    deterministic and does not compound.
    """
    synergies = get_theme_synergies(theme_id)
    characters = {char.get('id'): char for char in get_theme_characters(theme_id)}
    base_power = sum(
        characters[char_id].get('power', 0)
        for char_id in owned_character_ids
        if char_id in characters
    )

    total_bonus = 0
    active_synergies = []

    for synergy in synergies:
        required = set(synergy.get('required_character_ids', []))
        if required.issubset(owned_character_ids):
            bonus = synergy.get('bonus', {})
            bonus_type = bonus.get('type', 'fixed')
            if bonus_type == 'percentage':
                bonus_value = round(base_power * bonus.get('value', 0) / 100)
            else:
                bonus_type = 'fixed'
                bonus_value = bonus.get('value', 0)
            total_bonus += bonus_value
            active_synergies.append({
                'id': synergy['id'],
                'name': synergy['name'],
                'description': synergy.get('description', ''),
                'bonus': bonus_value,
                'bonus_type': bonus_type,
            })

    return total_bonus, active_synergies