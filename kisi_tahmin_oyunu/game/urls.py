from django.urls import path

from . import views

app_name = 'game'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/create/', views.create_room, name='api_create_room'),
    path('api/join/', views.join_room, name='api_join_room'),
    path('api/state/<str:room_code>/', views.get_room_state, name='api_get_room_state'),
    path('<str:room_code>/', views.game_room, name='game_room'),
]
