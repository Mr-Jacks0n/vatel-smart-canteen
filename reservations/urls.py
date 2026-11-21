from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("", views.reservation_list_view, name="list"),
    path("composer/<int:service_id>/", views.compose_meal_view, name="compose"),
    path(
        "composer/<int:service_id>/total/",
        views.compose_price_preview_view,
        name="price_preview",
    ),
    path(
        "ne-mange-pas/<int:service_id>/",
        views.decline_day_view,
        name="decline_day",
    ),
    path(
        "<int:reservation_id>/annuler/",
        views.cancel_reservation_view,
        name="cancel",
    ),
    path(
        "ticket/<str:ticket_token>/",
        views.ticket_view,
        name="ticket",
    ),
    path(
        "<int:reservation_id>/payer-retrait/",
        views.init_pickup_payment_view,
        name="init_pickup_payment",
    ),
    path(
        "regler-maintenant/",
        views.pay_now_scheduled_view,
        name="pay_now_scheduled",
    ),
    path(
        "semaine/",
        views.multi_reserve_view,
        name="multi_reserve",
    ),
    path(
        "<int:reservation_id>/noter/",
        views.rate_reservation_view,
        name="rate",
    ),
]
