"""Turn a Site into plain files: <page>.html, css/, js/, assets/.

The same output is used for in-app preview, the hosting server and export, so what you see in the
preview is exactly what gets exported. Paths are relative (``about.html``, ``assets/logo.png``), which
works for a folder opened from disk, for XAMPP htdocs and for the hosting server alike.
"""
import html as htmllib
import re
from urllib.parse import quote, unquote

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
    if (form.hasAttribute('data-bw-native')) return;
    form.addEventListener('submit', function(e){
      e.preventDefault();
      var status = form.querySelector('.bw-form-status');
      if (!status) { status = document.createElement('div'); status.className = 'bw-form-status'; form.appendChild(status); }
      if (!endpoint) { status.className = 'bw-form-status err'; status.textContent = 'ยังไม่ได้ตั้งค่าที่ส่งฟอร์ม'; return; }
      var data = new FormData(form);
      data.append('_form', form.getAttribute('name') || form.id || 'form');
      data.append('_page', document.body.getAttribute('data-bw-page') || '');
      var btn = form.querySelector('[type=submit],button'); if (btn) btn.disabled = true;
      fetch(endpoint, {method: 'POST', body: data}).then(function(r){
        if (!r.ok) throw new Error(r.status);
        status.className = 'bw-form-status ok';
        status.textContent = form.getAttribute('data-bw-success') || 'ส่งข้อมูลเรียบร้อย ขอบคุณค่ะ';
        form.reset();
      }).catch(function(){
        status.className = 'bw-form-status err'; status.textContent = 'ส่งไม่สำเร็จ กรุณาลองใหม่';
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
    shared = "\n".join(sec.css for sec in site.shared_sections.filter(enabled=True) if sec.css)
    base = BASE_CSS if site.use_base_styles else ""
    return theme_css(site) + base + "\n" + shared + "\n" + (site.custom_css or "")


def site_js(site):
    shared = "\n".join(sec.js for sec in site.shared_sections.filter(enabled=True) if sec.js)
    return SITE_JS + "\n" + shared + "\n" + (site.custom_js or "")


def nav_html(pages, current=None):
    """Menu links for the pages shown in the menu; child pages become a dropdown under their parent."""
    shown = [p for p in pages if p.show_in_nav]
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


def strip_body(html):
    m = BODY_RE.match(html or "")
    return m.group(1) if m else (html or "")


def page_css(page):
    return rel_media((page.css or "") + "\n" + (page.custom_css or ""), "../")


def body_html(page):
    return strip_body(page.html)


def full_body(page, pages, shared=None):
    """Shared header + page content + shared footer, with auto menus filled in."""
    shared = shared if shared is not None else shared_sections(page.site)
    parts = []
    head, foot = shared.get(SharedSection.HEADER), shared.get(SharedSection.FOOTER)
    if head and page.use_header:
        parts.append(strip_body(head.html))
    parts.append(body_html(page))
    if foot and page.use_footer:
        parts.append(strip_body(foot.html))
    return fill_nav("\n".join(parts), pages, page)


def visible_pages(site, include_drafts):
    qs = site.pages.all()
    return list(qs if include_drafts else qs.filter(status=Page.PUBLISHED))


def render_page(page, form_endpoint="", depth_prefix="", include_drafts=False, pages=None, shared=None):
    """Full HTML document for a page. ``form_endpoint`` is where forms POST (empty = not configured)."""
    site = page.site
    if pages is None:
        pages = visible_pages(site, include_drafts)
    e = htmllib.escape
    title = page.seo_title or (page.title if page.is_home and page.title == site.name else f"{page.title} | {site.name}")
    desc = page.seo_description or site.description
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(title)}</title>",
        '<meta name="generator" content="BuildWeb">',
    ]
    if desc:
        head.append(f'<meta name="description" content="{e(desc)}">')
    if page.seo_keywords:
        head.append(f'<meta name="keywords" content="{e(page.seo_keywords)}">')
    if page.noindex:
        head.append('<meta name="robots" content="noindex">')
    head.append(f'<meta property="og:title" content="{e(page.seo_title or page.title)}">')
    head.append('<meta property="og:type" content="website">')
    if desc:
        head.append(f'<meta property="og:description" content="{e(desc)}">')
    if page.og_image:
        head.append(f'<meta property="og:image" content="{e(rel_media(page.og_image))}">')
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

    body = rel_media(full_body(page, pages, shared))
    scripts = [f'<script src="{depth_prefix}js/site.js"></script>']
    if page.js:
        scripts.append(f"<script>\n{page.js}\n</script>")
    if page.custom_js:
        scripts.append(f"<script>\n{page.custom_js}\n</script>")
    attrs = f' data-bw-page="{e(page.slug)}"'
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
    pages = visible_pages(site, include_drafts)
    for page in pages:
        files[page.filename] = render_page(page, endpoint, pages=pages, shared=shared)
        files[f"css/{page.slug}.css"] = page_css(page)
        for src in (page.html, page.css, page.custom_css, page.og_image, page.head_code):
            referenced |= media_paths(src)
    # Every file uploaded to the site goes along, so links to PDFs etc. typed by hand keep working.
    for path in site.assets.values_list("file", flat=True):
        referenced.add(path)
    # HTML references are URL-encoded (Thai file names); files on disk are not.
    paths = {unquote(p) for p in referenced}
    assets = {f"assets/{p}": p for p in paths if (settings.MEDIA_ROOT / p).is_file()}
    return files, assets


def resolve(site, path, include_drafts):
    """Map a request path inside a site to ('text', content_type, str) / ('media', path) / None."""
    path = path.lstrip("/") or "index.html"
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
    if path in ("", "index.html", "index"):
        page = pages.filter(is_home=True).first() or pages.first()
    else:
        slug = path[:-5] if path.endswith(".html") else path
        page = pages.filter(slug=slug).first()
    if not page:
        return None
    return "page", page


def site_for_slug(slug, published_only):
    qs = Site.objects.filter(slug=slug)
    if published_only:
        qs = qs.filter(published=True)
    return qs.first()
