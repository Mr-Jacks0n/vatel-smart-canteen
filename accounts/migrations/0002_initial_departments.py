from django.db import migrations

INITIAL_DEPARTMENTS = [
    "Direction",
    "Pédagogie",
    "Administration",
    "Hospitalité",
]


def seed_departments(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    for name in INITIAL_DEPARTMENTS:
        Department.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_departments, migrations.RunPython.noop),
    ]
