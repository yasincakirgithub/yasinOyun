from django.urls import path

from . import views

app_name = 'auction'

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health, name='health'),
    path('api/rooms/', views.api_create_room, name='api_create_room'),
    path('api/rooms/join/', views.api_join_room, name='api_join_room'),
    path('api/rooms/<str:room_code>/state/', views.api_room_state, name='api_room_state'),
    path('api/rooms/<str:room_code>/leave/', views.api_leave_room, name='api_leave_room'),
    path('api/rooms/<str:room_code>/settings/', views.api_update_settings, name='api_update_settings'),
    path('api/rooms/<str:room_code>/theme/', views.api_select_theme, name='api_select_theme'),
    path('api/rooms/<str:room_code>/start/', views.api_start_auction, name='api_start_auction'),
    path('api/rooms/<str:room_code>/bid/', views.api_bid, name='api_bid'),
    path('api/rooms/<str:room_code>/new-game/', views.api_new_game, name='api_new_game'),
    path('room/<str:room_code>/', views.game_room, name='game_room'),
]