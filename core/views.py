from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from menus.services import get_week_services

from .models import Notification


def home(request):
    """Page d'accueil publique avec aperçu du menu de la semaine."""
    services = get_week_services(published_only=True)[:5]
    return render(request, "core/home.html", {"services": services})


@login_required
def notifications_view(request):
    notifications = Notification.objects.filter(user=request.user)[:50]
    return render(
        request,
        "core/notifications.html",
        {"notifications": notifications},
    )


@login_required
@require_POST
def notification_mark_read_view(request, notif_id: int):
    notif = get_object_or_404(Notification, pk=notif_id, user=request.user)
    if not notif.is_read:
        notif.is_read = True
        notif.save(update_fields=["is_read"])
    if request.htmx:
        return render(
            request,
            "core/partials/notification_item.html",
            {"notif": notif},
        )
    return redirect("core:notifications")


def service_worker_view(request):
    return render(
        request,
        "core/sw.js",
        content_type="application/javascript",
    )


def offline_view(request):
    return render(request, "core/offline.html")
