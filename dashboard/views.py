from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.models import Department, ParentLink, User
from canteen.closure import run_closure, trigger_pending_closures_if_needed
from core.models import AuditLog
from core.services import log_sensitive_action
from menus.models import MealService
from payments.models import Payment
from payments.services import confirm_payment
from reservations.models import Reservation
from wallet.models import AnnualPass
from wallet.services import activate_annual_pass, admin_adjustment

from .services import get_financial_report, get_operational_stats


@admin_required
def dashboard_home(request):
    trigger_pending_closures_if_needed()
    period = request.GET.get("period", "week")
    if period not in ("day", "week", "month"):
        period = "week"
    fin = get_financial_report(period=period)
    ops = get_operational_stats()
    return render(
        request,
        "dashboard/home.html",
        {"fin": fin, "ops": ops, "period": period},
    )


@admin_required
def admin_orders_view(request):
    trigger_pending_closures_if_needed()
    qs = (
        Reservation.objects.select_related(
            "service", "beneficiary", "beneficiary__department"
        )
        .prefetch_related("items__option__dish")
        .order_by("-service__date", "-created_at")
    )
    date_filter = request.GET.get("date", "")
    status_filter = request.GET.get("status", "")
    payment_filter = request.GET.get("payment_status", "")
    role_filter = request.GET.get("role", "")
    dept_filter = request.GET.get("department", "")

    if date_filter:
        qs = qs.filter(service__date=date_filter)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if payment_filter:
        qs = qs.filter(payment_status=payment_filter)
    if role_filter:
        qs = qs.filter(beneficiary__role=role_filter)
    if dept_filter and dept_filter.isdigit():
        qs = qs.filter(beneficiary__department_id=int(dept_filter))

    return render(
        request,
        "dashboard/orders.html",
        {
            "orders": qs[:100],
            "departments": Department.objects.filter(is_active=True),
            "filters": {
                "date": date_filter,
                "status": status_filter,
                "payment_status": payment_filter,
                "role": role_filter,
                "department": dept_filter,
            },
            "status_choices": Reservation.Status.choices,
            "payment_choices": Reservation.PaymentStatus.choices,
        },
    )


@admin_required
def admin_users_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "create_user":
                role = request.POST.get("role")
                if role not in (
                    User.Role.PERSONNEL,
                    User.Role.PARENT,
                    User.Role.EQUIPE,
                    User.Role.ELEVE,
                ):
                    raise ValidationError("Rôle non autorisé.")
                dept_id = request.POST.get("department")
                dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
                user = User.objects.create_user(
                    email=request.POST.get("email", "").strip(),
                    password=request.POST.get("password", ""),
                    first_name=request.POST.get("first_name", "").strip(),
                    last_name=request.POST.get("last_name", "").strip(),
                    role=role,
                    department=dept if role == User.Role.PERSONNEL else None,
                )
                log_sensitive_action(
                    actor=request.user,
                    action="USER_CREATED",
                    target_repr=f"{user.email} ({user.role})",
                    reason="Création de compte depuis l'espace administration",
                )
                messages.success(request, f"Compte {user.email} ({user.get_role_display()}) créé.")

            elif action == "link_parent":
                parent = get_object_or_404(User, pk=request.POST.get("parent_id"), role=User.Role.PARENT)
                child = get_object_or_404(User, pk=request.POST.get("child_id"), role=User.Role.ELEVE)
                link, created = ParentLink.objects.get_or_create(
                    parent=parent,
                    child=child,
                    defaults={"created_by": request.user},
                )
                if created:
                    log_sensitive_action(
                        actor=request.user,
                        action="PARENT_LINK_CREATED",
                        target_repr=f"{parent.email} -> {child.email}",
                        reason="Lien parent-enfant validé par l'administration",
                    )
                    messages.success(request, f"Lien créé : {parent.full_name} → {child.full_name}.")
                else:
                    messages.info(request, "Ce lien parent-enfant existe déjà.")

            elif action == "create_department":
                name = request.POST.get("name", "").strip()
                if not name:
                    raise ValidationError("Le nom du département est obligatoire.")
                Department.objects.create(name=name)
                messages.success(request, f"Département « {name} » ajouté.")

            elif action == "toggle_active":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                if target.pk == request.user.pk:
                    raise ValidationError("Vous ne pouvez pas suspendre votre propre compte.")
                target.is_active = not target.is_active
                target.save(update_fields=["is_active"])
                log_sensitive_action(
                    actor=request.user,
                    action="USER_STATUS_CHANGED",
                    target_repr=target.email,
                    reason="Compte réactivé" if target.is_active else "Compte suspendu",
                )
                messages.success(request, f"Statut de {target.email} mis à jour.")

            elif action == "adjust_wallet":
                target = get_object_or_404(User, pk=request.POST.get("user_id"))
                amount = int(request.POST.get("amount") or 0)
                direction = request.POST.get("direction", "+")
                reason = request.POST.get("reason", "")
                admin_adjustment(target, amount, direction, reason, actor=request.user)
                messages.success(request, f"Ajustement enregistré pour {target.full_name}.")
        except (ValidationError, ValueError) as exc:
            msg = " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            messages.error(request, msg)
        return redirect("dashboard:users")

    return render(
        request,
        "dashboard/users.html",
        {
            "users": User.objects.select_related("department").order_by("role", "last_name"),
            "departments": Department.objects.all(),
            "parents": User.objects.filter(role=User.Role.PARENT),
            "students": User.objects.filter(role=User.Role.ELEVE),
            "links": ParentLink.objects.select_related("parent", "child").order_by("-created_at"),
        },
    )


@admin_required
def admin_passes_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "confirm_transfer":
                ref = request.POST.get("reference", "")
                confirm_payment(ref, actor=request.user)
                messages.success(request, f"Virement {ref} confirmé et forfait activé.")
            elif action == "manual_pass":
                student = get_object_or_404(
                    User, pk=request.POST.get("student_id"), role=User.Role.ELEVE
                )
                reason = request.POST.get("reason", "")
                activate_annual_pass(student, actor=request.user, payment=None, reason=reason)
                messages.success(
                    request, f"Forfait « Année soldée » activé manuellement pour {student.full_name}."
                )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("dashboard:passes")

    return render(
        request,
        "dashboard/passes.html",
        {
            "active_passes": AnnualPass.objects.filter(
                status=AnnualPass.Status.ACTIVE
            ).select_related("student", "payment", "activated_by"),
            "pending_transfers": Payment.objects.filter(
                method=Payment.Method.BANK_TRANSFER,
                status=Payment.Status.PENDING,
            ).select_related("beneficiary", "payer"),
            "students": User.objects.filter(role=User.Role.ELEVE),
        },
    )


@admin_required
def admin_closure_view(request):
    last_summary = None
    if request.method == "POST":
        force = request.POST.get("force") == "on"
        last_summary = run_closure(force=force)
        log_sensitive_action(
            actor=request.user,
            action="MANUAL_CLOSURE_RUN",
            target_repr=f"{last_summary['services_closed']} service(s)",
            reason=(
                f"Débits: {last_summary['debited_count']} ({last_summary['debited_amount']} FCFA), "
                f"Replis retrait: {last_summary['fallback_pickup_count']}, "
                f"Annulations: {last_summary['cancelled_count']}"
            ),
        )
        messages.success(
            request,
            f"Clôture exécutée : {last_summary['debited_count']} débit(s), "
            f"{last_summary['fallback_pickup_count']} repli(s) au retrait, "
            f"{last_summary['cancelled_count']} annulation(s).",
        )

    services = MealService.objects.filter(is_published=True).order_by("-date")[:15]
    scheduled_count = Reservation.objects.filter(
        status=Reservation.Status.CONFIRMED,
        payment_status=Reservation.PaymentStatus.SCHEDULED,
    ).count()
    return render(
        request,
        "dashboard/closure.html",
        {
            "services": services,
            "scheduled_count": scheduled_count,
            "last_summary": last_summary,
            "now": timezone.now(),
        },
    )


@admin_required
def admin_audit_view(request):
    logs = AuditLog.objects.select_related("actor")[:100]
    return render(request, "dashboard/audit.html", {"logs": logs})
