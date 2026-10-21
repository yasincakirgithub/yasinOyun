import uuid

from django.db import models
from django.utils import timezone

MAX_PLAYERS = 10
MIN_PLAYERS = 4
BOARD_SIZE = 25
TIMER_CHOICES = (0, 30, 60, 90, 120)
LANGUAGE_CHOICES = (('tr', 'Türkçe'), ('en', 'English'))
STARTING_TEAM_CHOICES = (('random', 'Rastgele'), ('red', 'Kırmızı'), ('blue', 'Mavi'))
TEAM_CHOICES = (('red', 'Kırmızı Takım'), ('blue', 'Mavi Takım'))
ROLE_CHOICES = (('spymaster', 'Spymaster'), ('operative', 'Operative'))
CATEGORY_CHOICES = (
    ('red', 'Kırmızı ajan'),
    ('blue', 'Mavi ajan'),
    ('neutral', 'Nötr'),
    ('assassin', 'Suikastçı'),
)


def default_settings():
    return {
        'timer_seconds': 0,
        'starting_team': 'random',
        'min_players': MIN_PLAYERS,
        'allow_zero_clue': False,
        'extra_guess': True,
    }


class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('STARTING', 'Tahta hazırlanıyor'),
        ('IN_PROGRESS', 'Devam ediyor'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=12, unique=True, db_index=True)
    host = models.ForeignKey(
        'GamePlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hosted_rooms',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    max_players = models.PositiveSmallIntegerField(default=MAX_PLAYERS)
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='tr')
    settings = models.JSONField(default=default_settings, blank=True)
    current_session = models.ForeignKey(
        'GameSession',
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
        return f'Codenames {self.room_code}'

    def active_players(self):
        return self.players.filter(left=False)


class GamePlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='players')
    display_name = models.CharField(max_length=30)
    name_key = models.CharField(max_length=60)
    session_token_hash = models.CharField(max_length=64, unique=True)
    team = models.CharField(max_length=10, choices=TEAM_CHOICES, default='red')
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default='operative')
    connected = models.BooleanField(default=False)
    connection_count = models.PositiveSmallIntegerField(default=0)
    left = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'name_key'],
                name='codenames_unique_player_name_per_room',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} ({self.team}/{self.role})'


class GameSession(models.Model):
    STATUS_CHOICES = [
        ('IN_PROGRESS', 'Devam ediyor'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]
    WINNER_CHOICES = TEAM_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='sessions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IN_PROGRESS')
    starting_team = models.CharField(max_length=10, choices=TEAM_CHOICES)
    current_team = models.CharField(max_length=10, choices=TEAM_CHOICES)
    current_turn = models.PositiveIntegerField(default=1)
    clue_word = models.CharField(max_length=32, blank=True, default='')
    clue_number = models.PositiveSmallIntegerField(null=True, blank=True)
    guesses_used = models.PositiveSmallIntegerField(default=0)
    max_guesses = models.PositiveSmallIntegerField(default=1)
    remaining_agents = models.JSONField(default=dict)
    winner = models.CharField(max_length=10, choices=WINNER_CHOICES, blank=True, default='')
    end_reason = models.CharField(max_length=40, blank=True, default='')
    turn_deadline = models.DateTimeField(null=True, blank=True)
    turn_duration = models.PositiveSmallIntegerField(default=0)
    word_source = models.CharField(max_length=20, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.room.room_code} / {self.started_at:%Y-%m-%d %H:%M}'


class GameWord(models.Model):
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name='words')
    word = models.CharField(max_length=40)
    normalized = models.CharField(max_length=40)
    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES)
    position = models.PositiveSmallIntegerField()
    revealed = models.BooleanField(default=False)
    revealed_by = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revealed_words',
    )
    revealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'position'],
                name='codenames_unique_word_position',
            ),
            models.UniqueConstraint(
                fields=['session', 'normalized'],
                name='codenames_unique_word_per_game',
            ),
        ]

    def __str__(self):
        return f'{self.position}: {self.word} ({self.category})'


class ChatMessage(models.Model):
    KIND_CHOICES = [('chat', 'Sohbet'), ('system', 'Sistem')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='messages')
    player = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
    )
    display_name = models.CharField(max_length=30, blank=True, default='')
    team = models.CharField(max_length=10, blank=True, default='')
    role = models.CharField(max_length=12, blank=True, default='')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='chat')
    text = models.CharField(max_length=400)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.display_name}: {self.text[:40]}'


class GameEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='events')
    session = models.ForeignKey(
        GameSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='events',
    )
    player = models.ForeignKey(
        GamePlayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
    )
    event_type = models.CharField(max_length=40)
    event_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.event_type} ({self.room.room_code})'
