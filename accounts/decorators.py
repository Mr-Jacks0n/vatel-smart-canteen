"""Décorateurs et mixins de contrôle d'accès par rôle."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*allowed_roles):
    """Restreint l'accès d'une vue aux rôles autorisés (403 sinon)."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.role not in allowed_roles:
                raise PermissionDenied("Vous n'avez pas accès à cette page.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


eleve_required = role_required(User.Role.ELEVE)
personnel_required = role_required(User.Role.PERSONNEL)
diner_required = role_required(User.Role.ELEVE, User.Role.PERSONNEL)
parent_required = role_required(User.Role.PARENT)
equipe_required = role_required(User.Role.EQUIPE, User.Role.ADMIN)
admin_required = role_required(User.Role.ADMIN)


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied("Vous n'avez pas accès à cette page.")
        return super().dispatch(request, *args, **kwargs)
