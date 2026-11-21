from django.urls import path

from . import views

app_name = "parents"

urlpatterns = [
    path("", views.parent_home_view, name="home"),
    path("enfant/<int:child_id>/", views.child_detail_view, name="child_detail"),
    path("enfant/<int:child_id>/recharger/", views.child_topup_view, name="child_topup"),
    path(
        "enfant/<int:child_id>/forfait-annuel/",
        views.child_annual_prepayment_view,
        name="child_annual_prepayment",
    ),
    path(
        "enfant/<int:child_id>/reglages-debit/",
        views.child_debit_settings_view,
        name="child_debit_settings",
    ),
    path(
        "enfant/<int:child_id>/regler-maintenant/",
        views.child_pay_now_view,
        name="child_pay_now",
    ),
]
