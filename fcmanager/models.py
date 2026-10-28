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


class Player(models.Model):
    """One row of the FC26 dataset, kept in the database.

    The dataset is imported once with ``manage.py import_fc26`` (or lazily on
    the first draft) and every market search is served from these columns, so
    the game no longer needs to hold the whole CSV in memory per room.
    """

    player_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=120, db_index=True)
    full_name = models.CharField(max_length=200, blank=True, default='')
    positions = models.JSONField(default=list, blank=True)
    primary_position = models.CharField(max_length=8, db_index=True)
    bucket = models.CharField(max_length=8, db_index=True)

    overall = models.PositiveSmallIntegerField(db_index=True)
    potential = models.PositiveSmallIntegerField(default=0)
    value_eur = models.BigIntegerField(default=0, db_index=True)
    wage_eur = models.BigIntegerField(default=0)
    age = models.PositiveSmallIntegerField(db_index=True)

    nationality = models.CharField(max_length=60, blank=True, default='', db_index=True)
    league = models.CharField(max_length=120, blank=True, default='', db_index=True)
    club = models.CharField(max_length=120, blank=True, default='', db_index=True)

    height_cm = models.PositiveSmallIntegerField(default=0)
    weight_kg = models.PositiveSmallIntegerField(default=0)
    preferred_foot = models.CharField(max_length=20, blank=True, default='')
    weak_foot = models.PositiveSmallIntegerField(default=0)
    skill_moves = models.PositiveSmallIntegerField(default=0)
    international_reputation = models.PositiveSmallIntegerField(default=0)

    pace = models.PositiveSmallIntegerField(default=0)
    shooting = models.PositiveSmallIntegerField(default=0)
    passing = models.PositiveSmallIntegerField(default=0)
    dribbling = models.PositiveSmallIntegerField(default=0)
    defending = models.PositiveSmallIntegerField(default=0)
    physic = models.PositiveSmallIntegerField(default=0)

    gk_diving = models.PositiveSmallIntegerField(default=0)
    gk_handling = models.PositiveSmallIntegerField(default=0)
    gk_kicking = models.PositiveSmallIntegerField(default=0)
    gk_positioning = models.PositiveSmallIntegerField(default=0)
    gk_reflexes = models.PositiveSmallIntegerField(default=0)
    gk_speed = models.PositiveSmallIntegerField(default=0)

    mentality_penalties = models.PositiveSmallIntegerField(default=0)
    image_url = models.CharField(max_length=300, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-overall', 'player_id']
        indexes = [
            models.Index(fields=['bucket', '-overall']),
            models.Index(fields=['bucket', 'value_eur']),
        ]

    def __str__(self):
        return f'{self.name} ({self.overall})'

    def to_dict(self) -> dict:
        """Return the compact player payload the rest of the game expects."""
        from .data import photo_url

        return {
            'player_id': self.player_id,
            'name': self.name,
            'full_name': self.full_name or self.name,
            'positions': list(self.positions or ()),
            'primary_position': self.primary_position,
            'bucket': self.bucket,
            'overall': self.overall,
            'potential': self.potential,
            'value_eur': self.value_eur,
            'wage_eur': self.wage_eur,
            'age': self.age,
            'nationality': self.nationality,
            'league': self.league,
            'club': self.club,
            'height_cm': self.height_cm,
            'weight_kg': self.weight_kg,
            'preferred_foot': self.preferred_foot,
            'weak_foot': self.weak_foot,
            'skill_moves': self.skill_moves,
            'international_reputation': self.international_reputation,
            'pace': self.pace,
            'shooting': self.shooting,
            'passing': self.passing,
            'dribbling': self.dribbling,
            'defending': self.defending,
            'physic': self.physic,
            'gk_diving': self.gk_diving,
            'gk_handling': self.gk_handling,
            'gk_kicking': self.gk_kicking,
            'gk_positioning': self.gk_positioning,
            'gk_reflexes': self.gk_reflexes,
            'gk_speed': self.gk_speed,
            'mentality_penalties': self.mentality_penalties,
            'image_url': photo_url(self.player_id, self.image_url),
        }


class MarketPlayer(models.Model):
    """A draft pick inside one room.

    Rows are created only when a manager drafts a player; the searchable pool
    itself lives in :class:`Player`.
    """

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
