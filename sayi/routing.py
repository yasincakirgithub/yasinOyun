from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path('sayi/ws/game/<str:room_code>/', consumers.GameConsumer.as_asgi()),
]
