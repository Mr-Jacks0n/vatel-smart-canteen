from datetime import date

from django.core.management.base import BaseCommand

from canteen.closure import run_closure


class Command(BaseCommand):
    help = "Exécute la clôture idempotente des réservations dont l'heure limite est atteinte."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date de service spécifique (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force la clôture même avant l'heure limite (démonstration).",
        )

    def handle(self, *args, **options):
        target_date = date.fromisoformat(options["date"]) if options.get("date") else None
        summary = run_closure(target_date=target_date, force=options.get("force", False))
        self.stdout.write(
            self.style.SUCCESS(
                f"Clôture terminée : {summary['services_closed']} service(s), "
                f"{summary['debited_count']} débit(s) ({summary['debited_amount']} FCFA), "
                f"{summary['fallback_pickup_count']} repli(s) au retrait, "
                f"{summary['cancelled_count']} annulation(s)."
            )
        )
