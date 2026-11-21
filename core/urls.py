from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("notifications/", views.notifications_view, name="notifications"),
    path(
        "notifications/<int:notif_id>/lue/",
        views.notification_mark_read_view,
        name="notification_mark_read",
    ),
    path("sw.js", views.service_worker_view, name="service_worker"),
    path("hors-ligne/", views.offline_view, name="offline"),
]
