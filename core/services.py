"""Services transversaux : notifications internes et journalisation d'audit."""

from accounts.models import ParentLink

from .models import AuditLog, Notification


def notify(user, kind, message, link=""):
    return Notification.objects.create(
        user=user,
        kind=kind,
        message=message,
        link=link,
    )


def notify_with_parents(user, kind, message, link=""):
    """Notifie l'utilisateur et chacun de ses parents liés."""
    created = [notify(user, kind, message, link=link)]
    parent_links = ParentLink.objects.filter(child=user).select_related("parent")
    for pl in parent_links:
        created.append(
            notify(
                pl.parent,
                kind,
                f"[{user.full_name}] {message}",
                link=link,
            )
        )
    return created


def log_sensitive_action(actor, action, target_repr, reason=""):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_repr=str(target_repr)[:200],
        reason=reason or "",
    )
