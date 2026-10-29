"""A whole site in one file (.bwsite = zip): pages, shared sections, theme, collections with their rows,
files, members, API keys, webhooks, connectors, functions, jobs, form submissions and statistics.

Used for:
- backups (download, automatic daily copies) and restoring them        → import_site(mode="new" | "replace")
- moving a site to another machine                                     → import_site(mode="new")
- deploying to a BuildWeb server (server.py)                           → import_site(mode="deploy")

"deploy" updates the design and the content managed in the desktop app but keeps what is created on the
server: rows of server-data collections (forms, public/member writes), members, form submissions, stats.
Secrets travel decrypted inside the file (only when include_secrets) and are re-encrypted on arrival.
"""
import io
import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import services
from .models import (ApiKey, Asset, AssetFolder, Collection, Connector, FormSubmission, Function, Job, Page, Record,
                     SharedSection, Site, SiteUser, Stat, Webhook)

FORMAT = "buildweb-site"
SITE_FIELDS = ("name", "slug", "description", "language", "theme", "nav", "favicon", "head_code", "custom_css", "custom_js",
               "form_endpoint", "published", "use_base_styles", "base_url", "contact", "api", "auth", "shop")
PAGE_FIELDS = ("title", "slug", "is_home", "status", "show_in_nav", "use_header", "use_footer", "nav_label", "nav_order",
               "seo_title", "seo_description", "seo_keywords", "og_image", "noindex", "head_code", "body_class",
               "custom_css", "custom_js", "project_data", "html", "css", "js", "detail_field", "access",
               "access_rules")
SHARED_FIELDS = ("kind", "enabled", "managed", "project_data", "html", "css", "js")
COLLECTION_FIELDS = ("name", "slug", "fields", "mode", "source_database", "source_table", "live_order", "live_desc",
                     "live_limit", "options")


def _iso(dt):
    return dt.isoformat() if dt else None


def _dt(s):
    return parse_datetime(s) if s else None


def server_owned(col_data):
    """Rows of this collection are created on the live site (forms, public/member API writes): a deploy
    must not overwrite them. Collection.options["server"] overrides the guess."""
    opts = col_data.get("options") or {}
    if "server" in opts:
        return bool(opts["server"])
    api = opts.get("api") or {}
    return bool(opts.get("forms")) or api.get("create") in ("public", "user", "owner")


# --- export ---------------------------------------------------------------------------------------

def site_dict(site, include_secrets=True):
    from .crypto import decrypt, decrypt_dict

    d = {"format": FORMAT, "version": 1, "app": settings.VERSION, "created": timezone.now().isoformat(),
         "site": {f: getattr(site, f) for f in SITE_FIELDS}}
    pages = list(site.pages.select_related("parent", "collection"))
    d["pages"] = [{**{f: getattr(p, f) for f in PAGE_FIELDS}, "parent": p.parent.slug if p.parent else None,
                   "collection": p.collection.slug if p.collection else None} for p in pages]
    d["shared"] = [{f: getattr(s, f) for f in SHARED_FIELDS} for s in site.shared_sections.all()]
    d["collections"] = []
    for c in site.collections.select_related("connection"):
        conn = None
        if c.connection:
            conn = {"name": c.connection.name, "host": c.connection.host, "port": c.connection.port,
                    "user": c.connection.user, "database": c.connection.database, "socket": c.connection.socket,
                    "password": decrypt(c.connection.password) if include_secrets else ""}
        d["collections"].append({**{f: getattr(c, f) for f in COLLECTION_FIELDS}, "connection": conn,
                                 "records": [{"id": r.id, "data": r.data, "position": r.position, "approved": r.approved,
                                              "owner": r.owner.email if r.owner_id else None,
                                              "created_at": _iso(r.created_at)}
                                             for r in c.records.select_related("owner")]})
    d["assets"] = [{"file": a.file.name, "name": a.name, "folder": a.folder, "kind": a.kind, "size": a.size, "alt": a.alt}
                   for a in site.assets.all()]
    d["folders"] = list(site.folders.values_list("path", flat=True))
    d["members"] = [{"email": u.email, "name": u.name, "password": u.password, "role": u.role, "is_active": u.is_active,
                     "email_verified": u.email_verified, "profile": u.profile, "created_at": _iso(u.created_at),
                     "last_login": _iso(u.last_login)} for u in site.members.all()]
    d["api_keys"] = [{"name": k.name, "prefix": k.prefix, "key_hash": k.key_hash, "write": k.write,
                      "collections": k.collections, "revoked": k.revoked} for k in site.api_keys.all()]
    d["webhooks"] = [{"name": h.name, "url": h.url, "events": h.events, "collections": h.collections, "headers": h.headers,
                      "signing_secret": h.signing_secret if include_secrets else "", "active": h.active}
                     for h in site.webhooks.all()]
    d["connectors"] = [{"name": c.name, "url": c.url, "method": c.method, "headers": c.headers, "body": c.body,
                        "items_path": c.items_path, "collection": c.collection.slug if c.collection else None,
                        "key_field": c.key_field} for c in site.connectors.select_related("collection")]
    d["functions"] = [{"slug": f.slug, "name": f.name, "code": f.code, "access": f.access, "timeout": f.timeout,
                       "enabled": f.enabled} for f in site.functions.all()]
    d["jobs"] = [{"name": j.name, "schedule": j.schedule, "action": j.action, "params": j.params, "enabled": j.enabled}
                 for j in site.jobs.all()]
    d["submissions"] = [{"form_name": s.form_name, "page": s.page.slug if s.page else None, "data": s.data, "ip": s.ip,
                         "user_agent": s.user_agent, "is_read": s.is_read, "created_at": _iso(s.created_at)}
                        for s in site.submissions.select_related("page")]
    d["stats"] = list(site.stats.values("day", "kind", "key", "count"))
    for s in d["stats"]:
        s["day"] = s["day"].isoformat()
    if include_secrets:
        d["secrets"] = decrypt_dict(site.secrets)
    return d


def export_site(site, dest=None, include_secrets=True, include_media=True):
    """Write the site to ``dest`` (path or file object; a temp file when None). Returns the path/file."""
    if dest is None:
        dest = Path(tempfile.mkstemp(suffix=".bwsite")[1])
    d = site_dict(site, include_secrets)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("site.json", json.dumps(d, ensure_ascii=False, default=str))
        if include_media:
            for a in d["assets"]:
                p = settings.MEDIA_ROOT / a["file"]
                if p.is_file():
                    z.write(p, "media/" + a["file"])
    return dest


def export_bytes(site, include_secrets=True):
    buf = io.BytesIO()
    export_site(site, buf, include_secrets)
    return buf.getvalue()


def read_bundle(src):
    z = zipfile.ZipFile(src)
    try:
        d = json.loads(z.read("site.json"))
    except (KeyError, ValueError):
        raise ValueError("ไม่ใช่ไฟล์สำรองของ BuildWeb (.bwsite)")
    if d.get("format") != FORMAT:
        raise ValueError("ไม่ใช่ไฟล์สำรองของ BuildWeb (.bwsite)")
    return z, d


# --- import ---------------------------------------------------------------------------------------

def _safe_media_path(name):
    p = Path(name)
    if p.is_absolute() or ".." in p.parts or not name.startswith("sites/"):
        return None
    return p


def _write_media(z, d):
    names = set(z.namelist())
    for a in d.get("assets", []):
        rel = _safe_media_path(a["file"])
        if rel is None or ("media/" + a["file"]) not in names:
            continue
        target = settings.MEDIA_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with z.open("media/" + a["file"]) as src, open(target, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)


@transaction.atomic
def import_site(src, mode="new", slug=None):
    """mode: "new" (a copy next to existing sites), "replace" (restore: the site with the same slug is
    replaced), "deploy" (update the design, keep server-side data). Returns the Site."""
    from .crypto import encrypt, encrypt_dict

    z, d = read_bundle(src)
    sd = dict(d["site"])
    existing = Site.objects.filter(slug=slug or sd["slug"]).first()
    if mode == "replace" and existing:
        existing.delete()
        existing = None
    if mode == "deploy" and existing:
        site = existing
        for f in SITE_FIELDS:
            if f != "slug" and f in sd:
                setattr(site, f, sd[f])
    else:
        if mode == "new":
            sd["slug"] = services.unique_site_slug(slug or sd["slug"])
            if Site.objects.filter(name=sd["name"]).exists():
                sd["name"] = f"{sd['name']} (กู้คืน)"
        site = Site(**{f: sd[f] for f in SITE_FIELDS if f in sd})
    if "secrets" in d:
        site.secrets = encrypt_dict(d["secrets"])
    site.save()
    deploying = mode == "deploy" and existing is not None

    _write_media(z, d)
    # files
    site.assets.all().delete()
    site.folders.all().delete()
    Asset.objects.bulk_create([Asset(site=site, file=a["file"], name=a["name"], folder=a["folder"], kind=a["kind"],
                                     size=a["size"], alt=a.get("alt", "")) for a in d.get("assets", [])])
    AssetFolder.objects.bulk_create([AssetFolder(site=site, path=p) for p in d.get("folders", [])])

    # members (a deploy keeps the server's members and only adds new ones)
    have = set(site.members.values_list("email", flat=True)) if deploying else set()
    if not deploying:
        site.members.all().delete()
    SiteUser.objects.bulk_create([SiteUser(site=site, **{k: m[k] for k in ("email", "name", "password", "role", "is_active",
                                                                            "email_verified", "profile")},
                                           last_login=_dt(m.get("last_login")))
                                  for m in d.get("members", []) if m["email"] not in have])
    users = {u.email: u for u in site.members.all()}

    # collections
    keep = {}
    if deploying:
        for c in site.collections.all():
            keep[c.slug] = c
    wanted = {c["slug"] for c in d.get("collections", [])}
    for slug_, c in list(keep.items()):
        if slug_ not in wanted:
            c.delete()
            keep.pop(slug_)
    from .models import DataConnection

    cols, fresh = {}, set()
    for cd in d.get("collections", []):
        conn = None
        if cd.get("connection"):
            cc = cd["connection"]
            conn = DataConnection.objects.filter(host=cc["host"], port=cc["port"], user=cc["user"], name=cc["name"]).first()
            if not conn:
                conn = DataConnection.objects.create(name=cc["name"], host=cc["host"], port=cc["port"], user=cc["user"],
                                                     database=cc["database"], socket=cc.get("socket", ""),
                                                     password=encrypt(cc.get("password", "")))
        col = keep.get(cd["slug"])
        fields = {f: cd[f] for f in COLLECTION_FIELDS if f in cd}
        if col:
            for k, v in fields.items():
                setattr(col, k, v)
            col.connection = conn
            col.save()
        else:
            col = Collection.objects.create(site=site, connection=conn, **fields)
        cols[cd["slug"]] = col
        if deploying and server_owned(cd) and col.records.exists():
            continue  # rows created on the live site stay
        fresh.add(cd["slug"])
        col.records.all().delete()
        Record.objects.bulk_create([Record(collection=col, data=r["data"], position=r.get("position", 0),
                                           approved=r.get("approved", True), owner=users.get(r.get("owner")))
                                    for r in cd.get("records", [])], batch_size=500)
        # relation fields point at row ids: map old ids to the new ones
    _remap_relations(d, cols, fresh)

    # pages & shared sections
    site.pages.all().delete()
    created = {}
    for pd in d.get("pages", []):
        fields = {f: pd[f] for f in PAGE_FIELDS if f in pd}
        created[pd["slug"]] = Page.objects.create(site=site, collection=cols.get(pd.get("collection")), **fields)
    for pd in d.get("pages", []):
        if pd.get("parent") and pd["parent"] in created:
            p = created[pd["slug"]]
            p.parent = created[pd["parent"]]
            p.save(update_fields=["parent"])
    site.shared_sections.all().delete()
    SharedSection.objects.bulk_create([SharedSection(site=site, **{f: s[f] for f in SHARED_FIELDS}) for s in d.get("shared", [])])

    # API keys: same keys work everywhere the site runs
    known = {k.prefix: k for k in site.api_keys.all()} if deploying else {}
    if not deploying:
        site.api_keys.all().delete()
    for kd in d.get("api_keys", []):
        k = known.get(kd["prefix"]) or ApiKey(site=site, prefix=kd["prefix"])
        for f in ("name", "key_hash", "write", "collections", "revoked"):
            setattr(k, f, kd[f])
        k.save()

    # logic
    from . import logic

    site.webhooks.all().delete()
    Webhook.objects.bulk_create([Webhook(site=site, **h) for h in d.get("webhooks", [])])
    site.connectors.all().delete()
    Connector.objects.bulk_create([Connector(site=site, collection=cols.get(c.pop("collection", None)), **c)
                                   for c in [dict(x) for x in d.get("connectors", [])]])
    site.functions.all().delete()
    Function.objects.bulk_create([Function(site=site, **f) for f in d.get("functions", [])])
    site.jobs.all().delete()
    for jd in d.get("jobs", []):
        try:
            nxt = logic.next_run(jd["schedule"])
        except ValueError:
            nxt = None
        Job.objects.create(site=site, next_run=nxt, **jd)

    # data that belongs to the live site
    if not deploying:
        site.submissions.all().delete()
        FormSubmission.objects.bulk_create([FormSubmission(site=site, page=created.get(s.get("page")), form_name=s["form_name"],
                                                           data=s["data"], ip=s.get("ip", ""), user_agent=s.get("user_agent", ""),
                                                           is_read=s.get("is_read", False),
                                                           created_at=_dt(s.get("created_at")) or timezone.now())
                                            for s in d.get("submissions", [])])
        site.stats.all().delete()
        Stat.objects.bulk_create([Stat(site=site, day=datetime.fromisoformat(s["day"]).date(), kind=s["kind"], key=s["key"],
                                       count=s["count"]) for s in d.get("stats", [])])
    site.touch()
    return site


def _remap_relations(d, cols, fresh):
    """Relation fields store row ids, which change when rows are recreated."""
    idmap = {}
    for cd in d.get("collections", []):
        if cd["slug"] not in fresh:
            continue
        col = cols[cd["slug"]]
        new = list(col.records.order_by("id").values_list("id", flat=True))
        old = [r["id"] for r in cd.get("records", [])]
        if len(new) == len(old):
            idmap[cd["slug"]] = dict(zip(old, new))
    for cd in d.get("collections", []):
        if cd["slug"] not in fresh:
            continue
        rels = [f for f in cd["fields"] if f.get("type") == "relation" and f.get("relation") in idmap]
        if not rels:
            continue
        for rec in cols[cd["slug"]].records.all():
            changed = False
            for f in rels:
                v, m = rec.data.get(f["name"]), idmap[f["relation"]]
                if isinstance(v, list):
                    nv = [m.get(x, x) for x in v]
                elif isinstance(v, int):
                    nv = m.get(v, v)
                else:
                    continue
                if nv != v:
                    rec.data[f["name"]] = nv
                    changed = True
            if changed:
                rec.save(update_fields=["data"])


# --- automatic backups ----------------------------------------------------------------------------

KEEP = 14


def backup_dir(site):
    return settings.DATA_DIR / "backups" / site.slug


def auto_backup(site):
    folder = backup_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{site.slug}-{timezone.localtime():%Y%m%d-%H%M}.bwsite"
    export_site(site, path)
    for old in sorted(folder.glob("*.bwsite"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def list_backups(site):
    folder = backup_dir(site)
    if not folder.exists():
        return []
    return [{"name": p.name, "size": p.stat().st_size, "at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
            for p in sorted(folder.glob("*.bwsite"), reverse=True)]


def backup_all_due():
    """Called by the scheduler: one backup per site per day (when app.auto_backup is on)."""
    from buildweb import config

    if not config.load()["app"].get("auto_backup", True):
        return
    for site in Site.objects.all():
        latest = list_backups(site)
        if latest and (datetime.now() - datetime.fromisoformat(latest[0]["at"])).total_seconds() < 86400:
            continue
        try:
            auto_backup(site)
        except Exception:
            pass


@transaction.atomic
def apply_pull(site, d):
    """Replace the local copy of server-side data with what the server has (see server_api.pull)."""
    users = {}
    site.members.all().delete()
    for m in d.get("members", []):
        users[m["email"]] = SiteUser.objects.create(site=site, **{k: m[k] for k in ("email", "name", "password", "role", "is_active",
                                                                                     "email_verified", "profile")},
                                                    last_login=_dt(m.get("last_login")))
    rows = 0
    for slug, records in (d.get("collections") or {}).items():
        col = site.collections.filter(slug=slug).first()
        if not col:
            continue
        col.records.all().delete()
        Record.objects.bulk_create([Record(collection=col, data=r["data"], position=r.get("position", 0),
                                           approved=r.get("approved", True), owner=users.get(r.get("owner")))
                                    for r in records], batch_size=500)
        rows += len(records)
    pages = {p.slug: p for p in site.pages.all()}
    site.submissions.all().delete()
    FormSubmission.objects.bulk_create([FormSubmission(site=site, page=pages.get(s.get("page")), form_name=s["form_name"],
                                                       data=s["data"], ip=s.get("ip", ""), user_agent=s.get("user_agent", ""),
                                                       is_read=s.get("is_read", False),
                                                       created_at=_dt(s.get("created_at")) or timezone.now())
                                        for s in d.get("submissions", [])])
    site.stats.all().delete()
    Stat.objects.bulk_create([Stat(site=site, day=datetime.fromisoformat(s["day"]).date(), kind=s["kind"], key=s["key"],
                                   count=s["count"]) for s in d.get("stats", [])])
    return {"rows": rows, "members": len(users), "submissions": len(d.get("submissions", []))}
