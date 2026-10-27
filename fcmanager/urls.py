from django.urls import path

from . import views

app_name = 'fcmanager'

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health, name='health'),
    path('api/rooms/', views.api_create_room, name='api_create_room'),
    path('api/rooms/join/', views.api_join_room, name='api_join_room'),
    path('api/rooms/<str:room_code>/state/', views.api_room_state, name='api_room_state'),
    path('api/rooms/<str:room_code>/leave/', views.api_leave_room, name='api_leave_room'),
    path('api/rooms/<str:room_code>/start-draft/', views.api_start_draft, name='api_start_draft'),
    path('api/rooms/<str:room_code>/pick/', views.api_pick, name='api_pick'),
    path('api/rooms/<str:room_code>/remove/', views.api_remove, name='api_remove'),
    path('api/rooms/<str:room_code>/clear/', views.api_clear_squad, name='api_clear_squad'),
    path('api/rooms/<str:room_code>/swap/', views.api_swap, name='api_swap'),
    path('api/rooms/<str:room_code>/lock/', views.api_lock, name='api_lock'),
    path('api/rooms/<str:room_code>/unlock/', views.api_unlock, name='api_unlock'),
    path('api/rooms/<str:room_code>/start-match/', views.api_start_match, name='api_start_match'),
    path('api/rooms/<str:room_code>/new-season/', views.api_new_season, name='api_new_season'),
    path('room/<str:room_code>/', views.game_room, name='game_room'),
]
