from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/status/', views.api_status, name='api_status'),
    path('api/recording/', views.api_recording, name='api_recording'),
    path('api/simulation/', views.api_simulation, name='api_simulation'),
    path('api/kafka-check/', views.api_kafka_check, name='api_kafka_check'),
    path('api/lag-stats/', views.api_lag_stats, name='api_lag_stats'),
]