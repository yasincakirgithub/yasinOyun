from django.contrib import admin
from .models import GameRoom, GamePlayer, Guess


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
    
    # Hide secret number in admin list and detail views
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Make secret number widget hidden or masked
        if 'secret_number' in form.base_fields:
            form.base_fields['secret_number'].widget.attrs['readonly'] = True
            form.base_fields['secret_number'].help_text = 'Secret number is hidden for security'
        return form
    
    # In list view, show masked secret
    def secret_number_masked(self, obj):
        return '••••' if obj.secret_number else None
    secret_number_masked.short_description = 'Secret Number'


@admin.register(Guess)
class GuessAdmin(admin.ModelAdmin):
    list_display = ('game_player', 'value', 'result', 'created_at', 'turn_number')
    list_filter = ('created_at', 'game_player__game_room__room_code')
    search_fields = ('value', 'result', 'game_player__player_identifier')
    readonly_fields = ('id', 'created_at')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('game_player__game_room')