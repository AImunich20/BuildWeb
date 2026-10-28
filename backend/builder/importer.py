"""Import an existing website (HTML files, a .zip, a folder, or a GitHub repository) into BuildWeb.

Every .html file becomes a page. Local stylesheets become the site's CSS, inline <style> becomes page CSS,
scripts are kept (external ones in <head>, local/inline ones as page JavaScript), images/fonts/files are
uploaded to the file manager, and links between the pages are rewritten to the new file names.

Archives are untrusted: paths are sanitised, sizes are capped, and nothing from them is ever executed.
"""
import io
import posixpath
import re
import urllib.error
import urllib.request
import zipfile
from html import unescape
from urllib.parse import quote, unquote, urlsplit

from django.core.files.base import ContentFile
from django.db import transaction

from . import services
from .models import Asset, Page, Site, slugify_th

MAX_FILES = 4000
MAX_TOTAL = 300 * 1024 * 1024
MAX_FILE = 100 * 1024 * 1024
MAX_PAGES = 300
SKIP_DIRS = {"__MACOSX", ".git", "node_modules", ".github", ".idea", ".vscode", "__pycache__"}
BUILD_DIRS = ("dist", "build", "public", "docs", "site", "_site", "out", "www")

TAG_RE = lambda tag: re.compile(rf"<{tag}\b[^>]*>(.*?)</{tag}>", re.S | re.I)  # noqa: E731
HEAD_RE = re.compile(r"<head\b[^>]*>(.*?)</head>", re.S | re.I)
BODY_RE = re.compile(r"<body\b([^>]*)>(.*?)(?:</body>|$)", re.S | re.I)
TITLE_RE = TAG_RE("title")
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ATTR_RE = lambda name: re.compile(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)  # noqa: E731
REF_ATTR_RE = re.compile(r"""(\s(?:src|href|poster|data-src|data-background|action)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
SRCSET_RE = re.compile(r"""(\s(?:srcset|data-srcset)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
STYLE_ATTR_RE = re.compile(r"""(\sstyle\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
CSS_URL_RE = re.compile(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", re.I)
CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\()?\s*["']([^"']+)["']\s*\)?\s*([^;]*);""", re.I)
GITHUB_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(?:tree|blob)/([^/]+)(?:/(.*))?)?/?$")
SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+)$")


class ImportErrorTH(ValueError):
    pass


def attr(tag, name):
    m = ATTR_RE(name).search(tag)
    return unescape(next(g for g in m.groups() if g is not None)) if m else ""


def is_external(ref):
    r = ref.strip().lower()
    return r.startswith(("http://", "https://", "//", "data:", "mailto:", "tel:", "javascript:", "#", "sms:", "blob:")) or not r


# --- collecting files -----------------------------------------------------------------------------

class Bundle:
    """Files of the site being imported: {posix relative path: bytes}."""

    def __init__(self):
        self.files = {}
        self.total = 0

    def add(self, path, data):
        path = clean_path(path)
        if not path:
            return
        if len(self.files) >= MAX_FILES:
            raise ImportErrorTH(f"ไฟล์เยอะเกินไป (เกิน {MAX_FILES} ไฟล์)")
        if len(data) > MAX_FILE:
            return  # skip huge files (videos etc.) rather than failing the whole import
        self.total += len(data)
        if self.total > MAX_TOTAL:
            raise ImportErrorTH("ขนาดรวมเกิน 300 MB")
        self.files[path] = data

    def strip_common_prefix(self):
        if not self.files:
            return
        firsts = {p.split("/", 1)[0] for p in self.files}
        if len(firsts) == 1 and all("/" in p for p in self.files):
            prefix = firsts.pop() + "/"
            self.files = {p[len(prefix):]: d for p, d in self.files.items()}

    def subdir(self, sub):
        sub = clean_path(sub or "").strip("/")
        if not sub:
            return
        prefix = sub + "/"
        picked = {p[len(prefix):]: d for p, d in self.files.items() if p.startswith(prefix)}
        if not picked:
            raise ImportErrorTH(f"ไม่พบโฟลเดอร์ “{sub}” ใน repo")
        self.files = picked


def clean_path(path):
    parts = []
    for part in (path or "").replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return ""  # never allow escaping the archive
        if part in SKIP_DIRS or part == ".DS_Store" or part.startswith("._"):
            return ""
        parts.append(part)
    return "/".join(parts)


def from_zip(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ImportErrorTH("ไฟล์ .zip เสียหรือไม่ใช่ zip") from e
    b = Bundle()
    for info in z.infolist():
        if info.is_dir() or info.file_size > MAX_FILE:
            continue
        if info.file_size + b.total > MAX_TOTAL:
            raise ImportErrorTH("ขนาดรวมหลังแตกไฟล์เกิน 300 MB")
        name = info.filename
        if info.flag_bits & 0x800 == 0:
            try:  # zips made on Thai Windows/macOS without the UTF-8 flag
                name = name.encode("cp437").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        b.add(name, z.read(info))
    b.strip_common_prefix()
    return b


def from_uploads(files, paths=None):
    """Uploaded files (optionally with their relative paths from a folder upload). A single .zip is
    unpacked."""
    paths = paths or []
    if len(files) == 1 and files[0].name.lower().endswith(".zip"):
        return from_zip(files[0].read())
    b = Bundle()
    for i, f in enumerate(files):
        rel = paths[i] if i < len(paths) and paths[i] else f.name
        b.add(rel, f.read())
    b.strip_common_prefix()
    return b


def parse_github(url):
    url = (url or "").strip()
    m = GITHUB_RE.match(url) or SHORT_RE.match(url)
    if not m:
        raise ImportErrorTH("ลิงก์ GitHub ไม่ถูกต้อง — ตัวอย่าง https://github.com/ชื่อผู้ใช้/ชื่อrepo")
    g = m.groups()
    return g[0], g[1], (g[2] if len(g) > 2 else None), (g[3] if len(g) > 3 else None)


def download(url, headers, limit=MAX_TOTAL):
    req = urllib.request.Request(url, headers={"User-Agent": "BuildWeb-importer", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ImportErrorTH("GitHub ปฏิเสธการเข้าถึง — repo ส่วนตัวต้องใส่ token หรือถูกจำกัดจำนวนครั้ง ลองใหม่ภายหลัง") from e
        if e.code == 404:
            raise ImportErrorTH("ไม่พบ repo หรือ branch นี้ (ถ้าเป็น repo ส่วนตัวต้องใส่ token)") from e
        raise ImportErrorTH(f"ดาวน์โหลดจาก GitHub ไม่ได้ ({e.code})") from e
    except urllib.error.URLError as e:
        raise ImportErrorTH(f"เชื่อมต่อ GitHub ไม่ได้: {e.reason}") from e
    if len(data) > limit:
        raise ImportErrorTH("repo ใหญ่เกิน 300 MB")
    return data


def from_github(url, branch="", subdir="", token=""):
    owner, repo, url_branch, url_sub = parse_github(url)
    ref = (branch or url_branch or "").strip()
    if token:
        api = f"https://api.github.com/repos/{owner}/{repo}/zipball/{quote(ref)}" if ref else \
            f"https://api.github.com/repos/{owner}/{repo}/zipball"
        data = download(api, {"Authorization": f"Bearer {token.strip()}", "Accept": "application/vnd.github+json"})
    else:
        data = download(f"https://github.com/{owner}/{repo}/archive/{quote(ref) if ref else 'HEAD'}.zip", {})
    b = from_zip(data)
    b.subdir(subdir or url_sub or "")
    return b, f"{owner}/{repo}"


def find_root(bundle):
    """The folder holding the site: the shallowest index.html, preferring build output folders."""
    htmls = [p for p in bundle.files if p.lower().endswith((".html", ".htm"))]
    if not htmls:
        if "package.json" in bundle.files:
            raise ImportErrorTH("ไม่พบไฟล์ HTML — โปรเจกต์นี้ต้อง build ก่อน (เช่น React/Vue/Vite) "
                                "ให้ build แล้วนำเข้าโฟลเดอร์ dist/ หรือ build/ แทน")
        raise ImportErrorTH("ไม่พบไฟล์ .html ในสิ่งที่นำเข้า")
    index = sorted((p for p in htmls if posixpath.basename(p).lower() in ("index.html", "index.htm")),
                   key=lambda p: (p.count("/"), p))
    if index and index[0].count("/") == 0:
        return ""
    for d in BUILD_DIRS:
        if f"{d}/index.html" in bundle.files:
            return d
    if index:
        return posixpath.dirname(index[0])
    return posixpath.dirname(sorted(htmls, key=lambda p: (p.count("/"), p))[0])


def decode(data):
    for enc in ("utf-8-sig", "cp874", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


# --- converting -----------------------------------------------------------------------------------

class Importer:
    def __init__(self, bundle, site, root=""):
        self.b = bundle
        self.site = site
        self.root = root
        self.assets = {}  # bundle path -> media url
        self.page_files = {}  # bundle path -> new filename
        self.css_parts = []
        self.css_seen = set()
        self.warnings = []
        self.asset_count = 0

    # paths
    def resolve(self, base_dir, ref):
        ref = unescape(ref.strip())
        parts = urlsplit(ref)
        path = parts.path
        if not path:
            return None, ref
        if path.startswith("/"):
            full = posixpath.normpath(posixpath.join(self.root, path.lstrip("/")))
        else:
            full = posixpath.normpath(posixpath.join(base_dir, path))
        full = unquote(full)
        suffix = (f"?{parts.query}" if parts.query else "") + (f"#{parts.fragment}" if parts.fragment else "")
        return full, suffix

    def asset_url(self, path):
        if path in self.assets:
            return self.assets[path]
        data = self.b.files.get(path)
        if data is None:
            return None
        rel = posixpath.relpath(path, self.root or ".") if self.root else path
        folder = "imported/" + posixpath.dirname(rel) if posixpath.dirname(rel) else "imported"
        name = posixpath.basename(path)
        a = Asset(site=self.site, name=name, folder=folder.strip("/"), kind=Asset.kind_for(name), size=len(data))
        a.file.save(name, ContentFile(data), save=False)
        a.name = posixpath.basename(a.file.name)
        a.save()
        self.assets[path] = a.url
        self.asset_count += 1
        return a.url

    def rewrite_ref(self, base_dir, ref):
        if is_external(ref):
            return ref
        path, suffix = self.resolve(base_dir, ref)
        if path is None:
            return ref
        if path in self.page_files:
            return self.page_files[path] + (suffix if suffix.startswith("#") else "")
        for candidate in (path, posixpath.join(path, "index.html")):
            if candidate in self.page_files:
                return self.page_files[candidate] + (suffix if "#" in suffix else "")
        url = self.asset_url(path)
        return url + (suffix if "#" in suffix else "") if url else ref

    def rewrite_css(self, css, base_dir, depth=0):
        def imp(m):
            if depth > 5 or is_external(m.group(1)):
                return m.group(0)
            path, _ = self.resolve(base_dir, m.group(1))
            data = self.b.files.get(path)
            if data is None:
                return m.group(0)
            return self.rewrite_css(decode(data), posixpath.dirname(path), depth + 1)

        css = CSS_IMPORT_RE.sub(imp, css)
        return CSS_URL_RE.sub(lambda m: f'url("{self.rewrite_ref(base_dir, m.group(2))}")', css)

    def rewrite_html(self, html, base_dir):
        html = REF_ATTR_RE.sub(lambda m: m.group(1) + m.group(2) + self.rewrite_ref(base_dir, m.group(3)) + m.group(2), html)

        def srcset(m):
            items = []
            for item in m.group(3).split(","):
                bits = item.strip().split(None, 1)
                if bits:
                    bits[0] = self.rewrite_ref(base_dir, bits[0])
                    items.append(" ".join(bits))
            return m.group(1) + m.group(2) + ", ".join(items) + m.group(2)

        html = SRCSET_RE.sub(srcset, html)
        return STYLE_ATTR_RE.sub(lambda m: m.group(1) + m.group(2) + self.rewrite_css(m.group(3), base_dir) + m.group(2), html)

    # pages
    def plan_pages(self, htmls, start_order):
        used = set(self.site.pages.values_list("slug", flat=True))
        home_taken = self.site.pages.filter(is_home=True).exists()
        plan = []
        root_index = posixpath.join(self.root, "index.html") if self.root else "index.html"
        for path in htmls:
            rel = posixpath.relpath(path, self.root) if self.root else path
            stem = re.sub(r"\.html?$", "", rel, flags=re.I)
            is_home = path.lower() in (root_index.lower(), root_index.lower()[:-1]) and not home_taken
            base = "home" if is_home else slugify_th(stem.replace("/index", "").replace("/", "-"), "page")
            if base in services.RESERVED_SLUGS:
                base += "-page"
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            self.page_files[path] = "index.html" if is_home else f"{slug}.html"
            plan.append((path, slug, is_home))
        if not home_taken and not any(h for _, _, h in plan) and plan:
            path, slug, _ = plan[0]
            plan[0] = (path, slug, True)
            self.page_files[path] = "index.html"
        return plan

    def convert_page(self, path, slug, is_home, order):
        raw = COMMENT_RE.sub("", decode(self.b.files[path]))
        base_dir = posixpath.dirname(path)
        hm = HEAD_RE.search(raw)
        head = hm.group(1) if hm else ""
        bm = BODY_RE.search(raw)
        body_attrs, body = (bm.group(1), bm.group(2)) if bm else ("", HEAD_RE.sub("", raw))
        title = unescape((TITLE_RE.search(head).group(1) if TITLE_RE.search(head) else "").strip()) or slug
        desc = kw = ""
        for tag in META_RE.findall(head):
            n = attr(tag, "name").lower()
            if n == "description":
                desc = attr(tag, "content")
            elif n == "keywords":
                kw = attr(tag, "content")
        head_code, page_css, js = [], [], []
        for tag in LINK_RE.findall(head) + LINK_RE.findall(body):
            rel = attr(tag, "rel").lower()
            href = attr(tag, "href")
            if not href:
                continue
            if "stylesheet" in rel:
                if is_external(href):
                    head_code.append(tag)
                else:
                    p, _ = self.resolve(base_dir, href)
                    if p in self.b.files and p not in self.css_seen:
                        self.css_seen.add(p)
                        self.css_parts.append(f"/* {posixpath.basename(p)} */\n" + self.rewrite_css(decode(self.b.files[p]), posixpath.dirname(p)))
            elif "icon" in rel and not is_external(href):
                url = self.rewrite_ref(base_dir, href)
                if url.startswith("/media/") and not self.site.favicon:
                    self.site.favicon = url
            elif is_external(href) and rel in ("preconnect", "dns-prefetch", "preload"):
                head_code.append(tag)
        body = LINK_RE.sub("", body)
        for css in STYLE_RE.findall(head) + STYLE_RE.findall(body):
            page_css.append(self.rewrite_css(css, base_dir))
        body = STYLE_RE.sub("", body)
        for attrs, code in SCRIPT_RE.findall(head) + SCRIPT_RE.findall(body):
            src, typ = attr(attrs, "src"), attr(attrs, "type").lower()
            if src and is_external(src):
                head_code.append(f"<script{attrs}></script>")
            elif src:
                p, _ = self.resolve(base_dir, src)
                if p in self.b.files:
                    if typ == "module":
                        self.warnings.append(f"{posixpath.basename(path)}: สคริปต์แบบ module ({posixpath.basename(p)}) อาจทำงานไม่ครบ")
                    js.append(decode(self.b.files[p]))
            elif typ in ("application/ld+json", "application/json", "text/template", "text/x-template"):
                head_code.append(f"<script{attrs}>{code}</script>")
            elif code.strip():
                js.append(code)
        body = SCRIPT_RE.sub("", body)
        body = self.rewrite_html(body, base_dir).strip()
        page = Page.objects.create(
            site=self.site, title=title[:200], slug=slug, is_home=is_home, nav_order=order,
            nav_label=("หน้าแรก" if is_home else title[:100]), show_in_nav=True,
            seo_description=desc, seo_keywords=kw[:300], head_code="\n".join(dict.fromkeys(head_code)),
            body_class=attr(f"<body{body_attrs}>", "class")[:300], html=body, css="\n".join(page_css),
            custom_js="\n;\n".join(js), use_header=True, use_footer=True,
        )
        return page

    def run(self):
        htmls = sorted((p for p in self.b.files if p.lower().endswith((".html", ".htm"))
                        and (not self.root or p.startswith(self.root + "/"))),
                       key=lambda p: (p.count("/"), p != posixpath.join(self.root, "index.html").lstrip("/"), p))
        if len(htmls) > MAX_PAGES:
            self.warnings.append(f"นำเข้าเฉพาะ {MAX_PAGES} หน้าแรก จากทั้งหมด {len(htmls)} หน้า")
            htmls = htmls[:MAX_PAGES]
        start = (self.site.pages.order_by("-nav_order").values_list("nav_order", flat=True).first() or 0) + 1
        pages = []
        for i, (path, slug, is_home) in enumerate(self.plan_pages(htmls, start)):
            pages.append(self.convert_page(path, slug, is_home, start + i))
        if self.css_parts:
            marker = "/* ---- imported ---- */"
            self.site.custom_css = ((self.site.custom_css + "\n" + marker + "\n") if self.site.custom_css else "") + "\n\n".join(self.css_parts)
        self.site.save()
        for p in pages:
            if p.is_home:
                p.make_home()
        return pages


@transaction.atomic
def import_bundle(bundle, site=None, name="", extract_parts=True, menu_only_top=True):
    root = find_root(bundle)
    created = site is None
    if created:
        site = Site.objects.create(name=name or "เว็บที่นำเข้า", slug=services.unique_site_slug(name or "imported"),
                                   use_base_styles=False)
    imp = Importer(bundle, site, root)
    pages = imp.run()
    if menu_only_top and len(pages) > 12:
        for p in pages[12:]:
            p.show_in_nav = False
            p.save(update_fields=["show_in_nav"])
    shared_note = ""
    if extract_parts and len(pages) > 1:
        try:
            services.extract_shared(site, min_pages=max(2, (len(pages) + 1) // 2))
        except ValueError:
            shared_note = "ไม่พบ <header>/<footer> ที่ใช้ร่วมกัน — แต่ละหน้าเก็บส่วนหัว/ท้ายของตัวเองไว้"
    services.create_shared(site, enabled=False)
    if shared_note:
        imp.warnings.append(shared_note)
    return {
        "site_id": site.id, "created": created, "pages": len(pages), "assets": imp.asset_count,
        "css_files": len(imp.css_parts), "root": root or "/", "warnings": imp.warnings,
        "editor": f"/sites/{site.id}/edit/{site.home_page().id}/" if site.home_page() else f"/sites/{site.id}/",
    }
