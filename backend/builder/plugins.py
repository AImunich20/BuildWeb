"""Plugins: connect a site to another program — a local app such as HarmoMed, or any HTTP service.

A plugin is described by a manifest (JSON). BuildWeb finds it in one of these ways (discover/probe):
  1. the program serves its own manifest at /.well-known/buildweb-plugin.json
  2. a built-in preset recognises it (PRESETS, e.g. HarmoMed)
  3. it publishes an OpenAPI description (/openapi.json …) → actions are made from it
  4. otherwise it is listed as a web app that can be added with a hand-written manifest

    {"id": "harmomed", "name": "HarmoMed", "description": "...",
     "health": {"path": "/api/indicators"},
     "links": [{"label": "เปิดโปรแกรม", "path": "/"}],
     "actions": {"grade": {"label": "...", "method": "POST", "path": "/api/grade", "body": "multipart", "timeout": 180,
                           "inputs": [{"name": "target", "label": "ภาพ", "type": "file", "required": true, "accept": ".jpg,.png"},
                                      {"name": "indicator", "type": "select", "options_from": {"path": "/api/indicators", "value": "name"}}],
                           "result": {"show": [{"label": "L*", "path": "report.metrics.signal.L", "format": "number:2"}],
                                      "images": [{"label": "ผลลัพธ์", "url": "/files/{report.full_result}"}]}}},
     "syncs": {"runs": {"label": "...", "path": "/api/runs", "items": "", "key": "filename", "every": "every 10 min",
                        "fields": {"quality": "report.metrics.quality"}, "images": {"image": "/files/{full}"}}}}

What a site can do with a plugin:
  - call an action from the app (test), from a page block <div data-bw-plugin="slug/action"> (when the action is
    open to visitors: Plugin.settings["access"][action] = "public" | "user") — POST <site>/api/v1/plugins/<slug>/<action>
  - save each call's inputs and results as a row of a collection (Plugin.settings["save"][action])
  - sync a list from the program into a collection on a schedule (a Connector with plugin/plugin_sync set; images are
    copied into the site's files so they work on the published site)
Every call is written to RunLog (kind "plugin"). Headers may use {{secret.NAME}}.
"""
import base64
import html as htmllib
import io
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.client import HTTPException

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Asset, Connector, Job, Plugin, Record

WELL_KNOWN = "/.well-known/buildweb-plugin.json"
OPENAPI_PATHS = ("/openapi.json", "/api/openapi.json", "/swagger.json", "/v3/api-docs", "/api/schema/?format=json")
SCAN_PORTS = (3000, 3001, 4000, 5000, 5001, 5060, 5100, 5173, 7860, 8000, 8001, 8008, 8080, 8081, 8501, 8888, 9000)
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")
INPUT_NAME_RE = re.compile(r"^[\w.\-\[\]]{1,80}$")
INPUT_TYPES = ("text", "longtext", "number", "select", "bool", "file", "email", "date", "json")
BODIES = ("none", "json", "form", "multipart")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
ACCESS = ("off", "public", "user")
MAX_RESPONSE = 20_000_000
MAX_IMAGE = 8_000_000
TEMPLATE_RE = re.compile(r"\{([\w.\[\]-]+)\}")

HARMOMED_SHOW = [
    {"label": "คุณภาพภาพ", "path": "metrics.quality"},
    {"label": "indicator", "path": "metrics.indicator"},
    {"label": "สีสัญญาณ (หลังปรับ)", "path": "metrics.signal.hex", "format": "color"},
    {"label": "L*", "path": "metrics.signal.L", "format": "number:2"},
    {"label": "a*", "path": "metrics.signal.a", "format": "number:2"},
    {"label": "b*", "path": "metrics.signal.b", "format": "number:2"},
    {"label": "ΔE ก่อนปรับ", "path": "metrics.deltaE_before", "format": "number:2"},
    {"label": "ΔE หลังปรับ", "path": "metrics.deltaE_after", "format": "number:2"},
    {"label": "ข้อควรระวัง", "path": "metrics.issues", "format": "list"},
]
PRESETS = {
    "harmomed": {
        "id": "harmomed", "name": "HarmoMed",
        "description": "ปรับสีภาพ indicator ที่ถ่ายจากกล้อง/แสงต่างกันให้เทียบกันได้ แล้วอ่านค่าสี L*a*b* ของแต่ละช่อง",
        "detect": [{"path": "/", "contains": "HarmoMed"}, {"path": "/api/indicators", "list": True}, {"path": "/api/runs", "list": True}],
        "health": {"path": "/api/indicators"},
        "links": [{"label": "เปิดหน้าโปรแกรม", "path": "/"}, {"label": "ค่าที่อ่านได้ทั้งหมด (CSV)", "path": "/export/readings.csv"},
                  {"label": "กรอบ calibration (PDF)", "path": "/frame.pdf"}],
        "actions": {
            "grade": {
                "label": "วิเคราะห์ภาพ indicator", "method": "POST", "path": "/api/grade", "body": "multipart", "timeout": 240,
                "submit": "วิเคราะห์ภาพ",
                "description": "อัปโหลดภาพ indicator → ปรับสีให้เทียบกับภาพอ้างอิง แล้วอ่านค่าสี",
                "inputs": [
                    {"name": "target", "label": "ภาพที่ถ่าย", "type": "file", "required": True,
                     "accept": ".jpg,.jpeg,.png,.webp,.bmp,.dng", "max_mb": 40},
                    {"name": "indicator", "label": "ชนิด indicator", "type": "select", "placeholder": "เลือกให้อัตโนมัติ",
                     "options_from": {"path": "/api/indicators", "value": "name", "label": "name"}},
                    {"name": "white_point", "label": "จุดขาว", "type": "select", "options": ["match", "standard", "reference"],
                     "default": "match"},
                    {"name": "sample_id", "label": "รหัสตัวอย่าง", "type": "text"},
                    {"name": "concentration", "label": "ความเข้มข้น", "type": "number"},
                    {"name": "minutes", "label": "เวลา (นาที)", "type": "number"},
                    {"name": "operator", "label": "ผู้ทดสอบ", "type": "text"},
                    {"name": "notes", "label": "หมายเหตุ", "type": "longtext"},
                ],
                "result": {"show": [{"label": "รหัสงาน", "path": "filename"}]
                           + [{**s, "path": "report." + s["path"]} for s in HARMOMED_SHOW],
                           "images": [{"label": "ภาพหลังปรับสี", "url": "/files/{report.full_result}"},
                                      {"label": "สรุปผล", "url": "/files/{report.plot}"}]},
            },
            "run": {
                "label": "ดูผลงานเดิม", "method": "GET", "path": "/api/runs/{name}", "submit": "ดูผล",
                "inputs": [{"name": "name", "label": "รหัสงาน", "type": "text", "required": True, "in": "path"}],
                "result": {"show": [{"label": "รหัสงาน", "path": "filename"}, {"label": "เวลา", "path": "created"}] + HARMOMED_SHOW,
                           "images": [{"label": "ภาพหลังปรับสี", "url": "/files/{full_result}"},
                                      {"label": "สรุปผล", "url": "/files/{plot}"}]},
            },
        },
        "syncs": {
            "runs": {
                "label": "ผลการวิเคราะห์ทั้งหมด", "path": "/api/runs", "key": "filename", "every": "every 10 min",
                "fields": {"filename": "filename", "time": "time", "status": "status",
                           "indicator": "report.metrics.indicator", "quality": "report.metrics.quality",
                           "signal_hex": "report.metrics.signal.hex", "L": "report.metrics.signal.L",
                           "a": "report.metrics.signal.a", "b": "report.metrics.signal.b",
                           "deltaE_before": "report.metrics.deltaE_before", "deltaE_after": "report.metrics.deltaE_after",
                           "sample_id": "report.study.sample_id", "concentration": "report.study.concentration",
                           "minutes": "report.study.minutes", "operator": "report.study.operator", "notes": "report.study.notes"},
                "images": {"image": "/files/{full}", "plot_image": "/files/{plot}"},
            },
        },
    },
}


class PluginError(ValueError):
    def __init__(self, message, status=400, code="plugin_error", fields=None):
        super().__init__(message)
        self.status, self.code, self.fields = status, code, fields


# --- HTTP -----------------------------------------------------------------------------------------

def _host(url):
    return urllib.parse.urlsplit(url).netloc or url


def http(method, url, headers=None, body=None, timeout=20, limit=MAX_RESPONSE):
    """(status, content type, bytes). Network problems raise PluginError (status 502)."""
    if not re.match(r"^https?://", url or "", re.I):
        raise PluginError("ที่อยู่ต้องขึ้นต้นด้วย http:// หรือ https://")
    req = urllib.request.Request(url, data=body, method=method.upper(), headers={"User-Agent": "BuildWeb-plugin", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(limit + 1)
            if len(data) > limit:
                raise PluginError(f"ผลลัพธ์จาก {_host(url)} ใหญ่เกิน {limit // 1_000_000} MB", status=502)
            return r.status, r.headers.get_content_type(), data
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get_content_type() if e.headers else ""), e.read(200_000)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, HTTPException) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            reason = f"ไม่ตอบภายใน {timeout} วินาที"
        raise PluginError(f"เชื่อมต่อ {_host(url)} ไม่ได้: {reason}", status=502, code="unreachable") from e


def _json(data):
    try:
        return json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return None


def multipart(fields, files):
    """(body, content type) for a multipart/form-data request. fields: [(name, value)], files: [(name, filename, type, bytes)]."""
    boundary = "----BuildWeb" + uuid.uuid4().hex
    safe = lambda s: re.sub(r'[\r\n"]', "_", str(s))  # noqa: E731
    out = io.BytesIO()
    for k, v in fields:
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{safe(k)}"\r\n\r\n'.encode())
        out.write(str(v).encode())
        out.write(b"\r\n")
    for k, filename, ctype, data in files:
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{safe(k)}"; filename="{safe(filename)}"\r\n'
                  f"Content-Type: {ctype or 'application/octet-stream'}\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def clean_base(url):
    url = (url or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc or parts.query or parts.fragment or re.search(r"[\s<>\"'\\]", url):
        raise PluginError("ใส่ที่อยู่ของโปรแกรม เช่น http://127.0.0.1:5060", fields={"base_url": "ที่อยู่ไม่ถูกต้อง"})
    return url


def headers_of(plugin):
    from .logic import fill_secrets

    return {k: v for k, v in fill_secrets(plugin.site, plugin.headers or {}).items() if k}


def dig(obj, path):
    from .logic import dig as _dig

    return _dig(obj, path) if path else obj


def fill(template, ctx):
    """'/files/{report.plot}' → '/files/results/3_plot.jpg'; None when a value is missing or unsafe."""
    missing = []

    def one(m):
        v = dig(ctx, m.group(1))
        s = "" if v is None else str(v)
        if not s or ".." in s or "://" in s or s.startswith("//"):
            missing.append(m.group(1))
            return ""
        return urllib.parse.quote(s.lstrip("/"), safe="/")

    out = TEMPLATE_RE.sub(one, template or "")
    return None if missing or not out.startswith("/") else out


# --- manifests ------------------------------------------------------------------------------------

def _s(v, n=200):
    return str(v if v is not None else "").strip()[:n]


def _path(p):
    p = _s(p, 500)
    if not p.startswith("/") or "://" in p or p.startswith("//"):
        raise PluginError(f"path ต้องขึ้นต้นด้วย / (ได้ “{p}”)")
    return p


def _clean_input(i, path):
    name = _s(i.get("name"), 80)
    if not INPUT_NAME_RE.match(name):
        raise PluginError(f"ชื่อช่อง “{name}” ไม่ถูกต้อง")
    t = i.get("type") if i.get("type") in INPUT_TYPES else "text"
    x = {"name": name, "label": _s(i.get("label") or name, 120), "type": t, "required": bool(i.get("required"))}
    x["in"] = "path" if "{%s}" % name in path else (i.get("in") if i.get("in") in ("query", "body") else "body")
    for k, n in (("placeholder", 200), ("accept", 200), ("help", 300)):
        if i.get(k):
            x[k] = _s(i[k], n)
    if i.get("default") not in (None, ""):
        x["default"] = _s(i["default"], 500)
    if t == "select":
        x["options"] = [_s(o, 200) for o in (i.get("options") or [])[:200] if _s(o)]
        of = i.get("options_from") or {}
        if of.get("path"):
            x["options_from"] = {"path": _path(of["path"]), "items": _s(of.get("items"), 100),
                                 "value": _s(of.get("value"), 80), "label": _s(of.get("label") or of.get("value"), 80)}
    if t == "file":
        x["max_mb"] = max(1, min(200, int(float(i.get("max_mb") or 20))))
    return x


def _clean_action(a):
    path = _path(a.get("path"))
    method = _s(a.get("method") or "GET", 8).upper()
    if method not in METHODS:
        raise PluginError(f"method ต้องเป็น {', '.join(METHODS)}")
    inputs = [_clean_input(i, path) for i in (a.get("inputs") or [])[:40] if isinstance(i, dict)]
    body = a.get("body") if a.get("body") in BODIES else ("multipart" if any(i["type"] == "file" for i in inputs)
                                                           else "none" if method == "GET" else "json")
    if method == "GET":
        body = "none"
        for i in inputs:
            if i["in"] == "body":
                i["in"] = "query"
    res = a.get("result") or {}
    result = {"show": [{"label": _s(s.get("label") or s.get("path"), 120), "path": _s(s.get("path"), 200),
                        "format": _s(s.get("format"), 30)} for s in (res.get("show") or [])[:40] if isinstance(s, dict) and s.get("path")],
              "images": [{"label": _s(s.get("label"), 120), "url": _path(s.get("url"))}
                         for s in (res.get("images") or [])[:8] if isinstance(s, dict) and s.get("url")]}
    return {"label": _s(a.get("label") or path, 120), "description": _s(a.get("description"), 500), "method": method, "path": path,
            "body": body, "timeout": max(1, min(600, int(float(a.get("timeout") or 60)))), "submit": _s(a.get("submit"), 60),
            "inputs": inputs, "result": result}


def clean_manifest(m):
    """Validate a manifest from a program / the app / a preset; unknown keys are dropped."""
    if not isinstance(m, dict):
        raise PluginError("manifest ต้องเป็น JSON object")
    actions = {}
    for k, a in list((m.get("actions") or {}).items())[:60]:
        if not KEY_RE.match(str(k)) or not isinstance(a, dict):
            raise PluginError(f"ชื่อ action “{k}” ใช้ a-z 0-9 _ -")
        actions[str(k)] = _clean_action(a)
    syncs = {}
    for k, s in list((m.get("syncs") or {}).items())[:20]:
        if not KEY_RE.match(str(k)) or not isinstance(s, dict):
            raise PluginError(f"ชื่อ sync “{k}” ใช้ a-z 0-9 _ -")
        syncs[str(k)] = {"label": _s(s.get("label") or k, 120), "path": _path(s.get("path")), "items": _s(s.get("items"), 100),
                         "key": _s(s.get("key"), 80), "every": _s(s.get("every"), 60),
                         "fields": {_s(n, 80): _s(p, 200) for n, p in list((s.get("fields") or {}).items())[:80] if _s(n)},
                         "images": {_s(n, 80): _path(t) for n, t in list((s.get("images") or {}).items())[:8] if _s(n)}}
    health = m.get("health") or {}
    return {"id": slugify(_s(m.get("id") or m.get("name"), 60)) or "plugin", "name": _s(m.get("name") or "โปรแกรม", 100),
            "description": _s(m.get("description"), 500), "version": _s(m.get("version"), 30),
            "health": {"path": _path(health["path"]) if health.get("path") else "/"},
            "links": [{"label": _s(x.get("label"), 80), "path": _path(x.get("path"))} for x in (m.get("links") or [])[:10]
                      if isinstance(x, dict) and x.get("path")],
            "actions": actions, "syncs": syncs}


def _schema(spec, s, depth=0):
    while isinstance(s, dict) and "$ref" in s and depth < 10:
        s = dig(spec, s["$ref"].lstrip("#/").replace("/", "."))
        depth += 1
    return s if isinstance(s, dict) else {}


def _openapi_input(name, s, required, where):
    t = s.get("type")
    x = {"name": name, "label": s.get("title") or name, "required": required, "in": where}
    if s.get("enum"):
        x.update(type="select", options=[str(o) for o in s["enum"]])
    elif s.get("format") in ("binary", "base64") or (t == "array" and (s.get("items") or {}).get("format") == "binary"):
        x["type"] = "file"
    elif t in ("integer", "number"):
        x["type"] = "number"
    elif t == "boolean":
        x["type"] = "bool"
    elif t in ("object", "array"):
        x["type"] = "json"
    else:
        x["type"] = "date" if s.get("format") == "date" else "email" if s.get("format") == "email" else "text"
    if s.get("default") is not None:
        x["default"] = s["default"] if not isinstance(s["default"], (dict, list)) else json.dumps(s["default"])
    if s.get("description"):
        x["help"] = str(s["description"])[:300]
    return x


def from_openapi(spec):
    """A manifest made from an OpenAPI 3 / Swagger 2 description (one action per operation)."""
    info = spec.get("info") or {}
    prefix = ""
    servers = spec.get("servers") or []
    if servers and str(servers[0].get("url", "")).startswith("/"):
        prefix = str(servers[0]["url"]).rstrip("/")
    elif spec.get("basePath"):
        prefix = str(spec["basePath"]).rstrip("/")
    actions, used = {}, set()
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = item.get(method)
            if not isinstance(op, dict) or len(actions) >= 60:
                continue
            key = slugify(op.get("operationId") or f"{method}-{path}").replace("-", "_")[:56] or method
            while key in used:
                key += "_"
            used.add(key)
            inputs, body = [], "none"
            for prm in (item.get("parameters") or []) + (op.get("parameters") or []):
                prm = _schema(spec, prm)
                if prm.get("in") in ("query", "path") and prm.get("name"):
                    inputs.append(_openapi_input(prm["name"], _schema(spec, prm.get("schema") or prm), bool(prm.get("required")), prm["in"]))
                elif prm.get("in") == "formData" and prm.get("name"):  # Swagger 2
                    body = "multipart" if prm.get("type") == "file" else ("form" if body == "none" else body)
                    inputs.append({**_openapi_input(prm["name"], prm, bool(prm.get("required")), "body"),
                                   **({"type": "file"} if prm.get("type") == "file" else {})})
            content = (_schema(spec, op.get("requestBody")).get("content") or {})
            for ctype, kind in (("multipart/form-data", "multipart"), ("application/x-www-form-urlencoded", "form"), ("application/json", "json")):
                if ctype in content:
                    body = kind
                    s = _schema(spec, content[ctype].get("schema"))
                    req = set(s.get("required") or [])
                    for name, ps in list((s.get("properties") or {}).items())[:30]:
                        inputs.append(_openapi_input(name, _schema(spec, ps), name in req, "body"))
                    break
            actions[key] = {"label": (op.get("summary") or f"{method.upper()} {path}")[:120], "description": (op.get("description") or "")[:500],
                            "method": method.upper(), "path": prefix + re.sub(r"\{([^}]+)\}", lambda m: "{" + re.sub(r"[^\w.-]", "_", m.group(1)) + "}", path),
                            "body": body, "inputs": inputs}
    return clean_manifest({"id": info.get("title"), "name": info.get("title") or "API", "description": info.get("description"),
                           "version": info.get("version"), "actions": actions})


# --- finding programs -----------------------------------------------------------------------------

def _get(url, timeout=3):
    try:
        return http("GET", url, timeout=timeout, limit=3_000_000)
    except PluginError:
        return None, "", b""


def _matches(base, checks):
    for c in checks:
        status, ctype, data = _get(base + c["path"])
        if status != 200:
            return False
        if c.get("contains") and c["contains"].encode() not in data:
            return False
        if c.get("list") and not isinstance(_json(data), list):
            return False
    return True


def probe(base):
    """What program runs at ``base``: {"url", "how", "kind", "manifest"} or None when nothing answers."""
    base = clean_base(base)
    status, ctype, data = _get(base + WELL_KNOWN)
    if status == 200 and isinstance(_json(data), dict):
        try:
            m = clean_manifest(_json(data))
            return {"url": base, "how": "manifest", "kind": "manifest", "manifest": m}
        except PluginError:
            pass
    for pid, preset in PRESETS.items():
        if _matches(base, preset["detect"]):
            return {"url": base, "how": "preset", "kind": pid, "manifest": clean_manifest(preset)}
    for p in OPENAPI_PATHS:
        status, ctype, data = _get(base + p)
        spec = _json(data) if status == 200 else None
        if isinstance(spec, dict) and isinstance(spec.get("paths"), dict) and (spec.get("openapi") or spec.get("swagger")):
            try:
                m = from_openapi(spec)
                m["health"] = {"path": p.split("?")[0]}
                return {"url": base, "how": "openapi", "kind": "openapi", "manifest": m}
            except PluginError:
                break
    status, ctype, data = _get(base + "/")
    if status is None or status >= 400:  # e.g. macOS AirPlay on port 5000 answers 403 to everything
        return None
    title = re.search(rb"<title[^>]*>(.*?)</title>", data or b"", re.S | re.I)
    name = htmllib.unescape(title.group(1).decode("utf-8", "replace")).strip()[:100] if title else ""
    return {"url": base, "how": "web", "kind": "manifest",
            "manifest": clean_manifest({"name": name or _host(base), "links": [{"label": "เปิดหน้าโปรแกรม", "path": "/"}]})}


def _open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def discover(urls=(), exclude_ports=()):
    """Programs on this computer (common ports on 127.0.0.1) plus ``urls``."""
    ports = [p for p in SCAN_PORTS if p not in set(exclude_ports)]
    with ThreadPoolExecutor(max_workers=16) as ex:
        live = [p for p, ok in zip(ports, ex.map(_open, ports)) if ok]
        bases = list(dict.fromkeys([clean_base(u) for u in urls if u] + [f"http://127.0.0.1:{p}" for p in live]))
        found = [f for f in ex.map(lambda b: _safe_probe(b), bases) if f]
    order = {"preset": 0, "manifest": 1, "openapi": 2, "web": 3}
    return sorted(found, key=lambda f: order.get(f["how"], 9))


def _safe_probe(base):
    try:
        return probe(base)
    except PluginError:
        return None


# --- calling actions ------------------------------------------------------------------------------

def _coerce(inp, v):
    t = inp["type"]
    if isinstance(v, str):
        v = v.strip()
    if v in (None, "") or (t == "bool" and v in (False, "false", "0", "off", "")):
        return False if t == "bool" and v not in (None, "") else None
    if t == "number":
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise PluginError(f"“{inp['label']}” ต้องเป็นตัวเลข", fields={inp["name"]: "ต้องเป็นตัวเลข"})
        return int(n) if n.is_integer() else n
    if t == "bool":
        return True
    if t == "json":
        if isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(v)
        except ValueError:
            raise PluginError(f"“{inp['label']}” ต้องเป็น JSON", fields={inp["name"]: "JSON ไม่ถูกต้อง"})
    if t == "select" and inp.get("options") and not inp.get("options_from") and str(v) not in inp["options"]:
        raise PluginError(f"“{inp['label']}” ต้องเป็นหนึ่งในตัวเลือก", fields={inp["name"]: "ไม่มีในตัวเลือก"})
    return str(v)[:10000 if t in ("longtext", "text") else 500]


def _format(v, fmt):
    if v is None:
        return ""
    if fmt.startswith("number"):
        try:
            return round(float(v), int(fmt.split(":")[1]) if ":" in fmt else 2)
        except (TypeError, ValueError):
            return str(v)
    if fmt == "color":
        return str(v) if re.fullmatch(r"#[0-9a-fA-F]{3,8}", str(v)) else ""
    if fmt == "list" or isinstance(v, list):
        items = v if isinstance(v, list) else [v]
        return " · ".join(str(x.get("message") or x.get("label") or x.get("name") or json.dumps(x, ensure_ascii=False))
                          if isinstance(x, dict) else str(x) for x in items[:30])
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)[:2000]
    return v if isinstance(v, (int, float, bool)) else str(v)[:5000]


def _show(action, parsed):
    spec = action["result"]["show"]
    if spec:
        return [{"label": s["label"], "value": _format(dig(parsed, s["path"]), s["format"]), "format": s["format"]} for s in spec]
    if isinstance(parsed, dict):
        return [{"label": k, "value": _format(v, ""), "format": ""} for k, v in list(parsed.items())[:30]
                if not isinstance(v, (dict, list))]
    return []


def fetch_image(plugin, path, headers=None):
    """(content type, bytes) of an image the program serves, or None."""
    try:
        status, ctype, data = http("GET", plugin.base_url + path, headers if headers is not None else headers_of(plugin),
                                   timeout=30, limit=MAX_IMAGE)
    except PluginError:
        return None
    return (ctype, data) if status == 200 and ctype.startswith("image/") and data else None


def _error_text(parsed, data):
    if isinstance(parsed, dict):
        e = parsed.get("error") or parsed.get("message") or parsed.get("detail")
        if isinstance(e, dict):
            e = e.get("message") or json.dumps(e, ensure_ascii=False)
        if e:
            return str(e)[:300]
    return re.sub(r"<[^>]+>|\s+", " ", data.decode("utf-8", "replace")).strip()[:300]


def call(plugin, key, values=None, files=None, save=False, owner=True):
    """Run action ``key``. values: {name: value}; files: {name: (filename, content type, bytes)}.
    Returns {"show": [{label, value, format}], "images": [{label, src (data: URI)}], "saved", "data" (owner only)}."""
    from .logic import record

    action = (plugin.manifest.get("actions") or {}).get(key)
    if not action:
        raise PluginError("ไม่พบคำสั่งนี้ในปลั๊กอิน", status=404, code="not_found")
    values, files = values or {}, files or {}
    path, query, fields, body_json, upload, kept = action["path"], [], [], {}, [], {}
    for inp in action["inputs"]:
        name = inp["name"]
        if inp["type"] == "file":
            f = files.get(name)
            if not f and inp["required"]:
                raise PluginError(f"เลือกไฟล์ “{inp['label']}”", fields={name: "ต้องเลือกไฟล์"})
            if f:
                upload.append((name, f[0], f[1], f[2]))
            continue
        v = _coerce(inp, values.get(name, inp.get("default")))
        if v is None:
            if inp["required"]:
                raise PluginError(f"กรอก “{inp['label']}”", fields={name: "ต้องกรอก"})
            continue
        kept[name] = v
        if inp["in"] == "path":
            path = path.replace("{%s}" % name, urllib.parse.quote(str(v), safe=""))
        elif inp["in"] == "query":
            query.append((name, "true" if v is True else v))
        elif action["body"] == "json":
            body_json[name] = v
        else:
            fields.append((name, "true" if v is True else json.dumps(v) if isinstance(v, (dict, list)) else v))
    if "{" in path:
        raise PluginError("ข้อมูลในลิงก์ไม่ครบ")
    headers = headers_of(plugin)
    req_headers, body = dict(headers), None
    if action["body"] == "multipart":
        body, req_headers["Content-Type"] = multipart(fields, upload)
    elif action["body"] == "form":
        body, req_headers["Content-Type"] = urllib.parse.urlencode(fields).encode(), "application/x-www-form-urlencoded"
    elif action["body"] == "json":
        body, req_headers["Content-Type"] = json.dumps(body_json, ensure_ascii=False).encode(), "application/json"
    url = plugin.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
    started = time.time()
    label = f"{plugin.name} · {action['label']}"[:100]
    try:
        status, ctype, data = http(action["method"], url, req_headers, body, timeout=action["timeout"])
    except PluginError as e:
        record(plugin.site, "plugin", label, False, "error", (time.time() - started) * 1000, str(e))
        raise
    parsed = _json(data) if (ctype.endswith("json") or data[:1] in (b"{", b"[")) else None
    ok = 200 <= status < 300
    msg = f"HTTP {status}" + ("" if ok else " · " + _error_text(parsed, data))
    record(plugin.site, "plugin", label, ok, status, (time.time() - started) * 1000, msg,
           json.dumps({"request": {"method": action["method"], "url": url, "inputs": kept, "files": [u[1] for u in upload]},
                       "response": parsed if parsed is not None else data[:2000].decode("utf-8", "replace")},
                      ensure_ascii=False, default=str)[:20000])
    if not ok:
        raise PluginError(f"{plugin.name} ตอบกลับ: {_error_text(parsed, data) or 'HTTP ' + str(status)}",
                          status=422 if 400 <= status < 500 else 502, code="plugin_failed")
    result = parsed if parsed is not None else {"text": data[:20000].decode("utf-8", "replace")}
    images = []
    for spec in action["result"]["images"]:
        p = fill(spec["url"], result)
        img = fetch_image(plugin, p, headers) if p else None
        if img:
            images.append({"label": spec["label"], "type": img[0], "bytes": img[1]})
    out = {"show": _show(action, result),
           "images": [{"label": i["label"], "src": f"data:{i['type']};base64,{base64.b64encode(i['bytes']).decode()}"} for i in images],
           "saved": None}
    if save and plugin_setting(plugin, "save", key):
        out["saved"] = save_result(plugin, key, kept, out["show"], images)
    if owner:
        out["data"] = result if len(data) < 300_000 else {"note": "ผลลัพธ์ใหญ่เกินกว่าจะแสดงทั้งหมด"}
    return out


def plugin_setting(plugin, group, key, default=""):
    return ((plugin.settings or {}).get(group) or {}).get(key, default)


def options_for(plugin, inp, _cache={}):
    """Choices of a select input: fixed options, or read from the program (cached for a minute)."""
    opts = [(o, o) for o in inp.get("options") or []]
    of = inp.get("options_from")
    if not of:
        return opts
    ck = (plugin.id, plugin.base_url, of["path"])
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 60:
        return opts + hit[1]
    found = []
    try:
        status, _, data = http("GET", plugin.base_url + of["path"], headers_of(plugin), timeout=3, limit=2_000_000)
        items = dig(_json(data), of["items"]) if status == 200 else None
        for it in (items if isinstance(items, list) else [])[:200]:
            v = dig(it, of["value"]) if isinstance(it, dict) and of["value"] else it
            lb = dig(it, of["label"]) if isinstance(it, dict) and of["label"] else v
            if v not in (None, ""):
                found.append((str(v), str(lb)))
    except PluginError:
        pass
    _cache[ck] = (time.time(), found)
    return opts + found


def check(plugin):
    started = time.time()
    try:
        status, _, _ = http("GET", plugin.base_url + (plugin.manifest.get("health") or {}).get("path", "/"), headers_of(plugin),
                            timeout=5, limit=5_000_000)
        ok = status < 500 and status not in (401, 403, 404)
        msg = f"ออนไลน์ · {int((time.time() - started) * 1000)} ms" if ok else f"ตอบกลับ HTTP {status}"
    except PluginError as e:
        ok, msg = False, str(e)
    plugin.last_check, plugin.last_ok, plugin.last_status = timezone.now(), ok, msg[:300]
    plugin.save(update_fields=["last_check", "last_ok", "last_status"])
    return ok, msg


# --- saving results & syncing lists ---------------------------------------------------------------

def store_image(site, folder, name, ctype, data):
    from django.core.files.base import ContentFile

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg"}.get(ctype, "img")
    if ext in ("svg", "img"):  # only plain raster images are copied into the site's files
        return ""
    a = Asset(site=site, name=f"{name}.{ext}", folder=folder, kind="image", size=len(data))
    a.file.save(a.name, ContentFile(data), save=False)
    a.save()
    return a.url


def _add_row(col, row):
    from . import data

    by_source = {f.get("source", f["name"]): f["name"] for f in col.fields}
    used = set(col.field_names)
    for c, v in row.items():
        if c not in by_source:
            k = data.field_key(c, used)
            by_source[c] = k
            col.fields.append({"name": k, "label": c, "type": data.infer_type(c, [v]), "source": c})
    col.save()
    pos = (col.records.order_by("-position").values_list("position", flat=True).first() or 0) + 1
    rec = Record.objects.create(collection=col, position=pos, data={by_source[k]: data.plain(v) for k, v in row.items()})
    data.invalidate(col)
    return rec


@transaction.atomic
def save_result(plugin, key, inputs, show, images):
    """One row per call in the collection set for the action (made on the first save)."""
    from . import data, logic

    site, action = plugin.site, plugin.manifest["actions"][key]
    labels = {i["name"]: i["label"] for i in action["inputs"]}
    row = {"เวลา": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")}
    row.update({labels.get(k, k): v for k, v in inputs.items()})
    row.update({s["label"]: s["value"] for s in show})
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for n, img in enumerate(images):
        row[img["label"] or f"ภาพ {n + 1}"] = store_image(site, f"plugins/{plugin.slug}", f"{key}-{stamp}-{n + 1}", img["type"], img["bytes"])
    slug = plugin_setting(plugin, "save", key)
    col = site.collections.filter(slug=slug).first() if slug and slug != "new" else None
    if col is None:
        col = data.create_collection(site, f"{plugin.name} · {action['label']}", list(row), [])
        for f in col.fields:
            f.setdefault("source", f.get("label") or f["name"])
        col.save()
        s = dict(plugin.settings or {})
        s["save"] = {**(s.get("save") or {}), key: col.slug}
        plugin.settings = s
        plugin.save(update_fields=["settings"])
    rec = _add_row(col, row)
    logic.emit(site, "record.created", {"_id": rec.id, **rec.data}, collection=col.slug)
    return {"collection": col.slug, "id": rec.id}


def sync_rows(conn):
    """Rows of a plugin sync (called by logic.run_connector); images are copied into the site's files once."""
    from .logic import data_max, flatten

    plugin = conn.site.plugins.filter(slug=conn.plugin).first()
    if not plugin:
        raise RuntimeError(f"ไม่พบปลั๊กอิน “{conn.plugin}”")
    spec = (plugin.manifest.get("syncs") or {}).get(conn.plugin_sync)
    if not spec:
        raise RuntimeError("ปลั๊กอินนี้ไม่มีรายการให้ดึงแล้ว")
    headers = headers_of(plugin)
    try:
        status, _, data = http("GET", plugin.base_url + spec["path"], headers, timeout=60)
    except PluginError as e:
        raise RuntimeError(str(e))
    if not 200 <= status < 300:
        raise RuntimeError(f"{plugin.name} ตอบกลับ HTTP {status}")
    items = dig(_json(data), spec["items"])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError("ผลลัพธ์ไม่ใช่รายการ")
    folder, rows, fetched = f"plugins/{plugin.slug}", [], 0
    known = {a.name.rsplit(".", 1)[0]: a.url for a in Asset.objects.filter(site=conn.site, folder=folder)}
    for item in items[:data_max()]:
        if spec["fields"]:
            from .data import plain

            row = {n: plain(_format(dig(item, p), "") if isinstance(dig(item, p), (list, dict)) else dig(item, p))
                   for n, p in spec["fields"].items()}
        else:
            row = flatten(item)
        for name, tmpl in spec["images"].items():
            p = fill(tmpl, item)
            if not p:
                row[name] = ""
                continue
            ident = slugify(f"{conn.plugin_sync}-{name}-{p}")[:120]
            if ident not in known and fetched < 200:
                fetched += 1
                img = fetch_image(plugin, p, headers)
                known[ident] = store_image(conn.site, folder, ident, *img) if img else ""
            row[name] = known.get(ident, "")
        rows.append(row)
    return rows


def ensure_sync(plugin, key, schedule=None):
    """The Connector (and optional scheduled Job) of sync ``key``."""
    from .logic import next_run

    spec = plugin.manifest["syncs"][key]
    conn = Connector.objects.filter(site=plugin.site, plugin=plugin.slug, plugin_sync=key).first()
    if conn is None:
        conn = Connector.objects.create(site=plugin.site, name=f"{plugin.name} · {spec['label']}"[:100], plugin=plugin.slug,
                                        plugin_sync=key, url=plugin.base_url + spec["path"], key_field=spec["key"])
    if schedule:
        job = next((j for j in plugin.site.jobs.filter(action="run_connector") if (j.params or {}).get("connector") == conn.id), None)
        if job is None:
            Job.objects.create(site=plugin.site, name=f"ซิงก์ {conn.name}"[:100], schedule=schedule, action="run_connector",
                               params={"connector": conn.id}, next_run=next_run(schedule))
    return conn


def unique_slug(site, name, exclude=None):
    base = slugify(name)[:50] or "plugin"
    slug, n = base, 1
    while site.plugins.filter(slug=slug).exclude(pk=exclude).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def setup(site, found, name="", headers=None, syncs=(), pages=()):
    """Connect a program found by probe(): save the plugin, start its syncs, make pages for actions."""
    from . import logic

    m = clean_manifest(found["manifest"])
    p = Plugin.objects.create(site=site, name=(name or m["name"])[:100], slug=unique_slug(site, name or m["id"] or m["name"]),
                              kind=found.get("kind") or "manifest", base_url=clean_base(found["url"]), headers=headers or {},
                              manifest=m, settings={"access": {}, "save": {}})
    report = []
    for key in syncs:
        if key not in m["syncs"]:
            continue
        conn = ensure_sync(p, key, m["syncs"][key]["every"] or "every 10 min")
        try:
            n = logic.run_connector(conn)
            report.append(f"ดึง “{m['syncs'][key]['label']}” แล้ว {n} แถว")
        except RuntimeError as e:
            report.append(f"ดึง “{m['syncs'][key]['label']}” ไม่สำเร็จ: {e}")
    for key in pages:
        if key in m["actions"]:
            page = make_page(p, key)
            report.append(f"สร้างหน้า “{page.title}” ({page.filename})")
    check(p)
    return p, report


def make_page(plugin, key):
    from . import services

    action = plugin.manifest["actions"][key]
    s = dict(plugin.settings or {})
    s["access"] = {**(s.get("access") or {}), key: plugin_setting(plugin, "access", key) or "public"}
    if s["access"][key] == "off":
        s["access"][key] = "public"
    plugin.settings = s
    plugin.save(update_fields=["settings"])
    title = action["label"]
    page = services.create_page(plugin.site, title, layout="blank", status="draft")
    e = htmllib.escape
    page.html = (f'<section style="padding:60px 20px"><div class="bw-container" style="max-width:760px">'
                 f'<h1>{e(title)}</h1>' + (f"<p>{e(action['description'])}</p>" if action["description"] else "")
                 + block_html(plugin, key) + "</div></section>")
    page.project_data = {}
    page.save(update_fields=["html", "project_data"])
    return page


# --- on pages -------------------------------------------------------------------------------------

def block_html(plugin, key):
    """What the editor block inserts: a slot that render.fill_plugins turns into the action's form."""
    label = htmllib.escape(f"{plugin.name} · {plugin.manifest['actions'][key]['label']}")
    return f'<div data-bw-plugin="{plugin.slug}/{key}" class="bw-plugin"><p>ฟอร์มปลั๊กอิน: {label}</p></div>'


PLUGIN_RE = re.compile(r'(<div\b[^>]*\bdata-bw-plugin="([\w-]+)/([\w-]+)"[^>]*>).*?(</div>)', re.S | re.I)
PLUGIN_CSS = """<style>.bw-plugin-form{display:grid;gap:12px;max-width:560px}.bw-plugin-form label{display:grid;gap:6px;font-weight:600}
.bw-plugin-form input,.bw-plugin-form select,.bw-plugin-form textarea{font:inherit;font-weight:400;padding:11px 13px;border:1px solid #d9d9e3;border-radius:10px;background:#fff}
.bw-plugin-form .bw-check{display:flex;align-items:center;gap:8px}.bw-plugin-form .bw-check input{width:18px;height:18px}
.bw-plugin-form button{cursor:pointer;font:inherit;font-weight:600;justify-self:start}.bw-plugin-form small{font-weight:400;opacity:.7}
.bw-plugin-status{min-height:1.2em}.bw-plugin-status.err{color:#b91c1c}.bw-plugin-status.ok{color:#047857}
.bw-plugin-result{display:grid;gap:14px;margin-top:6px}.bw-plugin-result table{border-collapse:collapse;width:100%}
.bw-plugin-result td{padding:8px 10px;border-bottom:1px solid #ececf1;vertical-align:top}.bw-plugin-result td:first-child{opacity:.7;width:40%}
.bw-plugin-swatch{display:inline-block;width:18px;height:18px;border-radius:5px;vertical-align:-3px;margin-right:8px;border:1px solid rgba(0,0,0,.15)}
.bw-plugin-images{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.bw-plugin-images figure{margin:0}.bw-plugin-images img{width:100%;border-radius:10px;border:1px solid #ececf1}
.bw-plugin-images figcaption{font-size:.9em;opacity:.75;margin-top:4px}</style>"""
# Sends the form to <site>/api/v1/plugins/<slug>/<action> and shows the result (text only, images as data: URIs).
PLUGIN_JS = r"""
(function(){
  document.querySelectorAll('form[data-bw-plugin-form]').forEach(function(form){
    var url = new URL('api/v1/plugins/' + form.getAttribute('data-bw-plugin-form'), document.baseURI).href;
    var status = form.querySelector('.bw-plugin-status'), out = form.querySelector('.bw-plugin-result');
    function el(tag, text, cls){ var e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
    form.addEventListener('submit', function(e){
      e.preventDefault();
      var btn = form.querySelector('[type=submit]'); if (btn) btn.disabled = true;
      status.className = 'bw-plugin-status'; status.textContent = 'กำลังประมวลผล…'; out.hidden = true; out.innerHTML = '';
      fetch(url, {method: 'POST', body: new FormData(form), credentials: 'same-origin'}).then(function(r){
        return r.json().catch(function(){ return {}; }).then(function(j){
          if (!r.ok) throw new Error((j.error && j.error.message) || ('เกิดข้อผิดพลาด (' + r.status + ')'));
          return j;
        });
      }).then(function(j){
        status.className = 'bw-plugin-status ok'; status.textContent = form.getAttribute('data-bw-done') || 'เสร็จแล้ว';
        if ((j.show || []).length) {
          var t = el('table'), tb = el('tbody'); t.appendChild(tb);
          j.show.forEach(function(s){
            var tr = el('tr'), v = el('td'); tr.appendChild(el('td', s.label));
            if (s.format === 'color' && /^#[0-9a-f]{3,8}$/i.test(s.value)) { var sw = el('span', null, 'bw-plugin-swatch'); sw.style.background = s.value; v.appendChild(sw); }
            v.appendChild(document.createTextNode(s.value === '' || s.value == null ? '—' : String(s.value)));
            tr.appendChild(v); tb.appendChild(tr);
          });
          out.appendChild(t);
        }
        var imgs = (j.images || []).filter(function(i){ return /^data:image\/(png|jpeg|webp|gif);base64,/.test(i.src); });
        if (imgs.length) {
          var g = el('div', null, 'bw-plugin-images');
          imgs.forEach(function(i){ var f = el('figure'), im = el('img'); im.src = i.src; im.alt = i.label || ''; f.appendChild(im); if (i.label) f.appendChild(el('figcaption', i.label)); g.appendChild(f); });
          out.appendChild(g);
        }
        out.hidden = !out.childNodes.length;
      }).catch(function(err){ status.className = 'bw-plugin-status err'; status.textContent = err.message; })
        .finally(function(){ if (btn) btn.disabled = false; });
    });
  });
})();
"""


def form_html(plugin, key):
    e = htmllib.escape
    action = plugin.manifest["actions"][key]
    parts = []
    for inp in action["inputs"]:
        name, req = e(inp["name"]), " required" if inp["required"] else ""
        label = e(inp["label"]) + (" *" if inp["required"] else "")
        hint = f"<small>{e(inp['help'])}</small>" if inp.get("help") else ""
        ph = f' placeholder="{e(inp["placeholder"])}"' if inp.get("placeholder") and inp["type"] != "select" else ""
        dv = e(inp.get("default", ""))
        if inp["type"] == "file":
            acc = f' accept="{e(inp["accept"])}"' if inp.get("accept") else ""
            parts.append(f'<label>{label}<input type="file" name="{name}"{acc}{req}>{hint}</label>')
        elif inp["type"] == "select":
            opts = "".join(f'<option value="{e(v)}"{" selected" if v == inp.get("default") else ""}>{e(lb)}</option>'
                           for v, lb in options_for(plugin, inp))
            first = "" if inp.get("default") else f'<option value="">{e(inp.get("placeholder") or "— เลือก —")}</option>'
            parts.append(f'<label>{label}<select name="{name}"{req}>{first}{opts}</select>{hint}</label>')
        elif inp["type"] == "bool":
            parts.append(f'<label class="bw-check"><input type="checkbox" name="{name}" value="true"> {label}</label>')
        elif inp["type"] in ("longtext", "json"):
            parts.append(f'<label>{label}<textarea name="{name}" rows="3"{ph}{req}>{dv}</textarea>{hint}</label>')
        else:
            t = {"number": "number", "email": "email", "date": "date"}.get(inp["type"], "text")
            step = ' step="any"' if t == "number" else ""
            parts.append(f'<label>{label}<input type="{t}" name="{name}" value="{dv}"{ph}{step}{req}>{hint}</label>')
    submit = e(action["submit"] or action["label"])
    return (f'<form class="bw-plugin-form" data-bw-plugin-form="{plugin.slug}/{key}">' + "".join(parts)
            + f'<button type="submit" class="bw-btn">{submit}</button><div class="bw-plugin-status" role="status"></div>'
              f'<div class="bw-plugin-result" hidden></div></form>')


def fill_plugins(html, site):
    if "data-bw-plugin=" not in html:
        return html
    found = {p.slug: p for p in site.plugins.filter(enabled=True)}

    def one(m):
        p, key = found.get(m.group(2)), m.group(3)
        if not p or key not in (p.manifest.get("actions") or {}):
            body = '<p class="bw-plugin-status err">ไม่พบปลั๊กอินนี้</p>'
        elif plugin_setting(p, "access", key, "off") == "off":
            body = '<p class="bw-plugin-status">ฟอร์มนี้ยังไม่เปิดให้ผู้เข้าชมใช้ (ตั้งที่ ตรรกะ › ปลั๊กอิน)</p>'
        else:
            body = form_html(p, key)
        return m.group(1) + body + m.group(4)

    out = PLUGIN_RE.sub(one, html)
    return out.replace("</head>", PLUGIN_CSS + "</head>", 1) if "</head>" in out else PLUGIN_CSS + out


def has_public(site):
    return any(v != "off" for p in site.plugins.filter(enabled=True) for v in ((p.settings or {}).get("access") or {}).values())


def public_call(plugin, key, request, user, owner):
    """POST <site>/api/v1/plugins/<slug>/<action> from a page form."""
    if plugin is None or key not in (plugin.manifest.get("actions") or {}):
        raise PluginError("ไม่พบปลั๊กอินนี้", status=404, code="not_found")
    rule = plugin_setting(plugin, "access", key, "off")
    if not owner:
        if rule == "off":
            raise PluginError("คำสั่งนี้ไม่ได้เปิดให้ใช้จากหน้าเว็บ", status=403, code="forbidden")
        if rule == "user" and user is None:
            raise PluginError("ต้องเข้าสู่ระบบสมาชิกก่อน", status=401, code="login_required")
    action = plugin.manifest["actions"][key]
    if request.content_type == "application/json":
        try:
            values = json.loads(request.body or b"{}")
        except ValueError:
            raise PluginError("JSON ไม่ถูกต้อง")
        values = values if isinstance(values, dict) else {}
    else:
        values = {k: request.POST.get(k) for k in request.POST}
    files = {}
    for inp in action["inputs"]:
        f = request.FILES.get(inp["name"]) if inp["type"] == "file" else None
        if not f:
            continue
        if f.size > inp["max_mb"] * 1_000_000:
            raise PluginError(f"ไฟล์ “{inp['label']}” ใหญ่เกิน {inp['max_mb']} MB", status=413, fields={inp["name"]: "ไฟล์ใหญ่เกิน"})
        exts = [x.strip().lower() for x in (inp.get("accept") or "").split(",") if x.strip().startswith(".")]
        if exts and not any(f.name.lower().endswith(x) for x in exts):
            raise PluginError(f"ไฟล์ “{inp['label']}” ต้องเป็น {', '.join(exts)}", fields={inp["name"]: "ชนิดไฟล์ไม่ถูกต้อง"})
        files[inp["name"]] = (f.name, f.content_type or "application/octet-stream", f.read())
    return call(plugin, key, values, files, save=True, owner=owner)


# --- app ------------------------------------------------------------------------------------------

def to_json(p):
    conns = {c.plugin_sync: c for c in Connector.objects.filter(site=p.site, plugin=p.slug).select_related("collection")}
    m = p.manifest or {}
    return {
        "id": p.id, "name": p.name, "slug": p.slug, "kind": p.kind, "base_url": p.base_url, "headers": p.headers,
        "enabled": p.enabled, "description": m.get("description", ""), "links": m.get("links", []),
        "last_check": p.last_check.isoformat() if p.last_check else None, "last_ok": p.last_ok, "last_status": p.last_status,
        "manifest": m,
        "actions": [{"key": k, "label": a["label"], "description": a["description"], "method": a["method"], "path": a["path"],
                     "inputs": [{**i, "choices": options_for(p, i) if i["type"] == "select" else None} for i in a["inputs"]],
                     "access": plugin_setting(p, "access", k, "off"), "save": plugin_setting(p, "save", k),
                     "block": block_html(p, k)} for k, a in (m.get("actions") or {}).items()],
        "syncs": [{"key": k, "label": s["label"], "path": s["path"], "every": s["every"],
                   "connector": conns[k].id if k in conns else None,
                   "collection": conns[k].collection.slug if k in conns and conns[k].collection else "",
                   "last_run": conns[k].last_run.isoformat() if k in conns and conns[k].last_run else None,
                   "last_status": conns[k].last_status if k in conns else ""} for k, s in (m.get("syncs") or {}).items()],
    }
