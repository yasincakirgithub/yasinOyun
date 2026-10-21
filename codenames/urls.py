from django.urls import path

from . import views

app_name = 'codenames'

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health, name='health'),
    path('api/rooms/', views.api_create_room, name='api_create_room'),
    path('api/rooms/join/', views.api_join_room, name='api_join_room'),
    path('api/rooms/<str:room_code>/state/', views.api_room_state, name='api_room_state'),
    path('api/rooms/<str:room_code>/leave/', views.api_leave_room, name='api_leave_room'),
    path('api/rooms/<str:room_code>/settings/', views.api_update_settings, name='api_update_settings'),
    path('api/rooms/<str:room_code>/assign-roles/', views.api_assign_roles, name='api_assign_roles'),
    path('api/rooms/<str:room_code>/preference/', views.api_update_preference, name='api_update_preference'),
    path('api/rooms/<str:room_code>/start/', views.api_start_game, name='api_start_game'),
    path('api/rooms/<str:room_code>/new-game/', views.api_new_game, name='api_new_game'),
    path('api/rooms/<str:room_code>/clue/', views.api_submit_clue, name='api_submit_clue'),
    path('api/rooms/<str:room_code>/guess/', views.api_guess, name='api_guess'),
    path('api/rooms/<str:room_code>/chat/', views.api_chat, name='api_chat'),
    path('api/rooms/<str:room_code>/end-turn/', views.api_end_turn, name='api_end_turn'),
    path('api/rooms/<str:room_code>/events/', views.api_events, name='api_events'),
    path('room/<str:room_code>/', views.game_room, name='game_room'),
]
