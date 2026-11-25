"""Authentication and authorization module (D4)."""

from modules.auth.service import AdminPrincipal, StudentPrincipal, require_admin, require_student

__all__ = [
    "AdminPrincipal",
    "StudentPrincipal",
    "require_admin",
    "require_student",
]
