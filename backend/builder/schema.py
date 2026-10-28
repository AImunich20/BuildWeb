"""Collection schema: field definitions, validation and type coercion — shared by the admin table, forms and
the REST API, so data is checked the same way wherever it comes from.

A field is a dict:
  name, label, type, source          (source = the MySQL column for imported/live collections)
  required, unique, hidden           (hidden = never returned by the public API)
  default                            (used when a new row leaves the field out)
  min, max                           (number range, or text length for text types)
  pattern                            (regular expression the whole text must match)
  options                            (choices of a "select" field)
  relation, multiple                 (target collection slug of a "relation" field; several ids or one)
"""
import json
import re
from datetime import date, datetime

TYPES = {
    "text": "ข้อความ", "longtext": "ข้อความยาว", "html": "HTML", "number": "ตัวเลข", "bool": "ใช่/ไม่",
    "date": "วันที่", "datetime": "วันเวลา", "email": "อีเมล", "link": "ลิงก์", "image": "รูป", "select": "ตัวเลือก",
    "relation": "เชื่อมชุดข้อมูล", "json": "JSON",
}
TEXT_TYPES = {"text", "longtext", "html", "email", "link", "image", "select"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OPTION_KEYS = ("required", "unique", "hidden", "default", "min", "max", "pattern", "options", "relation", "multiple")


class ValidationError(Exception):
    def __init__(self, fields):
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = fields


def clean_field(f, name):
    """A field definition from the UI/API → a stored one (unknown keys dropped, types checked)."""
    out = {"name": name, "label": str(f.get("label") or name)[:100],
           "type": f.get("type") if f.get("type") in TYPES else "text", "source": f.get("source", name)}
    for k in ("required", "unique", "hidden", "multiple"):
        if f.get(k) in (True, "1", "true", "on", 1):
            out[k] = True
    for k in ("min", "max"):
        if f.get(k) not in (None, ""):
            try:
                out[k] = float(f[k]) if "." in str(f[k]) else int(f[k])
            except (TypeError, ValueError):
                pass
    if f.get("pattern"):
        try:
            re.compile(f["pattern"])
            out["pattern"] = str(f["pattern"])[:300]
        except re.error:
            raise ValidationError({name: "รูปแบบ (regex) ไม่ถูกต้อง"})
    if f.get("default") not in (None, ""):
        out["default"] = f["default"]
    if out["type"] == "select":
        opts = f.get("options") or []
        if isinstance(opts, str):
            opts = [o.strip() for o in re.split(r"[,\n]", opts)]
        out["options"] = [str(o)[:100] for o in opts if str(o).strip()][:200]
    if out["type"] == "relation":
        out["relation"] = str(f.get("relation") or "")[:60]
    return out


def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def coerce(f, v):
    """Convert a submitted value to the field's type. Raises ValueError with a Thai message."""
    t = f.get("type", "text")
    if _empty(v):
        return [] if t == "relation" and f.get("multiple") else ("" if t != "bool" else False)
    if t == "number":
        if isinstance(v, bool):
            raise ValueError("ต้องเป็นตัวเลข")
        try:
            n = float(str(v).replace(",", "").strip())
        except ValueError:
            raise ValueError("ต้องเป็นตัวเลข")
        return int(n) if n.is_integer() else n
    if t == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("1", "true", "on", "yes", "ใช่"):
            return True
        if s in ("0", "false", "off", "no", "ไม่"):
            return False
        raise ValueError("ต้องเป็น true หรือ false")
    if t == "date":
        s = str(v).strip()[:10]
        try:
            return date.fromisoformat(s).isoformat()
        except ValueError:
            raise ValueError("วันที่ต้องเป็นแบบ YYYY-MM-DD")
    if t == "datetime":
        s = str(v).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s).isoformat(timespec="seconds")
        except ValueError:
            raise ValueError("วันเวลาต้องเป็นแบบ ISO 8601 เช่น 2026-10-29T14:30:00")
    if t == "email":
        s = str(v).strip()
        if not EMAIL_RE.match(s):
            raise ValueError("อีเมลไม่ถูกต้อง")
        return s.lower()
    if t == "select":
        s = str(v).strip()
        if f.get("options") and s not in f["options"]:
            raise ValueError("ต้องเป็นหนึ่งใน: " + ", ".join(f["options"][:10]))
        return s
    if t == "relation":
        items = v if isinstance(v, list) else re.split(r"[,\s]+", str(v).strip())
        ids = []
        for x in items:
            if str(x).strip() == "":
                continue
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                raise ValueError("ต้องเป็นรหัส (_id) ของแถวที่เชื่อม")
        return ids if f.get("multiple") else (ids[0] if ids else "")
    if t == "json":
        if isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            raise ValueError("JSON ไม่ถูกต้อง")
    if isinstance(v, (dict, list)):
        raise ValueError("ต้องเป็นข้อความ")
    return str(v)


def validate(col, data, partial=False, current=None, exclude_id=None, unique_values=None):
    out, errors = _validate(col, data, partial, current, exclude_id, unique_values)
    if errors:
        raise ValidationError(errors)
    return out


def _validate(col, data, partial=False, current=None, exclude_id=None, unique_values=None):
    """Check and convert ``data`` for ``col``. Returns the clean dict (only known fields).

    partial: PATCH — only the given fields are checked (required ones may be absent).
    current: the stored row being updated (for required checks on PATCH).
    unique_values: callable(field_name, exclude_id) -> iterable of existing values (for "unique").
    """
    errors, out = {}, {}
    for f in col.fields:
        name = f["name"]
        present = name in data
        if not present and partial:
            continue
        if not present and current is None and "default" in f:
            raw = f["default"]
        else:
            raw = data.get(name)
        try:
            value = coerce(f, raw)
        except ValueError as e:
            errors[name] = str(e)
            continue
        effective = value if present or not partial else (current or {}).get(name)
        if f.get("required") and _empty(effective) and f.get("type") != "bool":
            errors[name] = "จำเป็นต้องกรอก"
            continue
        if not _empty(value):
            lo, hi = f.get("min"), f.get("max")
            if f.get("type") == "number":
                if lo is not None and value < lo:
                    errors[name] = f"ต้องไม่น้อยกว่า {lo}"
                elif hi is not None and value > hi:
                    errors[name] = f"ต้องไม่เกิน {hi}"
            elif f.get("type") in TEXT_TYPES:
                if lo is not None and len(value) < lo:
                    errors[name] = f"ต้องยาวอย่างน้อย {lo} ตัวอักษร"
                elif hi is not None and len(value) > hi:
                    errors[name] = f"ยาวได้ไม่เกิน {hi} ตัวอักษร"
            if name not in errors and f.get("pattern") and isinstance(value, str) and not re.fullmatch(f["pattern"], value):
                errors[name] = "รูปแบบไม่ถูกต้อง"
            if name not in errors and f.get("unique") and unique_values is not None:
                norm = str(value).strip().lower()
                if any(str(x).strip().lower() == norm for x in unique_values(name, exclude_id)):
                    errors[name] = "ค่านี้มีอยู่แล้ว (ต้องไม่ซ้ำ)"
        out[name] = value
    return out, errors


def record_unique_values(col):
    """unique_values() for a copy-mode collection."""
    def values(name, exclude_id):
        qs = col.records.all()
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        return [d.get(name) for d in qs.values_list("data", flat=True) if not _empty(d.get(name))]
    return values


def relation_errors(col, clean):
    """Relation ids must exist in the target collection (copy mode targets only)."""
    errors = {}
    for f in col.fields:
        if f.get("type") != "relation" or f["name"] not in clean or _empty(clean[f["name"]]):
            continue
        target = col.site.collections.filter(slug=f.get("relation")).first()
        if not target:
            errors[f["name"]] = f"ไม่พบชุดข้อมูล “{f.get('relation')}” ที่เชื่อมไว้"
            continue
        if target.mode != target.COPY:
            continue
        ids = clean[f["name"]] if isinstance(clean[f["name"]], list) else [clean[f["name"]]]
        found = set(target.records.filter(pk__in=ids).values_list("pk", flat=True))
        missing = [i for i in ids if i not in found]
        if missing:
            errors[f["name"]] = f"ไม่พบแถว _id {', '.join(map(str, missing))} ใน “{target.name}”"
    return errors


def full_validate(col, data, partial=False, current=None, exclude_id=None):
    """Validate everything and report every problem at once (types, rules, uniqueness, relations)."""
    clean, errors = _validate(col, data, partial, current, exclude_id,
                              record_unique_values(col) if col.mode == col.COPY else None)
    errors.update(relation_errors(col, clean))
    if errors:
        raise ValidationError(errors)
    return clean
