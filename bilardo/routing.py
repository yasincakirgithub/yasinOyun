from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('bilardo/ws/game/<str:room_code>/', consumers.GameConsumer.as_asgi()),
]
