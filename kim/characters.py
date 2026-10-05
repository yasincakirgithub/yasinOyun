"""Character catalogue for the Guess Who game.

The catalogue is derived from the image files that live in
``kim/static/kim/characters/``. Any number of images is supported; adding a new
file to that folder is enough to make it playable. Files may be named either
``Mia.png`` or ``01_Mia.png`` — an optional leading numeric prefix is ignored
when the display name is rendered.
"""

import re
from pathlib import Path

CHARACTERS_DIR = Path(__file__).resolve().parent / 'static' / 'kim' / 'characters'
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# Leading numeric prefixes such as "01_", "1-", "02 " are not part of the name.
_PREFIX_RE = re.compile(r'^\d+[\s_\-]+')


def _pretty_name(raw):
    name = _PREFIX_RE.sub('', raw).replace('_', ' ').replace('-', ' ').strip()
    return name or raw.strip()


def _natural_key(value):
    """Sort "2" before "10" and keep names in a stable, readable order."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', value)]


def _load_characters():
    characters = []
    if not CHARACTERS_DIR.is_dir():
        return characters

    files = [
        path
        for path in CHARACTERS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    for path in sorted(files, key=lambda p: _natural_key(p.stem)):
        stem = path.stem
        characters.append(
            {
                'id': stem,
                'name': _pretty_name(stem),
                'image': f'kim/characters/{path.name}',
            }
        )
    return characters


CHARACTERS = _load_characters()
CHARACTER_MAP = {character['id']: character for character in CHARACTERS}
CHARACTER_IDS = set(CHARACTER_MAP)
CHARACTER_COUNT = len(CHARACTERS)
