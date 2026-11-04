from django.urls import path

from . import views

app_name = 'bilardo'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/create/', views.create_room, name='api_create_room'),
    path('api/join/', views.join_room, name='api_join_room'),
    path('yerel/<str:mode>/', views.local_game, name='local_game'),
    path('oda/<str:room_code>/', views.game_room, name='game_room'),
]
