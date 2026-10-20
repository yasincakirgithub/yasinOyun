from django.contrib import admin

from .models import GamePlayer, GameRoom, TableMeld


@admin.register(GameRoom)
class GameRoomAdmin(admin.ModelAdmin):
    list_display = ('room_code', 'status', 'round_number', 'total_rounds', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('room_code',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'started_at', 'finished_at')


@admin.register(GamePlayer)
class GamePlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'player_identifier', 'game_room', 'seat', 'opened', 'total_score')
    list_filter = ('opened', 'route')
    search_fields = ('name', 'player_identifier', 'game_room__room_code')
    readonly_fields = ('id', 'joined_at')


@admin.register(TableMeld)
class TableMeldAdmin(admin.ModelAdmin):
    list_display = ('game_room', 'owner', 'kind', 'score', 'created_at')
    list_filter = ('kind',)
    search_fields = ('game_room__room_code', 'owner__name')
    readonly_fields = ('id', 'created_at')
