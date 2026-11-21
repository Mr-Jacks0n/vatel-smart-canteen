from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("commandes/", views.admin_orders_view, name="orders"),
    path("utilisateurs/", views.admin_users_view, name="users"),
    path("forfaits/", views.admin_passes_view, name="passes"),
    path("cloture/", views.admin_closure_view, name="closure"),
    path("journal/", views.admin_audit_view, name="audit"),
]
