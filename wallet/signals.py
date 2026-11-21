from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User

from .models import Wallet


@receiver(post_save, sender=User)
def create_wallet_for_diner(sender, instance, created, **kwargs):
    if created and instance.role in (User.Role.ELEVE, User.Role.PERSONNEL):
        Wallet.objects.get_or_create(user=instance)
