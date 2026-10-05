from kim.routing import websocket_urlpatterns as kim_websocket_urlpatterns
from sayi.routing import websocket_urlpatterns as sayi_websocket_urlpatterns

# Each game routes its own WebSocket namespace (/sayi/... and /kim-bu/...).
websocket_urlpatterns = sayi_websocket_urlpatterns + kim_websocket_urlpatterns
