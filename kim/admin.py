from django.contrib import admin

from .models import Accusation, ChatMessage, GamePlayer, GameRoom


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'created_at', 'updated_at', 'winner_display')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'finished_at')

    def winner_display(self, obj):
        return obj.winner.player_identifier if obj.winner else None
    winner_display.short_description = 'Winner'


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('player_identifier', 'game_room', 'character_id', 'ready', 'joined_at')
    list_filter = ('ready', 'joined_at', 'game_room__room_code')
    search_fields = ('player_identifier', 'character_id', 'game_room__room_code')
    readonly_fields = ('id', 'joined_at')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('game_room', 'game_player', 'kind', 'text', 'created_at')
    list_filter = ('kind', 'created_at')
    search_fields = ('text', 'game_room__room_code', 'game_player__player_identifier')
    readonly_fields = ('id', 'created_at')


@admin.register(Accusation)
class AccusationAdmin(admin.ModelAdmin):
    list_display = ('game_player', 'character_id', 'correct', 'created_at')
    list_filter = ('correct', 'created_at')
    search_fields = ('character_id', 'game_player__player_identifier')
    readonly_fields = ('id', 'created_at')
