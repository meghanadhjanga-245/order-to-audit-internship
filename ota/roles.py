"""Named roles used for authorisation checks."""
from django.contrib.auth.models import Group

SALESMAN = "salesman"
ADMIN = "admin"
PRODUCTION = "production"
ACCOUNTANT = "accountant"
OWNER = "owner"

ALL_ROLES = [SALESMAN, ADMIN, PRODUCTION, ACCOUNTANT, OWNER]

ROLE_LABELS = {
    SALESMAN: "Salesman",
    ADMIN: "Factory admin",
    PRODUCTION: "Production supervisor",
    ACCOUNTANT: "Accountant / auditor",
    OWNER: "Owner",
}


def ensure_groups():
    """Idempotently create the five role groups."""
    for role in ALL_ROLES:
        Group.objects.get_or_create(name=role)


def roles_of(user):
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_ROLES)
    return set(user.groups.values_list("name", flat=True))


def has_role(user, *roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(roles_of(user) & set(roles))
