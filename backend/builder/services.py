"""Site/page operations shared by the views, the admin and the tests."""
import html as htmllib
import re

from django.db import transaction

from . import sections
from .models import Page, PageRevision, Record, SharedSection, Site, slugify_th

RESERVED_SLUGS = {"index", "css", "js", "assets", "__form", "static", "media", "api"}
NAV_RE = re.compile(r'<nav class="bw-nav-links">.*?</nav>', re.S)
FOOTER_MENU_RE = re.compile(r"(<div><h4>เมนู</h4>).*?(</div>)", re.S)
LOGO_RE = re.compile(r'(class="bw-logo">)แบรนด์ของคุณ(</a>)')


def unique_site_slug(base, exclude_id=None):
    base = slugify_th(base, "site")
    slug, n = base, 2
    while Site.objects.filter(slug=slug).exclude(pk=exclude_id).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def unique_page_slug(site, base, exclude_id=None):
    base = slugify_th(base, "page")
    if base in RESERVED_SLUGS:
        base = f"{base}-page"
    slug, n = base, 2
    while site.pages.filter(slug=slug).exclude(pk=exclude_id).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def validate_page_slug(site, slug, exclude_id=None):
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        return "ใช้ได้เฉพาะ a-z, 0-9 และ - (ขึ้นต้นด้วยตัวอักษรหรือตัวเลข)"
    if slug in RESERVED_SLUGS:
        return f"ชื่อ “{slug}” ถูกสงวนไว้ กรุณาใช้ชื่ออื่น"
    if site.pages.filter(slug=slug).exclude(pk=exclude_id).exists():
        return "มีหน้าที่ใช้ชื่อนี้แล้ว"
    return ""


def nav_links(pages, current_slug=None):
    out = []
    for p in pages:
        if not p["show_in_nav"]:
            continue
        href = "index.html" if p["is_home"] else f"{p['slug']}.html"
        out.append(f'<a href="{href}">{htmllib.escape(p["label"])}</a>')
    return "".join(out)


def personalize(html, site_name, pages):
    """Point template menus at the site's real pages and put the site name in the logo."""
    links = nav_links(pages)
    contact = next((p for p in pages if p["slug"] == "contact"), None)
    cta = f'<a href="contact.html" class="bw-btn">ติดต่อเรา</a>' if contact else ""
    if "data-bw-auto-nav" not in html:  # auto menus are filled at render time
        html = NAV_RE.sub(lambda m: f'<nav class="bw-nav-links">{links}{cta}</nav>', html)
        html = FOOTER_MENU_RE.sub(lambda m: m.group(1) + links + m.group(2), html)
    return brand(html, site_name)


def brand(html, site_name):
    return LOGO_RE.sub(lambda m: m.group(1) + htmllib.escape(site_name) + m.group(2), html)


def page_dicts(site):
    return [
        {"slug": p.slug, "label": p.menu_label, "is_home": p.is_home, "show_in_nav": p.show_in_nav}
        for p in site.pages.order_by("nav_order", "id")
    ]


@transaction.atomic
def create_site(name, template_id="blank", description=""):
    tpl = sections.TEMPLATE_BY_ID.get(template_id) or sections.TEMPLATE_BY_ID["blank"]
    site = Site.objects.create(name=name, slug=unique_site_slug(name), description=description, theme=dict(tpl["theme"]))
    planned = [{"slug": slug, "label": title, "is_home": i == 0, "show_in_nav": True}
               for i, (title, slug, _) in enumerate(tpl["pages"])]
    for i, (title, slug, ids) in enumerate(tpl["pages"]):
        html, css = sections.compose(ids)
        Page.objects.create(
            site=site, title=site.name if i == 0 else title, nav_label=title, slug=slug, is_home=i == 0, nav_order=i,
            html=personalize(html, site.name, planned), css=css,
        )
    # Blank sites start with an empty (disabled) header/footer the user can switch on later.
    has_parts = any(set(ids) & sections.SHARED_IDS for _, _, ids in tpl["pages"])
    has_contact = any(slug == "contact" for _, slug, _ in tpl["pages"])
    site.nav = {"cta": {"show": has_parts, "text": "ติดต่อเรา", "href": "contact.html" if has_contact else "#contact"}}
    site.save(update_fields=["nav"])
    create_shared(site, enabled=has_parts, managed_header=True)
    return site


def create_shared(site, enabled=True, managed_header=False):
    for kind, sid in ((SharedSection.HEADER, "navbar"), (SharedSection.FOOTER, "footer")):
        sec = sections.BY_ID[sid]
        SharedSection.objects.get_or_create(site=site, kind=kind, defaults={
            "enabled": enabled, "html": brand(sec["html"], site.name), "css": sec["css"],
            "managed": managed_header and kind == SharedSection.HEADER,
        })


def set_header_managed(site, managed):
    """Switch the header between the navbar settings (managed) and free design in the editor."""
    from .navbar import render_header

    create_shared(site, enabled=True)
    sec = site.shared_sections.get(kind=SharedSection.HEADER)
    if not managed and sec.managed:
        # Start the free design from what the settings produce; keep the menu automatic.
        html = render_header(site, list(site.pages.all()), None)
        html = re.sub(r'<span class="bw-nav-menu">.*?</span>(?=<a |</nav>)',
                      '<span class="bw-nav-menu" data-bw-auto-nav></span>', html, count=1, flags=re.S)
        from .navbar import NAV_CSS

        sec.html, sec.css, sec.project_data = html, NAV_CSS, {}
    sec.managed, sec.enabled = managed, True
    sec.save()
    site.touch()
    return sec


def similar(a, b, threshold=0.7):
    from difflib import SequenceMatcher

    text = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()[:4000]  # noqa: E731
    ta, tb = text(a), text(b)
    return ta == tb or SequenceMatcher(None, ta, tb).ratio() >= threshold


HEADER_RE = re.compile(r"<header\b[^>]*>.*?</header>", re.S | re.I)
FOOTER_RE = re.compile(r"<footer\b[^>]*>.*?</footer>", re.S | re.I)


@transaction.atomic
def extract_shared(site, min_pages=1):
    """Older sites (and imported ones) repeat their header/footer on every page: take them from the home
    page into the shared sections and remove them from all pages. Returns how many pages changed.

    ``min_pages``: only treat a header/footer as shared when that many pages contain it (the importer uses
    2, so a one-off <header class="hero"> on the home page stays where it is)."""
    home = site.home_page()
    if not home:
        return 0
    from .render import strip_body

    body = strip_body(home.html)
    found = {SharedSection.HEADER: HEADER_RE.search(body), SharedSection.FOOTER: FOOTER_RE.search(body)}
    if min_pages > 1:
        bodies = [strip_body(p.html) for p in site.pages.all()]
        for kind, rx in ((SharedSection.HEADER, HEADER_RE), (SharedSection.FOOTER, FOOTER_RE)):
            ref = found[kind]
            if ref and sum(1 for b in bodies if (m := rx.search(b)) and similar(m.group(0), ref.group(0), 0.85)) < min_pages:
                found[kind] = None
    if not any(found.values()):
        raise ValueError("ไม่พบ <header> หรือ <footer> ในหน้าแรก")
    for kind, m in found.items():
        if not m:
            continue
        html = m.group(0)
        if kind == SharedSection.HEADER:
            html = re.sub(r'<nav class="bw-nav-links">(.*?)(<a [^>]*class="bw-btn"[^>]*>.*?</a>)?\s*</nav>',
                          lambda n: '<nav class="bw-nav-links"><span class="bw-nav-auto" data-bw-auto-nav></span>'
                          + (n.group(2) or "") + "</nav>", html, count=1, flags=re.S)
        else:
            html = re.sub(r"(<div><h4>เมนู</h4>).*?(</div>)",
                          lambda n: n.group(1) + '<nav class="bw-footer-links" data-bw-auto-nav></nav>' + n.group(2),
                          html, count=1, flags=re.S)
        SharedSection.objects.update_or_create(site=site, kind=kind, defaults={
            "enabled": True, "html": html, "css": home.css, "project_data": {}})
    changed = 0
    for p in site.pages.all():
        new = strip_body(p.html)
        for kind, rx in ((SharedSection.HEADER, HEADER_RE), (SharedSection.FOOTER, FOOTER_RE)):
            ref = found[kind]
            m = rx.search(new) if ref else None
            # Only remove it when it is the same header/footer as the home page's (not e.g. an <article> header).
            if m and similar(m.group(0), ref.group(0)):
                new = new[:m.start()] + new[m.end():]
        if new != strip_body(p.html):
            PageRevision.snapshot(p, "ก่อนแยกส่วนหัว/ท้ายร่วม")
            p.html, p.project_data = new.strip(), {}
            p.save(update_fields=["html", "project_data", "updated_at"])
            changed += 1
    site.touch()
    return changed


@transaction.atomic
def create_page(site, title, slug="", layout="basic", **fields):
    layout_def = sections.LAYOUT_BY_ID.get(layout) or sections.LAYOUT_BY_ID["blank"]
    slug = slug or unique_page_slug(site, title)
    order = (site.pages.order_by("-nav_order").values_list("nav_order", flat=True).first() or 0) + 1
    shared = site.shared_sections.filter(enabled=True).exists()
    html, css = sections.compose(layout_def["sections"], shared=shared)
    html = html.replace("<h1>ชื่อหน้า</h1>", f"<h1>{htmllib.escape(title)}</h1>")
    page = Page(site=site, title=title, slug=slug, nav_order=order, **fields)
    pages = page_dicts(site) + [{"slug": slug, "label": page.menu_label, "is_home": False, "show_in_nav": page.show_in_nav}]
    page.html = personalize(html, site.name, pages)
    page.css = css
    if not site.pages.exists():
        page.is_home = True
    page.save()
    if page.is_home:
        page.make_home()
    site.touch()
    return page


@transaction.atomic
def duplicate_page(page):
    copy = Page.objects.get(pk=page.pk)
    copy.pk = None
    copy.is_home = False
    copy.title = f"{page.title} (สำเนา)"
    copy.nav_label = f"{page.menu_label} (สำเนา)" if page.nav_label else ""
    copy.slug = unique_page_slug(page.site, f"{page.slug}-copy")
    copy.nav_order = page.nav_order + 1
    copy.save()
    return copy


@transaction.atomic
def delete_page(page):
    site = page.site
    was_home = page.is_home
    page.delete()
    if was_home:
        nxt = site.pages.order_by("nav_order", "id").first()
        if nxt:
            nxt.make_home()
    site.touch()


@transaction.atomic
def duplicate_site(site):
    pages = list(site.pages.all())
    copy = Site.objects.get(pk=site.pk)
    copy.pk = None
    copy.name = f"{site.name} (สำเนา)"
    copy.slug = unique_site_slug(f"{site.slug}-copy")
    copy.host_port = None  # unique, and the copy should not take over the original's address
    copy.base_url, copy.publish = "", {}
    copy.save()
    col_map = {}
    for col in site.collections.all():
        records = list(col.records.all())
        old_id = col.pk
        col.pk = None
        col.site = copy
        col.save()
        col_map[old_id] = col
        Record.objects.bulk_create([Record(collection=col, data=r.data, position=r.position, approved=r.approved)
                                    for r in records], batch_size=500)
    for p in pages:
        p.pk = None
        p.site = copy
        p.parent = None
        p.collection = col_map.get(p.collection_id)
        p.save()
    for sec in SharedSection.objects.filter(site=site):
        sec.pk = None
        sec.site = copy
        sec.save()
    return copy


def save_shared(sec, project, html, css, js=""):
    sec.project_data, sec.html, sec.css, sec.js = project or {}, html or "", css or "", js or ""
    sec.save()
    sec.site.touch()


def save_editor(page, project, html, css, js="", snapshot_every=300):
    """Store the editor state. A revision is kept at most every ``snapshot_every`` seconds."""
    from django.utils import timezone

    last = page.revisions.first()
    if page.html and (not last or (timezone.now() - last.created_at).total_seconds() > snapshot_every):
        PageRevision.snapshot(page, "บันทึกอัตโนมัติ")
    page.project_data = project or {}
    page.html = html or ""
    page.css = css or ""
    page.js = js or ""
    page.save(update_fields=["project_data", "html", "css", "js", "updated_at"])
    page.site.touch()


def restore_revision(rev):
    page = rev.page
    PageRevision.snapshot(page, "ก่อนย้อนเวอร์ชัน")
    page.project_data, page.html, page.css, page.js = rev.project_data, rev.html, rev.css, rev.js
    page.save(update_fields=["project_data", "html", "css", "js", "updated_at"])
    return page
