"""Special pages: who may open a page, as a list of conditions (Page.access == "rules", Page.access_rules).

    {"match": "all" | "any",
     "conditions": [
        {"type": "role", "values": ["vip", "gold"]},
        {"type": "verified"},                                         email confirmed
        {"type": "field", "field": "plan", "op": "eq", "value": "pro"}   a profile field of the member
        {"type": "email_domain", "values": ["company.co.th"]},
        {"type": "member_days", "value": 30},                         a member for at least N days
        {"type": "purchased", "product": 12, "since_days": 365},      bought (paid) — any product when empty
        {"type": "in_collection", "collection": "vip-list", "field": "email"},   their email is in a list
        {"type": "date_between", "from": "2026-11-01T00:00", "to": "2026-11-30T23:59"},   page open only then
     ],
     "deny": {"message": "...", "redirect": "pricing"}}             what a member who doesn't qualify sees

Members with the role "admin" may open every page. Visitors who are not signed in go to the login page when
a condition needs a member; a page limited only by dates shows the message instead.
"""
import re
from datetime import date, datetime, timedelta

from django.utils import timezone

TYPES = {
    "role": "บทบาท", "verified": "ยืนยันอีเมลแล้ว", "field": "ข้อมูลในโปรไฟล์", "email_domain": "อีเมลโดเมน",
    "member_days": "เป็นสมาชิกมาแล้ว (วัน)", "purchased": "เคยซื้อสินค้า", "in_collection": "มีชื่อในรายชื่อ (ชุดข้อมูล)",
    "date_between": "ช่วงวันเวลา",
}
OPS = {"eq": "เท่ากับ", "neq": "ไม่เท่ากับ", "contains": "มีคำว่า", "in": "เป็นหนึ่งใน (คั่นด้วย ,)", "gte": "มากกว่าหรือเท่ากับ",
       "lte": "น้อยกว่าหรือเท่ากับ", "exists": "มีค่า", "empty": "ว่าง", "future": "เป็นวันที่ยังไม่ถึง (ยังไม่หมดอายุ)",
       "past": "เป็นวันที่ผ่านมาแล้ว"}
NAME_RE = re.compile(r"^[\w-]{1,60}$")
PAID = ("paid", "shipped", "completed")
NO_USER = {"date_between"}


class RuleError(ValueError):
    pass


def _list(v):
    if isinstance(v, str):
        v = re.split(r"[,\n]", v)
    return [str(x).strip() for x in (v or []) if str(x).strip()][:50]


def _when(text):
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise RuleError(f"วันเวลาไม่ถูกต้อง: {text}")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def clean(rules, site):
    """Validate rules from the app; returns the stored form."""
    if not isinstance(rules, dict):
        raise RuleError("รูปแบบเงื่อนไขไม่ถูกต้อง")
    out = []
    for c in (rules.get("conditions") or [])[:20]:
        t = (c or {}).get("type")
        if t not in TYPES:
            raise RuleError("ไม่รู้จักเงื่อนไขนี้")
        x = {"type": t}
        if t in ("role", "email_domain"):
            x["values"] = [v.lower().lstrip("@") for v in _list(c.get("values"))] if t == "email_domain" else _list(c.get("values"))
            if not x["values"]:
                raise RuleError(f"ใส่ค่าของเงื่อนไข “{TYPES[t]}”")
        elif t == "field":
            x["field"] = str(c.get("field") or "").strip()
            x["op"] = c.get("op") if c.get("op") in OPS else "eq"
            x["value"] = str(c.get("value") or "").strip()[:200]
            if not NAME_RE.match(x["field"]):
                raise RuleError("ชื่อฟิลด์ในโปรไฟล์ใช้ a-z 0-9 _ - เช่น plan, expires")
        elif t == "member_days":
            x["value"] = max(0, int(float(c.get("value") or 0)))
        elif t == "purchased":
            x["product"] = int(c["product"]) if str(c.get("product") or "").strip().isdigit() else None
            x["since_days"] = max(0, int(float(c.get("since_days") or 0)))
        elif t == "in_collection":
            x["collection"] = str(c.get("collection") or "").strip()
            x["field"] = str(c.get("field") or "email").strip()
            if not site.collections.filter(slug=x["collection"]).exists():
                raise RuleError("เลือกชุดข้อมูลของรายชื่อ")
            if not NAME_RE.match(x["field"]):
                raise RuleError("ชื่อฟิลด์อีเมลไม่ถูกต้อง")
        elif t == "date_between":
            a, b = _when(c.get("from")), _when(c.get("to"))
            if not a and not b:
                raise RuleError("ใส่วันเริ่มหรือวันสิ้นสุดอย่างน้อยหนึ่งช่อง")
            if a and b and a >= b:
                raise RuleError("วันสิ้นสุดต้องอยู่หลังวันเริ่ม")
            x["from"], x["to"] = (str(c.get("from") or "").strip(), str(c.get("to") or "").strip())
        out.append(x)
    if not out:
        raise RuleError("เพิ่มเงื่อนไขอย่างน้อยหนึ่งข้อ")
    deny = rules.get("deny") or {}
    redirect = str(deny.get("redirect") or "").strip()
    if redirect and not site.pages.filter(slug=redirect).exists():
        raise RuleError("หน้าที่จะพาไปไม่มีอยู่")
    return {"match": "any" if rules.get("match") == "any" else "all", "conditions": out,
            "deny": {"message": str(deny.get("message") or "").strip()[:500], "redirect": redirect}}


# --- checking -------------------------------------------------------------------------------------

def _num_or_date(v):
    s = str(v if v is not None else "").strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _field(c, user):
    v = (user.profile or {}).get(c["field"])
    if c["field"] in ("name", "email", "role"):
        v = getattr(user, c["field"])
    s, want, op = ("" if v is None else str(v)).strip(), c.get("value", ""), c["op"]
    if op == "exists":
        return bool(s)
    if op == "empty":
        return not s
    if op == "eq":
        return s.lower() == want.lower()
    if op == "neq":
        return s.lower() != want.lower()
    if op == "contains":
        return want.lower() in s.lower()
    if op == "in":
        return s.lower() in [w.lower() for w in _list(want)]
    if op in ("future", "past"):
        try:
            d = date.fromisoformat(s[:10])
        except ValueError:
            return False
        today = timezone.localdate()
        return d >= today if op == "future" else d < today
    a, b = _num_or_date(s), _num_or_date(want)
    if a is None or b is None:
        return False
    return a >= b if op == "gte" else a <= b


def _purchased(c, user, site):
    from . import shop

    orders = shop.orders_col(site)
    if not orders:
        return False
    from django.db.models import Q

    qs = orders.records.filter(Q(owner=user) | Q(data__email__iexact=user.email))
    if c.get("since_days"):
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=c["since_days"]))
    for data in qs.values_list("data", flat=True)[:500]:
        if (data or {}).get("status") not in PAID:
            continue
        if not c.get("product") or any(int((i or {}).get("id") or 0) == c["product"] for i in data.get("items") or []):
            return True
    return False


def check_one(c, user, site):
    t = c["type"]
    if t == "date_between":
        now = timezone.now()
        a, b = _when(c.get("from")), _when(c.get("to"))
        return (not a or now >= a) and (not b or now <= b)
    if user is None:
        return False
    if t == "role":
        return user.role in c["values"]
    if t == "verified":
        return bool(user.email_verified)
    if t == "field":
        return _field(c, user)
    if t == "email_domain":
        return user.email.lower().rpartition("@")[2] in c["values"]
    if t == "member_days":
        return (timezone.now() - user.created_at).days >= c["value"]
    if t == "purchased":
        return _purchased(c, user, site)
    if t == "in_collection":
        col = site.collections.filter(slug=c["collection"]).first()
        return bool(col) and col.records.filter(approved=True, **{f"data__{c['field']}__iexact": user.email}).exists()
    return False


def evaluate(page, user):
    """(allowed, [(condition, passed)]) for a page with rules."""
    rules = page.access_rules or {}
    conds = rules.get("conditions") or []
    if user is not None and user.role == "admin":
        return True, [(c, True) for c in conds]
    results = [(c, check_one(c, user, page.site)) for c in conds]
    if not results:
        return False, results
    ok = any(r for _, r in results) if rules.get("match") == "any" else all(r for _, r in results)
    return ok, results


def needs_login(page):
    return any(c.get("type") not in NO_USER for c in (page.access_rules or {}).get("conditions") or [])


def describe(c):
    """One condition in Thai, for the app and the member test."""
    t = c["type"]
    if t == "role":
        return "บทบาท " + " หรือ ".join(c["values"])
    if t == "verified":
        return "ยืนยันอีเมลแล้ว"
    if t == "field":
        return f"โปรไฟล์ “{c['field']}” {OPS.get(c['op'], c['op'])}" + (f" {c['value']}" if c["op"] not in ("exists", "empty", "future", "past") else "")
    if t == "email_domain":
        return "อีเมล @" + " หรือ @".join(c["values"])
    if t == "member_days":
        return f"เป็นสมาชิกมาแล้ว {c['value']} วันขึ้นไป"
    if t == "purchased":
        return ("เคยซื้อสินค้า #" + str(c["product"]) if c.get("product") else "เคยซื้อสินค้า") + (
            f" ใน {c['since_days']} วันที่ผ่านมา" if c.get("since_days") else "")
    if t == "in_collection":
        return f"อีเมลอยู่ในชุดข้อมูล “{c['collection']}” (ฟิลด์ {c['field']})"
    if t == "date_between":
        return "ช่วง " + (c.get("from") or "…").replace("T", " ") + " ถึง " + (c.get("to") or "…").replace("T", " ")
    return t
