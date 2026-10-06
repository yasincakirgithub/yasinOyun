import uuid

import chess
from django.db import models


def initial_fen():
    """Starting position as a FEN string (the game's authoritative state)."""
    return chess.STARTING_FEN


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('IN_PROGRESS', 'Devam ediyor'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=10, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    # Current position in FEN notation. All move validation is done against it.
    fen = models.CharField(max_length=100, default=initial_fen)
    winner = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wins',
    )
    # PGN-style result: '1-0', '0-1' or '1/2-1/2'.
    result = models.CharField(max_length=10, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Room {self.room_code}"


class GamePlayer(models.Model):
    COLOR_CHOICES = [
        ('w', 'Beyaz'),
        ('b', 'Siyah'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    player_identifier = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=1, choices=COLOR_CHOICES)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('game_room', 'color')

    def __str__(self):
        return f"Player {self.player_identifier} ({self.get_color_display()}) in {self.game_room.room_code}"


class Move(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='moves')
    player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='moves')
    uci = models.CharField(max_length=5)
    san = models.CharField(max_length=12)
    fen_after = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.player.color}:{self.san}"
