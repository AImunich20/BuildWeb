"""Endpoints of a BuildWeb server (server.py) used by the desktop app.

  GET  /__bw/health             {"ok", "version"} (+ sites with a valid token)
  POST /__bw/deploy?site=…      body: a .bwsite file · updates the site, keeps server-side data
  GET  /__bw/pull?site=…        data created on the server: server-data collections, members, form posts, stats
  GET  /__bw/config             time zone, server clock, domains → sites
  POST /__bw/config             {"timezone"} · {"domains": {"shop.com": "my-shop"}} adds · {"remove_domains": [...]}
  GET  /__bw/domain-check?domain=…   200 when the domain belongs to a site (Caddy asks before getting a certificate)

Every call except a token-less health check needs ``Authorization: Bearer <BUILDWEB_DEPLOY_TOKEN>``.
"""
import hmac
import json
import os
import re
import shutil
import tempfile

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from buildweb import config

from . import backup, clock
from .models import Site


def token_ok(request):
    expected = os.environ.get("BUILDWEB_DEPLOY_TOKEN", "")
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    sent = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return bool(expected) and len(expected) >= 16 and hmac.compare_digest(sent, expected)


def denied():
    return JsonResponse({"ok": False, "error": "deploy token ไม่ถูกต้อง"}, status=401)


def health(request):
    body = {"ok": True, "app": "buildweb", "version": settings.VERSION, "server": True,
            "time": clock.info()["now"], "timezone": settings.TIME_ZONE}
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


# --- server settings set from the desktop app -----------------------------------------------------

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def saved_domains():
    return dict(config.load().get("server", {}).get("domains") or {})


def domains():
    """host → site slug: BUILDWEB_DOMAINS from .env plus the ones added from the app."""
    return {**saved_domains(), **settings.DOMAINS}


def _save_domains(d):
    raw = config._raw()
    raw.setdefault("server", {})["domains"] = d
    config.save(raw)


def config_json():
    return {"ok": True, **clock.info(), "domains": domains(), "env_domains": settings.DOMAINS,
            "sites": list(Site.objects.values_list("slug", flat=True))}


@csrf_exempt
def server_config(request):
    if not token_ok(request):
        return denied()
    if request.method == "POST":
        try:
            d = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"ok": False, "error": "JSON ไม่ถูกต้อง"}, status=400)
        if d.get("timezone"):
            if not clock.valid(d["timezone"]):
                return JsonResponse({"ok": False, "error": "ไม่รู้จักเขตเวลานี้"}, status=400)
            config.update("app", {"timezone": d["timezone"]})
            clock.apply(d["timezone"])
        if d.get("domains") or d.get("remove_domains"):
            cur = saved_domains()
            for host, slug in (d.get("domains") or {}).items():
                host = str(host).strip().lower().rstrip(".")
                if not DOMAIN_RE.match(host):
                    return JsonResponse({"ok": False, "error": f"โดเมนไม่ถูกต้อง: {host}"}, status=400)
                if not Site.objects.filter(slug=slug).exists():
                    return JsonResponse({"ok": False, "error": f"ไม่พบเว็บ {slug} บนเซิร์ฟเวอร์ (Deploy ก่อน)"}, status=400)
                cur[host] = slug
            for host in d.get("remove_domains") or []:
                cur.pop(str(host).strip().lower(), None)
            _save_domains(cur)
    return JsonResponse(config_json())


def domain_check(request):
    host = (request.GET.get("domain") or "").strip().lower().rstrip(".")
    ok = host in domains()
    return JsonResponse({"ok": ok}, status=200 if ok else 404)
