"""Online shop: products (a collection), a browser cart, checkout, orders and payments.

- The cart lives in the visitor's browser; at checkout the server re-reads every price and the stock from the
  products collection, so a tampered cart can't change what is charged.
- Payments: PromptPay QR (EMVCo payload built here, the QR is drawn in the browser), bank transfer, cash on
  delivery — those two/three take a payment slip upload — and Stripe Checkout (paid status comes from Stripe's
  signed webhook).
- Orders are rows of the "orders" collection (server-side data: a deploy never overwrites them). Customers
  follow their order with its number + a secret token; signed-in members also see it under their account.
Endpoints (no need to switch the collections API on): <site>/api/v1/shop/config · checkout · orders/<no>
· orders/<no>/slip · stripe-webhook.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from . import data
from .models import Collection, Record

SETTINGS = {
    "enabled": False,
    "currency": "THB",
    "products": "products",       # collection slugs
    "orders": "orders",
    "promptpay": "",              # mobile number or national ID / tax ID
    "bank": "",                   # transfer details shown to customers
    "cod": False,                 # cash on delivery
    "stripe": False,              # needs secrets STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET
    "shipping": 0,                # flat shipping fee
    "free_over": 0,               # free shipping from this subtotal (0 = never)
    "prefix": "BW",
    "low_stock": 3,               # tell the owner when a product's stock falls to this (0 = never)
    "coupons": [],                # [{"code", "type": "percent"|"amount", "value", "min", "expires", "limit", "used", "active"}]
    "pages": {},                  # {"cart": "cart.html", "checkout": "checkout.html", "order": "order.html"}
}
STATUSES = ["pending", "paid", "shipped", "completed", "cancelled"]
STATUS_TH = {"pending": "รอชำระ/ตรวจสอบ", "paid": "ชำระแล้ว", "shipped": "จัดส่งแล้ว", "completed": "สำเร็จ", "cancelled": "ยกเลิก"}
PAYMENTS = {"promptpay": "พร้อมเพย์ (QR)", "transfer": "โอนผ่านธนาคาร", "cod": "เก็บเงินปลายทาง", "stripe": "บัตรเครดิต/เดบิต"}

PRODUCT_FIELDS = [
    {"name": "name", "label": "ชื่อสินค้า", "type": "text", "required": True},
    {"name": "slug", "label": "ชื่อลิงก์", "type": "text"},
    {"name": "price", "label": "ราคา", "type": "number", "required": True, "min": 0},
    {"name": "compare_price", "label": "ราคาก่อนลด", "type": "number", "min": 0},
    {"name": "image", "label": "รูป", "type": "image"},
    {"name": "description", "label": "รายละเอียด", "type": "html"},
    {"name": "category", "label": "หมวดหมู่", "type": "text"},
    {"name": "stock", "label": "สต็อก (ว่าง = ไม่จำกัด)", "type": "number", "min": 0},
    {"name": "sku", "label": "รหัสสินค้า", "type": "text"},
    {"name": "options", "label": "ตัวเลือก (เช่น ไซซ์: S, M, L | สี: ดำ, ขาว)", "type": "text"},
    {"name": "active", "label": "แสดงขาย", "type": "bool", "default": True},
]
ORDER_FIELDS = [
    {"name": "number", "label": "เลขที่คำสั่งซื้อ", "type": "text", "unique": True},
    {"name": "status", "label": "สถานะ", "type": "select", "options": STATUSES, "default": "pending"},
    {"name": "customer", "label": "ชื่อลูกค้า", "type": "text", "required": True},
    {"name": "phone", "label": "โทรศัพท์", "type": "text", "required": True},
    {"name": "email", "label": "อีเมล", "type": "email"},
    {"name": "address", "label": "ที่อยู่จัดส่ง", "type": "longtext"},
    {"name": "items", "label": "รายการ", "type": "json"},
    {"name": "subtotal", "label": "ยอดสินค้า", "type": "number"},
    {"name": "shipping", "label": "ค่าส่ง", "type": "number"},
    {"name": "coupon", "label": "คูปอง", "type": "text"},
    {"name": "discount", "label": "ส่วนลด", "type": "number"},
    {"name": "total", "label": "ยอดรวม", "type": "number"},
    {"name": "payment", "label": "การชำระเงิน", "type": "select", "options": list(PAYMENTS)},
    {"name": "slip", "label": "สลิป", "type": "image", "hidden": True},
    {"name": "note", "label": "หมายเหตุลูกค้า", "type": "longtext"},
    {"name": "admin_note", "label": "บันทึกร้าน", "type": "longtext", "hidden": True},
    {"name": "token", "label": "รหัสติดตาม", "type": "text", "hidden": True},
    {"name": "stripe_session", "label": "Stripe session", "type": "text", "hidden": True},
    {"name": "created", "label": "สั่งเมื่อ", "type": "datetime"},
]


class ShopError(Exception):
    def __init__(self, status, code, message, fields=None):
        super().__init__(message)
        self.status, self.code, self.fields = status, code, fields


def settings(site):
    s = {**SETTINGS, **(site.shop or {})}
    s["pages"] = {"shop": "shop.html", "cart": "cart.html", "checkout": "checkout.html", "order": "order.html",
                  **(s.get("pages") or {})}
    return s


def save_settings(site, values):
    cur = settings(site)
    for k, default in SETTINGS.items():
        if k not in values or k in ("pages", "coupons"):
            continue
        v = values[k]
        if isinstance(default, bool):
            cur[k] = v in (True, "1", "true", "on", 1)
        elif isinstance(default, (int, float)):
            try:
                cur[k] = max(0, float(str(v or 0).replace(",", "")))
            except ValueError:
                raise ShopError(400, "validation", "ค่าส่งต้องเป็นตัวเลข", {k: "ต้องเป็นตัวเลข"})
        else:
            cur[k] = str(v or "").strip()[:1000]
    if cur["promptpay"] and not promptpay_target(cur["promptpay"]):
        raise ShopError(400, "validation", "พร้อมเพย์ต้องเป็นเบอร์มือถือ 10 หลัก หรือเลขบัตร/ผู้เสียภาษี 13 หลัก", {"promptpay": "ไม่ถูกต้อง"})
    site.shop = cur
    site.save(update_fields=["shop"])
    return cur


def money(v):
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- PromptPay (EMVCo merchant-presented QR, Thai QR Payment) -------------------------------------

def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


def crc16(payload):
    crc = 0xFFFF
    for b in payload.encode("ascii"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def promptpay_target(raw):
    """("01", "0066812345678") for a mobile number, ("02", 13 digits) for a national/tax ID, else None."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 10 and d.startswith("0"):
        return "01", "0066" + d[1:]
    if len(d) == 13:
        return "02", d
    if len(d) == 15:
        return "03", d
    return None


def promptpay_payload(account, amount=None):
    target = promptpay_target(account)
    if not target:
        raise ValueError("เลขพร้อมเพย์ไม่ถูกต้อง")
    merchant = _tlv("00", "A000000677010111") + _tlv(*target)
    p = (_tlv("00", "01") + _tlv("01", "12" if amount else "11") + _tlv("29", merchant) + _tlv("53", "764")
         + (_tlv("54", f"{money(amount):.2f}") if amount else "") + _tlv("58", "TH"))
    p += "6304"
    return p + crc16(p)


# --- collections ----------------------------------------------------------------------------------

def products_col(site):
    return site.collections.filter(slug=settings(site)["products"]).first()


def orders_col(site):
    return site.collections.filter(slug=settings(site)["orders"]).first()


def ensure_collections(site):
    s = settings(site)
    prod = products_col(site)
    if not prod:
        prod = Collection.objects.create(site=site, name="สินค้า", slug=data.unique_slug(site, s["products"]), fields=PRODUCT_FIELDS,
                                         options={"api": {"list": "public", "view": "public", "create": "key", "update": "key", "delete": "key"}})
    orders = orders_col(site)
    if not orders:
        orders = Collection.objects.create(site=site, name="คำสั่งซื้อ", slug=data.unique_slug(site, s["orders"]), fields=ORDER_FIELDS,
                                           options={"server": True, "api": {"list": "owner", "view": "owner", "create": "off",
                                                                            "update": "off", "delete": "off"}})
    for col, wanted in ((prod, ("options",)), (orders, ("coupon", "discount"))):  # collections from older versions
        names = col.field_names
        base = PRODUCT_FIELDS if col == prod else ORDER_FIELDS
        missing = [f for f in base if f["name"] in wanted and f["name"] not in names]
        if missing:
            col.fields = col.fields + missing
            col.save(update_fields=["fields"])
    save_settings(site, {"products": prod.slug, "orders": orders.slug})
    return prod, orders


# --- checkout -------------------------------------------------------------------------------------

def public_config(site):
    s = settings(site)
    methods = [m for m in ("promptpay", "transfer", "cod", "stripe")
               if (m == "promptpay" and s["promptpay"]) or (m == "transfer" and s["bank"]) or (m == "cod" and s["cod"])
               or (m == "stripe" and s["stripe"])]
    return {"currency": s["currency"], "shipping": s["shipping"], "free_over": s["free_over"], "bank": s["bank"],
            "coupons": any(c.get("active", True) for c in s.get("coupons") or []),
            "payments": [{"id": m, "label": PAYMENTS[m]} for m in methods], "pages": s["pages"]}


def next_number(site, orders):
    prefix = re.sub(r"[^A-Z0-9]", "", settings(site)["prefix"].upper())[:6] or "BW"
    day = timezone.localtime().strftime("%y%m%d")
    n = orders.records.filter(data__number__startswith=f"{prefix}{day}").count() + 1
    while orders.records.filter(data__number=f"{prefix}{day}{n:03d}").exists():  # deleted orders leave gaps
        n += 1
    return f"{prefix}{day}{n:03d}"


def parse_options(text):
    """"ไซซ์: S, M, L | สี: ดำ, ขาว" → {"ไซซ์": ["S", "M", "L"], "สี": ["ดำ", "ขาว"]}"""
    out = {}
    for part in str(text or "").split("|"):
        name, _, values = part.partition(":")
        vals = [v.strip() for v in values.split(",") if v.strip()]
        if name.strip() and vals:
            out[name.strip()] = vals
    return out


def clean_options(defined, chosen):
    opts = parse_options(defined)
    chosen = chosen if isinstance(chosen, dict) else {}
    out = {}
    for name, vals in opts.items():
        v = str(chosen.get(name, "")).strip()
        if v not in vals:
            raise ShopError(400, "options", f"เลือก{name}ให้ถูกต้อง ({', '.join(vals)})")
        out[name] = v
    return out


def find_coupon(s, code):
    code = str(code or "").strip().upper()
    return next((c for c in s.get("coupons") or [] if c.get("code", "").upper() == code), None) if code else None


def apply_coupon(s, code, subtotal):
    """(coupon or None, discount Decimal). Raises ShopError for a code that can't be used."""
    if not str(code or "").strip():
        return None, Decimal("0")
    c = find_coupon(s, code)
    if not c or not c.get("active", True):
        raise ShopError(400, "coupon", "ไม่พบคูปองนี้", {"coupon": "ไม่พบคูปอง"})
    if c.get("expires") and str(c["expires"]) < timezone.localdate().isoformat():
        raise ShopError(400, "coupon", "คูปองหมดอายุแล้ว", {"coupon": "หมดอายุ"})
    if c.get("limit") and int(c.get("used") or 0) >= int(c["limit"]):
        raise ShopError(400, "coupon", "คูปองถูกใช้ครบแล้ว", {"coupon": "ใช้ครบแล้ว"})
    if c.get("min") and subtotal < Decimal(str(c["min"])):
        raise ShopError(400, "coupon", f"ใช้ได้เมื่อซื้อครบ {float(c['min']):,.0f} บาท", {"coupon": "ยอดไม่ถึง"})
    value = Decimal(str(c.get("value") or 0))
    discount = (subtotal * value / 100) if c.get("type") == "percent" else value
    return c, min(subtotal, discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def use_coupon(site, code):
    s = settings(site)
    coupons = [dict(c) for c in s.get("coupons") or []]
    for c in coupons:
        if c.get("code", "").upper() == code.upper():
            c["used"] = int(c.get("used") or 0) + 1
    site.shop = {**(site.shop or {}), "coupons": coupons}
    site.save(update_fields=["shop"])


def save_coupons(site, coupons):
    out, seen = [], set()
    for c in coupons or []:
        code = re.sub(r"[^A-Z0-9_-]", "", str(c.get("code") or "").upper())[:30]
        if not code or code in seen:
            continue
        seen.add(code)
        try:
            value = float(c.get("value") or 0)
            minimum = float(c.get("min") or 0)
            limit = int(c.get("limit") or 0)
        except ValueError:
            raise ShopError(400, "validation", f"คูปอง {code}: ตัวเลขไม่ถูกต้อง")
        ctype = "percent" if c.get("type") == "percent" else "amount"
        if value <= 0 or (ctype == "percent" and value > 100):
            raise ShopError(400, "validation", f"คูปอง {code}: มูลค่าไม่ถูกต้อง")
        out.append({"code": code, "type": ctype, "value": value, "min": minimum, "limit": limit,
                    "expires": str(c.get("expires") or "")[:10], "used": int(c.get("used") or 0),
                    "active": c.get("active", True) in (True, "1", "true", "on", 1)})
    site.shop = {**(site.shop or {}), "coupons": out}
    site.save(update_fields=["shop"])
    return out


def email_customer(site, order, base, kind):
    """Order confirmation / status update to the customer (when SMTP is set up and they gave an email)."""
    from . import notify

    to = (order.get("email") or "").strip()
    if not to or not notify.smtp_ready():
        return
    s = settings(site)
    link = (base.rstrip("/") + "/" if base else "") + f"{s['pages']['order']}?n={order['number']}&t={order.get('token', '')}"
    items = "\n".join(f"- {i['name']} x {i['qty']}  {i['price'] * i['qty']:,.2f}" for i in order.get("items") or [])
    if kind == "confirm":
        subject = f"ยืนยันคำสั่งซื้อ {order['number']} · {site.name}"
        body = (f"ขอบคุณที่สั่งซื้อกับ {site.name}\n\nเลขที่ {order['number']}\n{items}\n"
                + (f"ส่วนลด ({order.get('coupon')}) -{order.get('discount', 0):,.2f}\n" if order.get("discount") else "")
                + f"ค่าส่ง {order.get('shipping', 0):,.2f}\nยอดรวม {order['total']:,.2f} บาท\nชำระโดย {PAYMENTS.get(order['payment'], order['payment'])}\n"
                + (f"\nโอนเข้าบัญชี:\n{s['bank']}\n" if order["payment"] == "transfer" and s["bank"] else "")
                + (f"\nติดตามคำสั่งซื้อ / ชำระเงิน / แนบสลิป:\n{link}\n" if base else ""))
    else:
        subject = f"คำสั่งซื้อ {order['number']}: {STATUS_TH.get(order['status'], order['status'])} · {site.name}"
        body = (f"คำสั่งซื้อ {order['number']} ของคุณ{order.get('customer', '')} เปลี่ยนสถานะเป็น “{STATUS_TH.get(order['status'])}”\n"
                + (f"\nดูรายละเอียด: {link}\n" if base else ""))
    try:
        notify.send_mail_to(to, subject, body + f"\n— {site.name}", from_name=site.name)
    except RuntimeError:
        pass


@transaction.atomic
def checkout(site, d, user=None, base=""):
    s = settings(site)
    prod, orders = products_col(site), orders_col(site)
    if not s["enabled"] or not prod or not orders:
        raise ShopError(404, "shop_disabled", "ร้านค้ายังไม่เปิด")
    items = d.get("items") or []
    if not isinstance(items, list) or not items:
        raise ShopError(400, "empty_cart", "ตะกร้าว่าง")
    pay = d.get("payment") or ""
    if pay not in [m["id"] for m in public_config(site)["payments"]]:
        raise ShopError(400, "validation", "เลือกวิธีชำระเงิน", {"payment": "เลือกวิธีชำระเงิน"})
    errors = {}
    for f in ("customer", "phone"):
        if not str(d.get(f) or "").strip():
            errors[f] = "จำเป็นต้องกรอก"
    if pay != "stripe" and not str(d.get("address") or "").strip():
        errors["address"] = "จำเป็นต้องกรอก"
    if errors:
        raise ShopError(422, "validation", "กรอกข้อมูลให้ครบ", errors)
    lines, subtotal = [], Decimal("0")
    for it in items[:100]:
        try:
            rid, qty = int(it.get("id")), int(it.get("qty") or 1)
        except (TypeError, ValueError, AttributeError):
            raise ShopError(400, "bad_item", "สินค้าในตะกร้าไม่ถูกต้อง")
        if qty < 1 or qty > 999:
            raise ShopError(400, "bad_item", "จำนวนไม่ถูกต้อง")
        rec = prod.records.select_for_update().filter(pk=rid, approved=True).first()
        if not rec or rec.data.get("active") in (False, 0, "0", "false"):
            raise ShopError(409, "unavailable", "มีสินค้าที่ไม่มีขายแล้วในตะกร้า กรุณาลบออก")
        name = str(rec.data.get("name") or "")
        stock = rec.data.get("stock")
        if stock not in (None, "") and int(float(stock)) < qty:
            raise ShopError(409, "out_of_stock", f"“{name}” เหลือ {int(float(stock))} ชิ้น")
        chosen = clean_options(rec.data.get("options"), it.get("options"))
        price = Decimal(str(rec.data.get("price") or 0))
        subtotal += price * qty
        label = name + (" (" + ", ".join(f"{k}: {v}" for k, v in chosen.items()) + ")" if chosen else "")
        lines.append((rec, {"id": rec.id, "name": label, "price": float(price), "qty": qty, "image": rec.data.get("image", ""),
                            "sku": rec.data.get("sku", ""), "options": chosen}))
    coupon, discount = apply_coupon(s, d.get("coupon"), subtotal)
    shipping = Decimal(str(s["shipping"] or 0))
    if s["free_over"] and subtotal >= Decimal(str(s["free_over"])):
        shipping = Decimal("0")
    total = max(Decimal("0"), subtotal - discount) + shipping
    for rec, line in lines:  # take the stock now; cancelled orders give it back
        if rec.data.get("stock") not in (None, ""):
            rec.data["stock"] = int(float(rec.data["stock"])) - line["qty"]
            rec.save(update_fields=["data", "updated_at"])
    token = secrets.token_urlsafe(16)
    order = {"number": next_number(site, orders), "status": "pending", "customer": str(d.get("customer"))[:150],
             "phone": str(d.get("phone"))[:40], "email": str(d.get("email") or "")[:200], "address": str(d.get("address") or "")[:2000],
             "items": [l for _, l in lines], "subtotal": money(subtotal), "shipping": money(shipping), "total": money(total),
             "coupon": coupon.get("code", "") if coupon else "", "discount": money(discount),
             "payment": pay, "slip": "", "note": str(d.get("note") or "")[:2000], "admin_note": "", "token": token,
             "stripe_session": "", "created": timezone.localtime().isoformat(timespec="seconds")}
    pos = (orders.records.aggregate(m=Max("position"))["m"] or 0) + 1
    rec = Record.objects.create(collection=orders, data=order, position=pos, owner=user)
    data.invalidate(prod)
    if coupon:
        use_coupon(site, coupon["code"])
    low = [r for r, _ in lines if s["low_stock"] and r.data.get("stock") not in (None, "") and int(float(r.data["stock"])) <= s["low_stock"]]
    out = {"number": order["number"], "token": token, "total": order["total"], "payment": pay,
           "url": f"{s['pages']['order']}?n={order['number']}&t={token}"}
    if pay == "promptpay":
        out["promptpay"] = promptpay_payload(s["promptpay"], order["total"])
    if pay == "stripe":
        out["redirect"] = stripe_session(site, rec, base)
    from . import logic

    logic.emit(site, "record.created", {"_id": rec.id, **{k: v for k, v in order.items() if k != "token"}}, orders.slug)
    notify_order(site, order)
    if low:
        from . import notify

        notify.notify_text(site.name, "สินค้าใกล้หมด\n" + "\n".join(f"• {r.data.get('name')}: เหลือ {int(float(r.data['stock']))}" for r in low),
                           {"event": "low_stock", "site": site.slug})
    email_customer(site, order, base, "confirm")
    return out


def find_order(site, number, token):
    orders = orders_col(site)
    rec = orders.records.filter(data__number=number).first() if orders else None
    if not rec or not token or not hmac.compare_digest(str(rec.data.get("token", "")), str(token)):
        raise ShopError(404, "not_found", "ไม่พบคำสั่งซื้อ")
    return rec


def order_public(site, rec):
    o = rec.data
    s = settings(site)
    out = {k: o.get(k) for k in ("number", "status", "customer", "items", "subtotal", "shipping", "total", "payment", "created",
                                 "note", "coupon", "discount", "phone", "address")}
    out["shop"] = site.name
    out["status_label"] = STATUS_TH.get(o.get("status"), o.get("status"))
    out["payment_label"] = PAYMENTS.get(o.get("payment"), o.get("payment"))
    out["has_slip"] = bool(o.get("slip"))
    if o.get("status") == "pending" and o.get("payment") == "promptpay" and s["promptpay"]:
        out["promptpay"] = promptpay_payload(s["promptpay"], o.get("total"))
    if o.get("payment") == "transfer":
        out["bank"] = s["bank"]
    return out


def attach_slip(site, rec, upload):
    from .models import Asset

    if not upload or upload.size > 8 * 1024 * 1024:
        raise ShopError(400, "bad_file", "แนบรูปสลิป (ไม่เกิน 8 MB)")
    head = upload.read(16)
    upload.seek(0)
    ext = image_kind(head)
    if not ext:  # judged by the file's bytes, never by the name or type the visitor sent
        raise ShopError(400, "bad_file", "สลิปต้องเป็นรูป JPG, PNG, WebP หรือ HEIC")
    upload.name = f"slip-{rec.data['number']}-{int(time.time())}.{ext}"
    asset = Asset.objects.create(site=site, file=upload, name=upload.name, folder="slips", kind="image", size=upload.size)
    rec.data["slip"] = asset.url
    rec.save(update_fields=["data", "updated_at"])
    notify_order(site, rec.data, "แนบสลิปแล้ว")


def image_kind(head):
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1"):
        return "heic"
    return None


def set_status(site, rec, status, note=None):
    """Owner changes an order's status; cancelling puts the stock back."""
    if status not in STATUSES:
        raise ShopError(400, "validation", "สถานะไม่ถูกต้อง")
    old = rec.data.get("status")
    if status == "cancelled" and old != "cancelled":
        prod = products_col(site)
        for line in rec.data.get("items") or []:
            p = prod.records.filter(pk=line.get("id")).first() if prod else None
            if p and p.data.get("stock") not in (None, ""):
                p.data["stock"] = int(float(p.data["stock"])) + int(line.get("qty") or 0)
                p.save(update_fields=["data", "updated_at"])
    rec.data["status"] = status
    if note is not None:
        rec.data["admin_note"] = str(note)[:2000]
    rec.save(update_fields=["data", "updated_at"])
    if status != old and status in ("paid", "shipped", "completed", "cancelled"):
        email_customer(site, rec.data, site.base_url, "status")
    from . import logic

    logic.emit(site, "record.updated", {"_id": rec.id, "number": rec.data.get("number"), "status": status}, rec.collection.slug)


def notify_order(site, order, extra=""):
    from . import notify

    lines = "\n".join(f"• {i['name']} × {i['qty']}" for i in order.get("items") or [])
    text = (f"คำสั่งซื้อ {order['number']}{' · ' + extra if extra else ''}\n{order['customer']} {order['phone']}\n{lines}\n"
            f"ยอดรวม {order['total']:,.2f} บาท · {PAYMENTS.get(order['payment'], order['payment'])}")
    notify.notify_text(site.name, text, {"event": "order", "site": site.slug, "order": {k: v for k, v in order.items() if k != "token"}})


# --- Stripe ---------------------------------------------------------------------------------------

STRIPE_API = "https://api.stripe.com/v1"


def stripe_session(site, rec, base):
    from urllib.parse import urlencode

    from . import logic

    key = logic.site_secrets(site).get("STRIPE_SECRET_KEY", "")
    if not key:
        raise ShopError(400, "stripe", "ยังไม่ได้ตั้งค่า STRIPE_SECRET_KEY ในค่าลับ")
    o, s = rec.data, settings(site)
    root = base.rstrip("/") + "/"
    params = [("mode", "payment"), ("client_reference_id", o["number"]),
              ("success_url", f"{root}{s['pages']['order']}?n={o['number']}&t={o['token']}&paid=1"),
              ("cancel_url", f"{root}{s['pages']['checkout']}"), ("metadata[order]", o["number"]), ("metadata[site]", site.slug)]
    for i, line in enumerate(o["items"]):
        params += [(f"line_items[{i}][quantity]", str(line["qty"])),
                   (f"line_items[{i}][price_data][currency]", s["currency"].lower()),
                   (f"line_items[{i}][price_data][unit_amount]", str(int(round(line["price"] * 100)))),
                   (f"line_items[{i}][price_data][product_data][name]", line["name"][:200])]
    if o["shipping"]:
        n = len(o["items"])
        params += [(f"line_items[{n}][quantity]", "1"), (f"line_items[{n}][price_data][currency]", s["currency"].lower()),
                   (f"line_items[{n}][price_data][unit_amount]", str(int(round(o["shipping"] * 100)))),
                   (f"line_items[{n}][price_data][product_data][name]", "ค่าจัดส่ง")]
    status, text = logic.http_request("POST", f"{STRIPE_API}/checkout/sessions",
                                      {"Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded"},
                                      urlencode(params))
    try:
        body = json.loads(text)
    except ValueError:
        body = {}
    if status >= 300 or not body.get("url"):
        raise ShopError(502, "stripe", "Stripe: " + ((body.get("error") or {}).get("message") or f"HTTP {status}"))
    rec.data["stripe_session"] = body.get("id", "")
    rec.save(update_fields=["data", "updated_at"])
    return body["url"]


def verify_stripe(site, payload, header, tolerance=300):
    from . import logic

    secret = logic.site_secrets(site).get("STRIPE_WEBHOOK_SECRET", "")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    ts, sigs = parts.get("t", ""), [v for k, v in (p.split("=", 1) for p in (header or "").split(",") if "=" in p) if k == "v1"]
    if not secret or not ts.isdigit() or abs(time.time() - int(ts)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def stripe_webhook(site, payload, header):
    if not verify_stripe(site, payload, header):
        raise ShopError(400, "bad_signature", "ลายเซ็น Stripe ไม่ถูกต้อง")
    event = json.loads(payload)
    if event.get("type") == "checkout.session.completed":
        obj = event["data"]["object"]
        number = (obj.get("metadata") or {}).get("order") or obj.get("client_reference_id")
        orders = orders_col(site)
        rec = orders.records.filter(data__number=number).first() if orders else None
        if rec and obj.get("payment_status") == "paid" and rec.data.get("status") == "pending":
            set_status(site, rec, "paid")
            notify_order(site, rec.data, "ชำระด้วยบัตรแล้ว")
    return {"received": True}


# --- dashboard ------------------------------------------------------------------------------------

def summary(site):
    orders = orders_col(site)
    if not orders:
        return {"today": 0, "today_count": 0, "pending": 0, "month": 0}
    now = timezone.localtime()
    today, month, pending, count = Decimal("0"), Decimal("0"), 0, 0
    for o in orders.records.values_list("data", flat=True):
        st = o.get("status")
        created = str(o.get("created") or "")
        if st == "pending":
            pending += 1
        if st in ("paid", "shipped", "completed"):
            if created[:7] == now.strftime("%Y-%m"):
                month += Decimal(str(o.get("total") or 0))
            if created[:10] == now.strftime("%Y-%m-%d"):
                today += Decimal(str(o.get("total") or 0))
                count += 1
    return {"today": money(today), "today_count": count, "pending": pending, "month": money(month)}
