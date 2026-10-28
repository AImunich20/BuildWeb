"""JSON API used by the dashboard, the site manager and the editor."""
import json
import re
import subprocess
from functools import wraps
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from buildweb import config

from . import dbtools, exporter, importer, notify, sections, services
from .hosting import server as hosting
from .models import DEFAULT_THEME, Asset, AssetFolder, FormSubmission, Page, PageRevision, SharedSection, Site

MAX_UPLOAD = 200 * 1024 * 1024
SAFE_NAME_RE = re.compile(r"[^\w.\-ก-๙ ]+")


class ApiError(Exception):
    def __init__(self, msg, status=400, field=None):
        super().__init__(msg)
        self.status, self.field = status, field


def api(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            if request.method == "POST" and request.content_type == "application/json":
                request.json = json.loads(request.body or b"{}")
            else:
                request.json = {}
            result = view(request, *args, **kwargs)
        except ApiError as e:
            return JsonResponse({"ok": False, "error": str(e), "field": e.field}, status=e.status)
        except (ValueError, RuntimeError, OSError) as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        if isinstance(result, JsonResponse):
            return result
        return JsonResponse({"ok": True, **(result or {})})

    return wrapper


def body(request):
    return request.json or request.POST


def as_bool(v):
    return v in (True, "1", "true", "on", 1)


# --- sites ----------------------------------------------------------------------------------------

def site_json(site):
    home = site.home_page()
    return {
        "id": site.id, "name": site.name, "slug": site.slug, "description": site.description,
        "language": site.language, "theme": site.get_theme(), "favicon": site.favicon, "head_code": site.head_code,
        "custom_css": site.custom_css, "custom_js": site.custom_js, "form_endpoint": site.form_endpoint,
        "published": site.published, "updated_at": site.updated_at.isoformat(),
        "host_port": site.host_port, "use_base_styles": site.use_base_styles,
        "home_page": home.id if home else None, "page_count": site.pages.count(),
        "shared": [shared_json(sec) for sec in site.shared_sections.order_by("-kind")],
    }


def shared_json(sec):
    return {"id": sec.id, "kind": sec.kind, "label": sec.label, "enabled": sec.enabled,
            "edit_url": f"/sites/{sec.site_id}/edit-shared/{sec.kind}/", "updated_at": sec.updated_at.isoformat()}


@require_POST
@api
def site_create(request):
    d = body(request)
    name = (d.get("name") or "").strip()
    if not name:
        raise ApiError("กรุณาตั้งชื่อเว็บ", field="name")
    site = services.create_site(name, d.get("template") or "blank", d.get("description", ""))
    return {"site": site_json(site), "editor": f"/sites/{site.id}/edit/{site.home_page().id}/"}


@require_POST
@api
def site_update(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    for f in ("name", "description", "language", "favicon", "head_code", "custom_css", "custom_js", "form_endpoint"):
        if f in d:
            setattr(site, f, d[f] if d[f] is not None else "")
    rehost = False
    if "published" in d and as_bool(d["published"]) != site.published:
        site.published = as_bool(d["published"])
        rehost = site.host_port is not None
    if "host_port" in d:
        port = int(d["host_port"]) if str(d["host_port"] or "").strip() else None
        if port is not None:
            h = config.load()["hosting"]
            if not 1024 <= port <= 65535 or port in (settings.ADMIN_PORT, int(h["port"])):
                raise ApiError("พอร์ตต้องอยู่ระหว่าง 1024-65535 และไม่ซ้ำกับพอร์ตของโปรแกรม/พอร์ตโฮสติ้งหลัก", field="host_port")
            if Site.objects.filter(host_port=port).exclude(pk=site.pk).exists():
                raise ApiError("มีเว็บอื่นใช้พอร์ตนี้แล้ว", field="host_port")
        rehost = rehost or port != site.host_port
        site.host_port = port
    if "slug" in d and d["slug"] != site.slug:
        slug = (d["slug"] or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise ApiError("ชื่อในลิงก์ใช้ได้เฉพาะ a-z, 0-9 และ -", field="slug")
        if Site.objects.filter(slug=slug).exclude(pk=site.pk).exists():
            raise ApiError("มีเว็บที่ใช้ชื่อนี้แล้ว", field="slug")
        site.slug = slug
    if "theme" in d and isinstance(d["theme"], dict):
        site.theme = {k: str(v) for k, v in {**site.get_theme(), **d["theme"]}.items() if k in DEFAULT_THEME}
    if "use_base_styles" in d:
        site.use_base_styles = as_bool(d["use_base_styles"])
    if not site.name.strip():
        raise ApiError("กรุณาตั้งชื่อเว็บ", field="name")
    site.save()
    if rehost and hosting.running:
        hosting.apply_config()
    return {"site": site_json(site), "hosting": hosting.status(with_tailscale=False) if rehost else None}


@require_POST
@api
def site_delete(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    for a in site.assets.all():
        a.file.delete(save=False)
    site.delete()
    h = config.load()["hosting"]
    if h.get("default_site") == site.slug:
        config.update("hosting", {"default_site": None})
    return {}


@require_POST
@api
def site_duplicate(request, site_id):
    return {"site": site_json(services.duplicate_site(get_object_or_404(Site, pk=site_id)))}


# --- pages ----------------------------------------------------------------------------------------

PAGE_FIELDS = ("title", "nav_label", "seo_title", "seo_description", "seo_keywords", "og_image", "head_code",
               "custom_css", "custom_js")


def page_json(p):
    return {
        "id": p.id, "title": p.title, "slug": p.slug, "is_home": p.is_home, "status": p.status,
        "show_in_nav": p.show_in_nav, "nav_label": p.nav_label, "nav_order": p.nav_order,
        "use_header": p.use_header, "use_footer": p.use_footer,
        "parent": p.parent_id, "seo_title": p.seo_title, "seo_description": p.seo_description,
        "seo_keywords": p.seo_keywords, "og_image": p.og_image, "noindex": p.noindex, "head_code": p.head_code,
        "custom_css": p.custom_css, "custom_js": p.custom_js, "filename": p.filename,
        "updated_at": p.updated_at.isoformat(), "edit_url": f"/sites/{p.site_id}/edit/{p.id}/",
    }


def apply_page_fields(page, d):
    for f in PAGE_FIELDS:
        if f in d:
            setattr(page, f, (d[f] or "").strip() if f in ("title", "nav_label", "seo_title") else (d[f] or ""))
    for f in ("show_in_nav", "noindex", "use_header", "use_footer"):
        if f in d:
            setattr(page, f, as_bool(d[f]))
    if "status" in d and d["status"] in (Page.DRAFT, Page.PUBLISHED):
        page.status = d["status"]
    if "parent" in d:
        pid = d["parent"] or None
        if pid and (int(pid) == page.pk or not page.site.pages.filter(pk=pid).exists()):
            raise ApiError("เลือกหน้าแม่ไม่ถูกต้อง", field="parent")
        page.parent_id = pid
    if not page.title:
        raise ApiError("กรุณาใส่ชื่อหน้า", field="title")


@require_GET
@api
def page_list(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    return {"pages": [page_json(p) for p in site.pages.all()]}


@require_POST
@api
def page_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    title = (d.get("title") or "").strip()
    if not title:
        raise ApiError("กรุณาใส่ชื่อหน้า", field="title")
    slug = (d.get("slug") or "").strip().lower() or services.unique_page_slug(site, title)
    err = services.validate_page_slug(site, slug)
    if err:
        raise ApiError(err, field="slug")
    probe = Page(site=site, title=title)
    apply_page_fields(probe, d)
    fields = {f: getattr(probe, f) for f in PAGE_FIELDS + ("show_in_nav", "noindex", "use_header", "use_footer", "status", "parent_id")
              if f != "title"}
    page = services.create_page(site, title, slug, d.get("layout") or "basic", **fields)
    if as_bool(d.get("is_home")):
        page.make_home()
    return {"page": page_json(page)}


@require_POST
@api
def page_update(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    d = body(request)
    if "slug" in d and d["slug"] != page.slug:
        slug = (d["slug"] or "").strip().lower()
        err = services.validate_page_slug(page.site, slug, exclude_id=page.pk)
        if err:
            raise ApiError(err, field="slug")
        page.slug = slug
    apply_page_fields(page, d)
    page.save()
    if as_bool(d.get("is_home")):
        page.make_home()
    page.site.touch()
    return {"page": page_json(page)}


@require_POST
@api
def page_delete(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    if page.site.pages.count() == 1:
        raise ApiError("ต้องมีอย่างน้อยหนึ่งหน้า")
    services.delete_page(page)
    return {}


@require_POST
@api
def page_duplicate(request, page_id):
    return {"page": page_json(services.duplicate_page(get_object_or_404(Page, pk=page_id)))}


@require_POST
@api
def page_make_home(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    page.make_home()
    return {"page": page_json(page)}


@require_POST
@api
def page_reorder(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    ids = [int(i) for i in body(request).get("ids", [])]
    with transaction.atomic():
        for i, pid in enumerate(ids):
            site.pages.filter(pk=pid).update(nav_order=i)
    site.touch()
    return {}


@require_POST
@api
def page_nav_sync(request, site_id):
    """Rewrite the menu (navbar + footer menu built from template sections) on every page to match
    the current page list."""
    site = get_object_or_404(Site, pk=site_id)
    pages = services.page_dicts(site)
    n = 0
    for p in site.pages.all():
        new = services.personalize(p.html, site.name, pages)
        if new != p.html:
            p.html, p.project_data = new, {}
            p.save(update_fields=["html", "project_data", "updated_at"])
            n += 1
    return {"updated": n}


# --- editor storage -------------------------------------------------------------------------------

@api
def page_project(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    if request.method == "POST":
        d = body(request)
        services.save_editor(page, d.get("project"), d.get("html", ""), d.get("css", ""), d.get("js", ""))
        return {"saved_at": page.updated_at.isoformat()}
    return {"project": page.project_data or None, "html": page.html, "css": page.css}


@api
def shared_project(request, shared_id):
    sec = get_object_or_404(SharedSection, pk=shared_id)
    if request.method == "POST":
        d = body(request)
        services.save_shared(sec, d.get("project"), d.get("html", ""), d.get("css", ""), d.get("js", ""))
        return {"saved_at": sec.updated_at.isoformat()}
    return {"project": sec.project_data or None, "html": sec.html, "css": sec.css}


@require_POST
@api
def shared_update(request, shared_id):
    sec = get_object_or_404(SharedSection, pk=shared_id)
    if "enabled" in body(request):
        sec.enabled = as_bool(body(request)["enabled"])
        sec.save(update_fields=["enabled", "updated_at"])
    return {"shared": shared_json(sec)}


@require_POST
@api
def shared_extract(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    return {"updated": services.extract_shared(site), "site": site_json(site)}


@require_GET
@api
def revision_list(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    return {"revisions": [{"id": r.id, "note": r.note, "created_at": r.created_at.isoformat()}
                          for r in page.revisions.all()]}


@require_POST
@api
def revision_snapshot(request, page_id):
    page = get_object_or_404(Page, pk=page_id)
    rev = PageRevision.snapshot(page, (body(request).get("note") or "บันทึกเวอร์ชัน")[:200])
    return {"id": rev.id}


@require_POST
@api
def revision_restore(request, rev_id):
    services.restore_revision(get_object_or_404(PageRevision, pk=rev_id))
    return {}


@require_GET
@api
def editor_sections(request):
    return {
        "sections": [{"id": s["id"], "label": s["label"], "category": s["category"], "icon": s["icon"],
                      "content": sections.block_content(s)} for s in sections.SECTIONS],
        "layouts": sections.PAGE_LAYOUTS,
    }


# --- files ----------------------------------------------------------------------------------------

def clean_folder(folder):
    parts = [SAFE_NAME_RE.sub("", p).strip() for p in (folder or "").replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    return "/".join(parts)


def asset_json(a):
    return {"id": a.id, "name": a.name, "folder": a.folder, "kind": a.kind, "size": a.size, "alt": a.alt,
            "url": a.url, "src": a.url, "type": "image" if a.kind == "image" else a.kind,
            "created_at": a.created_at.isoformat()}


def folder_list(site):
    folders = set(site.assets.exclude(folder="").values_list("folder", flat=True))
    folders |= set(site.folders.values_list("path", flat=True))
    out = set()
    for f in folders:
        parts = f.split("/")
        for i in range(1, len(parts) + 1):
            out.add("/".join(parts[:i]))
    return sorted(out)


@require_GET
@api
def asset_list(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    qs = site.assets.all()
    if "folder" in request.GET:
        qs = qs.filter(folder=clean_folder(request.GET["folder"]))
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    if request.GET.get("q"):
        qs = qs.filter(name__icontains=request.GET["q"])
    return {"assets": [asset_json(a) for a in qs], "folders": folder_list(site),
            "total_size": sum(site.assets.values_list("size", flat=True))}


@require_POST
@api
def asset_upload(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    folder = clean_folder(request.POST.get("folder", ""))
    files = request.FILES.getlist("files") or request.FILES.getlist("files[]") or list(request.FILES.values())
    if not files:
        raise ApiError("ไม่พบไฟล์ที่อัปโหลด")
    created = []
    for f in files:
        if f.size > MAX_UPLOAD:
            raise ApiError(f"ไฟล์ {f.name} ใหญ่เกิน 200 MB")
        name = SAFE_NAME_RE.sub("_", PurePosixPath(f.name).name).strip() or "file"
        a = Asset(site=site, name=name, folder=folder, kind=Asset.kind_for(name), size=f.size)
        a.file.save(name, f, save=False)
        a.name = PurePosixPath(a.file.name).name
        a.save()
        created.append(asset_json(a))
    # GrapesJS asset manager expects {"data": [...]}
    return {"data": created, "assets": created}


@require_POST
@api
def asset_update(request, asset_id):
    a = get_object_or_404(Asset, pk=asset_id)
    d = body(request)
    if "alt" in d:
        a.alt = (d["alt"] or "")[:255]
    new_folder = clean_folder(d["folder"]) if "folder" in d else a.folder
    new_name = SAFE_NAME_RE.sub("_", (d.get("name") or a.name)).strip() or a.name
    if new_folder != a.folder or new_name != a.name:
        old_path, old_url = a.file.name, a.url
        a.folder = new_folder
        target = Asset.file.field.upload_to(a, new_name)
        if default_storage.exists(target):
            raise ApiError("มีไฟล์ชื่อนี้อยู่ในโฟลเดอร์ปลายทางแล้ว", field="name")
        src = Path(settings.MEDIA_ROOT) / old_path
        dst = Path(settings.MEDIA_ROOT) / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        a.file.name, a.name = target, new_name
        # Keep pages that use the file working.
        new_url = a.file.url
        for p in a.site.pages.filter(html__contains=old_url):
            p.html = p.html.replace(old_url, new_url)
            p.css = p.css.replace(old_url, new_url)
            p.project_data = json.loads(json.dumps(p.project_data).replace(old_url, new_url))
            p.save(update_fields=["html", "css", "project_data"])
    a.save()
    return {"asset": asset_json(a)}


@require_POST
@api
def asset_delete(request, asset_id):
    a = get_object_or_404(Asset, pk=asset_id)
    used = [p.title for p in a.site.pages.filter(html__contains=a.url)]
    if used and not as_bool(body(request).get("force")):
        return JsonResponse({"ok": False, "in_use": used, "error": "ไฟล์นี้ถูกใช้อยู่ในหน้า: " + ", ".join(used)}, status=409)
    a.file.delete(save=False)
    a.delete()
    return {}


@require_POST
@api
def folder_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    path = clean_folder(body(request).get("path"))
    if not path:
        raise ApiError("กรุณาตั้งชื่อโฟลเดอร์", field="path")
    AssetFolder.objects.get_or_create(site=site, path=path)
    return {"folders": folder_list(site)}


@require_POST
@api
def folder_delete(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    path = clean_folder(body(request).get("path"))
    if site.assets.filter(folder=path).exists() or site.assets.filter(folder__startswith=path + "/").exists():
        raise ApiError("โฟลเดอร์ยังมีไฟล์อยู่ ลบหรือย้ายไฟล์ออกก่อน")
    site.folders.filter(path=path).delete()
    site.folders.filter(path__startswith=path + "/").delete()
    return {"folders": folder_list(site)}


# --- form submissions -----------------------------------------------------------------------------

@require_GET
@api
def submission_list(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    subs = site.submissions.select_related("page")[:1000]
    return {"submissions": [{"id": s.id, "form": s.form_name, "page": s.page.title if s.page else "", "data": s.data,
                             "ip": s.ip, "is_read": s.is_read, "created_at": s.created_at.isoformat()} for s in subs],
            "unread": site.submissions.filter(is_read=False).count()}


@require_POST
@api
def submission_action(request, sub_id, action):
    s = get_object_or_404(FormSubmission, pk=sub_id)
    if action == "delete":
        s.delete()
    elif action == "read":
        s.is_read = as_bool(body(request).get("value", True))
        s.save(update_fields=["is_read"])
    return {}


@require_POST
@api
def submission_read_all(request, site_id):
    get_object_or_404(Site, pk=site_id).submissions.update(is_read=True)
    return {}


# --- export ---------------------------------------------------------------------------------------

@require_POST
@api
def site_export(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    target = d.get("target") or "downloads"
    fmt = d.get("format") or "folder"
    drafts, php = as_bool(d.get("include_drafts")), as_bool(d.get("php_forms"))
    custom = (d.get("custom_path") or "").strip()
    if target == "xampp" and not config.XAMPP_HTDOCS.exists():
        raise ApiError("ไม่พบ XAMPP ที่ /Applications/XAMPP")
    config.update("export", {"last_target": target, "custom_path": custom})
    if fmt == "zip":
        folder = exporter.target_dir(target, site, custom).parent
        path, count = exporter.export_zip(site, folder, drafts, php)
        return {"path": str(path), "count": count}
    dest = exporter.target_dir(target, site, custom)
    path, count = exporter.export_folder(site, dest, drafts, php)
    url = f"http://localhost/{site.slug}/" if target == "xampp" else ""
    return {"path": str(path), "count": count, "url": url}


# --- system helpers -------------------------------------------------------------------------------

@require_POST
@api
def reveal(request):
    path = Path(body(request).get("path", "")).expanduser()
    if not path.exists():
        raise ApiError("ไม่พบไฟล์/โฟลเดอร์")
    subprocess.Popen(["open", "-R", str(path)])
    return {}


@require_POST
@api
def open_url(request):
    url = body(request).get("url", "")
    if not re.match(r"^https?://", url) and not url.endswith(".app"):
        raise ApiError("ลิงก์ไม่ถูกต้อง")
    subprocess.Popen(["open", url])
    return {}


# --- settings: hosting ----------------------------------------------------------------------------

@api
def hosting_settings(request):
    if request.method == "POST":
        d = body(request)
        values = {}
        if "enabled" in d:
            values["enabled"] = as_bool(d["enabled"])
        if "lan" in d:
            values["lan"] = as_bool(d["lan"])
        if "port" in d:
            port = int(d["port"])
            if not 1024 <= port <= 65535 or port == settings.ADMIN_PORT:
                raise ApiError("พอร์ตต้องอยู่ระหว่าง 1024-65535 และไม่ซ้ำกับพอร์ตของโปรแกรม", field="port")
            values["port"] = port
        if "default_site" in d:
            values["default_site"] = d["default_site"] or None
        if "tailscale" in d:
            values["tailscale"] = as_bool(d["tailscale"])
        if "funnel" in d:
            values["funnel"] = as_bool(d["funnel"])
        if "tailscale_port" in d:
            tp = int(d["tailscale_port"] or 443)
            if not 1 <= tp <= 65535:
                raise ApiError("พอร์ต HTTPS ไม่ถูกต้อง", field="tailscale_port")
            if values.get("funnel", config.load()["hosting"].get("funnel")) and tp not in (443, 8443, 10000):
                raise ApiError("Funnel ใช้ได้เฉพาะพอร์ต 443, 8443 หรือ 10000", field="tailscale_port")
            values["tailscale_port"] = tp
        config.update("hosting", values)
        if not hosting.apply_config():
            config.update("hosting", {"enabled": False})
            raise ApiError(hosting.error)
    return {"hosting": hosting.status()}


# --- settings: database ---------------------------------------------------------------------------

def db_from(d):
    cur = config.load()["db"]
    return {
        "engine": d.get("engine", cur["engine"]),
        "host": (d.get("host") or "127.0.0.1").strip(),
        "port": int(d.get("port") or 3306),
        "user": (d.get("user") or "root").strip(),
        "password": d.get("password", "") or "",
        "name": re.sub(r"[^A-Za-z0-9_]", "", d.get("name") or "buildweb") or "buildweb",
        "socket": (d.get("socket") or "").strip(),
    }


@require_GET
@api
def db_status(request):
    db = dict(config.load()["db"])
    db["password_set"] = bool(db.pop("password", ""))
    info = {"config": db, "active_engine": settings.DB_ENGINE, "failed": settings.DB_FAILED, "xampp": dbtools.xampp_info()}
    if settings.DB_ENGINE == "mysql" and not settings.DB_FAILED:
        try:
            info["server"] = dbtools.test_mysql(config.load()["db"])
        except RuntimeError as e:
            info["server_error"] = str(e)
    return info


@require_POST
@api
def db_test(request):
    db = db_from(body(request))
    if not body(request).get("password") and config.load()["db"]["password"] and body(request).get("keep_password"):
        db["password"] = config.load()["db"]["password"]
    return {"server": dbtools.test_mysql(db)}


@require_POST
@api
def db_switch(request):
    d = body(request)
    target = db_from(d)
    if d.get("keep_password") and not d.get("password"):
        target["password"] = config.load()["db"]["password"]
    mode = d.get("mode", "copy")  # copy | replace | existing
    current = None if not settings.DB_FAILED else dict(config.DEFAULTS["db"])
    if settings.DB_FAILED and target["engine"] == "mysql":
        # Fixing a broken MySQL connection: just test and save; the data is still in MySQL.
        dbtools.test_mysql(target)
        dbtools.create_database(target)
        dbtools.manage(["migrate", "--noinput"], db=target)
        config.update("db", target)
        steps = ["เชื่อมต่อสำเร็จ — กำลังรีสตาร์ท"]
    else:
        steps = dbtools.switch_database(target, copy_data=mode != "existing", current=current, replace=mode == "replace")
    dbtools.restart_soon()
    return {"steps": steps}


@csrf_exempt  # must work when the database (and so the session) is down; it only restarts the local server
@require_POST
@api
def system_restart(request):
    dbtools.restart_soon()
    return {}


# --- settings: notifications / app ----------------------------------------------------------------

SECRET_KEYS = ("telegram_token", "discord_webhook", "webhook_url")


def notify_public(cfg):
    out = {k: v for k, v in cfg.items() if k != "email"}
    out["email"] = {k: v for k, v in cfg["email"].items() if k != "password"}
    out["email"]["password_set"] = bool(cfg["email"].get("password"))
    out["channels"] = notify.channels(cfg)
    return out


@api
def notify_settings(request):
    if request.method == "POST":
        d = body(request)
        cur = config.load()["notify"]
        values = {}
        for k in ("enabled", "mac"):
            if k in d:
                values[k] = as_bool(d[k])
        for k in ("telegram_token", "telegram_chat", "discord_webhook", "webhook_url"):
            if k in d:
                values[k] = (d[k] or "").strip()
        for k in ("discord_webhook", "webhook_url"):
            if values.get(k) and not re.match(r"^https?://", values[k]):
                raise ApiError("ลิงก์ webhook ต้องขึ้นต้นด้วย http:// หรือ https://", field=k)
        if isinstance(d.get("email"), dict):
            e = {**cur["email"]}
            for k in ("host", "user", "from", "to"):
                if k in d["email"]:
                    e[k] = (d["email"][k] or "").strip()
            for k in ("enabled", "tls"):
                if k in d["email"]:
                    e[k] = as_bool(d["email"][k])
            if "port" in d["email"]:
                e["port"] = int(d["email"]["port"] or 587)
            if d["email"].get("password"):
                e["password"] = d["email"]["password"]
            values["email"] = e
        config.update("notify", values)
    return {"notify": notify_public(config.load()["notify"])}


@require_POST
@api
def notify_test(request):
    cfg = config.load()["notify"]
    only = body(request).get("channel") or None
    if not notify.channels(cfg):
        raise ApiError("ยังไม่ได้ตั้งค่าช่องทางแจ้งเตือน")
    text = notify.summary("เว็บทดสอบ", "contact", "ติดต่อ", {"name": "สมชาย ทดสอบ", "message": "นี่คือข้อความทดสอบจาก BuildWeb"})
    payload = {"event": "test", "site": "test", "data": {"name": "สมชาย ทดสอบ"}}
    return {"results": notify.deliver(cfg, "เว็บทดสอบ", text, payload, only=only)}


@api
def app_settings(request):
    if request.method == "POST":
        d = body(request)
        if "auto_update" in d:
            config.update("app", {"auto_update": as_bool(d["auto_update"])})
    return {"app": config.load()["app"]}


# --- import ---------------------------------------------------------------------------------------

def run_import(bundle, d, default_name):
    site = None
    if d.get("site_id"):
        site = get_object_or_404(Site, pk=int(d["site_id"]))
    try:
        return importer.import_bundle(bundle, site=site, name=(d.get("name") or "").strip() or default_name,
                                      extract_parts=as_bool(d.get("extract", True)))
    except importer.ImportErrorTH as e:
        raise ApiError(str(e))


@require_POST
@api
def import_upload(request):
    files = request.FILES.getlist("files")
    if not files:
        raise ApiError("กรุณาเลือกไฟล์ .html, .zip หรือโฟลเดอร์")
    try:
        bundle = importer.from_uploads(files, request.POST.getlist("paths"))
    except importer.ImportErrorTH as e:
        raise ApiError(str(e))
    first = files[0].name.rsplit(".", 1)[0]
    folder = (request.POST.getlist("paths") or [""])[0].split("/")[0]
    return run_import(bundle, request.POST, folder or first or "เว็บที่นำเข้า")


@require_POST
@api
def import_github(request):
    d = body(request)
    try:
        bundle, repo = importer.from_github(d.get("url", ""), d.get("branch", ""), d.get("subdir", ""), d.get("token", ""))
    except importer.ImportErrorTH as e:
        raise ApiError(str(e), field="url")
    return run_import(bundle, d, repo.split("/")[-1])
