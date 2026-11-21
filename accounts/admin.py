from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, DietaryProfile, ParentLink, User


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("last_name", "first_name")
    list_display = ("email", "first_name", "last_name", "role", "department", "is_active")
    list_filter = ("role", "is_active", "department")
    search_fields = ("email", "first_name", "last_name", "school_id")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Informations personnelles",
            {"fields": ("first_name", "last_name", "phone", "school_id", "class_name")},
        ),
        (
            "Rôle et rattachement",
            {"fields": ("role", "department")},
        ),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "department",
                    "password1",
                    "password2",
                ),
            },
        ),
    )


@admin.register(DietaryProfile)
class DietaryProfileAdmin(admin.ModelAdmin):
    list_display = ("user",)
    search_fields = ("user__email", "user__first_name", "user__last_name")
    filter_horizontal = ("allergies", "intolerances", "regimes")


@admin.register(ParentLink)
class ParentLinkAdmin(admin.ModelAdmin):
    list_display = ("parent", "child", "created_by", "created_at")
    search_fields = ("parent__email", "child__email")
    autocomplete_fields = ("parent", "child")
