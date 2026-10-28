from django.conf import settings


def app_context(request):
    return {
        "app_version": settings.VERSION,
        "db_engine": settings.DB_ENGINE,
        "db_failed": settings.DB_FAILED,
    }
