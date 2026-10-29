"""Versions of a site ("1.4.0" + release notes).

A release is a .bwsite snapshot in <data>/releases/<site id>/. It can be
- deployed to any publish target, now or at a scheduled time (the scheduler calls run_due()). Static targets
  (GitHub/Netlify/FTP) get files built from the snapshot, not from the site as it is being edited now;
  BuildWeb servers (production "server", "staging") get the snapshot itself, so their own data stays;
- compared with the previous version or with the site as it is now (diff());
- restored in the app (design and content back to that version, data from forms/orders/members kept);
- redeployed later, which is the rollback: deploy an older version to production again.
"""
import json
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import backup
from .models import Release

VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+][\w.]+)?$")
NAME_RE = re.compile(r"^[\w.+-]{1,40}$")
PAGE_KEYS = ("title", "status", "html", "css", "js", "seo_title", "seo_description", "seo_keywords", "og_image", "noindex",
             "head_code", "custom_css", "custom_js", "show_in_nav", "nav_label", "nav_order", "access", "access_rules", "is_home", "detail_field")
SITE_KEYS = [f for f in backup.SITE_FIELDS if f != "slug"]


class ReleaseError(Exception):
    pass


def release_dir(site):
    return settings.DATA_DIR / "releases" / str(site.id)


def path_of(release):
    return settings.DATA_DIR / "releases" / release.file


def suggest(site):
    """The next version numbers after the latest one that looks like x.y.z."""
    for r in site.releases.all()[:20]:
        m = VERSION_RE.match(r.version)
        if m:
            a, b, c = map(int, m.groups())
            return {"patch": f"{a}.{b}.{c + 1}", "minor": f"{a}.{b + 1}.0", "major": f"{a + 1}.0.0", "latest": r.version}
    return {"patch": "1.0.0", "minor": "1.0.0", "major": "1.0.0", "latest": None}


# --- comparing ------------------------------------------------------------------------------------

def _norm(d):
    return json.loads(json.dumps(d, ensure_ascii=False, default=str))


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def bundle_of(release):
    z, d = backup.read_bundle(path_of(release))
    z.close()
    return d


def current_of(site):
    return _norm(backup.site_dict(site, include_secrets=False))


def diff(old, new):
    """What changed from bundle dict ``old`` (None = nothing before) to ``new``."""
    old = old or {"site": {}, "pages": [], "collections": [], "assets": [], "shared": [], "functions": [], "jobs": [],
                  "webhooks": [], "connectors": []}
    op, np_ = {p["slug"]: p for p in old["pages"]}, {p["slug"]: p for p in new["pages"]}
    page = lambda p: {"slug": p["slug"], "title": p.get("title") or p["slug"]}  # noqa: E731
    pages = {"added": [page(np_[s]) for s in np_ if s not in op],
             "removed": [page(op[s]) for s in op if s not in np_],
             "changed": [page(np_[s]) for s in np_ if s in op and any(not _same(op[s].get(k), np_[s].get(k)) for k in PAGE_KEYS)]}
    oc, nc = {c["slug"]: c for c in old["collections"]}, {c["slug"]: c for c in new["collections"]}
    changed = []
    for s, c in nc.items():
        if s not in oc:
            continue
        o, notes = oc[s], []
        if not _same(o.get("fields"), c.get("fields")) or not _same(o.get("options"), c.get("options")):
            notes.append("โครงสร้าง")
        if not backup.server_owned(c):  # rows of server-data collections belong to the live site, not to versions
            rows = lambda x: [r["data"] for r in x.get("records", [])]  # noqa: E731
            if not _same(rows(o), rows(c)):
                a, b = len(o.get("records", [])), len(c.get("records", []))
                notes.append(f"ข้อมูล {a}→{b} แถว" if a != b else "แก้ข้อมูล")
        if notes:
            changed.append({"slug": s, "name": c.get("name") or s, "what": notes})
    collections = {"added": [{"slug": s, "name": nc[s].get("name") or s} for s in nc if s not in oc],
                   "removed": [{"slug": s, "name": oc[s].get("name") or s} for s in oc if s not in nc], "changed": changed}
    labels = {"name": "ชื่อเว็บ", "theme": "ธีม", "nav": "แถบเมนู", "custom_css": "CSS ทุกหน้า", "custom_js": "JavaScript ทุกหน้า",
              "head_code": "โค้ดใน <head>", "favicon": "ไอคอนเว็บ", "contact": "ปุ่มติดต่อ", "api": "REST API", "auth": "สมาชิก",
              "shop": "ร้านค้า", "base_url": "ที่อยู่เว็บ", "published": "การเผยแพร่", "description": "คำอธิบาย", "language": "ภาษา"}
    site_changes = [labels.get(k, k) for k in SITE_KEYS if not _same(old["site"].get(k), new["site"].get(k)) and old["site"]]
    if not _same(old.get("shared"), new.get("shared")):
        site_changes.append("ส่วนหัว/ส่วนท้าย")
    strip = lambda hooks: [{k: v for k, v in h.items() if k != "signing_secret"} for h in hooks or []]  # noqa: E731
    for key, label in (("functions", "ฟังก์ชัน"), ("jobs", "งานตั้งเวลา"), ("connectors", "ตัวเชื่อม API")):
        if not _same(old.get(key), new.get(key)):
            site_changes.append(label)
    if not _same(strip(old.get("webhooks")), strip(new.get("webhooks"))):
        site_changes.append("webhooks")
    of, nf = {a["file"] for a in old.get("assets", [])}, {a["file"] for a in new.get("assets", [])}
    out = {"pages": pages, "collections": collections, "settings": site_changes,
           "assets": {"added": len(nf - of), "removed": len(of - nf)}}
    out["total"] = (sum(len(v) for v in pages.values()) + sum(len(v) for v in collections.values()) + len(site_changes)
                    + out["assets"]["added"] + out["assets"]["removed"])
    return out


# --- creating & listing ---------------------------------------------------------------------------

def create(site, version, notes="", user=""):
    version = (version or "").strip()
    if not NAME_RE.match(version):
        raise ReleaseError("เลขเวอร์ชันใช้ตัวเลข ตัวอักษร . - + ได้ไม่เกิน 40 ตัว เช่น 1.2.0")
    if site.releases.filter(version=version).exists():
        raise ReleaseError(f"มีเวอร์ชัน {version} แล้ว")
    prev = site.releases.first()
    folder = release_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", version)
    name = f"{site.id}/{safe}-{timezone.localtime():%Y%m%d-%H%M%S}.bwsite"
    path = settings.DATA_DIR / "releases" / name
    backup.export_site(site, path)
    z, now = backup.read_bundle(path)
    z.close()
    try:
        before = bundle_of(prev) if prev else None
    except (OSError, ValueError):
        before = None
    summary = diff(before, now) if prev else {"first": True, "total": 0, "pages_count": len(now["pages"]),
                                              "collections_count": len(now["collections"])}
    return Release.objects.create(site=site, version=version, notes=(notes or "").strip()[:5000], file=name,
                                  size=path.stat().st_size, summary=summary, created_by=user[:150])


def to_json(r):
    return {"id": r.id, "version": r.version, "notes": r.notes, "size": r.size, "summary": r.summary,
            "created_at": r.created_at.isoformat(), "created_by": r.created_by,
            "scheduled_at": timezone.localtime(r.scheduled_at).isoformat() if r.scheduled_at else None,
            "scheduled_targets": r.scheduled_targets, "deploys": r.deploys[-20:]}


def live_versions(site):
    """{target: version} of what each publish target got last."""
    out = {}
    for target, cfg in (site.publish or {}).items():
        last = (cfg or {}).get("last") if isinstance(cfg, dict) else None
        if last and last.get("ok"):
            out[target] = last.get("version") or ""
    return out


def delete(release):
    path_of(release).unlink(missing_ok=True)
    release.delete()


def record(release, target, ok, message=""):
    r = Release.objects.filter(pk=release.pk).first()
    if not r:
        return
    r.deploys = (r.deploys or [])[-49:] + [{"target": target, "at": timezone.localtime().isoformat(timespec="seconds"),
                                            "ok": ok, "message": str(message)[:300]}]
    r.save(update_fields=["deploys"])


# --- using a snapshot -----------------------------------------------------------------------------

class _Undo(Exception):
    pass


def files_of(release):
    """The static files of the snapshot ({path: bytes}), built from a copy imported inside a transaction that is
    rolled back, so nothing of it stays in the database."""
    from .models import Site
    from .publish import site_files

    out = {}
    try:
        with transaction.atomic():
            tmp = backup.import_site(path_of(release), mode="new", slug=f"bw-release-{release.id}")
            name = bundle_of(release)["site"]["name"]
            Site.objects.filter(pk=tmp.pk).update(name=name)
            tmp.name = name
            out = site_files(tmp)
            raise _Undo
    except _Undo:
        pass
    return out


def restore(release):
    """Bring the site in the app back to this version. Rows created by the live site (server-data collections),
    members, form messages and statistics stay; a backup of the current state is taken first."""
    site = release.site
    backup.auto_backup(site)
    publish, base_url = site.publish, site.base_url
    site = backup.import_site(path_of(release), mode="deploy")
    site.publish, site.base_url = publish, base_url or site.base_url  # where it is published is not part of a version
    site.save(update_fields=["publish", "base_url"])
    return site


# --- scheduling -----------------------------------------------------------------------------------

def schedule(release, when, targets):
    from .publish import RUNNERS

    targets = [t for t in targets if t in RUNNERS]
    if not targets:
        raise ReleaseError("เลือกปลายทางอย่างน้อยหนึ่งที่")
    if when <= timezone.now():
        raise ReleaseError("เวลาต้องอยู่ในอนาคต")
    release.scheduled_at, release.scheduled_targets = when, targets
    release.save(update_fields=["scheduled_at", "scheduled_targets"])


def run_due():
    """Deploy releases whose time has come (called by the scheduler every 30 s)."""
    from . import notify, publish

    for r in Release.objects.select_related("site").filter(scheduled_at__lte=timezone.now()):
        targets, r.scheduled_at, r.scheduled_targets = r.scheduled_targets, None, []
        r.save(update_fields=["scheduled_at", "scheduled_targets"])
        for t in targets:
            label = publish.LABELS.get(t, t)
            try:
                res = publish.run(r.site, t, release=r)
                notify.notify_text(r.site.name, f"🚀 ปล่อยเวอร์ชัน {r.version} ไป {label} ตามเวลาที่ตั้งแล้ว {res.get('url') or ''}",
                                   {"event": "release", "site": r.site.slug, "version": r.version, "target": t, "ok": True})
            except Exception as e:
                notify.notify_text(r.site.name, f"⚠️ ปล่อยเวอร์ชัน {r.version} ไป {label} ไม่สำเร็จ: {e}",
                                   {"event": "release", "site": r.site.slug, "version": r.version, "target": t, "ok": False})


def parse_when(text):
    """'2026-11-01T09:00' (the server's time zone) → aware datetime."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat((text or "").strip())
    except ValueError:
        raise ReleaseError("เวลาไม่ถูกต้อง")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

