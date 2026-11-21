"""Signaux de création automatique des profils alimentaires."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DietaryProfile, User


@receiver(post_save, sender=User)
def create_user_related_objects(sender, instance, created, **kwargs):
    if created and instance.role in (User.Role.ELEVE, User.Role.PERSONNEL):
        DietaryProfile.objects.get_or_create(user=instance)
