import uuid

from django.db import models
from django.utils import timezone


def default_squad():
    return {}


class Room(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('DRAFT', 'Kadro kuruluyor'),
        ('FINISHED', 'Maç oynandı'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=12, unique=True, db_index=True)
    host = models.ForeignKey(
        'Participant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hosted_rooms',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')

    # Draft economy. Values are stored as whole units; EUR is the canonical
    # currency because the FC26 dataset prices players in EUR.
    budget_eur = models.BigIntegerField(default=0)
    budget_try = models.BigIntegerField(default=0)

    # Shared challenge definitions generated at the start of a season.
    challenges = models.JSONField(default=list, blank=True)

    current_match = models.ForeignKey(
        'Match',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_in_rooms',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'FC Manager {self.room_code}'

    def active_players(self):
        return self.players.filter(left=False)


class Participant(models.Model):
    SIDE_CHOICES = [('home', 'Ev sahibi'), ('away', 'Deplasman')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    display_name = models.CharField(max_length=30)
    name_key = models.CharField(max_length=60)
    session_token_hash = models.CharField(max_length=64, unique=True)
    side = models.CharField(max_length=10, choices=SIDE_CHOICES, default='home')
    connected = models.BooleanField(default=False)
    connection_count = models.PositiveSmallIntegerField(default=0)
    left = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'name_key'],
                name='fcmanager_unique_player_name_per_room',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} ({self.side})'


class MarketPlayer(models.Model):
    """A frozen snapshot of one FC26 CSV row used by a single room."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='market')
    player_id = models.BigIntegerField()
    data = models.JSONField(default=dict)
    picked_by = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='picks',
    )
    picked_slot = models.CharField(max_length=12, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'player_id'],
                name='fcmanager_unique_market_player',
            ),
            models.UniqueConstraint(
                fields=['room', 'picked_by', 'picked_slot'],
                name='fcmanager_unique_slot_pick',
                condition=models.Q(picked_by__isnull=False),
            ),
        ]

    def __str__(self):
        return f'{self.data.get("name", self.player_id)} ({self.room.room_code})'


class Match(models.Model):
    STATUS_CHOICES = [('FINISHED', 'Bitti')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='matches')
    home = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='home_matches',
    )
    away = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='away_matches',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='FINISHED')

    home_score = models.PositiveSmallIntegerField(default=0)
    away_score = models.PositiveSmallIntegerField(default=0)
    home_pen = models.PositiveSmallIntegerField(null=True, blank=True)
    away_pen = models.PositiveSmallIntegerField(null=True, blank=True)
    winner_side = models.CharField(max_length=10, blank=True, default='')

    home_snapshot = models.JSONField(default=dict)
    away_snapshot = models.JSONField(default=dict)
    stats = models.JSONField(default=dict)
    events = models.JSONField(default=list)
    mvp = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.room.room_code} {self.home_score}-{self.away_score}'
