from django.db import models
from django.core.validators import RegexValidator
import uuid


def validate_four_digit_unique(value):
    """Validate that value is exactly 4 digits, all unique, and first digit not zero."""
    if not value.isdigit() or len(value) != 4:
        raise ValidationError('Must be exactly 4 digits.')
    if value[0] == '0':
        raise ValidationError('First digit cannot be zero.')
    if len(set(value)) != 4:
        raise ValidationError('All digits must be unique.')


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Waiting for players'),
        ('SETTING_NUMBERS', 'Setting secret numbers'),
        ('IN_PROGRESS', 'In progress'),
        ('FINISHED', 'Finished'),
        ('ABANDONED', 'Abandoned'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=10, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_turn = models.ForeignKey('GamePlayer', on_delete=models.SET_NULL, null=True, blank=True, related_name='current_turn_in')
    winner = models.ForeignKey('GamePlayer', on_delete=models.SET_NULL, null=True, blank=True, related_name='wins')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Room {self.room_code}"


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    # For anonymous players, we'll use a session-based identifier or just rely on WebSocket connection
    # In production, this could link to Django User or have a session_key field
    player_identifier = models.CharField(max_length=100, unique=True)  # Could be session key or UUID
    secret_number = models.CharField(max_length=4, validators=[validate_four_digit_unique])
    joined_at = models.DateTimeField(auto_now_add=True)
    ready = models.BooleanField(default=False)
    turn_order = models.IntegerField(null=True, blank=True)  # 1 or 2
    
    class Meta:
        unique_together = ('game_room', 'turn_order')
    
    def __str__(self):
        return f"Player {self.player_identifier} in {self.game_room.room_code}"


class Guess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='guesses')
    value = models.CharField(max_length=4, validators=[validate_four_digit_unique])
    result = models.CharField(max_length=4)  # e.g., "+--", "++++", ""
    created_at = models.DateTimeField(auto_now_add=True)
    turn_number = models.IntegerField()  # Which turn this guess was made in
    
    def __str__(self):
        return f"{self.game_player} guessed {self.value}: {self.result}"