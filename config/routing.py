from amiral.routing import websocket_urlpatterns as amiral_websocket_urlpatterns
from kim.routing import websocket_urlpatterns as kim_websocket_urlpatterns
from okey101.routing import websocket_urlpatterns as okey101_websocket_urlpatterns
from satranc.routing import websocket_urlpatterns as satranc_websocket_urlpatterns
from sayi.routing import websocket_urlpatterns as sayi_websocket_urlpatterns

# Each game routes its own WebSocket namespace
# (/sayi/..., /kim-bu/..., /amiral/..., /satranc/... and /101-okey/...).
websocket_urlpatterns = (
    sayi_websocket_urlpatterns
    + kim_websocket_urlpatterns
    + amiral_websocket_urlpatterns
    + satranc_websocket_urlpatterns
    + okey101_websocket_urlpatterns
)
