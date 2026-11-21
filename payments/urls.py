from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("<str:reference>/simuler/", views.simulate_payment_view, name="simulate"),
    path("<str:reference>/confirmer/", views.simulate_confirm_view, name="simulate_confirm"),
    path("<str:reference>/echouer/", views.simulate_fail_view, name="simulate_fail"),
]
