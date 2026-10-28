"""The REST API of a site's collections, served at <site>/api/v1/ by the hosting server (and by the in-app
preview, where requests count as the site owner unless they send ``X-BW-As: public``).

  GET    api/v1/                       list of collections you can read
  GET    api/v1/openapi.json           OpenAPI 3.1 description (Swagger, Postman, code generators)
  GET    api/v1/<collection>           ?page=1&per_page=20&sort=-price,name&q=latte&filter=price>50;category=coffee
                                       &<field>=<value>&expand=author&fields=name,price
  POST   api/v1/<collection>           create (JSON or form data) → 201
  GET    api/v1/<collection>/<_id>
  PATCH  api/v1/<collection>/<_id>     change some fields;  PUT replaces the row
  DELETE api/v1/<collection>/<_id>     → 204

Access per collection and action (Collection.options["api"]): "public" (anyone), "key" (an API key, sent as
`X-API-Key: bw_…` or `Authorization: Bearer bw_…`) or "off" (only the owner, in the app). The whole API is
off until it is enabled for the site (Site.api["enabled"]). Errors are JSON:
{"error": {"code": "...", "message": "...", "fields": {...}}}.
"""
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time

from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from . import data, schema
from .models import ApiKey, ApiLog, Collection, Record

ACTIONS = ("list", "view", "create", "update", "delete")
WRITE_ACTIONS = {"create", "update", "delete"}
RULES = ("public", "key", "off")
DEFAULT_RULES = {"list": "public", "view": "public", "create": "key", "update": "key", "delete": "key"}
SITE_DEFAULTS = {"enabled": False, "cors": "*", "rate": 120, "log": True}
MAX_PER_PAGE = 200

_rate = {}
_rate_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, code, message, fields=None):
        super().__init__(message)
        self.status, self.code, self.fields = status, code, fields


def site_settings(site):
    return {**SITE_DEFAULTS, **(site.api or {})}


def rules(col):
    r = dict(DEFAULT_RULES)
    r.update({k: v for k, v in ((col.options or {}).get("api") or {}).items() if k in ACTIONS and v in RULES})
    return r


# --- keys -----------------------------------------------------------------------------------------

def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(site, name, write=False, collections=None):
    """Returns (ApiKey, plain key). The plain key is not stored anywhere."""
    plain = "bw_" + secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")
    key = ApiKey.objects.create(site=site, name=(name or "API key")[:100], prefix=plain[:12], key_hash=hash_key(plain),
                                write=bool(write), collections=list(collections or []))
    return key, plain


def find_key(request, site):
    """The ApiKey sent with the request, None when none was sent. A wrong key is an error, not "no key"."""
    plain = request.META.get("HTTP_X_API_KEY", "").strip()
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not plain and auth.lower().startswith("bearer "):
        plain = auth[7:].strip()
    if not plain:
        return None
    digest = hash_key(plain)
    for key in ApiKey.objects.filter(site=site, prefix=plain[:12], revoked=False):
        if hmac.compare_digest(key.key_hash, digest):
            if not key.last_used or (timezone.now() - key.last_used).total_seconds() > 60:
                ApiKey.objects.filter(pk=key.pk).update(last_used=timezone.now())
            return key
    raise ApiError(401, "invalid_key", "API key ไม่ถูกต้องหรือถูกยกเลิกแล้ว")


# --- request handling -----------------------------------------------------------------------------

def is_owner(request):
    """Requests through the in-app preview (127.0.0.1 only) are the site owner, unless they ask to be treated
    as the public (the API playground does that to show what visitors get)."""
    return not getattr(request, "is_public", False) and request.META.get("HTTP_X_BW_AS", "").lower() != "public"


def client_ip(request):
    return (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()


def check_rate(site, request, key, limit):
    if not limit:
        return
    ident = (site.id, f"k{key.id}" if key else client_ip(request))
    limit = limit * 5 if key else limit
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate.get(ident, []) if now - t < 60]
        if len(hits) >= limit:
            _rate[ident] = hits
            raise ApiError(429, "rate_limited", f"เรียกเกิน {limit} ครั้งต่อนาที กรุณารอสักครู่")
        hits.append(now)
        _rate[ident] = hits
        if len(_rate) > 10000:
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 60]:
                _rate.pop(k, None)


def cors(resp, site, request):
    allowed = str(site_settings(site).get("cors") or "").strip()
    origin = request.META.get("HTTP_ORIGIN", "")
    if allowed == "*":
        resp["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in [o.strip().rstrip("/") for o in re.split(r"[,\s]+", allowed) if o.strip()]:
        resp["Access-Control-Allow-Origin"] = origin
        resp["Vary"] = "Origin"
    resp["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    resp["Access-Control-Max-Age"] = "600"
    return resp


def error_response(e):
    body = {"error": {"code": e.code, "message": str(e)}}
    if e.fields:
        body["error"]["fields"] = e.fields
    return JsonResponse(body, status=e.status, json_dumps_params={"ensure_ascii": False})


def handle(request, site, path, base_url=""):
    """Entry point from public.serve for paths under api/."""
    started = time.time()
    key, status, err = None, 500, ""
    owner = is_owner(request)
    try:
        if request.method == "OPTIONS":
            resp = HttpResponse(status=204)
            status = 204
            return cors(resp, site, request)
        cfg = site_settings(site)
        if not cfg["enabled"] and not owner:
            raise ApiError(404, "api_disabled", "API ของเว็บนี้ยังไม่ได้เปิดใช้งาน")
        key = find_key(request, site)
        if not owner:
            check_rate(site, request, key, int(cfg.get("rate") or 0))
        resp = route(request, site, path.strip("/"), key, owner, base_url)
        status = resp.status_code
    except ApiError as e:
        resp, status, err = error_response(e), e.status, str(e)
    except schema.ValidationError as e:
        resp = error_response(ApiError(422, "validation", "ข้อมูลไม่ถูกต้อง", e.fields))
        status, err = 422, str(e)[:300]
    except RuntimeError as e:  # live MySQL down etc.
        resp = error_response(ApiError(503, "unavailable", str(e)))
        status, err = 503, str(e)[:300]
    if site_settings(site).get("log", True):
        log(site, request, status, started, key, err)
    return cors(resp, site, request)


_log_count = [0]


def log(site, request, status, started, key, err):
    try:
        ApiLog.objects.create(site=site, method=request.method[:8], path=request.get_full_path()[:300], status=status,
                              ms=int((time.time() - started) * 1000), key=key, ip=client_ip(request)[:64],
                              error=err[:300])
        _log_count[0] += 1
        if _log_count[0] % 200 == 0:  # keep the table small: 30 days or the last 5000 calls per site
            cutoff = timezone.now() - timezone.timedelta(days=30)
            ApiLog.objects.filter(site=site, at__lt=cutoff).delete()
            old = ApiLog.objects.filter(site=site).values_list("id", flat=True)[5000:]
            ApiLog.objects.filter(id__in=list(old[:5000])).delete()
    except Exception:
        pass


def route(request, site, path, key, owner, base_url):
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] != "v1":
        raise ApiError(404, "not_found", "ใช้ /api/v1/")
    parts = parts[1:]
    if not parts:
        return ok({"site": site.name, "version": "v1",
                   "collections": [collection_info(c, request, key, owner) for c in site.collections.all()
                                   if owner or allowed(c, "list", key, owner, quiet=True)]})
    if parts == ["openapi.json"]:
        return JsonResponse(openapi(site, base_url, owner), json_dumps_params={"ensure_ascii": False, "indent": 2})
    col = site.collections.select_related("connection").filter(slug=parts[0]).first()
    if not col:
        raise ApiError(404, "not_found", f"ไม่พบชุดข้อมูล “{parts[0]}”")
    if len(parts) == 1:
        if request.method == "GET":
            allowed(col, "list", key, owner)
            return list_rows(request, col, key, owner)
        if request.method == "POST":
            who = allowed(col, "create", key, owner)
            return create_row(request, col, who)
        raise ApiError(405, "method_not_allowed", "ใช้ GET หรือ POST")
    if len(parts) == 2:
        rid = parts[1]
        if request.method == "GET":
            allowed(col, "view", key, owner)
            return ok(item(col, get_row(col, rid, owner), owner, expand_set(request), fields_set(request), key))
        if request.method in ("PATCH", "PUT"):
            allowed(col, "update", key, owner)
            return update_row(request, col, rid, owner, partial=request.method == "PATCH")
        if request.method == "DELETE":
            allowed(col, "delete", key, owner)
            delete_row(col, rid, owner)
            return HttpResponse(status=204)
        raise ApiError(405, "method_not_allowed", "ใช้ GET, PATCH, PUT หรือ DELETE")
    raise ApiError(404, "not_found", "ไม่พบ endpoint นี้")


def ok(body, status=200):
    return JsonResponse(body, status=status, safe=False, json_dumps_params={"ensure_ascii": False})


def allowed(col, action, key, owner, quiet=False):
    """Raise unless the request may do ``action``; returns "owner", "key" or "public"."""
    if owner:
        return "owner"
    rule = rules(col)[action]
    write = action in WRITE_ACTIONS
    if rule == "public":  # a limited key never takes public access away
        return "key" if key and key.allows(col.slug, write) else "public"
    if rule == "key":
        if key and key.allows(col.slug, write):
            return "key"
        if quiet:
            return None
        if not key:
            raise ApiError(401, "key_required", "ต้องใช้ API key (ส่งใน header X-API-Key)")
        raise ApiError(403, "forbidden", "API key นี้ไม่มีสิทธิ์" + ("เขียน" if write else "อ่าน") + f"ชุดข้อมูล “{col.slug}”")
    if quiet:
        return None
    raise ApiError(403, "forbidden", f"ปิดการ{ {'list': 'อ่าน', 'view': 'อ่าน', 'create': 'เพิ่ม', 'update': 'แก้ไข', 'delete': 'ลบ'}[action]}ข้อมูลผ่าน API")


def collection_info(c, request, key, owner):
    r = rules(c)
    return {"slug": c.slug, "name": c.name, "mode": c.mode,
            "fields": [public_field(f) for f in c.fields if owner or not f.get("hidden")],
            "access": r}


def public_field(f):
    return {k: v for k, v in f.items() if k != "source"}


# --- reading --------------------------------------------------------------------------------------

def expand_set(request):
    return {x.strip() for x in request.GET.get("expand", "").split(",") if x.strip()}


def fields_set(request):
    return {x.strip() for x in request.GET.get("fields", "").split(",") if x.strip()}


def live_pk(col):
    """Field name holding the primary key of a live collection's table."""
    pk = data.primary_key(col)
    by_source = {f.get("source", f["name"]): f["name"] for f in col.fields}
    if not pk:
        raise ApiError(409, "no_primary_key", "ตารางนี้ไม่มี primary key จึงอ้างถึงแถวทีละแถวไม่ได้")
    return by_source.get(pk, data.field_key(pk)), pk


def all_rows(col, owner):
    """[(id, row dict, record or None)] in display order."""
    if col.mode == Collection.LIVE:
        name, _ = live_pk(col) if data.primary_key(col) else (None, None)
        return [(r.get(name) if name else i + 1, r, None) for i, r in enumerate(data.rows_for(col))]
    qs = col.records.all() if owner else col.records.filter(approved=True)
    return [(r.id, r.data, r) for r in qs]


def item(col, entry, owner, expand=(), only=(), key=None, _depth=0):
    rid, row, rec = entry
    out = {"_id": rid}
    for f in col.fields:
        if f.get("hidden") and not owner:
            continue
        if only and f["name"] not in only:
            continue
        v = row.get(f["name"], "")
        if f.get("type") == "relation" and f["name"] in expand and _depth == 0 and not _empty_rel(v):
            v = expand_relation(col, f, v, owner, key)
        out[f["name"]] = v
    if rec is not None:
        out["_created"] = rec.created_at.isoformat(timespec="seconds")
        out["_updated"] = rec.updated_at.isoformat(timespec="seconds")
        if owner:
            out["_approved"] = rec.approved
    return out


def _empty_rel(v):
    return v in ("", None, [])


def expand_relation(col, f, value, owner, key):
    target = col.site.collections.filter(slug=f.get("relation")).first()
    if not target or target.mode != Collection.COPY:
        return value
    try:
        allowed(target, "view", key, owner)
    except ApiError:
        return value  # no right to read the target: keep the ids
    ids = value if isinstance(value, list) else [value]
    qs = target.records.filter(pk__in=ids) if owner else target.records.filter(pk__in=ids, approved=True)
    by_id = {r.id: item(target, (r.id, r.data, r), owner, _depth=1) for r in qs}
    if isinstance(value, list):
        return [by_id[i] for i in ids if i in by_id]
    return by_id.get(value, value)


def sort_rows(entries, spec):
    for part in reversed([p.strip() for p in spec.split(",") if p.strip()]):
        desc = part.startswith("-")
        name = part.lstrip("-+")

        def k(e, name=name):
            v = e[0] if name == "_id" else e[1].get(name, "")
            try:
                return (0, float(v), "")
            except (TypeError, ValueError):
                return (1, 0, str(v).lower())

        entries = sorted(entries, key=k, reverse=desc)
    return entries


def list_rows(request, col, key, owner):
    g = request.GET
    entries = all_rows(col, owner)
    names = set(col.field_names)
    hidden = {f["name"] for f in col.fields if f.get("hidden")} if not owner else set()
    for name, value in g.items():  # ?category=coffee
        if name in names and name not in hidden:
            entries = [e for e in entries if str(e[1].get(name, "")).lower() == value.lower()]
    if g.get("filter"):
        keep = {id(r) for r in data.filter_rows([e[1] for e in entries], g["filter"], blocked=hidden)}
        entries = [e for e in entries if id(e[1]) in keep]
    if g.get("q"):
        q = g["q"].lower()
        entries = [e for e in entries if any(q in str(v).lower() for k, v in e[1].items() if k not in hidden)]
    if g.get("sort"):
        entries = sort_rows(entries, g["sort"])
    try:
        per = max(1, min(MAX_PER_PAGE, int(g.get("per_page") or 20)))
        page = max(1, int(g.get("page") or 1))
    except ValueError:
        raise ApiError(400, "bad_request", "page และ per_page ต้องเป็นตัวเลข")
    total = len(entries)
    chunk = entries[(page - 1) * per: page * per]
    exp, only = expand_set(request), fields_set(request)
    return ok({"items": [item(col, e, owner, exp, only, key) for e in chunk], "page": page, "per_page": per,
               "total": total, "total_pages": max(1, math.ceil(total / per))})


def get_row(col, rid, owner):
    if col.mode == Collection.LIVE:
        live_pk(col)  # raises when rows can't be addressed
        for e in all_rows(col, owner):
            if str(e[0]) == str(rid):
                return e
        raise ApiError(404, "not_found", f"ไม่พบแถว _id {rid}")
    try:
        rec = col.records.get(pk=int(rid), **({} if owner else {"approved": True}))
    except (ValueError, Record.DoesNotExist):
        raise ApiError(404, "not_found", f"ไม่พบแถว _id {rid}")
    return rec.id, rec.data, rec


# --- writing --------------------------------------------------------------------------------------

def body(request):
    if request.content_type == "application/json":
        try:
            d = json.loads(request.body or b"{}")
        except ValueError:
            raise ApiError(400, "bad_json", "JSON ไม่ถูกต้อง")
        if not isinstance(d, dict):
            raise ApiError(400, "bad_json", "ต้องส่งเป็น JSON object")
        return d
    return {k: (v[0] if len(v) == 1 else v) for k, v in request.POST.lists()}


def create_row(request, col, who):
    d = body(request)
    clean = schema.full_validate(col, d)
    if col.mode == Collection.LIVE:
        approved = who != "public" or col.opt("auto_approve") or not col.opt("forms")
        new_id = data.live_insert(col, clean, approved)
        data.invalidate(col)
        return ok({"_id": new_id, **{k: v for k, v in clean.items()}}, 201)
    # Public posts to a moderated collection wait for approval, like the site's forms.
    approved = who != "public" or not col.opt("forms") or col.opt("auto_approve")
    pos = (col.records.aggregate(m=Max("position"))["m"] or 0) + 1
    rec = Record.objects.create(collection=col, data={f["name"]: clean.get(f["name"], "") for f in col.fields},
                                position=pos, approved=approved)
    col.save(update_fields=["updated_at"])
    return ok(item(col, (rec.id, rec.data, rec), who == "owner"), 201)


def update_row(request, col, rid, owner, partial):
    d = body(request)
    if col.mode == Collection.LIVE:
        _, row, _ = get_row(col, rid, owner)
        clean = schema.full_validate(col, d, partial=partial, current=row)
        data.live_update(col, rid, clean)
        data.invalidate(col)
        return ok({"_id": rid, **{**row, **clean}})
    rid_, row, rec = get_row(col, rid, True)
    clean = schema.full_validate(col, d, partial=partial, current=row, exclude_id=rec.id)
    rec.data = {**rec.data, **clean} if partial else {f["name"]: clean.get(f["name"], "") for f in col.fields}
    rec.save()
    col.save(update_fields=["updated_at"])
    return ok(item(col, (rec.id, rec.data, rec), owner))


def delete_row(col, rid, owner):
    if col.mode == Collection.LIVE:
        get_row(col, rid, owner)
        data.live_delete(col, rid)
        data.invalidate(col)
        return
    _, _, rec = get_row(col, rid, True)
    rec.delete()
    col.save(update_fields=["updated_at"])


# --- OpenAPI --------------------------------------------------------------------------------------

JSON_TYPES = {"number": {"type": "number"}, "bool": {"type": "boolean"}, "date": {"type": "string", "format": "date"},
              "datetime": {"type": "string", "format": "date-time"}, "email": {"type": "string", "format": "email"},
              "link": {"type": "string", "format": "uri"}, "image": {"type": "string"}, "json": {}}


def field_schema(f):
    if f.get("type") == "relation":
        s = {"type": "array", "items": {"type": "integer"}} if f.get("multiple") else {"type": "integer"}
        s["description"] = f"_id ของ {f.get('relation')} (ใช้ ?expand={f['name']} เพื่อดึงทั้งแถว)"
    elif f.get("type") == "select":
        s = {"type": "string", "enum": f.get("options") or []}
    else:
        s = dict(JSON_TYPES.get(f.get("type"), {"type": "string"}))
    s["title"] = f.get("label") or f["name"]
    if "default" in f:
        s["default"] = f["default"]
    if f.get("pattern"):
        s["pattern"] = f["pattern"]
    for k, nk in (("min", "minimum"), ("max", "maximum")):
        if f.get(k) is not None:
            s[nk if f.get("type") == "number" else ("minLength" if k == "min" else "maxLength")] = f[k]
    return s


def openapi(site, base_url="", owner=False):
    paths, schemas = {}, {}
    err = {"$ref": "#/components/schemas/Error"}
    for c in site.collections.all():
        r = rules(c)
        if not owner and all(v == "off" for v in r.values()):
            continue
        name = re.sub(r"\W", "_", c.slug).title().replace("_", "")
        fields = [f for f in c.fields if owner or not f.get("hidden")]
        props = {"_id": {"type": "integer" if c.mode == Collection.COPY else "string", "readOnly": True}}
        props.update({f["name"]: field_schema(f) for f in fields})
        if c.mode == Collection.COPY:
            props["_created"] = {"type": "string", "format": "date-time", "readOnly": True}
            props["_updated"] = {"type": "string", "format": "date-time", "readOnly": True}
        schemas[name] = {"type": "object", "title": c.name, "properties": props,
                         "required": [f["name"] for f in fields if f.get("required")]}
        ref = {"$ref": f"#/components/schemas/{name}"}

        def sec(action):
            return [{"ApiKey": []}, {"Bearer": []}] if r[action] == "key" else []

        def op(action, summary, extra):
            if r[action] == "off" and not owner:
                return None
            return {"tags": [c.name], "summary": summary, "security": sec(action),
                    "responses": {**extra, "401": {"description": "ต้องใช้ API key", "content": {"application/json": {"schema": err}}},
                                  "429": {"description": "เรียกถี่เกินไป"}}}
        coll, one = {}, {}
        lst = op("list", f"รายการ {c.name}", {"200": {"description": "OK", "content": {"application/json": {"schema": {
            "type": "object", "properties": {"items": {"type": "array", "items": ref}, "page": {"type": "integer"},
                                             "per_page": {"type": "integer"}, "total": {"type": "integer"},
                                             "total_pages": {"type": "integer"}}}}}}})
        if lst:
            lst["parameters"] = [
                {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": MAX_PER_PAGE}},
                {"name": "sort", "in": "query", "schema": {"type": "string"}, "description": "เช่น -price,name"},
                {"name": "q", "in": "query", "schema": {"type": "string"}, "description": "ค้นหาทุกฟิลด์"},
                {"name": "filter", "in": "query", "schema": {"type": "string"}, "description": "เช่น price>50;category=coffee"},
                {"name": "expand", "in": "query", "schema": {"type": "string"}, "description": "ฟิลด์ relation ที่จะดึงทั้งแถว"},
                {"name": "fields", "in": "query", "schema": {"type": "string"}, "description": "เลือกฟิลด์ที่ต้องการ"},
            ]
            coll["get"] = lst
        cr = op("create", f"เพิ่ม {c.name}", {"201": {"description": "สร้างแล้ว", "content": {"application/json": {"schema": ref}}},
                                               "422": {"description": "ข้อมูลไม่ถูกต้อง", "content": {"application/json": {"schema": err}}}})
        if cr:
            cr["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref}}}
            coll["post"] = cr
        idp = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
        for action, method, summary, resp in (("view", "get", "ดูหนึ่งแถว", {"200": {"description": "OK", "content": {"application/json": {"schema": ref}}}}),
                                              ("update", "patch", "แก้ไขบางฟิลด์", {"200": {"description": "OK", "content": {"application/json": {"schema": ref}}}}),
                                              ("delete", "delete", "ลบ", {"204": {"description": "ลบแล้ว"}})):
            o = op(action, f"{summary} · {c.name}", {**resp, "404": {"description": "ไม่พบ"}})
            if o:
                o["parameters"] = idp
                if method == "patch":
                    o["requestBody"] = {"content": {"application/json": {"schema": ref}}}
                one[method] = o
        if coll:
            paths[f"/{c.slug}"] = coll
        if one:
            paths[f"/{c.slug}/{{id}}"] = one
    schemas["Error"] = {"type": "object", "properties": {"error": {"type": "object", "properties": {
        "code": {"type": "string"}, "message": {"type": "string"}, "fields": {"type": "object"}}}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{site.name} API", "version": "1", "description": f"REST API ของ {site.name} (สร้างโดย BuildWeb)"},
        "servers": [{"url": (base_url.rstrip("/") + "/api/v1") if base_url else "api/v1"}],
        "paths": paths,
        "components": {"schemas": schemas, "securitySchemes": {
            "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "Bearer": {"type": "http", "scheme": "bearer"}}},
    }
