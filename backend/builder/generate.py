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
