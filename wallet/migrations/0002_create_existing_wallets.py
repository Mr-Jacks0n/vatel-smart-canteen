from django.db import migrations


def create_wallets_for_existing_diners(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Wallet = apps.get_model("wallet", "Wallet")
    for user in User.objects.filter(role__in=["ELEVE", "PERSONNEL"]):
        Wallet.objects.get_or_create(user=user)


class Migration(migrations.Migration):
    dependencies = [
        ("wallet", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_wallets_for_existing_diners, migrations.RunPython.noop
        ),
    ]
