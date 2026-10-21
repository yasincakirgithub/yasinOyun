from django.core.management.base import BaseCommand
from django.utils import timezone

from codenames.models import GameRoom


class Command(BaseCommand):
    help = 'Delete expired Codenames rooms and all related data.'

    def handle(self, *args, **options):
        now = timezone.now()
        queryset = GameRoom.objects.filter(expires_at__isnull=False, expires_at__lt=now)
        count = queryset.count()
        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {count} expired Codenames room(s).'))
