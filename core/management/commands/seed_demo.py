from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Department, DietaryProfile, ParentLink, User
from menus.models import Allergen, Dish, MealOption, MealService, Regime
from payments.models import Payment
from payments.services import confirm_payment, create_payment, fail_payment
from reservations.models import Reservation
from reservations.services import decline_day, reserve
from wallet.models import Wallet
from wallet.services import has_active_pass, update_debit_settings


class Command(BaseCommand):
    help = "Peuple la base de façon idempotente avec les données de démonstration Vatel Smart Canteen."

    def handle(self, *args, **options):
        demo_password = getattr(settings, "DEMO_PASSWORD", "")
        if not demo_password:
            raise CommandError(
                "La variable d'environnement DEMO_PASSWORD doit être définie avant d'exécuter seed_demo."
            )

        dept_dir, _ = Department.objects.get_or_create(name="Direction")
        dept_ped, _ = Department.objects.get_or_create(name="Pédagogie")

        def ensure_user(email, first_name, last_name, role, department=None, class_name="", school_id="", is_staff=False, is_superuser=False):
            user = User.objects.filter(email=email).first()
            if user:
                if school_id and not user.school_id:
                    user.school_id = school_id
                    user.save(update_fields=["school_id"])
                return user
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=role,
                department=department,
                class_name=class_name,
                school_id=school_id,
                is_staff=is_staff,
                is_superuser=is_superuser,
                is_active=True,
            )
            user.set_password(demo_password)
            user.full_clean()
            user.save()
            return user

        admin = ensure_user("admin@vatel.demo", "Admin", "Vatel", User.Role.ADMIN, school_id="VTL-ADM-001", is_staff=True, is_superuser=True)
        equipe = ensure_user("equipe@vatel.demo", "Chef", "Yao", User.Role.EQUIPE, school_id="VTL-EQP-001")
        staff_ped = ensure_user("claire.pedagogie@vatel.demo", "Claire", "Mory", User.Role.PERSONNEL, department=dept_ped, school_id="VTL-PRO-101")
        staff_dir = ensure_user("marc.direction@vatel.demo", "Marc", "Diagne", User.Role.PERSONNEL, department=dept_dir, school_id="VTL-PRO-102")

        eleve_aya = ensure_user("aya.eleve@vatel.demo", "Aya", "Kouassi", User.Role.ELEVE, class_name="Bachelor 2", school_id="VTL-2026-001")
        eleve_kader = ensure_user("kader.forfait@vatel.demo", "Kader", "Kouassi", User.Role.ELEVE, class_name="Bachelor 1", school_id="VTL-2026-002")
        eleve_sali = ensure_user("sali.soldefaible@vatel.demo", "Sali", "Touré", User.Role.ELEVE, class_name="MBA 1", school_id="VTL-2026-003")
        eleve_yao = ensure_user("yao.sanssolde@vatel.demo", "Yao", "Brou", User.Role.ELEVE, class_name="Bachelor 3", school_id="VTL-2026-004")

        parent_fatou = ensure_user("fatou.parent@vatel.demo", "Fatou", "Kouassi", User.Role.PARENT)
        parent_jean = ensure_user("jean.parent@vatel.demo", "Jean", "Touré", User.Role.PARENT)

        ParentLink.objects.get_or_create(parent=parent_fatou, child=eleve_aya, defaults={"created_by": admin})
        ParentLink.objects.get_or_create(parent=parent_fatou, child=eleve_kader, defaults={"created_by": admin})
        ParentLink.objects.get_or_create(parent=parent_jean, child=eleve_sali, defaults={"created_by": admin})

        # Profils alimentaires
        peanut = Allergen.objects.filter(name="arachides").first()
        milk = Allergen.objects.filter(name="lait").first()
        halal = Regime.objects.filter(name="halal").first()
        veg = Regime.objects.filter(name="végétarien").first()

        prof_aya, _ = DietaryProfile.objects.get_or_create(user=eleve_aya)
        if peanut:
            prof_aya.allergies.add(peanut)
        if halal:
            prof_aya.regimes.add(halal)

        prof_sali, _ = DietaryProfile.objects.get_or_create(user=eleve_sali)
        if milk:
            prof_sali.intolerances.add(milk)

        # Réglages de débit (journalier, hebdomadaire, auto désactivé)
        update_debit_settings(staff_ped, Wallet.DebitFrequency.WEEKLY, True)
        update_debit_settings(eleve_yao, Wallet.DebitFrequency.DAILY, False)

        # Portefeuilles & paiements initiaux (idempotents)
        if Wallet.objects.get(user=eleve_aya).balance == 0 and not Payment.objects.filter(beneficiary=eleve_aya).exists():
            p = create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=eleve_aya,
                payer=parent_fatou,
                method=Payment.Method.WAVE,
                amount=10000,
                phone_number="0701020304",
            )
            confirm_payment(p.reference, actor=parent_fatou)

        if Wallet.objects.get(user=eleve_sali).balance == 0 and not Payment.objects.filter(beneficiary=eleve_sali).exists():
            p = create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=eleve_sali,
                payer=parent_jean,
                method=Payment.Method.ORANGE_MONEY,
                amount=1000,
                phone_number="0705060708",
            )
            confirm_payment(p.reference, actor=parent_jean)

        if Wallet.objects.get(user=staff_ped).balance == 0 and not Payment.objects.filter(beneficiary=staff_ped).exists():
            p = create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=staff_ped,
                payer=staff_ped,
                method=Payment.Method.BANK_CARD,
                amount=10000,
            )
            confirm_payment(p.reference, actor=staff_ped)

        # Forfait « Année soldée » pour Kader
        if not has_active_pass(eleve_kader):
            p_ann = create_payment(
                kind=Payment.Kind.ANNUAL_PREPAYMENT,
                beneficiary=eleve_kader,
                payer=parent_fatou,
                method=Payment.Method.WAVE,
                phone_number="0701020304",
            )
            confirm_payment(p_ann.reference, actor=parent_fatou)

        # Virement bancaire en attente pour Sali (pour l'écran admin Forfaits & virements)
        if not Payment.objects.filter(
            beneficiary=eleve_sali, method=Payment.Method.BANK_TRANSFER
        ).exists():
            create_payment(
                kind=Payment.Kind.ANNUAL_PREPAYMENT,
                beneficiary=eleve_sali,
                payer=parent_jean,
                method=Payment.Method.BANK_TRANSFER,
            )

        # Paiement échoué de démonstration
        if not Payment.objects.filter(status=Payment.Status.FAILED).exists():
            p_fail = create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=eleve_yao,
                payer=eleve_yao,
                method=Payment.Method.MTN_MOMO,
                amount=2000,
                phone_number="0501020304",
            )
            fail_payment(p_fail.reference, actor=eleve_yao)

        # Plats des 3 catégories
        dishes_spec = [
            ("Salade fraîcheur avocat", Dish.Category.ENTREE, "Avocat, tomates cerises, citron vert", "salade.jpg", [], [veg, halal]),
            ("Velouté de potiron", Dish.Category.ENTREE, "Potiron, crème légère, muscade", "salade.jpg", [milk], [veg, halal]),
            ("Poulet braisé & attiéké", Dish.Category.PLAT, "Poulet fermier, attiéké, oignons, tomates", "attieke.jpg", [], [halal]),
            ("Poulet Yassa & riz parfumé", Dish.Category.PLAT, "Poulet mariné citron-oignons, riz jasmin", "yassa.jpg", [], [halal]),
            ("Mafé bœuf sauce arachide", Dish.Category.PLAT, "Bœuf mijoté, pâte d'arachide, riz blanc", "riz-gras.jpg", [peanut], [halal]),
            ("Brochettes grillées & alloco", Dish.Category.PLAT, "Bœuf mariné, bananes plantains dorées", "brochettes.jpg", [], [halal]),
            ("Salade de fruits tropicaux", Dish.Category.DESSERT, "Mangue, ananas, papaye, menthe", "dessert.jpg", [], [veg, halal]),
            ("Yaourt vanille & miel", Dish.Category.DESSERT, "Yaourt fermier, vanille, miel local", "dessert.jpg", [milk], [veg, halal]),
        ]
        dishes = {}
        for name, cat, ingredients, img, alls, regs in dishes_spec:
            dish, _ = Dish.objects.get_or_create(
                name=name,
                defaults={"category": cat, "ingredients": ingredients, "image": img},
            )
            for a in alls:
                if a:
                    dish.allergens.add(a)
            for r in regs:
                if r:
                    dish.compatible_regimes.add(r)
            dishes[name] = dish

        # Services publiés sur 2 semaines (lundi à vendredi)
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        service_dates = [
            monday + timedelta(days=offset)
            for offset in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)
        ]
        # S'assurer qu'aujourd'hui a un service ouvert pour la démo comptoir
        if today not in service_dates:
            service_dates.insert(0, today)

        services = {}
        for d in sorted(set(service_dates)):
            deadline = (
                timezone.now() + timedelta(hours=3)
                if d <= today + timedelta(days=1)
                else MealService.compute_deadline(d)
            )
            svc, _ = MealService.objects.get_or_create(
                date=d,
                service_type=MealService.ServiceType.DEJEUNER,
                defaults={
                    "meal_price": 1500,
                    "extra_portion_price": 500,
                    "is_published": True,
                    "reservation_deadline": deadline,
                },
            )
            if not svc.options.exists():
                for dish_name in (
                    "Salade fraîcheur avocat",
                    "Velouté de potiron",
                    "Poulet braisé & attiéké",
                    "Poulet Yassa & riz parfumé",
                    "Mafé bœuf sauce arachide",
                    "Salade de fruits tropicaux",
                    "Yaourt vanille & miel",
                ):
                    MealOption.objects.get_or_create(
                        service=svc, dish=dishes[dish_name], defaults={"capacity": 35}
                    )
            services[d] = svc

        # Quelques réservations de démo sur un jour futur
        demo_day = next((d for d in sorted(services) if d > today), today)
        demo_svc = services[demo_day]
        opts = {o.dish.name: o for o in demo_svc.options.select_related("dish")}

        if not Reservation.objects.filter(beneficiary=eleve_aya, service=demo_svc).exists():
            reserve(
                eleve_aya,
                demo_svc.pk,
                [opts["Salade fraîcheur avocat"].pk, opts["Poulet braisé & attiéké"].pk],
                skip_dessert=True,
            )

        if not Reservation.objects.filter(beneficiary=eleve_kader, service=demo_svc).exists():
            reserve(
                eleve_kader,
                demo_svc.pk,
                [opts["Salade fraîcheur avocat"].pk, opts["Poulet Yassa & riz parfumé"].pk, opts["Salade de fruits tropicaux"].pk],
                extra_portions=1,
            )

        if not Reservation.objects.filter(beneficiary=staff_ped, service=demo_svc).exists():
            reserve(
                staff_ped,
                demo_svc.pk,
                [opts["Poulet braisé & attiéké"].pk, opts["Salade de fruits tropicaux"].pk],
                skip_starter=True,
                fulfillment=Reservation.Fulfillment.DELIVERY,
                delivery_location="Bâtiment Pédagogie — Bureau 204",
            )

        if not Reservation.objects.filter(beneficiary=eleve_yao, service=demo_svc).exists():
            reserve(
                eleve_yao,
                demo_svc.pk,
                [opts["Poulet Yassa & riz parfumé"].pk],
                skip_starter=True,
                skip_dessert=True,
            )

        if not Reservation.objects.filter(beneficiary=staff_dir, service=demo_svc).exists():
            decline_day(staff_dir, demo_svc.pk)

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo terminé avec succès ({User.objects.count()} utilisateurs, "
                f"{MealService.objects.count()} services, {Reservation.objects.count()} réservations)."
            )
        )
