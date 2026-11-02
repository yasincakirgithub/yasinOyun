from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('oyunlar/', views.games, name='games'),
    path('api/comments/<slug:game>/', views.comments, name='comments'),
    path('api/gold/', views.gold_price, name='gold_price'),
]
