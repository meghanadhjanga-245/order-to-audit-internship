from .models import CompanySettings
from .roles import ROLE_LABELS, roles_of

DEMO_USERS = [
    {
        "username": "admin",
        "role": "admin",
        "label": "Factory Admin",
        "badge": "Desk / Invoicing",
        "icon": "👑",
    },
    {
        "username": "production",
        "role": "production",
        "label": "Production Supervisor",
        "badge": "Floor / BOM",
        "icon": "🏭",
    },
    {
        "username": "salesman_a",
        "role": "salesman",
        "label": "Salesman A",
        "badge": "Retailer A (TN)",
        "icon": "📱",
    },
    {
        "username": "salesman_b",
        "role": "salesman",
        "label": "Salesman B",
        "badge": "Distributor B (KA)",
        "icon": "🚚",
    },
    {
        "username": "accountant",
        "role": "accountant",
        "label": "Auditor / Accountant",
        "badge": "GST & Reports",
        "icon": "📊",
    },
    {
        "username": "owner",
        "role": "owner",
        "label": "Owner",
        "badge": "Oversight",
        "icon": "💼",
    },
]


def role_context(request):
    """Expose the current user's roles and demo helpers to every template."""
    roles = sorted(roles_of(request.user))
    try:
        company = CompanySettings.get()
    except Exception:
        company = None

    return {
        "user_roles": roles,
        "role_labels": [ROLE_LABELS.get(r, r.title()) for r in roles],
        "primary_role": ROLE_LABELS.get(roles[0], "") if roles else "",
        "demo_users": DEMO_USERS,
        "current_username": request.user.username if request.user.is_authenticated else "",
        "company": company,
    }
