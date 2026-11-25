from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .roles import has_role


def role_required(*roles):
    """Allow the view only for the given roles (superusers always pass)."""

    def decorator(view):
        @wraps(view)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied(
                    "Your role does not have access to this screen."
                )
            return view(request, *args, **kwargs)

        return _wrapped

    return decorator
