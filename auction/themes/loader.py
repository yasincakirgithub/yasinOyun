"""Theme data loader and registry - now using database models."""

from __future__ import annotations

import random
from typing import Any

from django.core.cache import cache

from auction.models import Character, Synergy, Theme


# Theme metadata registry (kept as fallback/defaults)
THEME_METADATA = {
    'lotr': {
        'id': 'lotr',
        'name': 'The Lord of the Rings',
        'description': "Characters from J.R.R. Tolkien's Middle-earth",
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
        'description': "Characters from George R.R. Martin's A Song of Ice and Fire",
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
        'description': "Warriors from Akira Toriyama's Dragon Ball universe",
        'cover_image': '/static/auction/themes/dragon_ball/cover.webp',
        'character_count': 25,
        'accent': '#f59e0b',
        'accent_2': '#ef4444',
        'icon': '🐉',
    },
    'one_piece': {
        'id': 'one_piece',
        'name': 'One Piece',
        'description': "Pirates and marines from Eiichiro Oda's One Piece",
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
    'attack_on_titan': {
        'id': 'attack_on_titan',
        'name': 'Attack on Titan',
        'description': 'Soldiers and Titans from Hajime Isayama\'s Attack on Titan',
        'cover_image': '/static/auction/themes/attack_on_titan/cover.webp',
        'character_count': 25,
        'accent': '#dc2626',
        'accent_2': '#1f2937',
        'icon': '🗡️',
    },
    'demon_slayer': {
        'id': 'demon_slayer',
        'name': 'Demon Slayer',
        'description': 'Demon Slayers and Demons from Kimetsu no Yaiba',
        'cover_image': '/static/auction/themes/demon_slayer/cover.webp',
        'character_count': 25,
        'accent': '#f97316',
        'accent_2': '#7c2d12',
        'icon': '🌸',
    },
    'my_hero_academia': {
        'id': 'my_hero_academia',
        'name': 'My Hero Academia',
        'description': 'Heroes and Villains from Kohei Horikoshi\'s MHA',
        'cover_image': '/static/auction/themes/my_hero_academia/cover.webp',
        'character_count': 28,
        'accent': '#3b82f6',
        'accent_2': '#ef4444',
        'icon': '⚡',
    },
    'jujutsu_kaisen': {
        'id': 'jujutsu_kaisen',
        'name': 'Jujutsu Kaisen',
        'description': 'Sorcerers and Curses from Gege Akutami\'s JJK',
        'cover_image': '/static/auction/themes/jujutsu_kaisen/cover.webp',
        'character_count': 25,
        'accent': '#84cc16',
        'accent_2': '#1e1e1e',
        'icon': '👁️',
    },
    'cyberpunk': {
        'id': 'cyberpunk',
        'name': 'Cyberpunk 2077',
        'description': 'Edgerunners and Corpos from Night City',
        'cover_image': '/static/auction/themes/cyberpunk/cover.webp',
        'character_count': 25,
        'accent': '#ec4899',
        'accent_2': '#06b6d4',
        'icon': '🌆',
    },
    'elden_ring': {
        'id': 'elden_ring',
        'name': 'Elden Ring',
        'description': 'Demigods and Tarnished from the Lands Between',
        'cover_image': '/static/auction/themes/elden_ring/cover.webp',
        'character_count': 25,
        'accent': '#fbbf24',
        'accent_2': '#7c2d12',
        'icon': '💍',
    },
    'super_lig': {
        'id': 'super_lig',
        'name': 'Türkiye Süper Lig',
        'description': 'Türk futbolunun efsanevi yıldızları ve güncel crackler',
        'cover_image': '/static/auction/themes/super_lig/cover.webp',
        'character_count': 28,
        'accent': '#e31e24',
        'accent_2': '#ffd700',
        'icon': '⚽',
    },
    'turk_influencers': {
        'id': 'turk_influencers',
        'name': 'Türk İnternet Fenomenleri',
        'description': 'Türkiye\'nin en popüler sosyal medya fenomenleri',
        'cover_image': '/static/auction/themes/turk_influencers/cover.webp',
        'character_count': 25,
        'accent': '#ff6b35',
        'accent_2': '#f7b801',
        'icon': '📱',
    },
    'turk_youtubers': {
        'id': 'turk_youtubers',
        'name': 'Türk YouTuber\'ları',
        'description': 'Türkiye\'nin en çok izlenen YouTube içerik üreticileri',
        'cover_image': '/static/auction/themes/turk_youtubers/cover.webp',
        'character_count': 28,
        'accent': '#ff0000',
        'accent_2': '#ffffff',
        'icon': '▶️',
    },
}


def _get_theme_from_db(theme_id: str) -> Theme | None:
    """Get theme from database with caching."""
    cache_key = f'theme:{theme_id}'
    theme = cache.get(cache_key)
    if theme is not None:
        return theme
    try:
        theme = Theme.objects.filter(id=theme_id, is_active=True).first()
        if theme:
            cache.set(cache_key, theme, 3600)  # Cache for 1 hour
        return theme
    except Exception:
        return None


def _get_characters_from_db(theme_id: str) -> list[Character]:
    """Get characters for a theme from database with caching."""
    cache_key = f'theme_characters:{theme_id}'
    characters = cache.get(cache_key)
    if characters is not None:
        return characters
    try:
        characters = list(Character.objects.filter(theme_id=theme_id).order_by('name'))
        cache.set(cache_key, characters, 3600)
        return characters
    except Exception:
        return []


def _get_synergies_from_db(theme_id: str) -> list[Synergy]:
    """Get synergies for a theme from database with caching."""
    cache_key = f'theme_synergies:{theme_id}'
    synergies = cache.get(cache_key)
    if synergies is not None:
        return synergies
    try:
        synergies = list(Synergy.objects.filter(theme_id=theme_id).order_by('name'))
        cache.set(cache_key, synergies, 3600)
        return synergies
    except Exception:
        return []


def get_all_themes() -> list[dict[str, Any]]:
    """Get all available themes with metadata."""
    themes = []
    for theme_id, meta in THEME_METADATA.items():
        # Try to get from DB first
        db_theme = _get_theme_from_db(theme_id)
        if db_theme:
            meta_copy = {
                'id': db_theme.id,
                'name': db_theme.name,
                'description': db_theme.description,
                'cover_image': db_theme.cover_image,
                'accent': db_theme.accent,
                'accent_2': db_theme.accent_2,
                'icon': db_theme.icon,
                'character_count': db_theme.character_count,
            }
            themes.append(meta_copy)
        elif theme_id in THEME_METADATA:
            # Fallback to static metadata
            meta_copy = meta.copy()
            themes.append(meta_copy)
    return themes


def get_theme(theme_id: str) -> dict[str, Any] | None:
    """Get theme metadata by ID."""
    db_theme = _get_theme_from_db(theme_id)
    if db_theme:
        return {
            'id': db_theme.id,
            'name': db_theme.name,
            'description': db_theme.description,
            'cover_image': db_theme.cover_image,
            'accent': db_theme.accent,
            'accent_2': db_theme.accent_2,
            'icon': db_theme.icon,
            'character_count': db_theme.character_count,
            'synergies': [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description,
                    'bonus': {'type': s.bonus_type, 'value': s.bonus_value},
                    'required_character_ids': s.required_character_ids,
                }
                for s in _get_synergies_from_db(theme_id)
            ],
        }
    # Fallback to static metadata
    if theme_id not in THEME_METADATA:
        return None
    meta = THEME_METADATA[theme_id].copy()
    # Try to get synergies from DB
    db_synergies = _get_synergies_from_db(theme_id)
    if db_synergies:
        meta['synergies'] = [
            {
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'bonus': {'type': s.bonus_type, 'value': s.bonus_value},
                'required_character_ids': s.required_character_ids,
            }
            for s in db_synergies
        ]
    else:
        meta['synergies'] = []
    return meta


def get_theme_characters(theme_id: str, count: int | None = None) -> list[dict[str, Any]]:
    """Get characters for a theme, optionally limited to a specific count."""
    db_characters = _get_characters_from_db(theme_id)
    if not db_characters:
        return []
    characters = [
        {
            'id': c.id,
            'name': c.name,
            'universe': c.universe,
            'power': c.power,
            'image': c.image,
            'description': c.description,
        }
        for c in db_characters
    ]
    if count is not None and count < len(characters):
        return random.sample(characters, count)
    return characters


def get_character_by_id(theme_id: str, character_id: str) -> dict[str, Any] | None:
    """Get a specific character by ID."""
    db_characters = _get_characters_from_db(theme_id)
    for char in db_characters:
        if char.id == character_id:
            return {
                'id': char.id,
                'name': char.name,
                'universe': char.universe,
                'power': char.power,
                'image': char.image,
                'description': char.description,
            }
    return None


def get_theme_synergies(theme_id: str) -> list[dict[str, Any]]:
    """Get synergy definitions for a theme."""
    db_synergies = _get_synergies_from_db(theme_id)
    if not db_synergies:
        return []
    return [
        {
            'id': s.id,
            'name': s.name,
            'description': s.description,
            'bonus': {'type': s.bonus_type, 'value': s.bonus_value},
            'required_character_ids': s.required_character_ids,
        }
        for s in db_synergies
    ]


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