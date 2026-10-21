from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('codenames/ws/room/<str:room_code>/', consumers.GameConsumer.as_asgi()),
]
