from django.urls import path

from . import views

app_name = "menus"

urlpatterns = [
    path("", views.week_menu_view, name="week_menu"),
    path("gestion/", views.admin_service_list_view, name="admin_service_list"),
    path(
        "gestion/<int:service_id>/",
        views.admin_service_detail_view,
        name="admin_service_detail",
    ),
    path(
        "gestion/<int:service_id>/publication/",
        views.admin_service_toggle_publish_view,
        name="admin_service_toggle_publish",
    ),
    path(
        "gestion/option/<int:option_id>/capacite/",
        views.admin_option_update_capacity_view,
        name="admin_option_update_capacity",
    ),
    path(
        "gestion/option/<int:option_id>/supprimer/",
        views.admin_option_delete_view,
        name="admin_option_delete",
    ),
]
