from django.conf import settings


def app_context(request):
    from . import team

    role = team.role_of(request) if not getattr(request, "is_public", False) else None
    return {
        "bw_role": role, "bw_team": team.is_team_request(request),
        "bw_user": request.user.get_username() if hasattr(request, "user") and request.user.is_authenticated else "",
        "app_version": settings.VERSION,
        "db_engine": settings.DB_ENGINE,
        "db_failed": settings.DB_FAILED,
    }
