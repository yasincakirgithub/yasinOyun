"""Character catalogue for the Guess Who game.

The catalogue is derived from the PNG files that live in the project-level
``characters/`` directory. Files are expected to be named like
``01_Mia.png`` where the numeric prefix is the id and the rest is the name.
"""

from pathlib import Path

from django.conf import settings

CHARACTERS_DIR = Path(settings.BASE_DIR) / 'characters'


def _pretty_name(raw):
    raw = raw.replace('_', ' ').strip()
    if not raw:
        return raw
    return raw[0].upper() + raw[1:]


def _load_characters():
    characters = []
    if not CHARACTERS_DIR.is_dir():
        return characters

    for path in sorted(CHARACTERS_DIR.glob('*.png')):
        stem = path.stem
        prefix, sep, name = stem.partition('_')
        characters.append(
            {
                'id': stem,
                'name': _pretty_name(name) if sep else _pretty_name(stem),
                'image': f'characters/{path.name}',
            }
        )
    return characters


CHARACTERS = _load_characters()
CHARACTER_MAP = {character['id']: character for character in CHARACTERS}
CHARACTER_IDS = set(CHARACTER_MAP)
