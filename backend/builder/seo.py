"""SEO check of every page: a score out of 100 plus a list of things to fix, in plain Thai."""
import re

from . import render
from .data import strip_tags

IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
ALT_RE = re.compile(r"""\balt\s*=\s*("([^"]*)"|'([^']*)')""", re.I)
H1_RE = re.compile(r"<h1\b", re.I)
HREF_RE = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"'#?]+)""", re.I)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def check(ok, weight, title, tip, level="warn"):
    return {"ok": bool(ok), "weight": weight, "title": title, "tip": "" if ok else tip, "level": "ok" if ok else level}


def analyze_page(page, pages, files):
    site = page.site
    row = None
    if page.collection_id:
        items = render.detail_items(page, include_drafts=True)
        row = items[0] if items else None
    title, desc, image = render.page_meta(page, row, include_drafts=True)
    body = render.full_body(page, pages, row=row, include_drafts=True)
    text = strip_tags(SCRIPT_STYLE_RE.sub(" ", body))
    imgs = IMG_RE.findall(body)
    no_alt = [i for i in imgs if not (ALT_RE.search(i) and (ALT_RE.search(i).group(2) or ALT_RE.search(i).group(3) or "").strip())]
    h1 = len(H1_RE.findall(body))
    broken = sorted({h for h in HREF_RE.findall(body)
                     if h.endswith(".html") and not re.match(r"^[a-z]+:|^/|^\.\./", h, re.I) and "{{" not in h
                     and h not in files and not re.match(r"^[^/]+/[^/]+\.html$", h)})
    checks = [
        check(10 <= len(title) <= 65, 15, f"ชื่อเรื่อง {len(title)} ตัวอักษร",
              "ชื่อเรื่องควรยาว 10–65 ตัวอักษร — ตั้งได้ที่ “ตั้งค่าหน้า › ชื่อเรื่องบน Google”"),
        check(50 <= len(desc) <= 160, 15, "คำอธิบายหน้า" + (f" {len(desc)} ตัวอักษร" if desc else " — ยังไม่มี"),
              "เขียนคำอธิบาย 50–160 ตัวอักษร ที่บอกว่าหน้านี้มีอะไร (แสดงใต้ชื่อบน Google)", "err" if not desc else "warn"),
        check(h1 == 1, 12, f"หัวข้อใหญ่ (H1) {h1} อัน",
              "ทุกหน้าควรมีหัวข้อ H1 หนึ่งอันพอดี" if h1 == 0 else "มี H1 หลายอัน — เปลี่ยนอันรองเป็น H2", "err" if h1 == 0 else "warn"),
        check(not no_alt, 12, f"รูปที่ไม่มีคำอธิบาย (alt) {len(no_alt)}/{len(imgs)} รูป",
              "ใส่คำอธิบายรูป (alt) ช่วยให้ติด Google Images และคนตาบอดใช้งานได้ — เลือกรูปในตัวออกแบบ › ตั้งค่า › alt"),
        check(len(text) >= 250, 12, f"เนื้อหา {len(text):,} ตัวอักษร",
              "เนื้อหาน้อยไป — Google ชอบหน้าที่มีข้อความอธิบายอย่างน้อยสองสามย่อหน้า"),
        check(bool(image), 8, "รูปตอนแชร์ (og:image)", "ตั้งรูปตอนแชร์ เพื่อให้ลิงก์ใน Facebook/LINE มีรูปสวย", "info"),
        check(not broken, 10, "ลิงก์เสีย" + (f" {len(broken)} ลิงก์" if broken else " — ไม่มี"),
              "ลิงก์ไปหน้าที่ไม่มีอยู่: " + ", ".join(broken[:5]), "err"),
        check(re.fullmatch(r"[a-z0-9-]{1,60}", page.slug or "") is not None, 6, f"ลิงก์ของหน้า /{page.filename}",
              "ชื่อลิงก์ควรสั้น อ่านออก และเป็นภาษาอังกฤษตัวเล็ก เช่น about-us", "info"),
        check(not page.noindex, 10, "อนุญาตให้ Google เก็บหน้า", "หน้านี้ตั้ง noindex ไว้ Google จะไม่แสดงหน้านี้", "info"),
    ]
    total = sum(c["weight"] for c in checks)
    score = round(sum(c["weight"] for c in checks if c["ok"]) / total * 100)
    return {"page": page.id, "title": page.title, "score": score, "checks": checks,
            "preview": {"title": title, "description": desc, "image": image, "path": render.page_path(page, row)}}


def analyze_site(site):
    pages = render.visible_pages(site, include_drafts=True)
    files, _ = render.build_files(site, "export", include_drafts=True)
    results = [analyze_page(p, pages, files) for p in pages]
    site_checks = [
        check(bool(site.base_url), 30, "ที่อยู่เว็บจริง" + (f" {site.base_url}" if site.base_url else " — ยังไม่ได้ตั้ง"),
              "ใส่ที่อยู่เว็บจริงที่ “ตั้งค่าเว็บ” (หรือเผยแพร่ด้วยปุ่มเดียว ระบบตั้งให้เอง) เพื่อสร้าง sitemap.xml และลิงก์แชร์ที่ถูกต้อง"),
        check(bool(site.description), 20, "คำอธิบายเว็บ", "ใส่คำอธิบายเว็บที่ “ตั้งค่าเว็บ” ใช้แทนเมื่อหน้าไม่มีคำอธิบาย"),
        check(bool(site.favicon), 15, "ไอคอนเว็บ (favicon)", "ใส่ไอคอนเว็บที่ “ตั้งค่าเว็บ” — แสดงบนแท็บเบราว์เซอร์และผลค้นหา", "info"),
        check(True, 20, "robots.txt สร้างอัตโนมัติ", ""),
        check(bool(site.base_url), 15, "sitemap.xml" + (" สร้างอัตโนมัติ" if site.base_url else " — รอที่อยู่เว็บจริง"),
              "sitemap.xml จะสร้างเองเมื่อมีที่อยู่เว็บจริง", "info"),
    ]
    page_avg = round(sum(r["score"] for r in results) / len(results)) if results else 0
    site_score = round(sum(c["weight"] for c in site_checks if c["ok"]) / sum(c["weight"] for c in site_checks) * 100)
    return {"score": round(page_avg * 0.8 + site_score * 0.2), "site": site_checks, "pages": results}
