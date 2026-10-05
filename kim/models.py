import uuid

from django.db import models


def validate_four_digit_unique(value):
    """Legacy validator kept so the initial migration keeps loading."""
    from django.core.exceptions import ValidationError

    if not value.isdigit() or len(value) != 4:
        raise ValidationError('Must be exactly 4 digits.')
    if value[0] == '0':
        raise ValidationError('First digit cannot be zero.')
    if len(set(value)) != 4:
        raise ValidationError('All digits must be unique.')


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Waiting for players'),
        ('CHOOSING', 'Choosing characters'),
        ('IN_PROGRESS', 'In progress'),
        ('FINISHED', 'Finished'),
        ('ABANDONED', 'Abandoned'),
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
    question_owner = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_questions',
    )
    awaiting_answer = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Room {self.room_code}"


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    player_identifier = models.CharField(max_length=100, unique=True)
    character_id = models.CharField(max_length=64, blank=True, default='')
    eliminated = models.JSONField(default=list, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    ready = models.BooleanField(default=False)

    def __str__(self):
        return f"Player {self.player_identifier} in {self.game_room.room_code}"


class ChatMessage(models.Model):
    KIND_CHOICES = [
        ('chat', 'Chat'),
        ('question', 'Question'),
        ('answer', 'Answer'),
        ('system', 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='messages')
    game_player = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='chat')
    text = models.TextField()
    answer = models.CharField(max_length=3, blank=True, default='')
    reply_to = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"[{self.kind}] {self.text[:40]} ({self.game_room.room_code})"


class Accusation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game_player = models.ForeignKey(GamePlayer, on_delete=models.CASCADE, related_name='accusations')
    character_id = models.CharField(max_length=64)
    correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.game_player} -> {self.character_id} ({'correct' if self.correct else 'wrong'})"
