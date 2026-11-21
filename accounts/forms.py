from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm

from menus.models import Allergen, Regime

from .models import DietaryProfile, User


class PublicRegistrationForm(UserCreationForm):
    """Inscription publique : crée uniquement un compte élève avec Matricule Vatel."""

    school_id = forms.CharField(
        label="Matricule Vatel",
        max_length=50,
        required=False,
        help_text="Votre numéro de matricule étudiant Vatel (ex. VTL-2026-042). Si laissé vide, un matricule provisoire vous sera attribué.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control font-monospace text-uppercase",
                "placeholder": "Ex. VTL-2026-042",
                "autocomplete": "off",
            }
        ),
    )
    first_name = forms.CharField(
        label="Prénom",
        max_length=80,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name", "placeholder": "Ex. Awa"}),
    )
    last_name = forms.CharField(
        label="Nom",
        max_length=80,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name", "placeholder": "Ex. Koné"}),
    )
    class_name = forms.CharField(
        label="Classe / Niveau",
        max_length=60,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Ex. Bachelor 3 · Management Hôtelier"}
        ),
    )
    email = forms.EmailField(
        label="Adresse e-mail",
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email", "placeholder": "prenom.nom@vatel.ci"}),
    )

    class Meta:
        model = User
        fields = ("school_id", "first_name", "last_name", "class_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})

    def clean_school_id(self):
        school_id = (self.cleaned_data.get("school_id") or "").strip().upper()
        if school_id and User.objects.filter(school_id__iexact=school_id).exists():
            raise forms.ValidationError("Ce numéro de matricule Vatel est déjà rattaché à un compte.")
        return school_id

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cette adresse e-mail.")
        return email

    def save(self, commit=True):
        import secrets

        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        school_id = self.cleaned_data.get("school_id")
        if not school_id:
            school_id = f"VTL-2026-{secrets.randbelow(9000) + 1000}"
        user.school_id = school_id
        user.class_name = (self.cleaned_data.get("class_name") or "").strip()
        user.role = User.Role.ELEVE
        user.department = None
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.full_clean()
            user.save()
        return user


class EmailLoginForm(forms.Form):
    """Connexion par adresse e-mail OU par numéro de matricule Vatel."""

    email = forms.CharField(
        label="Adresse e-mail ou Matricule Vatel",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "username",
                "placeholder": "prenom.nom@vatel.ci ou VTL-2026-001",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "current-password"}
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        identifier = (cleaned_data.get("email") or "").strip()
        password = cleaned_data.get("password")
        if identifier and password:
            login_email = identifier.lower()
            if "@" not in identifier:
                matched = User.objects.filter(school_id__iexact=identifier).first()
                if matched:
                    login_email = matched.email
            self.user_cache = authenticate(
                self.request,
                username=login_email,
                password=password,
            )
            if self.user_cache is None or not self.user_cache.is_active:
                raise forms.ValidationError(
                    "Identifiants incorrects. Vérifiez votre adresse e-mail (ou matricule Vatel) et votre mot de passe."
                )
        return cleaned_data

    def get_user(self):
        return self.user_cache


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("school_id", "first_name", "last_name", "phone", "class_name")
        widgets = {
            "school_id": forms.TextInput(
                attrs={"class": "form-control font-monospace text-uppercase", "placeholder": "Ex. VTL-2026-042"}
            ),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "class_name": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school_id"].label = "Matricule Vatel"
        if self.instance and self.instance.role != User.Role.ELEVE:
            self.fields.pop("class_name", None)


class DietaryProfileForm(forms.ModelForm):
    allergies = forms.ModelMultipleChoiceField(
        label="Allergies déclarées",
        queryset=Allergen.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    intolerances = forms.ModelMultipleChoiceField(
        label="Intolérances",
        queryset=Allergen.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    regimes = forms.ModelMultipleChoiceField(
        label="Régimes alimentaires",
        queryset=Regime.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DietaryProfile
        fields = ("allergies", "intolerances", "regimes", "preferences", "notes")
        widgets = {
            "preferences": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
