from django.contrib import admin

from .models import Allergen, Dish, MealOption, MealService, Regime


@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Regime)
class RegimeAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active")
    list_filter = ("category", "is_active", "allergens", "compatible_regimes")
    search_fields = ("name", "ingredients")
    filter_horizontal = ("allergens", "compatible_regimes")


class MealOptionInline(admin.TabularInline):
    model = MealOption
    extra = 1
    readonly_fields = ("reserved_count",)


@admin.register(MealService)
class MealServiceAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "service_type",
        "meal_price",
        "extra_portion_price",
        "is_published",
        "reservation_deadline",
    )
    list_filter = ("is_published", "service_type")
    inlines = [MealOptionInline]
