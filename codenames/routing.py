from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('ws/codenames/<str:room_code>/', consumers.GameConsumer.as_asgi()),
]