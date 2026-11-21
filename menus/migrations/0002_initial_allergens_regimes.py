from django.db import migrations

INITIAL_ALLERGENS = [
    "arachides",
    "fruits à coque",
    "lait",
    "œufs",
    "poisson",
    "crustacés",
    "soja",
    "blé et gluten",
    "sésame",
]

INITIAL_REGIMES = [
    "végétarien",
    "végétalien",
    "sans porc",
    "halal",
    "sans gluten",
    "sans lactose",
]


def seed_allergens_and_regimes(apps, schema_editor):
    Allergen = apps.get_model("menus", "Allergen")
    Regime = apps.get_model("menus", "Regime")
    for name in INITIAL_ALLERGENS:
        Allergen.objects.get_or_create(name=name)
    for name in INITIAL_REGIMES:
        Regime.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("menus", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_allergens_and_regimes, migrations.RunPython.noop),
    ]
