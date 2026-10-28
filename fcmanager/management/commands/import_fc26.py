"""Import the FC26 CSV dataset into the ``Player`` table."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from fcmanager.data import CSV_PATH, import_catalogue


class Command(BaseCommand):
    help = 'Load every FC26 player row into the database (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            dest='path',
            help=f'CSV file to import (default: {CSV_PATH})',
        )
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Delete existing catalogue rows first.',
        )

    def handle(self, *args, **options):
        path = Path(options['path'] or CSV_PATH).expanduser()
        if not path.exists():
            raise CommandError(f'Dataset not found: {path}')

        count = import_catalogue(path, replace=options['replace'])
        if not count:
            raise CommandError(f'No players were imported from {path}')

        self.stdout.write(self.style.SUCCESS(
            f'{count} FC26 players imported/updated from {path}',
        ))
