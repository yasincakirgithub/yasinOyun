from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    # Number guessing game
    path('sayi/', include('sayi.urls')),
    # "Kim Bu?" character guessing game
    path('kim-bu/', include('kim.urls')),
    # Landing page (last so it only matches the root)
    path('', include('core.urls')),
]
