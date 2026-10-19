import uuid

from django.db import models

# Board is square: 9x9. Columns are labelled A-I, rows 1-9 in the UI.
GRID_SIZE = 9

# Fleet used by both players. Total = 18 occupied cells out of 81.
FLEET = [
    {'id': 'amiral', 'name': 'Amiral', 'size': 5},
    {'id': 'kruvazor', 'name': 'Kruvazör', 'size': 4},
    {'id': 'denizalti', 'name': 'Denizaltı', 'size': 3},
    {'id': 'hucumbot1', 'name': 'Hücumbot 1', 'size': 2},
    {'id': 'hucumbot2', 'name': 'Hücumbot 2', 'size': 2},
    {'id': 'kesif1', 'name': 'Keşif 1', 'size': 1},
    {'id': 'kesif2', 'name': 'Keşif 2', 'size': 1},
]


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('PLACING', 'Gemiler yerleştiriliyor'),
        ('IN_PROGRESS', 'Devam ediyor'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=10, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_turn = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_turn_in',
    )
    winner = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wins',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Room {self.room_code}"


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    player_identifier = models.CharField(max_length=100, unique=True)
    # List of ships: [{'id', 'name', 'size', 'cells': [[row, col], ...]}, ...]
    ships = models.JSONField(default=list, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    ready = models.BooleanField(default=False)

    def __str__(self):
        return f"Player {self.player_identifier} in {self.game_room.room_code}"


class Shot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='shots')
    shooter = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='shots_fired')
    row = models.IntegerField()
    col = models.IntegerField()
    hit = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        mark = 'vuruş' if self.hit else 'ıska'
        return f"{self.shooter} -> ({self.row}, {self.col}) {mark}"
