from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        LOW_BALANCE = "LOW_BALANCE", "Solde faible"
        INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE", "Solde insuffisant"
        PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Paiement confirmé"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Paiement échoué"
        RESERVATION_CONFIRMED = "RESERVATION_CONFIRMED", "Réservation confirmée"
        RESERVATION_CANCELLED = "RESERVATION_CANCELLED", "Réservation annulée"
        GENERAL = "GENERAL", "Information"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinataire",
    )
    kind = models.CharField(
        "Type", max_length=30, choices=Kind.choices, default=Kind.GENERAL
    )
    message = models.TextField("Message")
    link = models.CharField("Lien", max_length=255, blank=True)
    is_read = models.BooleanField("Lue", default=False)
    created_at = models.DateTimeField("Créée le", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.user}"


class AuditLog(models.Model):
    """Journal des opérations sensibles (sans mot de passe ni donnée alimentaire)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Auteur",
    )
    action = models.CharField("Action", max_length=80)
    target_repr = models.CharField("Cible", max_length=200)
    reason = models.TextField("Motif", blank=True)
    created_at = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journal d'audit"

    def __str__(self):
        return f"{self.action} ({self.created_at:%d/%m/%Y %H:%M})"
