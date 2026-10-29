"""Serving sites: in-app preview (drafts included) and the hosting server (published only)."""
import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils._os import safe_join
from django.views.decorators.csrf import csrf_exempt

from buildweb import config

from . import forms, members, notify, render, restapi, stats
from .middleware import SITE_ENV_KEY
from .models import FormSubmission, Site

MAX_FIELDS = 60
MAX_VALUE = 5000


def serve(request, site, path, include_drafts):
    if path.endswith("__form"):
        return receive_form(request, site)
    root = request.path[:len(request.path) - len(path)] if path and request.path.endswith(path) else request.path
    base = request.build_absolute_uri(root if root.endswith("/") else root + "/")
    if path == "api" or path.startswith("api/"):
        return restapi.handle(request, site, path[3:], base_url=site.base_url or base, root_path=root or "/")
    found = render.resolve(site, path, include_drafts, base=base)
    if found is None:
        return not_found(site)
    kind = found[0]
    if kind == "text":
        resp = HttpResponse(found[2], content_type=f"{found[1]}; charset=utf-8")
    elif kind == "media":
        try:
            full = safe_join(settings.MEDIA_ROOT, found[1])
        except Exception:
            raise Http404
        try:
            resp = FileResponse(open(full, "rb"), content_type=mimetypes.guess_type(full)[0] or "application/octet-stream")
        except (FileNotFoundError, IsADirectoryError):
            return not_found(site)
    else:
        page = found[1]
        owner = not getattr(request, "is_public", False)  # the in-app preview sees every page
        user = members.current_user(request, site)
        if not owner and not members.can_view(page, user):
            return members_only(request, site, user, root)
        resp = HttpResponse(render.render_page(page, "__form", include_drafts=include_drafts, row=found[2],
                                               user=user, owner_view=owner),
                            content_type="text/html; charset=utf-8")
        if page.access:
            resp["Cache-Control"] = "private, no-store"
        if getattr(request, "is_public", False):
            stats.hit(site, request, path)
    resp["Cache-Control"] = "no-cache"
    return resp


def not_found(site):
    body = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>ไม่พบหน้านี้</title><body style=\"font-family:system-ui;display:grid;place-items:center;"
        'min-height:90vh;color:#374151;text-align:center"><div><h1 style="font-size:64px;margin:0">404</h1>'
        f'<p>ไม่พบหน้านี้</p><a href="./" style="color:#7c3aed">กลับหน้าแรกของ {site.name}</a></div>'
    )
    return HttpResponse(body, status=404)


@csrf_exempt
def receive_form(request, site):
    if request.method == "OPTIONS":
        resp = HttpResponse()
    elif request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    else:
        data = {}
        for key in list(request.POST.keys())[:MAX_FIELDS]:
            if key in ("_form", "_page", "csrfmiddlewaretoken"):
                continue
            values = [v[:MAX_VALUE] for v in request.POST.getlist(key)]
            data[key[:100]] = values[0] if len(values) == 1 else values
        if request.POST.get("_hp"):  # honeypot filled in: a bot. Pretend it worked.
            return cors(JsonResponse({"ok": True}))
        if not forms.allow(site, client_ip(request)):
            return cors(JsonResponse({"ok": False, "error": "ส่งบ่อยเกินไป กรุณารอสักครู่"}, status=429))
        data.pop("_hp", None)
        data.pop("_collection", None)
        page = site.pages.filter(slug=request.POST.get("_page", "")).first()
        saved = None
        if request.POST.get("_collection"):
            try:
                saved = forms.save_to_collection(site, request.POST.get("_collection"), data,
                                                 owner=members.current_user(request, site))
            except forms.FormError as e:
                return cors(JsonResponse({"ok": False, "error": str(e)}, status=400))
        sub = FormSubmission.objects.create(
            site=site, page=page, form_name=request.POST.get("_form", "")[:200], data=data,
            ip=client_ip(request)[:64],
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
        if saved:
            sub.data = {**sub.data, "_บันทึกลง": saved["label"]}
            sub.save(update_fields=["data"])
        notify.notify_submission(sub)
        from . import logic

        logic.emit(site, "form.submitted", {"form": sub.form_name, "page": page.slug if page else "", "data": data})
        resp = JsonResponse({"ok": True, "pending": bool(saved and saved["pending"])})
    return cors(resp)


def members_only(request, site, user, root):
    """A members-only page: send visitors to the login page, show members without the role a polite 403."""
    s = members.settings(site)
    if user is None:
        from urllib.parse import quote

        here = request.path[len(root):] if root and request.path.startswith(root) else request.path.lstrip("/")
        return HttpResponseRedirect(f"{root.rstrip('/')}/{s['pages']['login']}?next={quote(here)}")
    body = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>ไม่มีสิทธิ์เข้าถึง</title><body style="font-family:system-ui;display:grid;place-items:center;min-height:90vh;'
            'color:#374151;text-align:center"><div><h1 style="font-size:56px;margin:0">403</h1>'
            f'<p>หน้านี้สำหรับสมาชิกบางกลุ่มเท่านั้น</p><a href="{root}" style="color:#7c3aed">กลับหน้าแรก</a></div>')
    resp = HttpResponse(body, status=403)
    resp["Cache-Control"] = "private, no-store"
    return resp


def client_ip(request):
    return (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()


def cors(resp):
    # Exported copies of the site (opened from disk or XAMPP) may post here from another origin.
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# --- in-app preview -------------------------------------------------------------------------------

@csrf_exempt
def preview(request, slug, path=""):
    site = Site.objects.filter(slug=slug).first()
    if not site:
        raise Http404
    if not path and not request.path.endswith("/"):
        return HttpResponseRedirect(request.path + "/")
    return serve(request, site, path, include_drafts=True)


# --- hosting server -------------------------------------------------------------------------------

def domain_site(request):
    host = request.get_host().split(":")[0].lower()
    if settings.DOMAINS.get(host):
        return settings.DOMAINS[host]
    if settings.SERVER_MODE:  # domains connected from the desktop app (server_api.server_config)
        from .server_api import saved_domains

        return saved_domains().get(host)
    return None


@csrf_exempt
def public(request, path=""):
    pinned = request.META.get(SITE_ENV_KEY) or domain_site(request)
    if pinned:
        site = render.site_for_slug(pinned, published_only=True)
        if not site:
            raise Http404
        return serve(request, site, path, include_drafts=False)
    first, _, rest = path.partition("/")
    site = render.site_for_slug(first, published_only=True) if first else None
    if site:
        if not rest and not path.endswith("/") and not request.path.endswith("/"):
            return HttpResponseRedirect(request.path + "/")
        return serve(request, site, rest, include_drafts=False)
    default = config.load()["hosting"].get("default_site")
    site = render.site_for_slug(default, published_only=True) if default else None
    if site:
        return serve(request, site, path, include_drafts=False)
    if not path:
        return site_index()
    raise Http404


def site_index():
    sites = Site.objects.filter(published=True)
    items = "".join(f'<li><a href="{s.slug}/">{s.name}</a></li>' for s in sites) or "<li>ยังไม่มีเว็บที่เผยแพร่</li>"
    body = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>BuildWeb</title><body style="font-family:system-ui;max-width:640px;margin:60px auto;padding:0 20px;'
        f'color:#1f2937"><h1>เว็บไซต์บนเครื่องนี้</h1><ul style="line-height:2;font-size:18px">{items}</ul>'
    )
    return HttpResponse(body)
