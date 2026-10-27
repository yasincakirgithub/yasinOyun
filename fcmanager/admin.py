from django.contrib import admin

from .models import MarketPlayer, Match, Participant, Room


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0
    readonly_fields = ('id', 'joined_at', 'last_seen_at')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'host', 'budget_eur', 'budget_try', 'created_at', 'expires_at')
    list_filter = ('status', 'created_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [ParticipantInline]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'room', 'side', 'connected', 'locked', 'left', 'joined_at')
    list_filter = ('side', 'connected', 'locked', 'left')
    search_fields = ('display_name', 'room__room_code')
    readonly_fields = ('id', 'session_token_hash', 'joined_at', 'last_seen_at')


@admin.register(MarketPlayer)
class MarketPlayerAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'room', 'player_id', 'picked_by', 'picked_slot')
    list_filter = ('room__status',)
    search_fields = ('room__room_code', 'data__name')
    readonly_fields = ('data',)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('room', 'home', 'away', 'home_score', 'away_score', 'home_pen', 'away_pen', 'winner_side', 'started_at')
    list_filter = ('winner_side', 'started_at')
    search_fields = ('room__room_code',)
    readonly_fields = ('id', 'events', 'stats', 'home_snapshot', 'away_snapshot', 'mvp', 'started_at', 'finished_at')
