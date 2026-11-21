from django.urls import path

from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.wallet_home_view, name="home"),
    path("recharger/", views.wallet_topup_init_view, name="topup_init"),
    path("reglages/", views.wallet_settings_view, name="settings"),
]
