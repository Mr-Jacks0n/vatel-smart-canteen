from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Administration — Vatel Smart Canteen"
admin.site.site_title = "Vatel Smart Canteen"
admin.site.index_title = "Gestion des référentiels"

urlpatterns = [
    path("gestion-securisee/", admin.site.urls),
    path("", include("core.urls")),
    path("compte/", include("accounts.urls")),
    path("menu/", include("menus.urls")),
    path("portefeuille/", include("wallet.urls")),
    path("paiements/", include("payments.urls")),
    path("reservations/", include("reservations.urls")),
    path("parents/", include("parents.urls")),
    path("equipe/", include("canteen.urls")),
    path("administration/", include("dashboard.urls")),
]
