from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    DietaryProfileForm,
    EmailLoginForm,
    PublicRegistrationForm,
    UserProfileForm,
)
from .models import DietaryProfile, User


def register_view(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    if request.method == "POST":
        form = PublicRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request,
                "Bienvenue ! Votre compte élève a bien été créé.",
            )
            return redirect("accounts:profile")
    else:
        form = PublicRegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if request.method == "POST":
        form = EmailLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Bonjour {user.first_name} !")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            if user.role == User.Role.ADMIN:
                return redirect("dashboard:home")
            if user.role == User.Role.EQUIPE:
                return redirect("canteen:kitchen")
            if user.role == User.Role.PARENT:
                return redirect("parents:home")
            return redirect("menus:week_menu")
    else:
        form = EmailLoginForm(request=request)
    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": next_url},
    )


@require_POST
@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "Vous avez été déconnecté.")
    return redirect("core:home")


@login_required
def profile_view(request):
    user = request.user
    dietary_profile = None
    if user.is_diner:
        dietary_profile, _ = DietaryProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        user_form = UserProfileForm(request.POST, instance=user)
        dietary_form = (
            DietaryProfileForm(request.POST, instance=dietary_profile)
            if dietary_profile is not None
            else None
        )
        valid = user_form.is_valid() and (dietary_form is None or dietary_form.is_valid())
        if valid:
            user_form.save()
            if dietary_form is not None:
                dietary_form.save()
            messages.success(request, "Votre profil a été mis à jour.")
            return redirect("accounts:profile")
    else:
        user_form = UserProfileForm(instance=user)
        dietary_form = (
            DietaryProfileForm(instance=dietary_profile)
            if dietary_profile is not None
            else None
        )

    return render(
        request,
        "accounts/profile.html",
        {
            "user_form": user_form,
            "dietary_form": dietary_form,
        },
    )
