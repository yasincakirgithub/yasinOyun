import uuid

from django.db import models


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('IN_PROGRESS', 'Devam ediyor'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=10, unique=True)
    mode = models.CharField(max_length=24, default='three_cushion')
    target = models.PositiveIntegerField(default=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    # Oyunun otoritatif durumu: topların konumu, skorlar, sıra, faul bilgisi...
    state = models.JSONField(default=dict, blank=True)
    winner_seat = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Bilardo {self.room_code} ({self.mode})"


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    player_identifier = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=30, blank=True, default='')
    seat = models.PositiveSmallIntegerField(default=0)
    cue = models.CharField(max_length=20, default='klasik')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['seat', 'joined_at']
        unique_together = ('game_room', 'seat')

    def __str__(self):
        return f"{self.name or 'Oyuncu'} ({self.seat}) - {self.game_room.room_code}"


class Shot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='shots')
    player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='shots')
    angle = models.FloatField(default=0)
    power = models.FloatField(default=0)
    spin_x = models.FloatField(default=0)
    spin_y = models.FloatField(default=0)
    pocketed = models.JSONField(default=list, blank=True)
    foul = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.player} - güç {self.power:.2f}"
