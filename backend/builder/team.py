"""Team access: other people use this BuildWeb app over the network (LAN / Tailscale) with their own login.

- The owner on this computer (the 127.0.0.1 editor server) is always signed in as admin, as before.
- The team server (config "team": {"enabled", "port"}) serves the same app on 0.0.0.0:<port>, flagged with
  TEAM_ENV_KEY; there everyone must log in, and what they may do depends on their role:
    admin      everything, including app settings
    developer  everything inside their sites (API, logic, members, publishing), no app settings
    editor     content only (CMS mode): page content, data rows, files, form messages of their sites
- Every write request is written to AuditLog.
"""
import logging
import re
import threading

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse

log = logging.getLogger("buildweb")
TEAM_ENV_KEY = "buildweb.team"

ADMIN_ONLY = [r"^/settings/", r"^/django-admin/", r"^/api/settings/", r"^/api/system/(restart|shutdown|reveal)", r"^/api/team",
              r"^/api/data/connections", r"^/api/import/", r"^/api/sites/create$", r"^/api/sites/\d+/(delete|duplicate)$"]
EDITOR_DENY = [
    r"^/sites/\d+/(api|logic|members|settings|export|stats)/",
    r"^/sites/\d+/edit-shared/",
    r"^/api/sites/\d+/(update|restapi|logic|members|publish|server|backups|backup\.bwsite|export|navbar|blog|seo|stats|releases|domain)",
    r"^/api/releases/",
    r"^/api/sites/\d+/(collections/(create|import-file|import-mysql)|pages/(create|reorder|sync-nav)|shared/extract)",
    r"^/api/collections/\d+/(update|delete|resync|pages)$",
    r"^/api/pages/\d+/(update|delete|duplicate|home)$",
    r"^/api/shared/\d+/update$",
    r"^/api/(apikeys|logic|members)/",
    r"^/api/data/",
]
SITE_PATHS = [
    (re.compile(r"^/(?:api/)?sites/(\d+)(?:/|$)"), None),
    (re.compile(r"^/api/pages/(\d+)/"), "Page"),
    (re.compile(r"^/api/collections/(\d+)"), "Collection"),
    (re.compile(r"^/api/assets/(\d+)/"), "Asset"),
    (re.compile(r"^/api/shared/(\d+)/"), "SharedSection"),
    (re.compile(r"^/api/submissions/(\d+)/"), "FormSubmission"),
    (re.compile(r"^/api/members/(\d+)/"), "SiteUser"),
    (re.compile(r"^/api/apikeys/(\d+)/"), "ApiKey"),
    (re.compile(r"^/api/revisions/(\d+)/"), "PageRevision"),
    (re.compile(r"^/api/releases/(\d+)/"), "Release"),
]


def is_team_request(request):
    return bool(request.META.get(TEAM_ENV_KEY))


def member(user):
    return getattr(user, "team", None) if user and user.is_authenticated else None


def role_of(request):
    """"owner" on this computer, else the team role (None = not signed in)."""
    if not is_team_request(request):
        return "owner"
    m = member(request.user)
    if m:
        return m.role
    return "admin" if request.user.is_authenticated and request.user.is_superuser else None


def site_of(path):
    """The site id a URL is about (None when it is not about one site)."""
    from . import models

    for rx, model in SITE_PATHS:
        m = rx.match(path)
        if not m:
            continue
        pk = int(m.group(1))
        if model is None:
            return pk
        if model == "PageRevision":
            obj = models.PageRevision.objects.filter(pk=pk).select_related("page").first()
            return obj.page.site_id if obj else -1
        obj = getattr(models, model).objects.filter(pk=pk).values_list("site_id", flat=True).first()
        return obj if obj is not None else -1
    m = re.match(r"^/preview/([\w-]+)", path)
    if m:
        s = models.Site.objects.filter(slug=m.group(1)).values_list("id", flat=True).first()
        return s if s is not None else -1
    return None


def allowed_sites(request):
    """None = every site; otherwise a set of site ids."""
    role = role_of(request)
    if role in ("owner", "admin"):
        return None
    m = member(request.user)
    return set(m.sites if m else [])


def check(request):
    """None when the request may go on, otherwise a 403 response."""
    role = role_of(request)
    if role in ("owner", "admin"):
        return None
    path = request.path
    if any(re.search(p, path) for p in ADMIN_ONLY):
        return deny(request, "เฉพาะผู้ดูแลเท่านั้น")
    if role == "editor" and any(re.search(p, path) for p in EDITOR_DENY):
        return deny(request, "บัญชีผู้แก้เนื้อหาทำส่วนนี้ไม่ได้")
    sid = site_of(path)
    if sid is not None and sid not in allowed_sites(request):
        return deny(request, "คุณไม่มีสิทธิ์ในเว็บนี้")
    return None


def deny(request, msg):
    if request.path.startswith("/api/"):
        return JsonResponse({"ok": False, "error": msg}, status=403)
    return HttpResponseForbidden(f'<!doctype html><meta charset="utf-8"><body style="font-family:system-ui;padding:60px;text-align:center">'
                                 f"<h1>403</h1><p>{msg}</p><a href=\"/\">กลับหน้าแรก</a>")


def audit(request, response):
    if request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith(("/api/", "/django-admin/")):
        return
    try:
        from .models import AuditLog

        user = request.user.get_username() if getattr(request, "user", None) and request.user.is_authenticated else ""
        who = user if is_team_request(request) else f"{user or 'owner'} (เครื่องนี้)"
        sid = site_of(request.path)
        AuditLog.objects.create(user=who[:150], method=request.method, path=request.path[:300], status=response.status_code,
                                site_id=sid if sid and sid > 0 else None,
                                ip=(request.META.get("REMOTE_ADDR") or "")[:64])
    except Exception:
        pass


# --- the team server ------------------------------------------------------------------------------

class TeamServer:
    def __init__(self):
        self.server = None
        self.port = None
        self.error = ""
        self._lock = threading.Lock()

    def apply_config(self):
        from buildweb import config

        t = config.load().get("team", {})
        with self._lock:
            self._stop()
            if t.get("enabled"):
                self._start(int(t.get("port") or 5055))

    def _start(self, port):
        from django.core.wsgi import get_wsgi_application
        from waitress.server import create_server

        django_app = get_wsgi_application()

        def app(environ, start_response):
            environ[TEAM_ENV_KEY] = True
            return django_app(environ, start_response)

        try:
            self.server = create_server(app, host="0.0.0.0", port=port, threads=8, ident="BuildWeb-team",
                                        max_request_body_size=1024 ** 3)
        except OSError as e:
            self.error = f"เปิดพอร์ต {port} ไม่ได้: {e.strerror or e}"
            return
        self.port, self.error = port, ""
        threading.Thread(target=self._run, args=(self.server,), daemon=True, name="team-server").start()
        log.info("team access on 0.0.0.0:%s", port)

    @staticmethod
    def _run(server):
        try:
            server.run()
        except Exception:
            pass

    def _stop(self):
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        self.server, self.port = None, None

    def status(self):
        from .hosting import lan_ip

        urls = [f"http://{lan_ip()}:{self.port}/"] if self.port else []
        return {"running": bool(self.server), "port": self.port, "urls": urls, "error": self.error}


server = TeamServer()
