from django import forms

from .models import Dish, MealOption, MealService


class MealServiceForm(forms.ModelForm):
    class Meta:
        model = MealService
        fields = ("date", "meal_price", "extra_portion_price", "is_published")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "meal_price": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "step": 50}
            ),
            "extra_portion_price": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "step": 50}
            ),
            "is_published": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class MealOptionForm(forms.ModelForm):
    class Meta:
        model = MealOption
        fields = ("dish", "capacity")
        widgets = {
            "dish": forms.Select(attrs={"class": "form-select"}),
            "capacity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dish"].queryset = Dish.objects.filter(is_active=True).order_by(
            "category", "name"
        )
