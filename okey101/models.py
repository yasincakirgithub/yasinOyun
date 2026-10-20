import uuid

from django.db import models

MAX_PLAYERS = 4
MIN_PLAYERS = 4
DEFAULT_ROUNDS = 5
ROUND_CHOICES = (1, 3, 5, 7, 9, 11)


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('IN_PROGRESS', 'Devam ediyor'),
        ('ROUND_END', 'El bitti'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]
    MODE_CHOICES = [
        ('solo', 'Tekli'),
        ('pairs', 'Eşli'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=10, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='solo')
    creator_identifier = models.CharField(max_length=100, blank=True, default='')
    penalties_enabled = models.BooleanField(default=True)
    multipliers_enabled = models.BooleanField(default=True)

    # A round's hidden state. Tiles are JSON objects (see services.py).
    stock = models.JSONField(default=list, blank=True)
    discard_pile = models.JSONField(default=list, blank=True)
    indicator = models.JSONField(null=True, blank=True)
    okey = models.JSONField(null=True, blank=True)

    current_seat = models.PositiveSmallIntegerField(null=True, blank=True)
    turn_has_drawn = models.BooleanField(default=False)
    turn_taken_discard = models.BooleanField(default=False)
    turn_taken_tile_id = models.CharField(max_length=20, blank=True, default='')
    turn_start_opened = models.BooleanField(default=False)

    points_threshold = models.PositiveIntegerField(default=101)
    pairs_threshold = models.PositiveIntegerField(default=5)

    round_number = models.PositiveIntegerField(default=1)
    total_rounds = models.PositiveIntegerField(default=DEFAULT_ROUNDS)
    round_results = models.JSONField(default=list, blank=True)

    winner = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wins',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"101 Okey {self.room_code}"


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(
        GameRoom, on_delete=models.CASCADE, related_name='players'
    )
    player_identifier = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=30, blank=True, default='')
    seat = models.PositiveSmallIntegerField()

    hand = models.JSONField(default=list, blank=True)
    opened = models.BooleanField(default=False)
    route = models.CharField(max_length=10, blank=True, default='')  # points | pairs
    total_score = models.IntegerField(default=0)
    round_score = models.IntegerField(default=0)
    penalty = models.IntegerField(default=0)

    connected = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['seat']
        unique_together = ('game_room', 'seat')

    def __str__(self):
        return f"{self.name or self.player_identifier} (seat {self.seat})"


class TableMeld(models.Model):
    KIND_CHOICES = [
        ('run', 'Seri'),
        ('group', 'Grup'),
        ('pair', 'Çift'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(
        GameRoom, on_delete=models.CASCADE, related_name='melds'
    )
    owner = models.ForeignKey(
        GamePlayer, on_delete=models.CASCADE, related_name='melds'
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    tiles = models.JSONField(default=list, blank=True)
    score = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_kind_display()} ({self.score})"
