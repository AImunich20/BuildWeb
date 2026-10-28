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

from . import data, dbtools, members, restapi, schema, exporter, generate, importer, navbar, notify, publish, sections, seo, services, stats, system, widgets
from .hosting import server as hosting
from .models import (DEFAULT_THEME, ApiKey, Asset, AssetFolder, Collection, DataConnection, FormSubmission, Page, PageRevision, Record,
                     SharedSection, Site)

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
        "base_url": site.base_url, "contact": widgets.clean_contact(site.contact), "publish": publish_json(site),
        "api": restapi.site_settings(site),
    }


def publish_json(site):
    """Per-site publish targets without secrets."""
    out = {}
    for target, cfg in (site.publish or {}).items():
        cfg = dict(cfg or {})
        if cfg.pop("password", None):
            cfg["password_set"] = True
        if cfg.pop("token", None):
            cfg["token_set"] = True
        out[target] = cfg
    return out


def shared_json(sec):
    return {"id": sec.id, "kind": sec.kind, "label": sec.label, "enabled": sec.enabled, "managed": sec.managed,
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
    if "base_url" in d:
        url = (d["base_url"] or "").strip()
        if url and not re.match(r"^https?://[^\s/]+", url):
            raise ApiError("ที่อยู่เว็บต้องขึ้นต้นด้วย https:// เช่น https://myshop.com/", field="base_url")
        site.base_url = url if not url or url.endswith("/") else url + "/"
    if "contact" in d and isinstance(d["contact"], dict):
        site.contact = widgets.clean_contact(d["contact"])
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
        "collection": p.collection_id, "detail_field": p.detail_field, "access": p.access,
        "collection_slug": p.collection.slug if p.collection_id else "",
        "collection_name": p.collection.name if p.collection_id else "",
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
    if "collection" in d:
        cid = d["collection"] or None
        if cid and not page.site.collections.filter(pk=cid).exists():
            raise ApiError("เลือกชุดข้อมูลไม่ถูกต้อง", field="collection")
        if cid and page.is_home:
            raise ApiError("หน้าแรกเป็นหน้ารายละเอียดไม่ได้ — สร้างหน้าใหม่สำหรับรายละเอียด", field="collection")
        page.collection_id = int(cid) if cid else None
    if "detail_field" in d:
        page.detail_field = (d["detail_field"] or "")[:60]
    if "access" in d:
        a = (d["access"] or "").strip()
        if a and a != "members" and not re.fullmatch(r"role:[a-z0-9_,-]+", a):
            raise ApiError("ตั้งค่าการเข้าถึงไม่ถูกต้อง", field="access")
        page.access = a
        if a and page.is_home:
            raise ApiError("หน้าแรกต้องเปิดให้ทุกคน — สร้างหน้าแยกสำหรับสมาชิก", field="access")
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
    fields = {f: getattr(probe, f) for f in PAGE_FIELDS + ("show_in_nav", "noindex", "use_header", "use_footer", "status", "parent_id",
                                                           "collection_id", "detail_field", "access")
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
    system.reveal(path)
    return {}


@require_POST
@api
def open_url(request):
    url = body(request).get("url", "")
    if not re.match(r"^https?://", url) and not url.endswith((".app", ".exe", ".run")):
        raise ApiError("ลิงก์ไม่ถูกต้อง")
    system.open_target(url)
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


def shell_request(request):
    """Requests from the desktop shell / our own pages carry this header; a plain cross-site form can't."""
    return request.headers.get("X-BuildWeb") == "1"


@csrf_exempt  # must work when the database (and so the session) is down; it only restarts the local server
@require_POST
@api
def system_restart(request):
    if not shell_request(request):
        raise ApiError("forbidden", status=403)
    dbtools.restart_soon()
    return {}


@csrf_exempt
@require_POST
@api
def system_shutdown(request):
    """Called by the desktop shell when quitting (all platforms): take Tailscale links down, then exit."""
    if not shell_request(request):
        raise ApiError("forbidden", status=403)
    import os
    import threading

    def go():
        hosting.shutdown()
        os._exit(0)

    threading.Timer(0.2, go).start()
    return {}


# --- settings: notifications / app ----------------------------------------------------------------

SECRET_KEYS = ("telegram_token", "discord_webhook", "webhook_url", "line_token")


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
        for k in ("telegram_token", "telegram_chat", "discord_webhook", "webhook_url", "line_token", "line_to"):
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


@require_POST
@api
def tailscale_action(request, action):
    from . import tailscale

    if action == "connect":
        tailscale.connect()
        hosting.apply_tailscale()
    elif action == "open":
        tailscale.open_app()
    else:
        raise ApiError("unknown action", status=404)
    return {"hosting": hosting.status()}


# --- data: collections, connections, imports ------------------------------------------------------

def collection_json(c, with_count=True):
    count = None
    if with_count:
        count = c.records.count() if c.mode == Collection.COPY else None
    return {
        "id": c.id, "name": c.name, "slug": c.slug, "fields": c.fields, "mode": c.mode, "count": count,
        "connection": c.connection_id, "connection_name": c.connection.name if c.connection else "",
        "source_database": c.source_database, "source_table": c.source_table, "live_order": c.live_order,
        "live_desc": c.live_desc, "live_limit": c.live_limit, "options": c.options or {},
        "pending": c.records.filter(approved=False).count() if c.mode == Collection.COPY else 0,
        "detail_pages": [{"id": p.id, "title": p.title, "slug": p.slug, "edit_url": f"/sites/{p.site_id}/edit/{p.id}/"}
                         for p in c.detail_pages.all()],
        "last_synced": c.last_synced.isoformat() if c.last_synced else None, "updated_at": c.updated_at.isoformat(),
    }


def connection_json(c):
    return {"id": c.id, "name": c.name, "host": c.host, "port": c.port, "user": c.user, "database": c.database,
            "socket": c.socket, "password_set": bool(c.password)}


def clean_fields(raw):
    used, out = set(), []
    for f in raw or []:
        name = data.field_key(f.get("name") or f.get("label"), used)
        try:
            out.append(schema.clean_field(f, name))
        except schema.ValidationError as e:
            raise ApiError(f"ฟิลด์ {name}: {e.fields[name]}")
    return out


def validation_error(col, e):
    labels = {f["name"]: f.get("label") or f["name"] for f in col.fields}
    return ApiError(" · ".join(f"{labels.get(k, k)}: {v}" for k, v in e.fields.items()))


@require_GET
@api
def collection_list(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    return {"collections": [collection_json(c) for c in site.collections.select_related("connection")],
            "connections": [connection_json(c) for c in DataConnection.objects.all()]}


@require_POST
@api
def collection_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    name = (d.get("name") or "").strip()
    if not name:
        raise ApiError("กรุณาตั้งชื่อชุดข้อมูล", field="name")
    fields = clean_fields(d.get("fields") or [{"name": "title", "label": "ชื่อ"}, {"name": "detail", "label": "รายละเอียด", "type": "longtext"},
                                              {"name": "image", "label": "รูป", "type": "image"}])
    c = Collection.objects.create(site=site, name=name, slug=data.unique_slug(site, d.get("slug") or name), fields=fields)
    return {"collection": collection_json(c)}


@require_POST
@api
def collection_import_file(request, site_id):
    """CSV → one collection; .sql dump → one collection per table (optionally only ``tables``)."""
    site = get_object_or_404(Site, pk=site_id)
    f = request.FILES.get("file")
    if not f:
        raise ApiError("กรุณาเลือกไฟล์ .csv หรือ .sql")
    raw = f.read()
    created = []
    if f.name.lower().endswith(".sql"):
        text = raw.decode("utf-8", "replace")
        tables = data.parse_sql_dump(text)
        wanted = set(request.POST.getlist("tables"))
        if not tables:
            raise ApiError("ไม่พบตาราง (CREATE TABLE / INSERT) ในไฟล์ .sql")
        if request.POST.get("preview"):
            return {"tables": [{"name": n, "columns": t["columns"], "rows": len(t["rows"])} for n, t in tables.items()]}
        for name, t in tables.items():
            if wanted and name not in wanted:
                continue
            created.append(data.create_collection(site, name, t["columns"], t["rows"], sql_types=t["types"]))
    else:
        try:
            cols, rows = data.parse_csv(raw)
        except (UnicodeDecodeError, RuntimeError) as e:
            raise ApiError(f"อ่านไฟล์ CSV ไม่ได้: {e}")
        name = (request.POST.get("name") or f.name.rsplit(".", 1)[0]).strip()
        created.append(data.create_collection(site, name, cols, rows))
    return {"collections": [collection_json(c) for c in created]}


def connection_cfg(d):
    if d.get("connection_id"):
        c = get_object_or_404(DataConnection, pk=int(d["connection_id"]))
        cfg = c.as_config(d.get("database") if "database" in d else None)
        return c, cfg
    db = config.load()["db"]  # default: the app's own MySQL settings / XAMPP defaults
    return None, {"host": d.get("host") or db["host"], "port": d.get("port") or db["port"], "user": d.get("user") or db["user"],
                  "password": d.get("password", db["password"]), "name": d.get("database", ""), "socket": d.get("socket", "")}


@api
def connection_save(request):
    if request.method != "POST":
        return {"connections": [connection_json(c) for c in DataConnection.objects.all()]}
    d = body(request)
    c = DataConnection.objects.filter(pk=d.get("id")).first() if d.get("id") else DataConnection()
    c.name = (d.get("name") or "XAMPP").strip()[:100]
    c.host = (d.get("host") or "127.0.0.1").strip()
    c.port = int(d.get("port") or 3306)
    c.user = (d.get("user") or "root").strip()
    if d.get("password") or not c.pk:
        from .crypto import encrypt

        c.password = encrypt(d.get("password") or "")
    c.database = (d.get("database") or "").strip()
    c.socket = (d.get("socket") or "").strip()
    data.list_databases(c.as_config(""))  # fails with a clear message when unreachable
    c.save()
    return {"connection": connection_json(c)}


@require_POST
@api
def connection_delete(request, conn_id):
    get_object_or_404(DataConnection, pk=conn_id).delete()
    return {}


@require_POST
@api
def mysql_browse(request):
    """{connection_id} → databases; with {database} → tables (+columns, row counts)."""
    d = body(request)
    _, cfg = connection_cfg({**d, "database": ""})
    if d.get("database"):
        return {"tables": data.list_tables(cfg, d["database"])}
    return {"databases": data.list_databases(cfg)}


@require_POST
@api
def collection_import_mysql(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    conn = get_object_or_404(DataConnection, pk=int(d.get("connection_id") or 0))
    database, tables = d.get("database") or conn.database, d.get("tables") or []
    if not database or not tables:
        raise ApiError("เลือกฐานข้อมูลและตารางก่อน")
    mode = Collection.LIVE if d.get("mode") == "live" else Collection.COPY
    created = [data.import_mysql(site, conn, database, t, mode=mode) for t in tables]
    return {"collections": [collection_json(c) for c in created]}


@api
def collection_detail(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    if c.mode == Collection.COPY:
        rows = [{**r.data, "_id": r.id, "_approved": r.approved} for r in c.records.all()[:5000]]  # "_id": tables often have their own "id"
        return {"collection": collection_json(c), "rows": rows, "editable": True}
    try:
        rows = data.rows_for(c)
        err = ""
    except RuntimeError as e:
        rows, err = [], str(e)
    return {"collection": collection_json(c, with_count=False), "rows": rows[:5000], "editable": False, "error": err}


@require_POST
@api
def collection_update(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    d = body(request)
    if "name" in d:
        c.name = (d["name"] or c.name).strip()[:120]
    if "slug" in d and d["slug"] != c.slug:
        slug = (d["slug"] or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise ApiError("ชื่ออ้างอิงใช้ได้เฉพาะ a-z, 0-9 และ -", field="slug")
        if c.site.collections.filter(slug=slug).exclude(pk=c.pk).exists():
            raise ApiError("มีชุดข้อมูลที่ใช้ชื่อนี้แล้ว", field="slug")
        c.slug = slug
    if "fields" in d:
        old = {f["name"]: f for f in c.fields}
        fields = clean_fields(d["fields"])
        for f in fields:  # keep where live columns come from
            if f["name"] in old:
                f["source"] = old[f["name"]].get("source", f["name"])
        renames = {r["from"]: r["to"] for r in d.get("renames", []) if r.get("from") and r.get("to")}
        if renames and c.mode == Collection.COPY:
            for rec in c.records.all():
                rec.data = {renames.get(k, k): v for k, v in rec.data.items()}
                rec.save(update_fields=["data"])
        c.fields = fields
    for k in ("live_order",):
        if k in d:
            setattr(c, k, (d[k] or "")[:100])
    if "options" in d and isinstance(d["options"], dict):
        c.options = {k: as_bool(d["options"].get(k)) for k in ("forms", "auto_approve", "rss")}
    if "live_desc" in d:
        c.live_desc = as_bool(d["live_desc"])
    if "live_limit" in d:
        c.live_limit = max(1, min(5000, int(d["live_limit"] or 500)))
    c.save()
    data.invalidate(c)
    return {"collection": collection_json(c)}


@require_POST
@api
def collection_delete(request, col_id):
    get_object_or_404(Collection, pk=col_id).delete()
    return {}


@require_POST
@api
def collection_resync(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    if c.mode == Collection.LIVE:
        data.invalidate(c)
        return {"rows": len(data.rows_for(c))}
    return {"rows": data.resync(c)}


@require_POST
@api
def record_save(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    if c.mode != Collection.COPY:
        raise ApiError("ชุดข้อมูลแบบเชื่อมสดแก้ไขได้ที่ MySQL (phpMyAdmin)")
    d = body(request)
    raw = d.get("data", {})
    r = get_object_or_404(Record, pk=d["_id"], collection=c) if d.get("_id") else None
    try:  # inline edits send the whole row; new rows get defaults for what they leave out
        values = schema.full_validate(c, raw, partial=r is not None, current=r.data if r else None,
                                      exclude_id=r.id if r else None)
    except schema.ValidationError as e:
        raise validation_error(c, e)
    if r:
        r.data = {**r.data, **values}
        r.save()
        from . import logic

        logic.emit(c.site, "record.updated", {"_id": r.id, **r.data}, c.slug)
    else:
        pos = (c.records.order_by("-position").values_list("position", flat=True).first() or 0) + 1
        r = Record.objects.create(collection=c, data=values, position=pos)
        from . import logic

        logic.emit(c.site, "record.created", {"_id": r.id, **r.data}, c.slug)
    c.save(update_fields=["updated_at"])
    return {"row": {**r.data, "_id": r.id, "_approved": r.approved}}


@require_POST
@api
def record_approve(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    d = body(request)
    ids = [int(i) for i in d.get("ids", [])]
    n = c.records.filter(id__in=ids).update(approved=as_bool(d.get("value", True)))
    c.save(update_fields=["updated_at"])
    return {"updated": n}


@require_POST
@api
def collection_pages(request, col_id):
    """Generate a list page + detail page (or only the detail page) for a collection."""
    c = get_object_or_404(Collection, pk=col_id)
    d = body(request)
    lst, detail = generate.create_pages_for(c, (d.get("title") or "").strip(), with_list=as_bool(d.get("with_list", True)))
    return {"list": page_json(lst) if lst else None, "detail": page_json(detail)}


@require_POST
@api
def blog_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    col, lst, detail = generate.create_blog(site, (body(request).get("name") or "บทความ").strip())
    return {"collection": collection_json(col), "list": page_json(lst), "detail": page_json(detail)}


# --- SEO, statistics -------------------------------------------------------------------------------

@require_GET
@api
def site_seo(request, site_id):
    return seo.analyze_site(get_object_or_404(Site, pk=site_id))


@require_GET
@api
def site_stats(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    days = max(7, min(365, int(request.GET.get("days") or 30)))
    return {"stats": stats.summary(site, days), "hosting": hosting.running}


# --- publishing -----------------------------------------------------------------------------------

PUBLISH_FIELDS = {
    "github": ("repo", "branch", "url", "pages"),
    "netlify": ("site_id", "name", "url"),
    "ftp": ("host", "port", "user", "password", "path", "tls", "url"),
    "server": ("url", "token", "site_url"),
}


@api
def publish_settings(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        d = body(request)
        target = d.get("target")
        if target not in PUBLISH_FIELDS:
            raise ApiError("ไม่รู้จักปลายทางนี้")
        cur = dict((site.publish or {}).get(target) or {})
        for k in PUBLISH_FIELDS[target]:
            if k not in d:
                continue
            v = d[k]
            if k in ("pages", "tls"):
                v = as_bool(v)
            elif k == "port":
                v = int(v or 21)
            elif k in ("password", "token") and not v:
                continue  # empty = keep the saved one
            elif k in ("password", "token"):
                from .crypto import encrypt

                v = encrypt(str(v))
            else:
                v = str(v or "").strip()
            cur[k] = v
        if cur.get("url") and not re.match(r"^https?://", cur["url"]):
            raise ApiError("ที่อยู่เว็บต้องขึ้นต้นด้วย https://", field="url")
        if target == "github" and cur.get("repo") and not re.fullmatch(r"[\w.-]+(/[\w.-]+)?", cur["repo"]):
            raise ApiError("ชื่อ repo ต้องเป็นแบบ ชื่อ หรือ เจ้าของ/ชื่อ", field="repo")
        site.publish = {**(site.publish or {}), target: cur}
        site.save(update_fields=["publish"])
        if f"{target}_token" in d and d[f"{target}_token"]:
            config.update("publish", {f"{target}_token": d[f"{target}_token"].strip()})
    toks = publish.tokens()
    return {"publish": publish_json(site), "tokens": {t: bool(toks.get(f"{t}_token")) for t in ("github", "netlify")},
            "base_url": site.base_url}


@require_POST
@api
def publish_start(request, site_id, target):
    site = get_object_or_404(Site, pk=site_id)
    try:
        job = publish.start(site, target)
    except publish.PublishError as e:
        raise ApiError(str(e))
    return {"job": job}


@require_GET
@api
def publish_job(request, job_id):
    job = publish.job(job_id)
    if not job:
        raise ApiError("ไม่พบงานนี้ (โปรแกรมอาจถูกเปิดใหม่)", status=404)
    return {"job": job}


@require_POST
@api
def publish_test_ftp(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    from .crypto import decrypt

    cfg = {**((site.publish or {}).get("ftp") or {}), **{k: v for k, v in body(request).items() if v not in ("", None)}}
    cfg["password"] = decrypt(cfg.get("password", ""))
    try:
        ftp = publish.ftp_connect(cfg)
        where = ftp.pwd()
        ftp.quit()
    except publish.PublishError as e:
        raise ApiError(str(e))
    return {"message": f"เชื่อมต่อได้ (โฟลเดอร์เริ่มต้น {where})"}


@require_POST
@api
def record_delete(request, col_id):
    c = get_object_or_404(Collection, pk=col_id)
    ids = [int(i) for i in body(request).get("ids", [])]
    gone = [{"_id": r.id, **r.data} for r in c.records.filter(id__in=ids)]
    n, _ = c.records.filter(id__in=ids).delete()
    from . import logic

    for g in gone:
        logic.emit(c.site, "record.deleted", g, c.slug)
    return {"deleted": n}


def collection_csv(request, col_id):
    from django.http import HttpResponse

    c = get_object_or_404(Collection, pk=col_id)
    rows = data.rows_for(c)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{c.slug}.csv"'
    resp.write("﻿")
    import csv as _csv

    w = _csv.writer(resp)
    w.writerow([f["label"] for f in c.fields])
    for r in rows:
        w.writerow([r.get(f["name"], "") for f in c.fields])
    return resp


# --- navbar settings ------------------------------------------------------------------------------

@api
def navbar_settings(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        d = body(request)
        if "settings" in d:
            site.nav = navbar.clean(d["settings"])
            site.save(update_fields=["nav", "updated_at"])
        if "managed" in d:
            services.set_header_managed(site, as_bool(d["managed"]))
    head = site.shared_sections.filter(kind=SharedSection.HEADER).first()
    return {"settings": navbar.settings(site), "managed": bool(head and head.managed), "enabled": bool(head and head.enabled),
            "layouts": navbar.LAYOUTS, "pages": [{"title": p.menu_label, "href": p.filename} for p in site.pages.all()]}


# --- REST API management --------------------------------------------------------------------------

def key_json(k):
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "write": k.write, "collections": k.collections,
            "created_at": k.created_at.isoformat(), "last_used": k.last_used.isoformat() if k.last_used else None,
            "revoked": k.revoked}


@api
def restapi_settings(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        d = body(request)
        if isinstance(d.get("settings"), dict):
            cur = restapi.site_settings(site)
            st = d["settings"]
            if "enabled" in st:
                cur["enabled"] = as_bool(st["enabled"])
            if "log" in st:
                cur["log"] = as_bool(st["log"])
            if "cors" in st:
                cur["cors"] = str(st["cors"] or "").strip()[:1000] or "*"
            if "rate" in st:
                try:
                    cur["rate"] = max(0, min(100000, int(st["rate"] or 0)))
                except ValueError:
                    raise ApiError("จำนวนครั้งต่อนาทีต้องเป็นตัวเลข", field="rate")
            site.api = cur
            site.save(update_fields=["api"])
        for slug, r in (d.get("rules") or {}).items():
            col = site.collections.filter(slug=slug).first()
            if col and isinstance(r, dict):
                cur = restapi.rules(col)
                cur.update({k: v for k, v in r.items() if k in restapi.ACTIONS and v in restapi.RULES})
                col.options = {**(col.options or {}), "api": cur}
                col.save(update_fields=["options"])
    return {
        "settings": restapi.site_settings(site),
        "collections": [{"id": c.id, "slug": c.slug, "name": c.name, "mode": c.mode, "rules": restapi.rules(c),
                         "fields": c.fields, "hidden": [f["name"] for f in c.fields if f.get("hidden")]}
                        for c in site.collections.all()],
        "keys": [key_json(k) for k in site.api_keys.all()],
    }


@require_POST
@api
def restapi_key_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    name = (d.get("name") or "").strip()
    if not name:
        raise ApiError("ตั้งชื่อ key ก่อน เช่น “แอปมือถือ” หรือ “เว็บหลังบ้าน”", field="name")
    cols = [c for c in (d.get("collections") or []) if site.collections.filter(slug=c).exists()]
    key, plain = restapi.create_key(site, name, as_bool(d.get("write")), cols)
    return {"key": key_json(key), "plain": plain}


@require_POST
@api
def restapi_key_action(request, key_id, action):
    key = get_object_or_404(ApiKey, pk=key_id)
    if action == "revoke":
        key.revoked = True
        key.save(update_fields=["revoked"])
    elif action == "delete":
        key.delete()
    else:
        raise ApiError("unknown action", status=404)
    return {}


@require_GET
@api
def restapi_logs(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    logs = site.api_logs.select_related("key")[:200]
    return {"logs": [{"at": x.at.isoformat(), "method": x.method, "path": x.path, "status": x.status, "ms": x.ms,
                      "key": x.key.name if x.key else "", "ip": x.ip, "error": x.error} for x in logs]}


# --- site members ---------------------------------------------------------------------------------

def member_or_404(member_id):
    from .models import SiteUser

    return get_object_or_404(SiteUser, pk=member_id)


@api
def members_settings(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        d = body(request).get("settings") or {}
        cur = {**(site.auth or {})}
        for k in ("enabled", "signup", "verify_email"):
            if k in d:
                cur[k] = as_bool(d[k])
        if "roles" in d:
            roles = d["roles"] if isinstance(d["roles"], list) else re.split(r"[,\s]+", str(d["roles"]))
            roles = [r.strip().lower() for r in roles if r.strip()]
            bad = [r for r in roles if not members.ROLE_RE.match(r)]
            if bad:
                raise ApiError("ชื่อบทบาทใช้ได้เฉพาะ a-z 0-9 _ - เช่น member, vip, staff", field="roles")
            cur["roles"] = [r for r in dict.fromkeys(roles) if r != "admin"] or ["member"]
        if "default_role" in d:
            cur["default_role"] = str(d["default_role"] or "")
        if "min_password" in d:
            cur["min_password"] = max(6, min(64, int(d["min_password"] or 8)))
        if "after_login" in d:
            cur["after_login"] = str(d["after_login"] or "").strip()[:200]
        site.auth = cur
        site.save(update_fields=["auth"])
    s = members.settings(site)
    return {"settings": s, "roles": members.all_roles(site), "smtp": notify.smtp_ready(),
            "pages": {k: site.pages.filter(slug=v[:-5]).exists() for k, v in s["pages"].items()},
            "count": site.members.count()}


@require_GET
@api
def members_list(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    qs = site.members.all()
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q

        qs = qs.filter(Q(email__icontains=q) | Q(name__icontains=q))
    if request.GET.get("role"):
        qs = qs.filter(role=request.GET["role"])
    return {"members": [members.user_json(u, full=True) for u in qs[:500]], "total": qs.count()}


@require_POST
@api
def members_create(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    try:
        u = members.create_user(site, d.get("email"), d.get("password") or "", d.get("name"), d.get("role"), verified=True)
    except members.AuthError as e:
        raise ApiError(str(e), field=next(iter(e.fields or {}), None))
    return {"member": members.user_json(u, full=True)}


@require_POST
@api
def member_action(request, member_id, action):
    u = member_or_404(member_id)
    d = body(request)
    if action == "update":
        if "name" in d:
            u.name = str(d["name"] or "")[:150]
        if "role" in d:
            if d["role"] not in members.all_roles(u.site):
                raise ApiError("ไม่มีบทบาทนี้", field="role")
            u.role = d["role"]
        for k in ("is_active", "email_verified"):
            if k in d:
                setattr(u, k, as_bool(d[k]))
        u.save()
        if not u.is_active:
            u.tokens.all().delete()  # log a suspended member out everywhere
        return {"member": members.user_json(u, full=True)}
    if action == "reset-link":
        base = u.site.base_url or (hosting_base(u.site) or f"http://127.0.0.1:{settings.ADMIN_PORT}/preview/{u.site.slug}/")
        emailed = notify.smtp_ready()
        try:
            link = members.send_reset(u.site, u, base)
        except RuntimeError:
            emailed = False
            from .models import UserToken

            link = members.page_url(u.site, base, "reset", members.issue(u, UserToken.RESET))
        return {"link": link, "emailed": emailed}
    if action == "logout":
        u.tokens.all().delete()
        return {}
    if action == "delete":
        u.delete()
        return {}
    raise ApiError("unknown action", status=404)


def hosting_base(site):
    st = hosting.status(with_tailscale=False)
    if not st.get("running"):
        return ""
    own = next((x for x in st.get("site_ports", []) if x.get("slug") == site.slug), None)
    if own and own.get("urls"):
        return own["urls"][0]
    return (st.get("urls") or [""])[0] + site.slug + "/" if st.get("urls") else ""


@require_POST
@api
def members_pages(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    made = generate.create_member_pages(site)
    return {"created": [page_json(p) for p in made]}


# --- logic: secrets, webhooks, connectors, functions, jobs ------------------------------------------

def logic_state(site):
    from . import logic

    return {
        "secrets": [{"name": k, "preview": "•" * 8} for k in sorted((site.secrets or {}))],
        "webhooks": [{"id": h.id, "name": h.name, "url": h.url, "events": h.events, "collections": h.collections,
                      "headers": h.headers, "signing": bool(h.signing_secret), "active": h.active} for h in site.webhooks.all()],
        "connectors": [{"id": c.id, "name": c.name, "url": c.url, "method": c.method, "headers": c.headers, "body": c.body,
                        "items_path": c.items_path, "collection": c.collection.slug if c.collection else "",
                        "key_field": c.key_field, "last_run": c.last_run.isoformat() if c.last_run else None,
                        "last_status": c.last_status} for c in site.connectors.select_related("collection")],
        "functions": [{"id": f.id, "slug": f.slug, "name": f.name, "code": f.code, "access": f.access, "timeout": f.timeout,
                       "enabled": f.enabled, "updated_at": f.updated_at.isoformat()} for f in site.functions.all()],
        "jobs": [{"id": j.id, "name": j.name, "schedule": j.schedule, "action": j.action, "params": j.params,
                  "enabled": j.enabled, "last_run": j.last_run.isoformat() if j.last_run else None,
                  "next_run": j.next_run.isoformat() if j.next_run else None, "last_ok": j.last_ok} for j in site.jobs.all()],
        "events": logic.EVENTS, "template": logic.FN_TEMPLATE,
        "collections": [{"slug": c.slug, "name": c.name, "fields": c.field_names, "mode": c.mode} for c in site.collections.all()],
    }


@require_GET
@api
def logic_overview(request, site_id):
    return logic_state(get_object_or_404(Site, pk=site_id))


@require_POST
@api
def secret_save(request, site_id):
    from . import logic

    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    name = (d.get("name") or "").strip().upper()
    secrets_ = dict(site.secrets or {})
    if d.get("delete"):
        secrets_.pop(name, None)
    else:
        if not logic.NAME_RE.match(name):
            raise ApiError("ชื่อใช้ A-Z 0-9 _ และขึ้นต้นด้วยตัวอักษร เช่น LINE_TOKEN", field="name")
        if not d.get("value"):
            raise ApiError("ใส่ค่าลับ", field="value")
        from .crypto import encrypt

        secrets_[name] = encrypt(str(d["value"])[:4000])
    site.secrets = secrets_
    site.save(update_fields=["secrets"])
    return logic_state(site)


def _clean_headers(h):
    if isinstance(h, str):
        out = {}
        for line in h.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()[:100]] = v.strip()[:2000]
        return out
    return {str(k)[:100]: str(v)[:2000] for k, v in (h or {}).items()}


@require_POST
@api
def webhook_save(request, site_id):
    from . import logic
    from .models import Webhook

    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    h = site.webhooks.filter(pk=d.get("id")).first() if d.get("id") else Webhook(site=site)
    h.name = (d.get("name") or "Webhook").strip()[:100]
    h.url = (d.get("url") or "").strip()[:500]
    if not re.match(r"^https?://", logic.fill_secrets(site, h.url)):
        raise ApiError("URL ต้องขึ้นต้นด้วย https://", field="url")
    h.events = [e for e in d.get("events") or [] if e in logic.EVENTS]
    h.collections = [c for c in d.get("collections") or [] if site.collections.filter(slug=c).exists()]
    h.headers = _clean_headers(d.get("headers"))
    if "signing_secret" in d and d["signing_secret"] is not None:
        h.signing_secret = str(d["signing_secret"]).strip()[:80]
    h.active = as_bool(d.get("active", True))
    h.save()
    return logic_state(site)


@require_POST
@api
def logic_item_action(request, kind, item_id, action):
    """POST /api/logic/<webhook|connector|function|job>/<id>/<test|run|delete>"""
    from . import logic
    from .models import Connector, Function, Job, Webhook

    model = {"webhook": Webhook, "connector": Connector, "function": Function, "job": Job}.get(kind)
    if not model:
        raise ApiError("unknown", status=404)
    obj = get_object_or_404(model, pk=item_id)
    site = obj.site
    if action == "delete":
        obj.delete()
        return logic_state(site)
    if kind == "webhook" and action == "test":
        ok = logic.deliver(obj, {"event": "test", "site": site.slug, "collection": None,
                                 "at": "", "data": {"message": "ทดสอบจาก BuildWeb"}}, retries=())
        last = site.run_logs.filter(kind="webhook", ref=obj.name).first()
        return {"ok_delivery": ok, "message": last.message if last else ""}
    if kind == "connector" and action == "preview":
        try:
            rows = logic.fetch_connector(obj)
        except RuntimeError as e:
            raise ApiError(str(e))
        return {"rows": rows[:20], "total": len(rows), "columns": list(dict.fromkeys(k for r in rows[:200] for k in r))}
    if kind == "connector" and action == "run":
        try:
            n = logic.run_connector(obj)
        except RuntimeError as e:
            raise ApiError(str(e))
        return {"message": f"นำเข้า {n} แถว", **logic_state(site)}
    if kind == "function" and action == "test":
        d = body(request)
        payload = {"method": d.get("method") or "GET", "query": d.get("query") or {}, "body": d.get("body") or {},
                   "headers": {}, "user": None}
        status, out, logs = logic.call_function(obj, payload)
        return {"status": status, "body": out, "logs": logs}
    if kind == "job" and action == "run":
        ok, msg = logic.run_job(obj)
        return {"ok_run": ok, "message": msg, **logic_state(site)}
    raise ApiError("unknown action", status=404)


@require_POST
@api
def connector_save(request, site_id):
    from .models import Connector

    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    c = site.connectors.filter(pk=d.get("id")).first() if d.get("id") else Connector(site=site)
    c.name = (d.get("name") or "").strip()[:100]
    if not c.name:
        raise ApiError("ตั้งชื่อก่อน", field="name")
    c.url = (d.get("url") or "").strip()[:1000]
    if not re.match(r"^https?://|^\{\{\s*secret\.", c.url):
        raise ApiError("URL ต้องขึ้นต้นด้วย https://", field="url")
    c.method = (d.get("method") or "GET").upper() if (d.get("method") or "GET").upper() in ("GET", "POST") else "GET"
    c.headers = _clean_headers(d.get("headers"))
    c.body = str(d.get("body") or "")[:20000]
    c.items_path = (d.get("items_path") or "").strip()[:200]
    c.key_field = (d.get("key_field") or "").strip()[:100]
    slug = (d.get("collection") or "").strip()
    c.collection = site.collections.filter(slug=slug).first() if slug else None
    c.save()
    return logic_state(site)


@require_POST
@api
def function_save(request, site_id):
    from .models import Function

    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    f = site.functions.filter(pk=d.get("id")).first() if d.get("id") else Function(site=site)
    slug = (d.get("slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", slug):
        raise ApiError("ชื่อใช้ a-z 0-9 - เช่น send-order", field="slug")
    if site.functions.filter(slug=slug).exclude(pk=f.pk).exists():
        raise ApiError("มีฟังก์ชันชื่อนี้แล้ว", field="slug")
    f.slug, f.name = slug, (d.get("name") or "").strip()[:100]
    f.code = str(d.get("code") or "")[:200000]
    try:
        compile(f.code, "function.py", "exec")
    except SyntaxError as e:
        raise ApiError(f"โค้ดผิดที่บรรทัด {e.lineno}: {e.msg}", field="code")
    f.access = d.get("access") if d.get("access") in ("public", "user", "key", "off") else "key"
    f.timeout = max(1, min(60, int(d.get("timeout") or 10)))
    f.enabled = as_bool(d.get("enabled", True))
    f.save()
    return logic_state(site)


@require_POST
@api
def job_save(request, site_id):
    from . import logic
    from .models import Job

    site = get_object_or_404(Site, pk=site_id)
    d = body(request)
    j = site.jobs.filter(pk=d.get("id")).first() if d.get("id") else Job(site=site)
    j.name = (d.get("name") or "").strip()[:100] or "งานตั้งเวลา"
    j.schedule = (d.get("schedule") or "").strip()
    try:
        j.next_run = logic.next_run(j.schedule)
    except ValueError as e:
        raise ApiError(str(e), field="schedule")
    if d.get("action") not in Job.ACTIONS:
        raise ApiError("เลือกสิ่งที่จะทำ", field="action")
    j.action = d["action"]
    j.params = d.get("params") if isinstance(d.get("params"), dict) else {}
    j.enabled = as_bool(d.get("enabled", True))
    j.save()
    return logic_state(site)


@require_GET
@api
def run_logs(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    qs = site.run_logs.all()
    if request.GET.get("kind"):
        qs = qs.filter(kind=request.GET["kind"])
    return {"logs": [{"id": x.id, "kind": x.kind, "ref": x.ref, "ok": x.ok, "status": x.status, "ms": x.ms,
                      "message": x.message, "detail": x.detail[:6000], "at": x.at.isoformat()} for x in qs[:150]]}


# --- backups & BuildWeb server --------------------------------------------------------------------

def download(data, filename, ctype="application/zip"):
    from django.http import HttpResponse

    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def site_backup_download(request, site_id):
    from . import backup

    site = get_object_or_404(Site, pk=site_id)
    data = backup.export_bytes(site, include_secrets=request.GET.get("secrets", "1") == "1")
    return download(data, f"{site.slug}-{timezone_now():%Y%m%d-%H%M}.bwsite")


def timezone_now():
    from django.utils import timezone

    return timezone.localtime()


@api
def site_backups(request, site_id):
    from . import backup

    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        d = body(request)
        if d.get("action") == "create":
            backup.auto_backup(site)
        elif d.get("action") == "restore":
            path = backup.backup_dir(site) / Path(d.get("name", "")).name
            if not path.is_file():
                raise ApiError("ไม่พบไฟล์สำรองนี้")
            backup.auto_backup(site)  # what is there now can be restored too
            site = backup.import_site(path, mode="replace")
            return {"site_id": site.id, "backups": backup.list_backups(site)}
    return {"backups": backup.list_backups(site), "folder": str(backup.backup_dir(site)),
            "auto": config.load()["app"].get("auto_backup", True)}


def site_backup_file(request, site_id, name):
    from . import backup

    site = get_object_or_404(Site, pk=site_id)
    path = backup.backup_dir(site) / Path(name).name
    if not path.is_file():
        from django.http import Http404

        raise Http404
    return download(path.read_bytes(), path.name)


@require_POST
@api
def import_bwsite(request):
    from . import backup

    f = request.FILES.get("file")
    if not f:
        raise ApiError("เลือกไฟล์ .bwsite")
    site = backup.import_site(f, mode="new")
    return {"site": site_json(site), "url": f"/sites/{site.id}/"}


def server_cfg(site):
    from .crypto import decrypt

    cfg = dict((site.publish or {}).get("server") or {})
    cfg["token"] = decrypt(cfg.get("token", ""))
    return cfg


@require_POST
@api
def server_test(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    try:
        info = publish.server_call(server_cfg(site), "GET", "/__bw/health", timeout=15)
    except publish.PublishError as e:
        raise ApiError(str(e))
    on = any(s["slug"] == site.slug for s in info.get("sites", []))
    return {"message": f"เชื่อมต่อได้ · BuildWeb {info.get('version')} · ฐานข้อมูล {info.get('database')} · "
                       + ("มีเว็บนี้แล้ว" if on else "ยังไม่มีเว็บนี้ (กด Deploy)")}


@require_POST
@api
def server_pull(request, site_id):
    from . import backup

    site = get_object_or_404(Site, pk=site_id)
    try:
        d = publish.server_call(server_cfg(site), "GET", f"/__bw/pull?site={site.slug}", timeout=120)
    except publish.PublishError as e:
        raise ApiError(str(e))
    n = backup.apply_pull(site, d)
    return {"message": f"ดึงข้อมูลจากเซิร์ฟเวอร์แล้ว: {n['rows']} แถว · สมาชิก {n['members']} · ข้อความฟอร์ม {n['submissions']}"}


def server_kit(request, site_id):
    from . import serverkit

    site = get_object_or_404(Site, pk=site_id)
    return download(serverkit.build_kit(site, request.GET.get("domain", "")), f"buildweb-server-{site.slug}.zip")


# --- team access ----------------------------------------------------------------------------------

def team_json():
    from django.contrib.auth import get_user_model

    from .models import TeamMember

    out = []
    for u in get_user_model().objects.order_by("username"):
        m = TeamMember.objects.filter(user=u).first()
        if not m and not u.is_superuser:
            continue
        out.append({"id": u.id, "username": u.username, "name": u.get_full_name() or u.first_name, "role": m.role if m else "admin",
                    "sites": m.sites if m else [], "last_login": u.last_login.isoformat() if u.last_login else None,
                    "is_owner": u.is_superuser and not m})
    return out


@api
def team_settings(request):
    from . import team
    from .models import AuditLog, TeamMember

    if request.method == "POST":
        d = body(request)
        port = int(d.get("port") or 5055)
        if not 1024 <= port <= 65535 or port == settings.ADMIN_PORT:
            raise ApiError("พอร์ตไม่ถูกต้อง", field="port")
        config.update("team", {"enabled": as_bool(d.get("enabled")), "port": port})
        team.server.apply_config()
    return {"settings": config.load().get("team", {"enabled": False, "port": 5055}), "status": team.server.status(),
            "members": team_json(), "roles": dict(TeamMember.ROLES),
            "sites": [{"id": s.id, "name": s.name} for s in Site.objects.all()],
            "audit": [{"user": a.user, "method": a.method, "path": a.path, "status": a.status, "at": a.at.isoformat()}
                      for a in AuditLog.objects.all()[:150]]}


@require_POST
@api
def team_member_save(request):
    from django.contrib.auth import get_user_model

    from .models import TeamMember

    d = body(request)
    User = get_user_model()
    if d.get("id"):
        user = get_object_or_404(User, pk=d["id"])
    else:
        username = (d.get("username") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_.@-]{3,60}", username):
            raise ApiError("ชื่อผู้ใช้ใช้ a-z 0-9 . _ - @ ยาว 3 ตัวขึ้นไป", field="username")
        if User.objects.filter(username=username).exists():
            raise ApiError("มีชื่อผู้ใช้นี้แล้ว", field="username")
        if len(d.get("password") or "") < 8:
            raise ApiError("รหัสผ่านอย่างน้อย 8 ตัวอักษร", field="password")
        user = User.objects.create_user(username, password=d["password"])
    if user.is_superuser and not TeamMember.objects.filter(user=user).exists():
        raise ApiError("แก้บัญชีเจ้าของเครื่องไม่ได้")
    if "name" in d:
        user.first_name = (d.get("name") or "")[:150]
    if d.get("id") and d.get("password"):
        if len(d["password"]) < 8:
            raise ApiError("รหัสผ่านอย่างน้อย 8 ตัวอักษร", field="password")
        user.set_password(d["password"])
    user.save()
    role = d.get("role") if d.get("role") in dict(TeamMember.ROLES) else "editor"
    sites = [int(x) for x in d.get("sites") or [] if Site.objects.filter(pk=x).exists()]
    TeamMember.objects.update_or_create(user=user, defaults={"role": role, "sites": sites})
    return {"members": team_json()}


@require_POST
@api
def team_member_delete(request, user_id):
    from django.contrib.auth import get_user_model

    from .models import TeamMember

    user = get_object_or_404(get_user_model(), pk=user_id)
    if not TeamMember.objects.filter(user=user).exists():
        raise ApiError("ลบบัญชีเจ้าของเครื่องไม่ได้")
    user.delete()
    return {"members": team_json()}


# --- saved blocks ---------------------------------------------------------------------------------

def block_json(b):
    return {"id": b.id, "name": b.name, "category": b.category, "html": b.html, "css": b.css}


@api
def saved_blocks(request):
    from .models import SavedBlock

    if request.method == "POST":
        d = body(request)
        name = (d.get("name") or "").strip()[:120]
        if not name or not (d.get("html") or "").strip():
            raise ApiError("ตั้งชื่อบล็อก", field="name")
        SavedBlock.objects.create(name=name, category=(d.get("category") or "บล็อกของฉัน").strip()[:60], html=d["html"][:500000],
                                  css=(d.get("css") or "")[:200000],
                                  created_by=request.user.get_username() if request.user.is_authenticated else "")
    return {"blocks": [block_json(b) for b in SavedBlock.objects.all()]}


@require_POST
@api
def saved_block_delete(request, block_id):
    from .models import SavedBlock

    get_object_or_404(SavedBlock, pk=block_id).delete()
    return {"blocks": [block_json(b) for b in SavedBlock.objects.all()]}


# --- shop -----------------------------------------------------------------------------------------

def shop_error(e):
    return ApiError(str(e), field=next(iter(e.fields or {}), None))


@api
def shop_settings(request, site_id):
    from . import shop

    site = get_object_or_404(Site, pk=site_id)
    if request.method == "POST":
        try:
            shop.save_settings(site, body(request).get("settings") or {})
        except shop.ShopError as e:
            raise shop_error(e)
    prod, orders = shop.products_col(site), shop.orders_col(site)
    return {"settings": shop.settings(site), "summary": shop.summary(site), "statuses": shop.STATUS_TH, "payments": shop.PAYMENTS,
            "products": {"id": prod.id, "slug": prod.slug, "count": prod.records.count()} if prod else None,
            "orders_col": orders.id if orders else None,
            "secrets": {k: k in (site.secrets or {}) for k in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")},
            "stripe_webhook": "api/v1/shop/stripe-webhook"}


@require_POST
@api
def shop_setup(request, site_id):
    from . import generate

    site = get_object_or_404(Site, pk=site_id)
    prod, orders, made = generate.create_shop(site)
    return {"created": [page_json(p) for p in made], "products": prod.id}


@require_GET
@api
def shop_orders(request, site_id):
    from . import shop

    site = get_object_or_404(Site, pk=site_id)
    col = shop.orders_col(site)
    if not col:
        return {"orders": []}
    rows = [{**r.data, "_id": r.id, "member": r.owner.email if r.owner_id else ""} for r in col.records.select_related("owner").order_by("-id")[:1000]]
    st, q = request.GET.get("status"), (request.GET.get("q") or "").strip().lower()
    if st:
        rows = [r for r in rows if r.get("status") == st]
    if q:
        rows = [r for r in rows if q in f"{r.get('number')} {r.get('customer')} {r.get('phone')} {r.get('email')}".lower()]
    for r in rows:
        r.pop("token", None)
    return {"orders": rows}


@require_POST
@api
def shop_order_update(request, site_id, record_id):
    from . import shop

    site = get_object_or_404(Site, pk=site_id)
    col = shop.orders_col(site)
    rec = get_object_or_404(Record, pk=record_id, collection=col)
    d = body(request)
    try:
        shop.set_status(site, rec, d.get("status") or rec.data.get("status"), d.get("admin_note"))
    except shop.ShopError as e:
        raise shop_error(e)
    return {"order": {**{k: v for k, v in rec.data.items() if k != "token"}, "_id": rec.id}}
