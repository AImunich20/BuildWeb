"""Back-end logic of a site: secrets, webhooks, external API connectors, server functions and scheduled jobs.

- Secrets (Site.secrets) are only ever substituted server-side, as {{secret.NAME}} in webhook/connector
  headers, URLs and bodies, or through bw.secret("NAME") in functions. They never reach page HTML.
- Events (record.created/updated/deleted, form.submitted, member.registered) are POSTed as JSON to matching
  webhooks from a background thread, signed with HMAC-SHA256 (X-BuildWeb-Signature: sha256=…) and retried
  three times.
- Every delivery, job, connector run and function call is written to RunLog (last 1000 per site).
"""
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import Collection, Connector, Function, Job, Record, RunLog, Webhook

log = logging.getLogger("buildweb")
EVENTS = ["record.created", "record.updated", "record.deleted", "form.submitted", "member.registered"]
SECRET_RE = re.compile(r"\{\{\s*secret\.([A-Za-z0-9_]+)\s*\}\}")
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
RUNNER = Path(__file__).with_name("fn_runner.py")
RETRIES = (2, 10, 30)  # seconds before the 2nd, 3rd and 4th attempt


# --- secrets & logs -------------------------------------------------------------------------------

def site_secrets(site):
    from .crypto import decrypt_dict

    return decrypt_dict(site.secrets)


def fill_secrets(site, value):
    secrets_ = site_secrets(site)
    if isinstance(value, dict):
        return {k: fill_secrets(site, v) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    return SECRET_RE.sub(lambda m: str(secrets_.get(m.group(1), "")), value)


def record(site, kind, ref, ok, status="", ms=0, message="", detail=""):
    try:
        RunLog.objects.create(site=site, kind=kind, ref=str(ref)[:100], ok=ok, status=str(status)[:40], ms=int(ms),
                              message=str(message)[:300], detail=str(detail)[:20000])
        if RunLog.objects.filter(site=site).count() > 1100:
            old = RunLog.objects.filter(site=site).values_list("id", flat=True)[1000:]
            RunLog.objects.filter(id__in=list(old)).delete()
    except Exception:
        pass


# --- HTTP -----------------------------------------------------------------------------------------

def http_request(method, url, headers=None, body=None, timeout=20):
    """(status, text). Network problems raise RuntimeError with a readable message."""
    if not re.match(r"^https?://", url or "", re.I):
        raise RuntimeError("URL ต้องขึ้นต้นด้วย http:// หรือ https://")
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method.upper(),
                                 headers={"User-Agent": "BuildWeb", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"เชื่อมต่อ {url.split('/')[2] if '//' in url else url} ไม่ได้: {getattr(e, 'reason', e)}") from e


# --- events & webhooks ----------------------------------------------------------------------------

def emit(site, event, payload, collection=None):
    """Send ``event`` to the site's webhooks that want it (in the background)."""
    hooks = [h for h in site.webhooks.filter(active=True)
             if (not h.events or event in h.events) and (not h.collections or (collection and collection in h.collections))]
    if not hooks:
        return
    body = {"event": event, "site": site.slug, "collection": collection, "at": timezone.now().isoformat(timespec="seconds"),
            "data": payload}
    for h in hooks:
        if settings.TESTING:
            deliver(h, body, retries=())
        else:
            threading.Thread(target=_deliver_bg, args=(h.id, body), daemon=True).start()


def _deliver_bg(hook_id, body):
    close_old_connections()
    try:
        h = Webhook.objects.select_related("site").get(pk=hook_id)
        deliver(h, body)
    except Webhook.DoesNotExist:
        pass
    finally:
        close_old_connections()


def signature(secret, raw):
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def deliver(h, body, retries=RETRIES):
    raw = json.dumps(body, ensure_ascii=False, default=str).encode()
    delivery = uuid.uuid4().hex[:16]
    headers = {"Content-Type": "application/json", "X-BuildWeb-Event": body["event"], "X-BuildWeb-Delivery": delivery,
               **{k: v for k, v in fill_secrets(h.site, h.headers or {}).items() if k}}
    if h.signing_secret:
        headers["X-BuildWeb-Signature"] = signature(h.signing_secret, raw)
    url = fill_secrets(h.site, h.url)
    attempt, waits = 0, list(retries)
    while True:
        attempt += 1
        started = time.time()
        try:
            status, text = http_request("POST", url, headers, raw, timeout=15)
            ok = 200 <= status < 300
            msg = f"HTTP {status}"
        except RuntimeError as e:
            status, text, ok, msg = "error", "", False, str(e)
        record(h.site, "webhook", h.name, ok, status, (time.time() - started) * 1000,
               f"{body['event']} · {msg}" + (f" · ครั้งที่ {attempt}" if attempt > 1 else ""),
               json.dumps({"request": body, "response": text[:2000]}, ensure_ascii=False, default=str))
        if ok or not waits or (isinstance(status, int) and 400 <= status < 500 and status != 429):
            return ok
        time.sleep(waits.pop(0))


# --- connectors -----------------------------------------------------------------------------------

def dig(obj, path):
    """data.items / results[0].rows → the list of rows inside a JSON response."""
    for part in [p for p in re.split(r"\.|\[(\d+)\]", path or "") if p]:
        if isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)] if int(part) < len(obj) else None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def flatten(item):
    if not isinstance(item, dict):
        return {"value": item}
    out = {}
    for k, v in item.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}_{k2}"] = v2 if not isinstance(v2, (dict, list)) else json.dumps(v2, ensure_ascii=False)
        elif isinstance(v, list):
            out[k] = ", ".join(str(x) for x in v) if all(not isinstance(x, (dict, list)) for x in v) else json.dumps(v, ensure_ascii=False)
        else:
            out[k] = v
    return out


def fetch_connector(conn):
    site = conn.site
    body = fill_secrets(site, conn.body) if conn.body else None
    headers = fill_secrets(site, conn.headers or {})
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    status, text = http_request(conn.method or "GET", fill_secrets(site, conn.url), headers, body, timeout=30)
    if not 200 <= status < 300:
        raise RuntimeError(f"API ตอบกลับ HTTP {status}: {text[:200]}")
    try:
        parsed = json.loads(text)
    except ValueError:
        raise RuntimeError("ผลลัพธ์ไม่ใช่ JSON")
    items = dig(parsed, conn.items_path)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError(f"ไม่พบรายการที่ “{conn.items_path or '(ทั้งหมด)'}” — ลองตั้งตำแหน่งรายการ เช่น data.items")
    return [flatten(x) for x in items[: data_max()]]


def data_max():
    from .data import MAX_IMPORT_ROWS

    return MAX_IMPORT_ROWS


@transaction.atomic
def store_rows(conn, rows):
    from . import data

    site = conn.site
    if not rows:
        return 0
    columns = list(dict.fromkeys(k for r in rows for k in r))
    col = conn.collection
    if col is None:
        col = data.create_collection(site, conn.name, columns, rows)
        conn.collection = col
        conn.save(update_fields=["collection"])
        return len(rows)
    by_source = {f.get("source", f["name"]): f["name"] for f in col.fields}
    used = set(col.field_names)
    for c in columns:  # columns that appeared since the last run become new fields
        if c not in by_source:
            key = data.field_key(c, used)
            by_source[c] = key
            col.fields.append({"name": key, "label": c, "type": data.infer_type(c, [r.get(c) for r in rows[:200]]), "source": c})
    col.save()
    mapped = [{by_source[k]: data.plain(v) for k, v in r.items() if k in by_source} for r in rows]
    key = by_source.get(conn.key_field, conn.key_field) if conn.key_field else ""
    if key:
        existing = {str(r.data.get(key)): r for r in col.records.all()}
        pos = len(existing)
        for m in mapped:
            rec = existing.get(str(m.get(key)))
            if rec:
                rec.data = {**rec.data, **m}
                rec.save(update_fields=["data", "updated_at"])
            else:
                pos += 1
                Record.objects.create(collection=col, data=m, position=pos)
    else:
        col.records.all().delete()
        Record.objects.bulk_create([Record(collection=col, data=m, position=i) for i, m in enumerate(mapped)], batch_size=500)
    col.last_synced = timezone.now()
    col.save(update_fields=["last_synced", "updated_at"])
    data.invalidate(col)
    return len(mapped)


def run_connector(conn):
    started = time.time()
    try:
        if conn.plugin:
            from .plugins import sync_rows

            rows = sync_rows(conn)
        else:
            rows = fetch_connector(conn)
        n = store_rows(conn, rows)
        msg, ok = f"นำเข้า {n} แถว → {conn.collection.name if conn.collection else '-'}", True
    except (RuntimeError, ValueError) as e:
        msg, ok, n = str(e), False, 0
    conn.last_run, conn.last_status = timezone.now(), msg[:300]
    conn.save(update_fields=["last_run", "last_status"])
    record(conn.site, "connector", conn.name, ok, "ok" if ok else "error", (time.time() - started) * 1000, msg)
    if not ok:
        raise RuntimeError(msg)
    return n


# --- functions ------------------------------------------------------------------------------------

FN_TEMPLATE = '''def handler(request, bw):
    """request: method, query, body, headers, user (สมาชิกที่ล็อกอิน หรือ None)
    bw: list/get/create/update/delete(ชุดข้อมูล, ...), http(method, url, json=None, headers=None),
        secret("NAME"), log(...)
    คืนค่าเป็น dict/list (ได้ JSON 200) หรือ (status, dict)"""
    name = request["query"].get("name", "โลก")
    return {"message": f"สวัสดี {name}"}
'''


def call_function(fn, payload):
    """Run a function in a separate Python process (time limit, isolated from the app). Returns
    (status, body, logs)."""
    site = fn.site
    api_base = f"http://127.0.0.1:{settings.ADMIN_PORT}/preview/{site.slug}/api/v1/"
    job = {"code": fn.code, "request": payload, "api_base": api_base, "secrets": site_secrets(site)}
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "LANG")}
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    try:
        p = subprocess.run([sys.executable, "-I", str(RUNNER)], input=json.dumps(job, ensure_ascii=False, default=str),
                           capture_output=True, text=True, timeout=max(1, min(60, fn.timeout or 10)), env=env,
                           encoding="utf-8")
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {
            "ok": False, "status": 500, "body": {"error": {"code": "crashed", "message": "ฟังก์ชันหยุดทำงาน"}}, "logs": p.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        out = {"ok": False, "status": 504, "body": {"error": {"code": "timeout", "message": f"ทำงานเกิน {fn.timeout} วินาที"}}, "logs": ""}
    except (ValueError, IndexError):
        out = {"ok": False, "status": 500, "body": {"error": {"code": "bad_output", "message": "ฟังก์ชันส่งผลลัพธ์ไม่ถูกต้อง"}}, "logs": ""}
    ms = (time.time() - started) * 1000
    record(site, "function", fn.slug, out.get("ok", False), out.get("status"), ms,
           f"{payload.get('method', '')} {fn.slug} → {out.get('status')}",
           json.dumps({"request": payload, "response": out.get("body"), "logs": out.get("logs", "")}, ensure_ascii=False, default=str))
    return out.get("status", 500), out.get("body"), out.get("logs", "")


# --- schedules & jobs -----------------------------------------------------------------------------

DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
        "จ": 0, "อ": 1, "พ": 2, "พฤ": 3, "ศ": 4, "ส": 5, "อา": 6}
SCHEDULE_RE = re.compile(r"^(?:every\s+(\d+)\s*(m|min|h|hour|d|day)s?|hourly|daily\s+(\d{1,2}):(\d{2})"
                         r"|weekly\s+(\S+)\s+(\d{1,2}):(\d{2}))$", re.I)


def parse_schedule(text):
    m = SCHEDULE_RE.match((text or "").strip())
    if not m:
        raise ValueError("รูปแบบเวลาไม่ถูกต้อง ใช้เช่น every 15m · every 2h · hourly · daily 09:00 · weekly mon 09:00")
    if m.group(1):
        n = int(m.group(1))
        unit = m.group(2)[0].lower()
        minutes = n * {"m": 1, "h": 60, "d": 1440}[unit]
        if minutes < 5:
            raise ValueError("ถี่สุดได้ทุก 5 นาที")
        return ("every", minutes)
    if (text or "").strip().lower() == "hourly":
        return ("every", 60)
    if m.group(3):
        h, mi = int(m.group(3)), int(m.group(4))
        if h > 23 or mi > 59:
            raise ValueError("เวลาไม่ถูกต้อง")
        return ("daily", h, mi)
    day = DAYS.get(m.group(5).lower()[:3]) if m.group(5).lower()[:3] in DAYS else DAYS.get(m.group(5))
    if day is None:
        raise ValueError("วันไม่ถูกต้อง ใช้ mon tue wed thu fri sat sun")
    h, mi = int(m.group(6)), int(m.group(7))
    if h > 23 or mi > 59:
        raise ValueError("เวลาไม่ถูกต้อง")
    return ("weekly", day, h, mi)


def next_run(text, after=None):
    after = timezone.localtime(after or timezone.now())
    spec = parse_schedule(text)
    if spec[0] == "every":
        return after + timedelta(minutes=spec[1])
    if spec[0] == "daily":
        t = after.replace(hour=spec[1], minute=spec[2], second=0, microsecond=0)
        return t if t > after else t + timedelta(days=1)
    t = after.replace(hour=spec[2], minute=spec[3], second=0, microsecond=0) + timedelta(days=(spec[1] - after.weekday()) % 7)
    return t if t > after else t + timedelta(days=7)


def run_job(job):
    from . import data

    site, p = job.site, job.params or {}
    started = time.time()
    ok, msg, detail = True, "", ""
    try:
        if job.action == "call_url":
            status, text = http_request(p.get("method") or "GET", fill_secrets(site, p.get("url", "")),
                                        fill_secrets(site, p.get("headers") or {}), fill_secrets(site, p.get("body") or None))
            ok, msg, detail = 200 <= status < 300, f"HTTP {status}", text[:4000]
        elif job.action == "sync_mysql":
            col = site.collections.get(slug=p.get("collection"))
            if col.mode == Collection.LIVE:
                data.invalidate(col)
                msg = "ล้างแคชข้อมูลสดแล้ว"
            else:
                msg = f"ซิงก์ {data.resync(col)} แถว"
        elif job.action == "run_connector":
            n = run_connector(site.connectors.get(pk=p.get("connector")))
            msg = f"นำเข้า {n} แถว"
        elif job.action == "run_function":
            fn = site.functions.get(slug=p.get("function"))
            status, body, logs = call_function(fn, {"method": "POST", "query": {}, "body": p.get("body") or {}, "headers": {},
                                                    "user": None, "job": job.name})
            ok, msg, detail = 200 <= int(status) < 300, f"ฟังก์ชันตอบ {status}", json.dumps(body, ensure_ascii=False)[:4000]
        elif job.action == "purge_rows":
            col = site.collections.get(slug=p.get("collection"))
            days = max(1, int(p.get("days") or 30))
            n, _ = col.records.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()
            msg = f"ลบ {n} แถวที่เก่ากว่า {days} วัน"
        else:
            raise RuntimeError("ไม่รู้จักงานนี้")
    except Exception as e:  # a job must never take the scheduler down
        ok, msg = False, f"{type(e).__name__}: {e}"[:300]
    job.last_run, job.last_ok = timezone.now(), ok
    try:
        job.next_run = next_run(job.schedule)
    except ValueError:
        job.enabled = False
    job.save(update_fields=["last_run", "last_ok", "next_run", "enabled"])
    record(site, "job", job.name, ok, "ok" if ok else "error", (time.time() - started) * 1000, msg, detail)
    return ok, msg


_scheduler = {"thread": None}


def start_scheduler(interval=30):
    """Run due jobs every ``interval`` seconds in a daemon thread (started by run.py)."""
    if _scheduler["thread"]:
        return

    def loop():
        ticks = 0
        while True:
            time.sleep(interval)
            close_old_connections()
            try:
                for job in Job.objects.select_related("site").filter(enabled=True, next_run__lte=timezone.now()):
                    run_job(job)
                from .releases import run_due

                run_due()  # versions scheduled for a time
                if ticks % max(1, 3600 // interval) == 0:  # hourly check, one backup per site per day
                    from .backup import backup_all_due

                    backup_all_due()
            except Exception as e:
                log.warning("scheduler: %s", e)
            finally:
                close_old_connections()
                ticks += 1

    _scheduler["thread"] = threading.Thread(target=loop, daemon=True, name="buildweb-jobs")
    _scheduler["thread"].start()
