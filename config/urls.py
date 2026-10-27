from django.contrib import admin
from django.urls import include, path

from codenames.views import health as codenames_health

urlpatterns = [
    path('admin/', admin.site.urls),
    # Number guessing game
    path('sayi/', include('sayi.urls')),
    # "Kim Bu?" character guessing game
    path('kim-bu/', include('kim.urls')),
    # Battleship game ("Amiral Battı")
    path('amiral/', include('amiral.urls')),
    # Two-player chess game (python-chess)
    path('satranc/', include('satranc.urls')),
    # Multiplayer 101 Okey
    path('101-okey/', include('okey101.urls')),
    # Codenames word association game
    path('codenames/', include('codenames.urls')),
    # FC Manager football squad-building game
    path('fcmanager/', include('fcmanager.urls')),
    path('healthz/', codenames_health, name='healthz'),
    # Landing page (last so it only matches the root)
    path('', include('core.urls')),
]
