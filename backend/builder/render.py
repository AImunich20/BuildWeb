"""Turn a Site into plain files: <page>.html, css/, js/, assets/.

The same output is used for in-app preview, the hosting server and export, so what you see in the
preview is exactly what gets exported. Paths are relative (``about.html``, ``assets/logo.png``), which
works for a folder opened from disk, for XAMPP htdocs and for the hosting server alike.
"""
import html as htmllib
import re
from datetime import datetime, time as dtime
from email.utils import format_datetime
from urllib.parse import quote, unquote, urljoin

from django.conf import settings

from .models import Page, SharedSection, Site

MEDIA_RE = re.compile(r"""(?:https?://(?:127\.0\.0\.1|localhost)(?::\d+)?)?/media/([^"')\s?#]+)""")
BODY_RE = re.compile(r"^\s*<body[^>]*>(.*)</body>\s*$", re.S | re.I)
# Menus marked data-bw-auto-nav are filled with the site's pages at render time, so they never go stale.
AUTO_NAV_RE = re.compile(r"(<(span|nav|div|ul)\b[^>]*\bdata-bw-auto-nav\b[^>]*>).*?(</\2>)", re.S | re.I)

BASE_CSS = """*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:var(--bw-font-body),system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--bw-text);
background:var(--bw-background);line-height:1.65;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4,h5,h6{font-family:var(--bw-font-heading),var(--bw-font-body),sans-serif;line-height:1.25;margin:0 0 .5em}
p{margin:0 0 1em}
img,video{max-width:100%;height:auto}
a{color:var(--bw-primary)}
.bw-container{max-width:var(--bw-max-width);margin:0 auto;padding:0 20px}
.bw-btn{display:inline-block;padding:12px 26px;border-radius:999px;background:var(--bw-primary);color:#fff;
text-decoration:none;font-weight:600;border:2px solid var(--bw-primary);transition:transform .15s,box-shadow .15s}
.bw-btn:hover{transform:translateY(-2px);box-shadow:0 10px 24px -10px var(--bw-primary)}
.bw-btn-outline{background:transparent;color:var(--bw-primary)}
.bw-form-status{margin-top:12px;font-weight:600}
.bw-form-status.ok{color:#059669}.bw-form-status.err{color:#dc2626}
.bw-dd{position:relative;display:inline-flex;align-items:center}
.bw-dd>a::after{content:" ▾";font-size:.8em}
.bw-dd-menu{display:none;position:absolute;top:100%;left:0;min-width:190px;background:#fff;border-radius:12px;padding:8px;
box-shadow:0 18px 40px -16px rgba(0,0,0,.3);z-index:60;flex-direction:column}
.bw-dd-menu a{display:block;padding:8px 12px;border-radius:8px;white-space:nowrap}
.bw-dd-menu a:hover{background:var(--bw-surface)}
.bw-dd:hover .bw-dd-menu,.bw-dd:focus-within .bw-dd-menu{display:flex}
@media (max-width:768px){.bw-dd{display:block}.bw-dd-menu{display:flex;position:static;box-shadow:none;padding:0 0 0 14px;min-width:0}}
"""

SITE_JS = r"""(function(){
  var endpoint = document.body.getAttribute('data-bw-form');
  document.addEventListener('click', function(e){
    var t = e.target.closest('[data-bw-menu-toggle]');
    if (t) { var nav = document.querySelector(t.getAttribute('data-bw-menu-toggle')); if (nav) nav.classList.toggle('open'); }
  });
  document.querySelectorAll('form').forEach(function(form){
    if (form.hasAttribute('data-bw-native') || form.hasAttribute('data-bw-auth')) return;
    var hp = document.createElement('input'); hp.type = 'text'; hp.name = '_hp'; hp.tabIndex = -1; hp.autocomplete = 'off';
    hp.setAttribute('aria-hidden', 'true'); hp.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0';
    form.appendChild(hp);
    form.addEventListener('submit', function(e){
      e.preventDefault();
      var status = form.querySelector('.bw-form-status');
      if (!status) { status = document.createElement('div'); status.className = 'bw-form-status'; form.appendChild(status); }
      if (!endpoint) { status.className = 'bw-form-status err'; status.textContent = 'ยังไม่ได้ตั้งค่าที่ส่งฟอร์ม'; return; }
      var data = new FormData(form);
      data.append('_form', form.getAttribute('name') || form.id || 'form');
      data.append('_page', document.body.getAttribute('data-bw-page') || '');
      if (form.getAttribute('data-bw-collection')) data.append('_collection', form.getAttribute('data-bw-collection'));
      var btn = form.querySelector('[type=submit],button'); if (btn) btn.disabled = true;
      fetch(endpoint, {method: 'POST', body: data}).then(function(r){
        return r.json().catch(function(){ return {}; }).then(function(j){ if (!r.ok) throw new Error(j.error || r.status); return j; });
      }).then(function(j){
        status.className = 'bw-form-status ok';
        status.textContent = (j.pending && form.getAttribute('data-bw-pending')) || form.getAttribute('data-bw-success') ||
          (j.pending ? 'ส่งเรียบร้อย ข้อมูลจะแสดงหลังผ่านการตรวจสอบ' : 'ส่งข้อมูลเรียบร้อย ขอบคุณค่ะ');
        form.reset();
      }).catch(function(err){
        status.className = 'bw-form-status err';
        status.textContent = err && err.message && !/^\d+$/.test(err.message) ? err.message : 'ส่งไม่สำเร็จ กรุณาลองใหม่';
      }).finally(function(){ if (btn) btn.disabled = false; });
    });
  });
})();
"""

GOOGLE_FONTS = {
    "Prompt", "Kanit", "Sarabun", "Noto Sans Thai", "Mitr", "IBM Plex Sans Thai", "Bai Jamjuree", "Chakra Petch",
    "Anuphan", "K2D", "Niramit", "Pridi", "Taviraj", "Trirong", "Inter", "Poppins", "Roboto", "Montserrat",
    "Playfair Display", "Lora", "Open Sans", "Noto Serif Thai",
}


def theme_css(site):
    t = site.get_theme()
    return (
        ":root{"
        f"--bw-primary:{t['primary']};--bw-secondary:{t['secondary']};--bw-accent:{t['accent']};"
        f"--bw-text:{t['text']};--bw-muted:{t['muted']};--bw-background:{t['background']};--bw-surface:{t['surface']};"
        f"--bw-font-heading:'{t['font_heading']}';--bw-font-body:'{t['font_body']}';"
        f"--bw-radius:{t['radius']};--bw-max-width:{t['max_width']}"
        "}\n"
    )


def fonts_url(site):
    if not site.use_base_styles:
        return ""
    t = site.get_theme()
    fams = [f for f in dict.fromkeys([t["font_heading"], t["font_body"]]) if f in GOOGLE_FONTS]
    if not fams:
        return ""
    q = "&".join(f"family={quote(f).replace('%20', '+')}:wght@300;400;500;600;700" for f in fams)
    return f"https://fonts.googleapis.com/css2?{q}&display=swap"


def rel_media(text, prefix=""):
    """/media/sites/x/logo.png -> assets/sites/x/logo.png (relative to the site root). CSS files live in
    css/, so they pass prefix="../"."""
    return MEDIA_RE.sub(lambda m: prefix + "assets/" + m.group(1), text or "")


def media_paths(text):
    return set(MEDIA_RE.findall(text or ""))


def shared_sections(site):
    """{"header": SharedSection|None, "footer": ...} — only enabled ones."""
    out = {SharedSection.HEADER: None, SharedSection.FOOTER: None}
    for sec in site.shared_sections.filter(enabled=True):
        out[sec.kind] = sec
    return out


def site_css(site):
    from .anim import ANIM_CSS
    from .navbar import NAV_CSS

    from .widgets import CONTACT_CSS, DATA_CSS, SHOP_CSS

    shared = "\n".join(sec.css for sec in site.shared_sections.filter(enabled=True) if sec.css and not sec.managed)
    base = BASE_CSS if site.use_base_styles else ""
    return (theme_css(site) + base + NAV_CSS + ANIM_CSS + DATA_CSS + CONTACT_CSS + (SHOP_CSS if (site.shop or {}).get("enabled") else "")
            + "\n" + shared + "\n"
            + (site.custom_css or ""))


def site_js(site):
    from .anim import ANIM_JS
    from .navbar import NAV_JS

    from .widgets import AUTH_JS, DATA_JS, SDK_JS, SHOP_JS

    core = (SITE_JS.replace("\n})();", NAV_JS + ANIM_JS + DATA_JS + "\n})();", 1) + SDK_JS + AUTH_JS
            + (SHOP_JS if (site.shop or {}).get("enabled") else ""))
    shared = "\n".join(sec.js for sec in site.shared_sections.filter(enabled=True) if sec.js and not sec.managed)
    return core + "\n" + shared + "\n" + (site.custom_js or "")


def header_html(sec, site, pages, page):
    """The shared header for ``page``: generated from the navbar settings, or the freely designed one."""
    if sec.managed:
        from .navbar import render_header

        return render_header(site, pages, page)
    return strip_body(sec.html)


def nav_html(pages, current=None):
    """Menu links for the pages shown in the menu; child pages become a dropdown under their parent."""
    shown = [p for p in pages if p.show_in_nav and not p.collection_id]  # detail pages have no menu entry
    ids = {p.id for p in shown}
    e = htmllib.escape

    def link(p):
        cls = ' class="active"' if current is not None and p.id == current.id else ""
        return f'<a href="{p.filename}"{cls}>{e(p.menu_label)}</a>'

    out = []
    for p in shown:
        if p.parent_id in ids:
            continue
        kids = [c for c in shown if c.parent_id == p.id]
        if kids:
            out.append(f'<span class="bw-dd">{link(p)}<span class="bw-dd-menu">{"".join(link(c) for c in kids)}</span></span>')
        else:
            out.append(link(p))
    return "".join(out)


def fill_nav(html, pages, current=None):
    links = nav_html(pages, current)
    return AUTO_NAV_RE.sub(lambda m: m.group(1) + links + m.group(3), html or "")


# <div data-bw-member-fields="register|account"></div> inside a member form gets the site's extra member fields
# (Site.auth["fields"]) at render time, so the forms follow the field list set in the app.
MEMBER_FIELDS_RE = re.compile(r'(<div\b[^>]*\bdata-bw-member-fields="(register|account)"[^>]*>).*?(</div>)', re.S | re.I)
MEMBER_FIELDS_CSS = ("<style>[data-bw-member-fields]{display:contents}"
                     ".bw-auth select,.bw-auth textarea{font:inherit;font-weight:400;padding:12px 14px;border:1px solid #d9d9e3;border-radius:10px;background:#fff}"
                     ".bw-auth .bw-check{display:flex;align-items:center;gap:8px;font-weight:500}.bw-auth .bw-check input{width:18px;height:18px}</style>")
INPUT_TYPES = {"number": "number", "phone": "tel", "email": "email", "date": "date", "link": "url"}


def member_fields_html(fields, where, user=None):
    e = htmllib.escape
    out = []
    for f in fields:
        if not f.get(where):
            continue
        val = (user.profile or {}).get(f["name"], "") if user is not None else ""
        req = " required" if f.get("required") else ""
        name, label = e(f["name"]), e(f["label"]) + (" *" if f.get("required") else "")
        ph = f' placeholder="{e(f["placeholder"])}"' if f.get("placeholder") else ""
        if f["type"] == "bool":
            on = " checked" if val in (True, "True", "true", "1", "on") else ""
            out.append(f'<label class="bw-check"><input type="hidden" name="{name}" value="">'
                       f'<input type="checkbox" name="{name}" value="on"{on}{req}> {label}</label>')
        elif f["type"] == "select":
            opts = "".join(f'<option value="{e(o)}"{" selected" if str(val) == o else ""}>{e(o)}</option>' for o in f.get("options") or [])
            out.append(f'<label>{label}<select name="{name}"{req}><option value="">— เลือก —</option>{opts}</select></label>')
        elif f["type"] == "longtext":
            out.append(f'<label>{label}<textarea name="{name}" rows="3"{ph}{req}>{e(str(val))}</textarea></label>')
        else:
            t = INPUT_TYPES.get(f["type"], "text")
            step = ' step="any"' if t == "number" else ""
            out.append(f'<label>{label}<input type="{t}" name="{name}" value="{e(str(val))}"{ph}{step}{req}></label>')
    return "".join(out)


def fill_member_fields(html, site, user=None):
    if "data-bw-member-fields" not in html:
        return html
    fields = (site.auth or {}).get("fields") or []
    html = html.replace("</head>", MEMBER_FIELDS_CSS + "</head>", 1) if "</head>" in html else MEMBER_FIELDS_CSS + html
    return MEMBER_FIELDS_RE.sub(lambda m: m.group(1) + member_fields_html(fields, m.group(2).lower(), user) + m.group(3), html)


def strip_body(html):
    m = BODY_RE.match(html or "")
    return m.group(1) if m else (html or "")


def page_css(page):
    return rel_media((page.css or "") + "\n" + (page.custom_css or ""), "../")


def body_html(page):
    return strip_body(page.html)


def full_body(page, pages, shared=None, row=None, include_drafts=False, user=None):
    """Shared header + page content + shared footer, with auto menus filled in. ``row``: the row a detail
    page shows."""
    shared = shared if shared is not None else shared_sections(page.site)
    parts = []
    head, foot = shared.get(SharedSection.HEADER), shared.get(SharedSection.FOOTER)
    if head and page.use_header:
        parts.append(header_html(head, page.site, pages, page))
    parts.append(body_html(page))
    if foot and page.use_footer:
        parts.append(strip_body(foot.html))
    from .data import render_html

    out = render_html(fill_nav("\n".join(parts), pages, page), page.site, page, row, include_drafts, user)
    return fill_member_fields(out, page.site, user)  # after the binder: member values are never read as {{…}}


def visible_pages(site, include_drafts):
    qs = site.pages.all()
    return list(qs if include_drafts else qs.filter(status=Page.PUBLISHED))


def page_meta(page, row=None, include_drafts=False):
    """(title, description, og_image) of a page; on a detail page {{fields}} in the SEO settings are filled
    from the row and empty ones fall back to the row's title / text / image."""
    site = page.site
    if row is None:
        title = page.seo_title or (page.title if page.is_home and page.title == site.name else f"{page.title} | {site.name}")
        return title, page.seo_description or site.description, page.og_image
    from .data import render_html, strip_tags, title_field

    fields = page.collection.fields if page.collection_id else []

    def fill(text):
        return strip_tags(render_html(text, site, page, row, include_drafts)) if text else ""

    name = strip_tags(row.get(title_field(fields), "")) or page.title
    title = fill(page.seo_title) or f"{name} | {site.name}"
    desc = fill(page.seo_description)
    if not desc:
        for f in fields:
            if f.get("type") in ("longtext", "html") or f["name"] in ("excerpt", "description", "detail", "summary"):
                desc = strip_tags(row.get(f["name"], ""))
                if desc:
                    break
    if len(desc) > 160:
        desc = desc[:157].rstrip() + "…"
    image = render_html(page.og_image, site, page, row, include_drafts) if page.og_image else ""
    if not image or "{{" in image:
        image = next((str(row.get(f["name"]) or "") for f in fields if f.get("type") == "image" and row.get(f["name"])), "")
    return title, desc or site.description, image


def page_path(page, row=None):
    """Path of a page (or one row of a detail page) relative to the site root."""
    if row is not None:
        return row.get("_url") or f"{page.slug}/{quote(str(row.get('_slug', '')))}.html"
    return "" if page.is_home else page.filename


def absolute(site, rel, base=None):
    base = base if base is not None else site.base_url
    if not base or re.match(r"^[a-z]+:", rel or "", re.I):
        return rel
    return urljoin(base if base.endswith("/") else base + "/", rel or "")


def render_page(page, form_endpoint="", depth_prefix="", include_drafts=False, pages=None, shared=None, row=None,
                user=None, owner_view=True):
    """Full HTML document for a page. ``form_endpoint`` is where forms POST (empty = not configured).
    ``row``: render a detail page for this row (it lives one folder down, so it gets <base href="../">)."""
    site = page.site
    if pages is None:
        pages = visible_pages(site, include_drafts)
    if not owner_view:  # members-only pages stay out of the menu for those who can't open them
        from .members import can_view

        pages = [p for p in pages if can_view(p, user)]
    e = htmllib.escape
    title, desc, og_image = page_meta(page, row, include_drafts)
    from .anim import ANIM_HEAD

    head = ['<meta charset="utf-8">']
    if row is not None:
        head.append('<base href="../">')
    head += [
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        ANIM_HEAD,
        f"<title>{e(title)}</title>",
        '<meta name="generator" content="BuildWeb">',
    ]
    if desc:
        head.append(f'<meta name="description" content="{e(desc)}">')
    if page.seo_keywords:
        head.append(f'<meta name="keywords" content="{e(page.seo_keywords)}">')
    if page.noindex:
        head.append('<meta name="robots" content="noindex">')
    og_title = title if row is not None else (page.seo_title or page.title)
    head.append(f'<meta property="og:title" content="{e(og_title)}">')
    head.append(f'<meta property="og:type" content="{"article" if row is not None else "website"}">')
    head.append(f'<meta property="og:site_name" content="{e(site.name)}">')
    if desc:
        head.append(f'<meta property="og:description" content="{e(desc)}">')
    if og_image:
        head.append(f'<meta property="og:image" content="{e(absolute(site, rel_media(og_image)))}">')
        head.append('<meta name="twitter:card" content="summary_large_image">')
    if site.base_url and not page.noindex:
        url = absolute(site, page_path(page, row))
        head.append(f'<link rel="canonical" href="{e(url)}">')
        head.append(f'<meta property="og:url" content="{e(url)}">')
    if feed_collections(site, include_drafts):
        head.append(f'<link rel="alternate" type="application/rss+xml" title="{e(site.name)}" href="{depth_prefix}rss.xml">')
    if site.favicon:
        head.append(f'<link rel="icon" href="{e(rel_media(site.favicon))}">')
    fu = fonts_url(site)
    if fu:
        head.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
        head.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
        head.append(f'<link rel="stylesheet" href="{fu}">')
    head.append(f'<link rel="stylesheet" href="{depth_prefix}css/site.css">')
    head.append(f'<link rel="stylesheet" href="{depth_prefix}css/{page.slug}.css">')
    if site.head_code:
        head.append(rel_media(site.head_code))
    if page.head_code:
        head.append(rel_media(page.head_code))

    from .widgets import contact_html

    body = rel_media(full_body(page, pages, shared, row, include_drafts, user)) + "\n" + rel_media(contact_html(site))
    if (site.shop or {}).get("enabled"):
        from .shop import settings as shop_settings

        body += (f'\n<a class="bw-cartfab" href="{e(shop_settings(site)["pages"]["cart"])}" hidden aria-label="ตะกร้าสินค้า">'
                 '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/>'
                 '<circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/></svg>'
                 'ตะกร้า <b data-bw-cart-count>0</b></a>')
    scripts = [f'<script src="{depth_prefix}js/site.js"></script>']
    if page.js:
        scripts.append(f"<script>\n{page.js}\n</script>")
    if page.custom_js:
        scripts.append(f"<script>\n{page.custom_js}\n</script>")
    attrs = f' data-bw-page="{e(page.slug)}"'
    if (site.auth or {}).get("enabled"):
        from .members import settings as member_settings

        ms = member_settings(site)
        attrs += f' data-bw-after-login="{e(ms["after_login"] or ms["pages"]["account"])}"'
    if (site.shop or {}).get("enabled"):
        import json as _json

        from .shop import settings as shop_settings

        attrs += f' data-bw-shop="{e(site.slug)}" data-bw-shop-pages="{e(_json.dumps(shop_settings(site)["pages"]))}"'
    if page.body_class:
        attrs = f' class="{e(page.body_class)}"' + attrs
    if form_endpoint:
        attrs += f' data-bw-form="{e(form_endpoint)}"'
    return (
        f'<!doctype html>\n<html lang="{e(site.language or "th")}">\n<head>\n'
        + "\n".join(head)
        + f"\n</head>\n<body{attrs}>\n{body}\n"
        + "\n".join(scripts)
        + "\n</body>\n</html>\n"
    )


def form_endpoint_for(site, mode):
    """Where forms POST.  host/preview: the BuildWeb receiver; export: the site's setting or bw-form.php."""
    if mode in ("host", "preview"):
        return "__form"
    if site.form_endpoint:
        return site.form_endpoint
    return ""


def build_files(site, mode="export", include_drafts=False, php_forms=False):
    """Return ({relative_path: str}, {relative_asset_path: media_relative_path})."""
    endpoint = form_endpoint_for(site, mode)
    if mode == "export" and not endpoint and php_forms:
        endpoint = "bw-form.php"
    files = {"css/site.css": rel_media(site_css(site), "../"), "js/site.js": site_js(site)}
    referenced = media_paths(site.favicon) | media_paths(site.custom_css) | media_paths(site.head_code)
    shared = shared_sections(site)
    for sec in shared.values():
        if sec:
            referenced |= media_paths(sec.html) | media_paths(sec.css)
    # Members-only pages need the BuildWeb server to check who is asking: they never go into static files.
    pages = [p for p in visible_pages(site, include_drafts) if not p.access]
    for page in pages:
        if page.collection_id:  # one file per row: <page>/<row>.html
            for row in detail_items(page, include_drafts):
                files[f"{page.slug}/{row['_slug']}.html"] = render_page(page, endpoint, include_drafts=include_drafts,
                                                                        pages=pages, shared=shared, row=row)
                referenced |= media_paths(" ".join(str(v) for v in row.values()))
        else:
            files[page.filename] = render_page(page, endpoint, include_drafts=include_drafts, pages=pages, shared=shared)
        files[f"css/{page.slug}.css"] = page_css(page)
        for src in (page.html, page.css, page.custom_css, page.og_image, page.head_code):
            referenced |= media_paths(src)
    files["robots.txt"] = robots_txt(site, site.base_url, include_drafts)
    if site.base_url:
        files["sitemap.xml"] = sitemap_xml(site, site.base_url, include_drafts)
    if feed_collections(site, include_drafts):
        files["rss.xml"] = rss_xml(site, site.base_url, include_drafts)
    for c in site.collections.all():  # images of collection rows
        if c.mode == c.COPY:
            for rec in c.records.filter(approved=True):
                referenced |= media_paths(" ".join(str(v) for v in rec.data.values()))
    # Every file uploaded to the site goes along, so links to PDFs etc. typed by hand keep working.
    for path in site.assets.values_list("file", flat=True):
        referenced.add(path)
    # HTML references are URL-encoded (Thai file names); files on disk are not.
    paths = {unquote(p) for p in referenced}
    assets = {f"assets/{p}": p for p in paths if (settings.MEDIA_ROOT / p).is_file()}
    return files, assets


def resolve(site, path, include_drafts, base=""):
    """Map a request path inside a site to ('text', content_type, str) / ('media', path) /
    ('page', page, row) / None. ``base``: absolute URL of the site root (for sitemap/RSS)."""
    path = unquote(path.lstrip("/")) or "index.html"
    base = site.base_url or base
    if path == "robots.txt":
        return "text", "text/plain", robots_txt(site, base, include_drafts)
    if path == "sitemap.xml":
        return "text", "application/xml", sitemap_xml(site, base, include_drafts)
    if path == "rss.xml" and feed_collections(site, include_drafts):
        return "text", "application/rss+xml", rss_xml(site, base, include_drafts)
    if path == "css/site.css":
        return "text", "text/css", rel_media(site_css(site), "../")
    if path == "js/site.js":
        return "text", "application/javascript", site_js(site)
    if path.startswith("assets/"):
        return "media", path[len("assets/"):]
    pages = site.pages.all() if include_drafts else site.pages.filter(status=Page.PUBLISHED)
    if path.startswith("css/") and path.endswith(".css"):
        page = pages.filter(slug=path[4:-4]).first()
        return ("text", "text/css", page_css(page)) if page else None
    if path.endswith("/"):
        path = path[:-1]
    folder, _, name = path.rpartition("/")
    if folder and "/" not in folder:  # <detail page>/<row>.html
        page = pages.filter(slug=folder, collection__isnull=False).first()
        if not page:
            return None
        want = name[:-5] if name.endswith(".html") else name
        row = next((r for r in detail_items(page, include_drafts) if r["_slug"] == want), None)
        return ("page", page, row) if row else None
    if path in ("", "index.html", "index"):
        page = pages.filter(is_home=True, collection__isnull=True).first() or pages.filter(collection__isnull=True).first()
    else:
        slug = path[:-5] if path.endswith(".html") else path
        page = pages.filter(slug=slug).first()
    if not page:
        return None
    if page.collection_id:  # the template itself: show its first row while designing, nothing on the live site
        rows = detail_items(page, include_drafts) if include_drafts else []
        return ("page", page, rows[0]) if rows else None
    return "page", page, None


# --- detail pages, sitemap, robots, RSS -----------------------------------------------------------

def detail_items(page, include_drafts=False):
    """Rows of a detail page, each with _slug, _url, _prev_url/_next_url and _prev_title/_next_title."""
    from .data import detail_href, detail_rows, strip_tags, title_field

    try:
        items = detail_rows(page.collection, page.detail_field)
    except Exception:  # live MySQL down: no detail pages rather than a crash
        return []
    tf = title_field(page.collection.fields)
    out = []
    for i, (slug, row) in enumerate(items):
        prev, nxt = (items[i - 1] if i else None), (items[i + 1] if i + 1 < len(items) else None)
        out.append({**row, "_slug": slug, "_url": detail_href(page, slug), "_index": i + 1,
                    "_prev_url": detail_href(page, prev[0]) if prev else "", "_prev_title": strip_tags(prev[1].get(tf, "")) if prev else "",
                    "_next_url": detail_href(page, nxt[0]) if nxt else "", "_next_title": strip_tags(nxt[1].get(tf, "")) if nxt else ""})
    return out


def site_urls(site, include_drafts=False):
    """[(relative path, lastmod datetime)] of every indexable page, detail rows included."""
    out = []
    for page in visible_pages(site, include_drafts):
        if page.noindex or page.access:  # members-only pages are not for search engines
            continue
        if page.collection_id:
            out += [(page_path(page, row), page.updated_at) for row in detail_items(page, include_drafts)]
        else:
            out.append((page_path(page), page.updated_at))
    return out


def sitemap_xml(site, base, include_drafts=False):
    e = htmllib.escape
    items = "".join(f"<url><loc>{e(absolute(site, path, base))}</loc><lastmod>{mod:%Y-%m-%d}</lastmod></url>\n"
                    for path, mod in site_urls(site, include_drafts))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}</urlset>\n'


def robots_txt(site, base, include_drafts=False):
    lines = ["User-agent: *"]
    hidden = [p for p in visible_pages(site, include_drafts) if p.noindex]
    lines += [f"Disallow: /{p.slug + '/' if p.collection_id else p.filename}" for p in hidden] or ["Disallow:"]
    if base:
        lines.append(f"Sitemap: {absolute(site, 'sitemap.xml', base)}")
    return "\n".join(lines) + "\n"


def feed_collections(site, include_drafts=False):
    """Detail pages whose collection has RSS turned on."""
    qs = site.pages.filter(collection__isnull=False).select_related("collection")
    if not include_drafts:
        qs = qs.filter(status=Page.PUBLISHED)
    return [p for p in qs if p.collection.opt("rss")]


def rss_xml(site, base, include_drafts=False):
    from .data import parse_date, strip_tags, title_field

    e = htmllib.escape
    items = []
    for page in feed_collections(site, include_drafts):
        fields = page.collection.fields
        tf = title_field(fields)
        date_f = next((f["name"] for f in fields if f.get("type") == "date"), None)
        cat_f = next((f["name"] for f in fields if f["name"].lower() in ("category", "หมวด", "หมวดหมู่", "tag")), None)
        for row in detail_items(page, include_drafts):
            _, desc, _ = page_meta(page, row, include_drafts)
            d = parse_date(row.get(date_f)) if date_f else None
            when = datetime.combine(d, dtime(9, 0)).astimezone() if d else page.updated_at
            link = absolute(site, row["_url"], base)
            items.append((when, f"<item><title>{e(strip_tags(row.get(tf, '')))}</title><link>{e(link)}</link>"
                                f"<guid>{e(link)}</guid><pubDate>{format_datetime(when)}</pubDate>"
                                + (f"<category>{e(str(row.get(cat_f)))}</category>" if cat_f and row.get(cat_f) else "")
                                + f"<description>{e(desc)}</description></item>"))
    items.sort(key=lambda x: x[0], reverse=True)
    home = absolute(site, "", base) or "./"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>{e(site.name)}</title><link>{e(home)}</link><description>{e(site.description or site.name)}</description>"
            f"<language>{e(site.language or 'th')}</language>\n" + "\n".join(i for _, i in items[:50]) + "\n</channel></rss>\n")


def site_for_slug(slug, published_only):
    qs = Site.objects.filter(slug=slug)
    if published_only:
        qs = qs.filter(published=True)
    return qs.first()
