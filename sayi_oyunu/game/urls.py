from django.urls import path
from . import views

app_name = 'game'
urlpatterns = [
    path('', views.home, name='home'),
    path('<str:room_code>/', views.game_room, name='game_room'),
    path('api/create/', views.create_room, name='api_create_room'),
    path('api/join/', views.join_room, name='api_join_room'),
    path('api/secret/', views.set_secret, name='api_set_secret'),
    path('api/guess/', views.make_guess, name='api_make_guess'),
    path('api/state/<str:room_code>/', views.get_room_state, name='api_get_room_state'),
]