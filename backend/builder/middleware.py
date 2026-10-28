from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import OperationalError
from django.http import HttpResponse, JsonResponse
from django.utils.html import escape
from django.shortcuts import redirect

PUBLIC_ENV_KEY = "buildweb.public"
SITE_ENV_KEY = "buildweb.site"  # set by a site's own hosting port: that site is served at "/"


class PublicSiteMiddleware:
    """Requests from the hosting server (flagged in the WSGI environ) only see published sites."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_public = bool(request.META.get(PUBLIC_ENV_KEY))
        if request.is_public:
            request.urlconf = "builder.urls_public"
        return self.get_response(request)


class LocalAdminMiddleware:
    """The editor runs on 127.0.0.1 inside the desktop app, so the owner is signed in automatically
    (Django admin included). The hosting server never gets here with a session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(("/api/system/restart", "/api/system/shutdown")):
            return self.get_response(request)
        try:
            if not request.is_public and not request.user.is_authenticated and not settings.DB_FAILED:
                User = get_user_model()
                user = User.objects.filter(is_superuser=True).order_by("id").first()
                if user is None:
                    user = User.objects.create_superuser("admin", "", None)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        except OperationalError as e:
            return database_down(request, e)
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, OperationalError):
            return database_down(request, exception)
        return None


def database_down(request, error):
    """The database (usually XAMPP MySQL) went away while the app was running."""
    msg = "ฐานข้อมูลขาดการเชื่อมต่อ — ตรวจสอบว่า MySQL ใน XAMPP ยังเปิดอยู่"
    if request.path.startswith("/api/") or request.path.endswith("__form"):
        return JsonResponse({"ok": False, "error": msg}, status=503)
    if getattr(request, "is_public", False):
        return HttpResponse('<!doctype html><meta charset="utf-8"><title>ปิดปรับปรุงชั่วคราว</title>'
                            '<body style="font-family:system-ui;text-align:center;padding:80px 20px;color:#374151">'
                            "<h1>เว็บไซต์ปิดปรับปรุงชั่วคราว</h1><p>กรุณากลับมาใหม่อีกครั้งในภายหลัง</p>", status=503)
    html = f"""<!doctype html><meta charset="utf-8"><title>ฐานข้อมูลขาดการเชื่อมต่อ</title>
<body style="font-family:-apple-system,system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;background:#f7f7fb;color:#1f2433">
<div style="background:#fff;padding:36px 40px;border-radius:18px;box-shadow:0 20px 50px -25px rgba(0,0,0,.3);max-width:520px;text-align:center">
<div style="font-size:46px">⛁</div><h2>{msg}</h2><p style="color:#6b7280">{escape(str(error)[:200])}</p>
<p style="color:#6b7280">เปิด MySQL แล้วกด “ลองใหม่” — ถ้ายังเชื่อมต่อไม่ได้ โปรแกรมจะเข้าโหมดปลอดภัยให้แก้การตั้งค่า</p>
<button onclick="this.disabled=true;this.textContent='กำลังรีสตาร์ท...';fetch('/api/system/restart',{{method:'POST',headers:{{'X-BuildWeb':'1'}}}}).finally(()=>setTimeout(()=>location.href='/',6000))"
style="font:inherit;padding:11px 22px;border:0;border-radius:10px;background:linear-gradient(135deg,#7c3aed,#06b6d4);color:#fff;cursor:pointer">↻ ลองใหม่</button></div>"""
    return HttpResponse(html, status=503)


class DatabaseSafeModeMiddleware:
    """When the configured MySQL could not be reached at start, only the database settings work."""

    ALLOWED = ("/settings/database", "/static/", "/api/settings/", "/api/system/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DB_FAILED and not request.is_public and not request.path.startswith(self.ALLOWED):
            return redirect("/settings/database/")
        return self.get_response(request)
