from django.contrib import admin

from .models import GamePlayer, GameRoom, Move


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'result', 'winner', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'finished_at')


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('player_identifier', 'game_room', 'color', 'joined_at')
    list_filter = ('color', 'joined_at', 'game_room__room_code')
    search_fields = ('player_identifier', 'game_room__room_code')
    readonly_fields = ('id', 'joined_at')


@admin.register(Move)
class MoveAdmin(admin.ModelAdmin):
    list_display = ('game_room', 'player', 'san', 'uci', 'created_at')
    list_filter = ('created_at', 'game_room__room_code')
    search_fields = ('san', 'uci', 'game_room__room_code')
    readonly_fields = ('id', 'created_at')
