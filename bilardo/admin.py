from django.contrib import admin

from .models import GamePlayer, GameRoom, Shot


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'mode', 'target', 'status', 'winner_seat', 'created_at')
    list_filter = ('mode', 'status', 'created_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'finished_at')


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'game_room', 'seat', 'cue', 'joined_at')
    list_filter = ('cue', 'joined_at', 'game_room__mode')
    search_fields = ('name', 'player_identifier', 'game_room__room_code')
    readonly_fields = ('id', 'joined_at')


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    list_display = ('game_room', 'player', 'power', 'foul', 'created_at')
    list_filter = ('foul', 'created_at', 'game_room__mode')
    search_fields = ('game_room__room_code', 'player__name')
    readonly_fields = ('id', 'created_at')
