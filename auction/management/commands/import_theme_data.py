"""Management command to import theme data from JSON files to database."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from auction.models import Theme, Character, Synergy
from auction.themes.loader import THEME_METADATA


THEME_DIR = Path(__file__).resolve().parent.parent.parent / 'themes' / 'data'


class Command(BaseCommand):
    help = 'Import theme data from JSON files to database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--theme',
            type=str,
            help='Import only a specific theme (e.g., marvel, dc)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before importing',
        )

    def handle(self, *args, **options):
        theme_id = options.get('theme')
        clear = options.get('clear')

        if clear:
            self.stdout.write('Clearing existing theme data...')
            Synergy.objects.all().delete()
            Character.objects.all().delete()
            Theme.objects.all().delete()

        themes_to_import = [theme_id] if theme_id else list(THEME_METADATA.keys())

        for t_id in themes_to_import:
            if t_id not in THEME_METADATA:
                self.stdout.write(self.style.WARNING(f'Theme "{t_id}" not found in metadata, skipping'))
                continue

            self.import_theme(t_id)

        self.stdout.write(self.style.SUCCESS('Theme data import completed!'))

    def import_theme(self, theme_id: str):
        """Import a single theme from JSON file."""
        meta = THEME_METADATA[theme_id]
        data_file = THEME_DIR / f'{theme_id}.json'

        if not data_file.exists():
            self.stdout.write(self.style.WARNING(f'Data file not found for theme "{theme_id}", skipping'))
            return

        try:
            with data_file.open('r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            self.stdout.write(self.style.ERROR(f'Failed to load {data_file}: {exc}'))
            return

        with transaction.atomic():
            # Create or update Theme
            theme, created = Theme.objects.update_or_create(
                id=theme_id,
                defaults={
                    'name': meta['name'],
                    'description': meta.get('description', ''),
                    'cover_image': meta.get('cover_image', ''),
                    'accent': meta.get('accent', ''),
                    'accent_2': meta.get('accent_2', ''),
                    'icon': meta.get('icon', ''),
                    'character_count': len(data.get('characters', [])),
                }
            )

            action = 'Created' if created else 'Updated'
            self.stdout.write(f'  {action} theme: {theme.name}')

            # Import characters
            characters_data = data.get('characters', [])
            for char_data in characters_data:
                Character.objects.update_or_create(
                    id=char_data['id'],
                    theme=theme,
                    defaults={
                        'name': char_data['name'],
                        'universe': char_data.get('universe', ''),
                        'power': char_data.get('power', 0),
                        'image': char_data.get('image', ''),
                        'description': char_data.get('description', ''),
                    }
                )

            self.stdout.write(f'  Imported {len(characters_data)} characters')

            # Import synergies
            synergies_data = data.get('synergies', [])
            for synergy_data in synergies_data:
                bonus = synergy_data.get('bonus', {})
                Synergy.objects.update_or_create(
                    id=synergy_data['id'],
                    theme=theme,
                    defaults={
                        'name': synergy_data['name'],
                        'description': synergy_data.get('description', ''),
                        'bonus_type': bonus.get('type', 'fixed'),
                        'bonus_value': bonus.get('value', 0),
                        'required_character_ids': synergy_data.get('required_character_ids', []),
                    }
                )

            self.stdout.write(f'  Imported {len(synergies_data)} synergies')