"""Endpoints of a BuildWeb server (server.py) used by the desktop app.

  GET  /__bw/health             {"ok", "version"} (+ sites with a valid token)
  POST /__bw/deploy?site=…      body: a .bwsite file · updates the site, keeps server-side data
  GET  /__bw/pull?site=…        data created on the server: server-data collections, members, form posts, stats

Every call except a token-less health check needs ``Authorization: Bearer <BUILDWEB_DEPLOY_TOKEN>``.
"""
import hmac
import json
import os
import shutil
import tempfile

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import backup
from .models import Site


def token_ok(request):
    expected = os.environ.get("BUILDWEB_DEPLOY_TOKEN", "")
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    sent = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return bool(expected) and len(expected) >= 16 and hmac.compare_digest(sent, expected)


def denied():
    return JsonResponse({"ok": False, "error": "deploy token ไม่ถูกต้อง"}, status=401)


def health(request):
    body = {"ok": True, "app": "buildweb", "version": settings.VERSION, "server": True}
    if token_ok(request):
        body["sites"] = [{"slug": s.slug, "name": s.name, "updated_at": s.updated_at.isoformat()} for s in Site.objects.all()]
        body["database"] = settings.DB_ENGINE
    return JsonResponse(body)


@csrf_exempt
def deploy(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    if not token_ok(request):
        return denied()
    with tempfile.TemporaryFile() as tmp:
        shutil.copyfileobj(request, tmp, 1 << 20)  # streamed: bundles can be bigger than the in-memory limit
        tmp.seek(0)
        try:
            _, d = backup.read_bundle(tmp)
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        current = Site.objects.filter(slug=d["site"]["slug"]).first()
        if current:  # a copy of what was live, in case the deploy has to be undone
            try:
                backup.auto_backup(current)
            except Exception:
                pass
        tmp.seek(0)
        site = backup.import_site(tmp, mode="deploy")
    return JsonResponse({"ok": True, "site": site.slug, "created": current is None,
                         "pages": site.pages.count(), "collections": site.collections.count()})


def pull(request):
    if not token_ok(request):
        return denied()
    site = Site.objects.filter(slug=request.GET.get("site", "")).first()
    if not site:
        return JsonResponse({"ok": False, "error": "ไม่พบเว็บนี้บนเซิร์ฟเวอร์"}, status=404)
    d = backup.site_dict(site, include_secrets=False)
    owned = [c for c in d["collections"] if backup.server_owned(c)]
    return JsonResponse({"ok": True, "site": site.slug, "collections": {c["slug"]: c["records"] for c in owned},
                         "members": d["members"], "submissions": d["submissions"], "stats": d["stats"]},
                        json_dumps_params={"ensure_ascii": False})
