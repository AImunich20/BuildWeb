"""Form posts that become rows of a collection (reviews, sign-ups, guest books...).

A form with data-bw-collection="reviews" sends `_collection`; the collection must have "รับข้อมูลจากฟอร์ม"
turned on (Collection.options["forms"]), so a visitor can never write into any other collection.
Rows wait for approval (Record.approved=False) unless "auto_approve" is on. Live MySQL collections get an
INSERT into their table; they are held back only when the table has an `approved` column.
"""
import html as htmllib
import re
import threading
import time
from datetime import date

from django.db.models import Max

from . import data, schema
from .models import Collection, Record

RATE_WINDOW = 60  # seconds
RATE_MAX = 12     # posts per IP and site in that window
_hits = {}
_lock = threading.Lock()


class FormError(Exception):
    pass


def allow(site, ip):
    """Simple per-IP rate limit so a public form can't be flooded."""
    now = time.time()
    key = (site.id, ip)
    with _lock:
        recent = [t for t in _hits.get(key, []) if now - t < RATE_WINDOW]
        if len(recent) >= RATE_MAX:
            _hits[key] = recent
            return False
        recent.append(now)
        _hits[key] = recent
        if len(_hits) > 5000:  # forget idle visitors
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                _hits.pop(k, None)
    return True


def clean_value(field, value):
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    value = str(value or "").strip()
    typ = field.get("type", "text")
    if typ in ("image", "link") and value and not re.match(r"^https?://", value, re.I):
        return ""  # no javascript: or data: URLs from visitors
    if typ == "html":
        return htmllib.escape(value).replace("\n", "<br>")  # visitors never get to write raw HTML
    if typ == "number":
        try:
            f = float(value.replace(",", ""))
            return int(f) if f.is_integer() else f
        except ValueError:
            return ""
    if typ == "bool":
        return value.lower() in ("1", "true", "on", "yes", "ใช่")
    return value[:5000]


def save_to_collection(site, slug, posted, owner=None):
    col = site.collections.filter(slug=slug).first()
    if not col or not col.opt("forms"):
        raise FormError("ฟอร์มนี้ยังไม่ได้เปิดให้บันทึกลงชุดข้อมูล")
    by_label = {str(f.get("label", "")).strip().lower(): f for f in col.fields}
    values = {}
    for key, v in posted.items():
        f = next((x for x in col.fields if x["name"] == key), None) or by_label.get(key.strip().lower())
        if f and f["name"] not in ("_id", "approved"):
            values[f["name"]] = clean_value(f, v)
    if not any(str(v).strip() for v in values.values()):
        raise FormError("กรุณากรอกข้อมูล")
    for f in col.fields:  # a date field left out = the day it was sent
        if f.get("type") == "date" and not values.get(f["name"]):
            values[f["name"]] = date.today().isoformat()
    try:
        values = schema.full_validate(col, values)
    except schema.ValidationError as e:
        labels = {f["name"]: f.get("label") or f["name"] for f in col.fields}
        raise FormError(" · ".join(f"{labels.get(k, k)}: {v}" for k, v in e.fields.items()))
    approved = col.opt("auto_approve")
    if col.mode == Collection.LIVE:
        insert_live(col, values, approved)
        pending = not approved and "approved" in col.field_names
    else:
        pos = (col.records.aggregate(m=Max("position"))["m"] or 0) + 1
        Record.objects.create(collection=col, data={f["name"]: values.get(f["name"], "") for f in col.fields},
                              position=pos, approved=approved, owner=owner)
        col.save(update_fields=["updated_at"])
        pending = not approved
    return {"label": col.name, "pending": pending}


def insert_live(col, values, approved):
    if not col.connection:
        raise FormError("ชุดข้อมูลนี้ไม่มีการเชื่อมต่อ MySQL")
    try:
        data.live_insert(col, values, approved)
    except RuntimeError as e:
        raise FormError(f"บันทึกลง MySQL ไม่สำเร็จ: {e}") from e
    data.invalidate(col)
