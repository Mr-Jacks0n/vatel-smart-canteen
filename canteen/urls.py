from django.urls import path

from . import views

app_name = "canteen"

urlpatterns = [
    path("cuisine/", views.kitchen_view, name="kitchen"),
    path("cuisine/export-csv/", views.kitchen_export_csv_view, name="kitchen_export_csv"),
    path("comptoir/", views.counter_view, name="counter"),
    path("comptoir/ticket/<str:ticket_token>/", views.validate_qr_view, name="validate_qr"),
    path("comptoir/servir/<int:reservation_id>/", views.serve_ticket_view, name="serve_ticket"),
    path("livraisons/", views.deliveries_view, name="deliveries"),
]
