"""Pages generated from a collection: a list page (cards with search/categories/paging) and a detail page
(one page per row), plus the ready-made blog (collection + both pages + sample posts)."""
import html as htmllib
import re
from datetime import date, timedelta

from django.db import transaction

from . import data, sections, services
from .models import Collection, Page, Record

CAT_NAMES = ("category", "categories", "หมวด", "หมวดหมู่", "type", "ประเภท", "tag", "tags")
SKIP_RE = re.compile(r"^(id|_?id|.*_id|slug|approved|position|created_at|updated_at)$", re.I)

LIST_CSS = """.bw-list-sec{padding:56px 0 72px}
.bw-list-head{margin-bottom:22px}.bw-list-head h1{margin:0 0 6px}.bw-list-head p{margin:0;color:var(--bw-muted)}
.bw-list-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:22px}
.bw-list-card{display:flex;flex-direction:column;background:#fff;border:1px solid #ececf1;border-radius:var(--bw-radius);overflow:hidden;color:inherit;text-decoration:none;transition:transform .2s,box-shadow .2s}
.bw-list-card:hover{transform:translateY(-4px);box-shadow:0 20px 40px -26px rgba(0,0,0,.35)}
.bw-list-card img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;background:var(--bw-surface)}
.bw-list-body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:6px;flex:1}
.bw-list-body h3{margin:0;font-size:1.15em}.bw-list-body p{margin:0;color:var(--bw-muted);font-size:.95em}
.bw-list-meta{font-size:.82em;color:var(--bw-primary);font-weight:600;letter-spacing:.02em}
.bw-list-more{margin-top:auto;padding-top:8px;font-weight:600;color:var(--bw-primary)}"""

DETAIL_CSS = """.bw-detail{padding:40px 0 72px}
.bw-back{display:inline-flex;gap:6px;align-items:center;color:var(--bw-muted);text-decoration:none;margin-bottom:22px;font-size:.95em}
.bw-back:hover{color:var(--bw-primary)}
.bw-detail-grid{display:grid;grid-template-columns:1.1fr 1fr;gap:44px;align-items:start}
.bw-detail-grid:not(:has(> img)){grid-template-columns:minmax(0,760px)}
.bw-detail-img{width:100%;border-radius:var(--bw-radius);object-fit:cover;aspect-ratio:4/3;background:var(--bw-surface)}
.bw-detail h1{margin:0 0 10px;font-size:clamp(28px,4vw,40px)}
.bw-detail-meta{color:var(--bw-muted);margin:0 0 18px;display:flex;flex-wrap:wrap;gap:8px 14px;font-size:.95em}
.bw-detail-meta .bw-pill{background:var(--bw-surface);color:var(--bw-primary);padding:3px 12px;border-radius:999px;font-weight:600}
.bw-detail-rows{display:grid;gap:0;margin:18px 0;border-top:1px solid #ececf1}
.bw-detail-row{display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid #ececf1}
.bw-detail-row span{color:var(--bw-muted)}.bw-detail-row b{text-align:right}
.bw-detail-text{color:var(--bw-text);line-height:1.8}
.bw-article{max-width:760px;margin:0 auto}
.bw-article .bw-detail-img{aspect-ratio:16/9;margin:6px 0 28px}
.bw-article-body{font-size:1.08em;line-height:1.9}
.bw-article-body img{max-width:100%;border-radius:12px}.bw-article-body h2,.bw-article-body h3{margin-top:1.6em}
.bw-article-body blockquote{margin:1.4em 0;padding:4px 20px;border-left:4px solid var(--bw-primary);color:var(--bw-muted)}
.bw-pn{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:48px;padding-top:24px;border-top:1px solid #ececf1}
.bw-pn a{display:block;padding:14px 18px;border:1px solid #ececf1;border-radius:12px;text-decoration:none;color:inherit}
.bw-pn a:hover{border-color:var(--bw-primary)}.bw-pn small{display:block;color:var(--bw-muted)}
.bw-pn .bw-next{text-align:right;grid-column:2}
@media (max-width:768px){.bw-detail-grid{grid-template-columns:1fr;gap:24px}.bw-pn{grid-template-columns:1fr}.bw-pn .bw-next{grid-column:1}}"""


def roles(col):
    """Which field plays which part on a card / detail page."""
    fs = col.fields
    by_type = lambda t: next((f["name"] for f in fs if f.get("type") == t), None)  # noqa: E731
    title = data.title_field(fs)
    image = by_type("image")
    body = by_type("html")
    long = next((f["name"] for f in fs if f.get("type") == "longtext" and f["name"] != body), None)
    excerpt = next((f["name"] for f in fs if f["name"].lower() in ("excerpt", "summary", "short", "สรุป")), None) or long
    cat = next((f["name"] for f in fs if f["name"].lower() in CAT_NAMES), None)
    when = by_type("date")
    price = next((f["name"] for f in fs if f["name"].lower() in ("price", "ราคา", "cost")), None)
    used = {title, image, body, long, excerpt, cat, when}
    extra = [f for f in fs if f["name"] not in used and not SKIP_RE.match(f["name"]) and f.get("type") not in ("bool",)]
    return {"title": title, "image": image, "body": body, "long": long, "excerpt": excerpt, "cat": cat, "date": when,
            "price": price, "extra": extra}


def ph(name, flt=""):
    return "{{" + name + (("|" + flt) if flt else "") + "}}"


def list_html(col, title, intro="", per_page=9):
    r = roles(col)
    e = htmllib.escape
    meta = []
    if r["cat"]:
        meta.append(f'<span data-bw-if="{r["cat"]}">{ph(r["cat"])}</span>')
    if r["date"]:
        meta.append(f'<span data-bw-if="{r["date"]}">{ph(r["date"], "date")}</span>')
    attrs = f'data-bw-repeat="{col.slug}" data-bw-search="ค้นหา{e(title)}…" data-bw-paginate="{per_page}" data-bw-empty="ยังไม่มีข้อมูล"'
    if r["cat"]:
        attrs += f' data-bw-facet="{r["cat"]}"'
    if r["date"]:
        attrs += f' data-bw-sort="{r["date"]}" data-bw-order="desc"'
    price = f'<p class="bw-list-meta" data-bw-if="{r["price"]}">{ph(r["price"], "number")} บาท</p>' if r["price"] else ""
    excerpt = f'<p>{ph(r["excerpt"], "truncate:110")}</p>' if r["excerpt"] else ""
    return (f'<section class="bw-list-sec"><div class="bw-container">'
            f'<div class="bw-list-head" data-bw-anim="fade-up"><h1>{e(title)}</h1>' + (f"<p>{e(intro)}</p>" if intro else "") + '</div>'
            f'<div class="bw-list-grid" {attrs}>'
            f'<a class="bw-list-card" href="{{{{_url}}}}">'
            + (f'<img src="{ph(r["image"])}" alt="{ph(r["title"])}" loading="lazy" data-bw-if="{r["image"]}">' if r["image"] else "")
            + '<div class="bw-list-body">' + (f'<div class="bw-list-meta">{" · ".join(meta)}</div>' if meta else "")
            + f'<h3>{ph(r["title"])}</h3>{price}{excerpt}<span class="bw-list-more">อ่านต่อ →</span></div></a>'
            f'</div></div></section>')


def detail_html(col, back_href="index.html", back_label="กลับ"):
    r = roles(col)
    e = htmllib.escape
    back = f'<a class="bw-back" href="{e(back_href)}">← {e(back_label)}</a>'
    pn = ('<nav class="bw-pn"><a class="bw-prev" href="{{_prev_url}}" data-bw-if="_prev_url"><small>← ก่อนหน้า</small>{{_prev_title}}</a>'
          '<a class="bw-next" href="{{_next_url}}" data-bw-if="_next_url"><small>ถัดไป →</small>{{_next_title}}</a></nav>')
    meta = []
    if r["cat"]:
        meta.append(f'<span class="bw-pill" data-bw-if="{r["cat"]}">{ph(r["cat"])}</span>')
    if r["date"]:
        meta.append(f'<span data-bw-if="{r["date"]}">{ph(r["date"], "date")}</span>')
    author = next((f["name"] for f in col.fields if f["name"].lower() in ("author", "ผู้เขียน", "writer")), None)
    if author:
        meta.append(f'<span data-bw-if="{author}">โดย {ph(author)}</span>')
    img = (f'<img class="bw-detail-img" src="{ph(r["image"])}" alt="{ph(r["title"])}" data-bw-if="{r["image"]}">'
           if r["image"] else "")
    if r["body"]:  # article layout
        return (f'<section class="bw-detail"><div class="bw-container"><article class="bw-article">{back}'
                f'<h1>{ph(r["title"])}</h1><div class="bw-detail-meta">{"".join(meta)}</div>{img}'
                f'<div class="bw-article-body">{{{{{{{r["body"]}}}}}}}</div>{pn}</article></div></section>')
    rows = "".join(f'<div class="bw-detail-row" data-bw-if="{f["name"]}"><span>{e(f.get("label") or f["name"])}</span>'
                   f'<b>{ph(f["name"], "number" if f["name"] == r["price"] else "")}{" บาท" if f["name"] == r["price"] else ""}</b></div>'
                   for f in r["extra"])
    text = f'<div class="bw-detail-text" data-bw-if="{r["long"]}">{ph(r["long"])}</div>' if r["long"] else ""
    return (f'<section class="bw-detail"><div class="bw-container">{back}<div class="bw-detail-grid">{img}'
            f'<div><div class="bw-detail-meta">{"".join(meta)}</div><h1>{ph(r["title"])}</h1>{text}'
            f'<div class="bw-detail-rows">{rows}</div></div></div>{pn}</div></section>')


def _page(site, title, slug, html, css, **fields):
    order = (site.pages.order_by("-nav_order").values_list("nav_order", flat=True).first() or 0) + 1
    return Page.objects.create(site=site, title=title, slug=services.unique_page_slug(site, slug), html=html, css=css,
                               nav_order=order, **fields)


@transaction.atomic
def create_pages_for(col, list_title="", with_list=True, detail_slug=""):
    """A detail page for ``col`` and (optionally) a list page linking to it. Returns (list_page, detail_page)."""
    site = col.site
    list_page = None
    base = data.slugify_th(col.slug, "items")
    if with_list:
        list_title = list_title or col.name
        list_page = _page(site, list_title, base, list_html(col, list_title), LIST_CSS, show_in_nav=True)
    back = list_page.filename if list_page else "index.html"
    if not detail_slug:  # products.html lists, product/<row>.html shows one
        detail_slug = (base[:-1] if base.endswith("s") and len(base) > 3 else base + "-item") if with_list else base
    detail = _page(site, f"{col.name} (หน้ารายละเอียด)", detail_slug,
                   detail_html(col, back, f"กลับไป{list_title or 'หน้าแรก'}"), DETAIL_CSS, show_in_nav=False, collection=col,
                   seo_title="", seo_description="")
    site.touch()
    return list_page, detail


BLOG_FIELDS = [
    {"name": "title", "label": "หัวข้อ", "type": "text"},
    {"name": "slug", "label": "ชื่อลิงก์ (a-z)", "type": "text"},
    {"name": "cover", "label": "รูปปก", "type": "image"},
    {"name": "excerpt", "label": "สรุปสั้นๆ", "type": "longtext"},
    {"name": "content", "label": "เนื้อหา", "type": "html"},
    {"name": "category", "label": "หมวดหมู่", "type": "text"},
    {"name": "date", "label": "วันที่", "type": "date"},
    {"name": "author", "label": "ผู้เขียน", "type": "text"},
]

SAMPLE_POSTS = [
    ("ยินดีต้อนรับสู่บล็อกของเรา", "welcome", "ข่าวสาร",
     "บทความแรกของเรา เล่าที่มาของเว็บนี้และสิ่งที่คุณจะได้อ่านต่อจากนี้",
     "<p>นี่คือบทความตัวอย่าง แก้ไขหรือลบได้ที่แท็บ <b>ข้อมูล › บทความ</b> ในโปรแกรม BuildWeb</p>"
     "<h2>เขียนบทความใหม่</h2><p>กด “เพิ่มแถว” แล้วเขียนด้วยตัวแก้ไขข้อความ ใส่หัวข้อ รูป ลิงก์ และรายการได้</p>"
     "<blockquote>บทความใหม่จะขึ้นในหน้ารวมบทความ, หมวดหมู่ และ RSS ให้อัตโนมัติ</blockquote>"),
    ("5 เคล็ดลับเขียนบทความให้คนอ่านจนจบ", "writing-tips", "เคล็ดลับ",
     "หัวข้อชัด ย่อหน้าสั้น ใช้รูปช่วยเล่า และปิดท้ายด้วยสิ่งที่ผู้อ่านทำต่อได้",
     "<p>บทความที่ดีเริ่มจากหัวข้อที่บอกประโยชน์ชัดเจน</p><ol><li>เขียนหัวข้อให้เจาะจง</li><li>ย่อหน้าละ 2–3 บรรทัด</li>"
     "<li>ใช้หัวข้อย่อยช่วยให้อ่านเร็ว</li><li>ใส่รูปประกอบที่เกี่ยวข้อง</li><li>ปิดท้ายด้วยคำชวนให้ทำต่อ</li></ol>"),
    ("ทำให้เว็บติด Google ด้วยตัวเอง", "seo-basics", "เคล็ดลับ",
     "ตั้งชื่อเรื่องและคำอธิบายให้ทุกหน้า ใส่ alt ให้รูป แล้วส่ง sitemap.xml ให้ Google",
     "<p>BuildWeb สร้าง <code>sitemap.xml</code> และ <code>robots.txt</code> ให้เอง และให้คะแนน SEO ทุกหน้าในแท็บ “หน้าเว็บ”</p>"
     "<h2>ขั้นตอน</h2><ul><li>ตั้งชื่อเรื่องและคำอธิบายของแต่ละหน้า</li><li>ใส่คำอธิบายรูป (alt)</li>"
     "<li>ส่ง sitemap ใน Google Search Console</li></ul>"),
]


@transaction.atomic
def create_blog(site, name="บทความ"):
    col = Collection.objects.create(site=site, name=name, slug=data.unique_slug(site, "blog"), fields=BLOG_FIELDS,
                                    options={"rss": True})
    today = date.today()
    colors = [("#c4b5fd", "#67e8f9"), ("#fbcfe8", "#fde68a"), ("#a7f3d0", "#93c5fd")]
    Record.objects.bulk_create([
        Record(collection=col, position=i, data={
            "title": t, "slug": slug, "cover": sections.placeholder(cat, 1200, 675, *colors[i % 3]), "excerpt": ex,
            "content": body, "category": cat, "date": (today - timedelta(days=i * 3)).isoformat(), "author": site.name})
        for i, (t, slug, cat, ex, body) in enumerate(SAMPLE_POSTS)
    ])
    list_page, detail = create_pages_for(col, name, detail_slug="post")
    list_page.seo_description = f"บทความและข่าวสารล่าสุดจาก {site.name}"
    list_page.save(update_fields=["seo_description"])
    return col, list_page, detail


def form_html(col, title="ส่งข้อมูล", button="ส่ง"):
    """A form whose inputs match the collection's fields (for reviews, sign-ups...)."""
    e = htmllib.escape
    inputs = []
    for f in col.fields:
        if SKIP_RE.match(f["name"]) or f.get("type") in ("image", "bool"):
            continue
        if f.get("type") == "date" and f["name"].lower() in ("date", "created", "วันที่"):
            continue  # filled in with the day it was sent
        label = e(f.get("label") or f["name"])
        if f.get("type") in ("longtext", "html"):
            field = f'<textarea name="{e(f["name"])}" rows="4"></textarea>'
        else:
            typ = {"number": "number", "date": "date", "link": "url"}.get(f.get("type"), "text")
            if re.search(r"mail", f["name"], re.I):
                typ = "email"
            if re.search(r"phone|tel|โทร", f["name"], re.I):
                typ = "tel"
            field = f'<input type="{typ}" name="{e(f["name"])}">'
        inputs.append(f"<label>{label}{field}</label>")
    return (f'<section class="bw-contact"><div class="bw-container" style="max-width:640px"><h2>{e(title)}</h2>'
            f'<form class="bw-form" name="{e(col.slug)}" data-bw-collection="{e(col.slug)}" '
            f'data-bw-success="ขอบคุณ! ได้รับข้อมูลแล้ว" data-bw-pending="ขอบคุณ! ข้อมูลจะแสดงหลังผ่านการตรวจสอบ">'
            f'{"".join(inputs)}<button type="submit" class="bw-btn">{e(button)}</button></form></div></section>')


# --- member pages ---------------------------------------------------------------------------------

AUTH_CSS = """.bw-auth{padding:64px 0 80px}
.bw-auth-card{max-width:440px;margin:0 auto;background:#fff;border:1px solid #ececf1;border-radius:var(--bw-radius);padding:32px 30px;box-shadow:0 24px 60px -40px rgba(0,0,0,.35)}
.bw-auth-card h1{font-size:28px;margin:0 0 6px}.bw-auth-card>p{color:var(--bw-muted);margin:0 0 22px}
.bw-auth form{display:grid;gap:14px}
.bw-auth label{display:grid;gap:6px;font-weight:600;font-size:15px}
.bw-auth input{font:inherit;font-weight:400;padding:12px 14px;border:1px solid #d9d9e3;border-radius:10px}
.bw-auth input:focus{outline:2px solid var(--bw-primary);border-color:transparent}
.bw-auth button{cursor:pointer;font:inherit;font-weight:600;width:100%}
.bw-auth-links{display:flex;justify-content:space-between;gap:10px;margin-top:16px;font-size:.95em}
.bw-auth-wide{max-width:640px}
.bw-auth hr{border:0;border-top:1px solid #ececf1;margin:26px 0}"""


def _auth_page(title, intro, form, links="", wide=False):
    e = htmllib.escape
    return (f'<section class="bw-auth"><div class="bw-container"><div class="bw-auth-card{" bw-auth-wide" if wide else ""}">'
            f'<h1>{e(title)}</h1><p>{intro}</p>{form}{f"<div class=bw-auth-links>{links}</div>" if links else ""}</div></div></section>')


def member_pages_html(p):
    """{key: (title, html, access)} for the member pages; ``p`` maps key -> file name."""
    login = _auth_page("เข้าสู่ระบบ", "ยินดีต้อนรับกลับมา", (
        '<form data-bw-auth="login"><label>อีเมล<input type="email" name="email" autocomplete="email" required></label>'
        '<label>รหัสผ่าน<input type="password" name="password" autocomplete="current-password" required></label>'
        '<button type="submit" class="bw-btn">เข้าสู่ระบบ</button></form>'),
        f'<a href="{p["register"]}">สมัครสมาชิก</a><a href="{p["forgot"]}">ลืมรหัสผ่าน?</a>')
    register = _auth_page("สมัครสมาชิก", "สร้างบัญชีใหม่ใช้เวลาไม่ถึงนาที", (
        '<form data-bw-auth="register"><label>ชื่อ<input name="name" autocomplete="name" required></label>'
        '<label>อีเมล<input type="email" name="email" autocomplete="email" required></label>'
        '<label>รหัสผ่าน<input type="password" name="password" autocomplete="new-password" minlength="8" required></label>'
        '<button type="submit" class="bw-btn">สมัครสมาชิก</button></form>'),
        f'<span>มีบัญชีแล้ว?</span><a href="{p["login"]}">เข้าสู่ระบบ</a>')
    forgot = _auth_page("ลืมรหัสผ่าน", "ใส่อีเมลที่สมัครไว้ เราจะส่งลิงก์ตั้งรหัสผ่านใหม่ให้", (
        '<form data-bw-auth="forgot"><label>อีเมล<input type="email" name="email" autocomplete="email" required></label>'
        '<button type="submit" class="bw-btn">ส่งลิงก์</button></form>'), f'<a href="{p["login"]}">← กลับไปเข้าสู่ระบบ</a>')
    reset = _auth_page("ตั้งรหัสผ่านใหม่", "ตั้งรหัสผ่านใหม่ของคุณ", (
        '<form data-bw-auth="reset"><label>รหัสผ่านใหม่<input type="password" name="password" autocomplete="new-password" minlength="8" required></label>'
        '<label>ยืนยันรหัสผ่าน<input type="password" name="password2" autocomplete="new-password" minlength="8" required></label>'
        '<button type="submit" class="bw-btn">บันทึกรหัสผ่าน</button></form>'))
    account = _auth_page("บัญชีของฉัน", "สวัสดีคุณ{{user.name}} · {{user.email}}", (
        '<form data-bw-auth="profile"><label>ชื่อ<input name="name" value="{{user.name}}" autocomplete="name"></label>'
        '<button type="submit" class="bw-btn">บันทึกข้อมูล</button></form><hr>'
        '<form data-bw-auth="password"><label>รหัสผ่านปัจจุบัน<input type="password" name="current_password" autocomplete="current-password" required></label>'
        '<label>รหัสผ่านใหม่<input type="password" name="new_password" autocomplete="new-password" minlength="8" required></label>'
        '<button type="submit" class="bw-btn bw-btn-outline">เปลี่ยนรหัสผ่าน</button></form><hr>'
        '<button type="button" class="bw-btn bw-btn-outline" data-bw-logout>ออกจากระบบ</button>'), wide=True)
    return {"login": ("เข้าสู่ระบบ", login, ""), "register": ("สมัครสมาชิก", register, ""),
            "forgot": ("ลืมรหัสผ่าน", forgot, ""), "reset": ("ตั้งรหัสผ่านใหม่", reset, ""),
            "account": ("บัญชีของฉัน", account, "members")}


@transaction.atomic
def create_member_pages(site):
    """Create the member pages that don't exist yet; remembers their file names in Site.auth["pages"]."""
    from . import members

    s = members.settings(site)
    names = dict(s["pages"])
    made = []
    existing = {p.slug for p in site.pages.all()}
    for key in ("login", "register", "forgot", "reset", "account"):
        slug = names[key][:-5]
        if slug in existing:
            continue
        slug = services.unique_page_slug(site, slug)
        names[key] = f"{slug}.html"
    html = member_pages_html(names)
    for key, (title, body, access) in html.items():
        slug = names[key][:-5]
        if slug in existing:
            continue
        page = _page(site, title, slug, body, AUTH_CSS, show_in_nav=False, access=access, noindex=True)
        made.append(page)
    site.auth = {**(site.auth or {}), "pages": names, "enabled": True}
    site.save(update_fields=["auth"])
    site.touch()
    return made


# --- shop pages -----------------------------------------------------------------------------------

SHOP_CSS = LIST_CSS + """
.bw-price{font-weight:700;color:var(--bw-text)}.bw-price s{color:var(--bw-muted);font-weight:400;margin-left:6px;font-size:.9em}
.bw-list-card .bw-btn{margin-top:10px;width:100%;text-align:center;cursor:pointer;font:inherit;font-weight:600}
.bw-soldout{color:#dc2626;font-weight:600;font-size:.9em}
.bw-shop-page{padding:48px 0 72px}.bw-shop-page h1{margin:0 0 20px}"""

SAMPLE_PRODUCTS = [
    ("เสื้อยืดคอตตอน", "t-shirt", 390, 490, "เสื้อผ้า", 25), ("หมวกแก๊ป", "cap", 290, 0, "เครื่องประดับ", 12),
    ("กระเป๋าผ้า", "tote-bag", 250, 0, "เครื่องประดับ", 0), ("แก้วเก็บความเย็น", "tumbler", 450, 590, "ของใช้", 40),
]


def product_card_actions():
    return ('<button type="button" class="bw-btn" data-bw-add-to-cart="{{_id}}" data-name="{{name}}" data-price="{{price}}" '
            'data-image="{{image}}">ใส่ตะกร้า</button>')


@transaction.atomic
def create_shop(site):
    """Products + orders collections, sample products and the shop pages (list, product, cart, checkout, order)."""
    from . import shop

    prod, orders = shop.ensure_collections(site)
    if not prod.records.exists():
        colors = [("#c4b5fd", "#67e8f9"), ("#fbcfe8", "#fde68a"), ("#a7f3d0", "#93c5fd"), ("#fde68a", "#fca5a5")]
        Record.objects.bulk_create([Record(collection=prod, position=i, data={
            "name": n, "slug": slug, "price": p, "compare_price": cp or "", "category": cat, "stock": st, "sku": f"SKU-{i + 1:03d}",
            "active": True, "image": sections.placeholder(n, 800, 800, *colors[i % 4]),
            "description": f"<p>{n} คุณภาพดี ผลิตจากวัสดุคัดสรร ใช้งานได้นาน</p><ul><li>จัดส่งทั่วประเทศ</li><li>เปลี่ยนสินค้าได้ใน 7 วัน</li></ul>"})
            for i, (n, slug, p, cp, cat, st) in enumerate(SAMPLE_PRODUCTS)])
    e = htmllib.escape
    names = {}
    made = []
    existing = {p.slug for p in site.pages.all()}

    def page(key, title, slug, html, css, **kw):
        if slug in existing:
            names[key] = f"{slug}.html"
            return None
        p = _page(site, title, slug, html, css, **kw)
        names[key] = p.filename
        made.append(p)
        return p

    detail_slug = services.unique_page_slug(site, "product") if "product" in existing else "product"
    card = ('<section class="bw-list-sec bw-shop-page"><div class="bw-container"><h1>สินค้าทั้งหมด</h1>'
            f'<div class="bw-list-grid" data-bw-repeat="{prod.slug}" data-bw-filter="active!=false" data-bw-search="ค้นหาสินค้า…" '
            'data-bw-facet="category" data-bw-paginate="12" data-bw-empty="ยังไม่มีสินค้า">'
            '<div class="bw-list-card"><a href="{{_url}}"><img src="{{image}}" alt="{{name}}" loading="lazy" data-bw-if="image"></a>'
            '<div class="bw-list-body"><div class="bw-list-meta" data-bw-if="category">{{category}}</div>'
            '<a href="{{_url}}" style="color:inherit;text-decoration:none"><h3>{{name}}</h3></a>'
            '<div class="bw-price">฿{{price|number}} <s data-bw-if="compare_price">฿{{compare_price|number}}</s></div>'
            + product_card_actions() + '</div></div></div></div></section>')
    page("shop", "ร้านค้า", "shop", card, SHOP_CSS, show_in_nav=True)
    detail = ('<section class="bw-detail"><div class="bw-container"><a class="bw-back" href="{shop}">← กลับไปร้านค้า</a>'
              '<div class="bw-detail-grid"><img class="bw-detail-img" src="{{image}}" alt="{{name}}" data-bw-if="image">'
              '<div><div class="bw-detail-meta"><span class="bw-pill" data-bw-if="category">{{category}}</span><span data-bw-if="sku">{{sku}}</span></div>'
              '<h1>{{name}}</h1><p class="bw-price" style="font-size:1.6em">฿{{price|number}} <s data-bw-if="compare_price">฿{{compare_price|number}}</s></p>'
              '<div class="bw-detail-text">{{{description}}}</div>'
              '<div class="bw-buy"><input type="number" min="1" value="1" class="bw-qty" aria-label="จำนวน">'
              '<button type="button" class="bw-btn" data-bw-add-to-cart="{{_id}}" data-name="{{name}}" data-price="{{price}}" data-image="{{image}}" data-bw-qty-from=".bw-qty">ใส่ตะกร้า</button></div>'
              '</div></div>{pn}</div></section>')
    pn = ('<nav class="bw-pn"><a class="bw-prev" href="{{_prev_url}}" data-bw-if="_prev_url"><small>← ก่อนหน้า</small>{{_prev_title}}</a>'
          '<a class="bw-next" href="{{_next_url}}" data-bw-if="_next_url"><small>ถัดไป →</small>{{_next_title}}</a></nav>')
    shop_file = names.get("shop", "shop.html")
    if detail_slug not in existing:
        p = _page(site, "สินค้า (หน้ารายละเอียด)", detail_slug, detail.replace("{shop}", shop_file).replace("{pn}", pn),
                  DETAIL_CSS + "\n.bw-buy{display:flex;gap:10px;margin:22px 0}.bw-qty{width:84px;font:inherit;padding:10px;border:1px solid #d9d9e3;border-radius:10px}",
                  show_in_nav=False, collection=prod)
        made.append(p)
    page("cart", "ตะกร้าสินค้า", "cart", '<section class="bw-shop-page"><div class="bw-container" style="max-width:860px"><h1>ตะกร้าสินค้า</h1>'
         '<div data-bw-cart></div></div></section>', SHOP_CSS, show_in_nav=False)
    page("checkout", "ชำระเงิน", "checkout", '<section class="bw-shop-page"><div class="bw-container" style="max-width:960px"><h1>ชำระเงิน</h1>'
         '<form class="bw-checkout" data-bw-checkout><div class="bw-co-grid"><div>'
         '<label>ชื่อ-นามสกุล<input name="customer" autocomplete="name" required></label>'
         '<label>เบอร์โทร<input name="phone" type="tel" autocomplete="tel" required></label>'
         '<label>อีเมล <small>(รับใบยืนยัน)</small><input name="email" type="email" autocomplete="email"></label>'
         '<label>ที่อยู่จัดส่ง<textarea name="address" rows="3" autocomplete="street-address"></textarea></label>'
         '<label>หมายเหตุ<textarea name="note" rows="2"></textarea></label>'
         '<div class="bw-co-pay" data-bw-payments></div></div>'
         '<aside class="bw-co-sum"><h3>สรุปคำสั่งซื้อ</h3><div data-bw-cart-summary></div>'
         '<button type="submit" class="bw-btn" style="width:100%">ยืนยันคำสั่งซื้อ</button></aside></div></form></div></section>',
         SHOP_CSS, show_in_nav=False, noindex=True)
    page("order", "คำสั่งซื้อของคุณ", "order", '<section class="bw-shop-page"><div class="bw-container" style="max-width:760px">'
         '<div data-bw-order></div></div></section>', SHOP_CSS, show_in_nav=False, noindex=True)
    from . import shop as shop_mod

    shop_mod.save_settings(site, {"enabled": True})
    site.shop = {**site.shop, "pages": {**shop_mod.settings(site)["pages"], **names}}
    site.save(update_fields=["shop"])
    site.touch()
    return prod, orders, made
