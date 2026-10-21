from django.contrib import admin

from .models import (
    ChatMessage,
    GameEvent,
    GamePlayer,
    GameRoom,
    GameSession,
    GameWord,
)


class GamePlayerInline(admin.TabularInline):
    model = GamePlayer
    extra = 0
    readonly_fields = ('id', 'joined_at', 'last_seen_at')


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'language', 'host', 'created_at', 'expires_at')
    list_filter = ('status', 'language', 'created_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [GamePlayerInline]


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'room', 'team', 'role', 'connected', 'left', 'joined_at')
    list_filter = ('team', 'role', 'connected', 'left')
    search_fields = ('display_name', 'room__room_code')
    readonly_fields = ('id', 'session_token_hash', 'joined_at', 'last_seen_at')


class GameWordInline(admin.TabularInline):
    model = GameWord
    extra = 0
    readonly_fields = ('position', 'word', 'category', 'revealed')


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('room', 'status', 'starting_team', 'current_team', 'winner', 'started_at')
    list_filter = ('status', 'starting_team', 'current_team', 'winner')
    search_fields = ('room__room_code',)
    readonly_fields = ('id', 'started_at', 'ended_at')
    inlines = [GameWordInline]


@admin.register(GameWord)
class GameWordAdmin(admin.ModelAdmin):
    list_display = ('session', 'position', 'word', 'category', 'revealed')
    list_filter = ('category', 'revealed')
    search_fields = ('word', 'session__room__room_code')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'display_name', 'kind', 'created_at')
    list_filter = ('kind', 'created_at')
    search_fields = ('text', 'display_name', 'room__room_code')


@admin.register(GameEvent)
class GameEventAdmin(admin.ModelAdmin):
    list_display = ('room', 'event_type', 'player', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('room__room_code',)
