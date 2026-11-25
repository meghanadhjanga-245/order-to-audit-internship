"""One-line audit trail writer used by every document service."""
from ..models import AuditLog


def log_action(*, entity, action, user=None, detail=""):
    return AuditLog.objects.create(
        entity_type=entity._meta.model_name,
        entity_id=entity.pk,
        action=action,
        detail=detail[:300],
        user=user if getattr(user, "pk", None) else None,
    )
