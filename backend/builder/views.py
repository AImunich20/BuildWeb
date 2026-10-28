import csv
import json
import re

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from buildweb import config

from . import dbtools, generate, members, render as renderer, sections, services, stats
from .render import fonts_url
from .api import page_json, site_json
from .hosting import server as hosting
from .models import FormSubmission, Page, SharedSection, Site


def dump(data):
    # Embedded in <script type="application/json">: never let user content close the tag.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def dashboard(request):
    sites = Site.objects.all()
    cards = []
    for s in sites:
        home = s.home_page()
        spark = stats.sparkline(s)
        cards.append({"site": s, "home": home, "pages": s.pages.count(),
                      "unread": s.submissions.filter(is_read=False).count(),
                      "views": sum(spark[-7:]), "spark": spark_svg(spark)})
    return render(request, "builder/dashboard.html", {
        "cards": cards,
        "templates": sections.TEMPLATES,
        "stats": {
            "sites": sites.count(), "pages": Page.objects.count(),
            "unread": FormSubmission.objects.filter(is_read=False).count(),
            "views": sum(c["views"] for c in cards),
        },
        "hosting": hosting.status(),
        "site_choices": [{"id": s.id, "name": s.name} for s in sites],
        "nav": "dashboard",
    })


def spark_svg(values, w=120, h=28):
    """Tiny inline line chart of views per day for a dashboard card."""
    if not any(values):
        return ""
    top = max(values)
    step = w / max(1, len(values) - 1)
    pts = " ".join(f"{i * step:.1f},{h - 2 - (v / top) * (h - 4):.1f}" for i, v in enumerate(values))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" '
            f'stroke-linecap="round"/></svg>')


def site_manage(request, site_id, tab="pages"):
    site = get_object_or_404(Site, pk=site_id)
    if tab not in ("pages", "data", "api", "members", "files", "forms", "stats", "settings", "export"):
        tab = "pages"
    data = {
        "site": site_json(site),
        "pages": [page_json(p) for p in site.pages.all()],
        "layouts": sections.PAGE_LAYOUTS,
        "hosting": hosting.status(),
        "xampp": dbtools.xampp_info(),
        "export": config.load()["export"],
        "collections": [{"id": c.id, "name": c.name, "slug": c.slug, "fields": c.fields} for c in site.collections.all()],
        "roles": members.all_roles(site), "members_on": members.settings(site)["enabled"],
    }
    return render(request, "builder/site.html", {
        "site": site, "tab": tab, "data_json": dump(data),
        "unread": site.submissions.filter(is_read=False).count(), "nav": "sites",
    })


LINK_RE = re.compile(r"<link\b[^>]*rel=[\"']?stylesheet[^>]*>", re.I)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*src=[\"']([^\"']+)[\"']", re.I)
# Scripts that generate CSS at runtime; loaded into the editor canvas so imported sites look right.
CANVAS_SCRIPTS = ("cdn.tailwindcss.com",)


def canvas_assets(*head_codes):
    styles, scripts = [], []
    for code in head_codes:
        for tag in LINK_RE.findall(code or ""):
            m = HREF_RE.search(tag)
            if m:
                styles.append(m.group(1))
        for src in SCRIPT_SRC_RE.findall(code or ""):
            if any(k in src for k in CANVAS_SCRIPTS):
                scripts.append(src)
    return styles, scripts


def editor_page_data(site):
    return {
        "site": site_json(site),
        "pages": [page_json(p) for p in site.pages.all()],
        "preview_base": f"/preview/{site.slug}/",
        "fonts_url": fonts_url(site),
        "layouts": sections.PAGE_LAYOUTS,
        "collections": [{"id": c.id, "slug": c.slug, "name": c.name, "fields": c.fields, "mode": c.mode,
                         "forms": c.opt("forms"), "form_html": generate.form_html(c, f"ส่ง{c.name}"),
                         "has_detail": c.detail_pages.exists()}
                        for c in site.collections.all()],
        "members": {"enabled": members.settings(site)["enabled"], "pages": members.settings(site)["pages"]},
        "sections": [{"id": s["id"], "label": s["label"], "category": s["category"], "icon": s["icon"],
                      "content": sections.block_content(s)} for s in sections.SECTIONS],
    }


def editor(request, site_id, page_id):
    site = get_object_or_404(Site, pk=site_id)
    page = get_object_or_404(Page, pk=page_id, site=site)
    data = editor_page_data(site)
    pages = list(site.pages.all())
    shared = renderer.shared_sections(site)
    styles, scripts = canvas_assets(site.head_code, page.head_code)
    data.update({
        "page": page_json(page),
        "target": {"type": "page", "id": page.id, "title": page.title, "label": page.filename,
                   "storage": f"/api/pages/{page.id}/project"},
        # Shared header/footer shown (read-only) around the page in the canvas.
        "shared_preview": {
            kind: {"html": renderer.fill_nav(renderer.header_html(sec, site, pages, page) if kind == "header" else
                                              renderer.strip_body(sec.html), pages, page),
                   "css": "" if sec.managed else sec.css,
                   "edit_url": f"/sites/{site.id}/pages/?navbar=1" if sec.managed else f"/sites/{site.id}/edit-shared/{kind}/"}
            for kind, sec in shared.items()
            if sec and (page.use_header if kind == "header" else page.use_footer)
        },
        "canvas_styles": styles, "canvas_scripts": scripts,
    })
    return render(request, "builder/editor.html", {"site": site, "page": page, "data_json": dump(data)})


def editor_shared(request, site_id, kind):
    site = get_object_or_404(Site, pk=site_id)
    if kind not in (SharedSection.HEADER, SharedSection.FOOTER):
        raise Http404
    services.create_shared(site, enabled=False)  # make sure both exist
    sec = site.shared_sections.get(kind=kind)
    if sec.managed:  # generated from the navbar settings: edit those instead
        return redirect(f"/sites/{site.id}/pages/?navbar=1")
    data = editor_page_data(site)
    styles, scripts = canvas_assets(site.head_code)
    home = site.home_page()
    data.update({
        "page": page_json(home) if home else None,
        "target": {"type": "shared", "id": sec.id, "kind": kind, "title": sec.label, "label": "ใช้ทุกหน้า",
                   "enabled": sec.enabled, "storage": f"/api/shared/{sec.id}/project"},
        "shared_preview": {}, "canvas_styles": styles, "canvas_scripts": scripts,
        "nav_preview": renderer.nav_html(list(site.pages.all())),
    })
    return render(request, "builder/editor.html", {"site": site, "page": {"title": sec.label, "filename": "ใช้ทุกหน้า"},
                                                   "shared": sec, "data_json": dump(data)})


def editor_home(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    home = site.home_page()
    return redirect(f"/sites/{site.id}/edit/{home.id}/") if home else redirect(f"/sites/{site.id}/")


def settings_page(request):
    return render(request, "builder/settings.html", {
        "nav": "settings",
        "data_json": dump({
            "hosting": hosting.status(),
            "sites": [{"slug": s.slug, "name": s.name} for s in Site.objects.all()],
        }),
    })


def database_page(request):
    return render(request, "builder/database.html", {"nav": "database"})


def submissions_csv(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    subs = list(site.submissions.select_related("page"))
    keys = []
    for s in subs:
        for k in s.data:
            if k not in keys:
                keys.append(k)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{site.slug}-forms.csv"'
    resp.write("﻿")  # Excel needs the BOM to read Thai correctly
    w = csv.writer(resp)
    w.writerow(["วันที่", "ฟอร์ม", "หน้า", *keys, "IP"])
    for s in subs:
        w.writerow([s.created_at.strftime("%Y-%m-%d %H:%M"), s.form_name, s.page.title if s.page else "",
                    *[s.data.get(k, "") if not isinstance(s.data.get(k), list) else ", ".join(s.data[k]) for k in keys],
                    s.ip])
    return resp


def notify_page(request):
    return render(request, "builder/notify.html", {"nav": "notify"})
