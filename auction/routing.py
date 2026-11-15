from django.urls import re_path

from .consumers import AuctionConsumer

websocket_urlpatterns = [
    re_path(r'^auction/ws/room/(?P<room_code>[A-Z0-9]{1,12})/$', AuctionConsumer.as_asgi()),
]