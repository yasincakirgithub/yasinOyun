import uuid
from django.db import models
from django.utils import timezone


class AuctionRoom(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Oyuncu bekleniyor'),
        ('CONFIGURING', 'Ayarlar yapılıyor'),
        ('THEME_SELECT', 'Tema seçimi'),
        ('AUCTION', 'Açık artırma devam ediyor'),
        ('RESULTS', 'Sonuçlar'),
        ('FINISHED', 'Bitti'),
        ('ABANDONED', 'Terk edildi'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_code = models.CharField(max_length=12, unique=True, db_index=True)
    host = models.ForeignKey(
        'AuctionPlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hosted_rooms',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')

    # Game configuration
    theme_id = models.CharField(max_length=50, blank=True, default='')
    character_count = models.PositiveSmallIntegerField(default=10)
    starting_budget = models.PositiveIntegerField(default=2000)  # in cents ($20.00)
    starting_bid = models.PositiveIntegerField(default=100)  # in cents ($1.00)
    auction_duration = models.PositiveSmallIntegerField(default=20)  # seconds
    max_players = models.PositiveSmallIntegerField(default=8)
    extension_threshold = models.PositiveSmallIntegerField(default=3)  # seconds
    extension_duration = models.PositiveSmallIntegerField(default=5)  # seconds

    # Auction state
    current_character_index = models.PositiveSmallIntegerField(default=0)
    auction_deadline = models.DateTimeField(null=True, blank=True)
    current_highest_bid = models.PositiveIntegerField(default=0)
    current_highest_bidder = models.ForeignKey(
        'AuctionPlayer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_high_bids',
    )
    current_auction_extensions = models.PositiveSmallIntegerField(default=0)

    # Character pool for this game
    auction_characters = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Auction {self.room_code}'

    def active_players(self):
        return self.players.filter(left=False)

    def get_auction_characters(self):
        """Return the list of character IDs for this auction."""
        return self.auction_characters or []

    def get_current_character_id(self):
        """Get the current character being auctioned."""
        chars = self.get_auction_characters()
        if self.current_character_index < len(chars):
            return chars[self.current_character_index]
        return None


class AuctionPlayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(AuctionRoom, on_delete=models.CASCADE, related_name='players')
    display_name = models.CharField(max_length=30)
    name_key = models.CharField(max_length=60)
    session_token_hash = models.CharField(max_length=64, unique=True)
    connected = models.BooleanField(default=False)
    connection_count = models.PositiveSmallIntegerField(default=0)
    left = models.BooleanField(default=False)
    ready = models.BooleanField(default=False)

    # Game state
    budget = models.PositiveIntegerField(default=0)  # remaining budget in cents
    owned_characters = models.JSONField(default=list, blank=True)  # list of character IDs
    total_power = models.PositiveIntegerField(default=0)
    synergy_bonus = models.PositiveIntegerField(default=0)

    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'name_key'],
                name='auction_unique_player_name_per_room',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} (${self.budget / 100:.2f})'


class AuctionBid(models.Model):
    """Record of all bids for audit trail."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(AuctionRoom, on_delete=models.CASCADE, related_name='bids')
    player = models.ForeignKey(AuctionPlayer, on_delete=models.CASCADE, related_name='bids')
    character_id = models.CharField(max_length=100)
    amount = models.PositiveIntegerField()  # in cents
    created_at = models.DateTimeField(auto_now_add=True)
    is_winning = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class AuctionResult(models.Model):
    """Final results of a completed auction game."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.OneToOneField(AuctionRoom, on_delete=models.CASCADE, related_name='result')

    # Final rankings
    rankings = models.JSONField(default=list)  # list of {player_id, name, total_power, char_count, budget, rank}

    # Character ownership
    character_ownership = models.JSONField(default=dict)  # {character_id: player_id}

    # Synergies
    activated_synergies = models.JSONField(default=dict)  # {player_id: [synergy_data]}

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Result for {self.room.room_code}'