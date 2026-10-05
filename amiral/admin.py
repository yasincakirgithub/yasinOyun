from django.contrib import admin

from .models import GamePlayer, GameRoom, Shot


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'created_at', 'updated_at', 'winner')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'finished_at')

    def winner(self, obj):
        return obj.winner.player_identifier if obj.winner else None
    winner.short_description = 'Winner'


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('player_identifier', 'game_room', 'ready', 'joined_at')
    list_filter = ('ready', 'joined_at', 'game_room__room_code')
    search_fields = ('player_identifier', 'game_room__room_code')
    readonly_fields = ('id', 'joined_at')


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    list_display = ('game_room', 'shooter', 'row', 'col', 'hit', 'created_at')
    list_filter = ('hit', 'created_at', 'game_room__room_code')
    search_fields = ('game_room__room_code', 'shooter__player_identifier')
    readonly_fields = ('id', 'created_at')
