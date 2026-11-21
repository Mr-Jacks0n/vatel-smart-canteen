from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Department(models.Model):
    name = models.CharField("Département ou direction", max_length=120, unique=True)
    is_active = models.BooleanField("Actif", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Département / Direction"
        verbose_name_plural = "Départements / Directions"

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        email = self.normalize_email(email).lower()
        extra_fields.setdefault("role", User.Role.ELEVE)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("first_name", "Admin")
        extra_fields.setdefault("last_name", "Vatel")
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ELEVE = "ELEVE", "Élève"
        PERSONNEL = "PERSONNEL", "Personnel"
        PARENT = "PARENT", "Parent"
        EQUIPE = "EQUIPE", "Équipe cantine"
        ADMIN = "ADMIN", "Administrateur"

    email = models.EmailField("Adresse e-mail", unique=True)
    first_name = models.CharField("Prénom", max_length=80)
    last_name = models.CharField("Nom", max_length=80)
    phone = models.CharField("Téléphone", max_length=30, blank=True)
    school_id = models.CharField(
        "Identifiant scolaire / pro", max_length=50, blank=True
    )
    role = models.CharField(
        "Rôle", max_length=15, choices=Role.choices, default=Role.ELEVE
    )
    class_name = models.CharField("Classe / niveau", max_length=60, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="Département / Direction",
    )
    is_active = models.BooleanField("Actif", default=True)
    is_staff = models.BooleanField("Accès administration", default=False)
    date_joined = models.DateTimeField("Date d'inscription", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role="PERSONNEL", department__isnull=False)
                    | (~Q(role="PERSONNEL") & Q(department__isnull=True))
                ),
                name="accounts_user_department_only_for_personnel",
            ),
        ]

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()
        if self.role == self.Role.PERSONNEL and not self.department_id:
            raise ValidationError(
                {
                    "department": (
                        "Un département ou une direction est obligatoire pour le personnel."
                    )
                }
            )
        if self.role != self.Role.PERSONNEL and self.department_id:
            raise ValidationError(
                {
                    "department": (
                        "Le département ne doit être renseigné que pour le rôle Personnel."
                    )
                }
            )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_diner(self):
        return self.role in (self.Role.ELEVE, self.Role.PERSONNEL)

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"


class DietaryProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="dietary_profile",
        verbose_name="Utilisateur",
    )
    allergies = models.ManyToManyField(
        "menus.Allergen",
        blank=True,
        related_name="allergic_profiles",
        verbose_name="Allergies déclarées",
    )
    intolerances = models.ManyToManyField(
        "menus.Allergen",
        blank=True,
        related_name="intolerant_profiles",
        verbose_name="Intolérances",
    )
    regimes = models.ManyToManyField(
        "menus.Regime",
        blank=True,
        related_name="dietary_profiles",
        verbose_name="Régimes alimentaires",
    )
    preferences = models.CharField("Préférences", max_length=255, blank=True)
    notes = models.CharField("Précisions", max_length=500, blank=True)

    class Meta:
        verbose_name = "Profil alimentaire"
        verbose_name_plural = "Profils alimentaires"

    def __str__(self):
        return f"Profil alimentaire — {self.user.full_name}"


class ParentLink(models.Model):
    parent = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="child_links",
        limit_choices_to={"role": User.Role.PARENT},
        verbose_name="Parent",
    )
    child = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="parent_links",
        limit_choices_to={"role": User.Role.ELEVE},
        verbose_name="Enfant (élève)",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_parent_links",
        verbose_name="Validé par",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        verbose_name = "Lien parent-enfant"
        verbose_name_plural = "Liens parent-enfant"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "child"],
                name="accounts_unique_parent_child",
            )
        ]

    def clean(self):
        super().clean()
        if self.parent_id and self.parent.role != User.Role.PARENT:
            raise ValidationError(
                {"parent": "L'utilisateur sélectionné doit avoir le rôle Parent."}
            )
        if self.child_id and self.child.role != User.Role.ELEVE:
            raise ValidationError(
                {"child": "L'enfant lié doit avoir le rôle Élève."}
            )

    def __str__(self):
        return f"{self.parent.full_name} → {self.child.full_name}"
