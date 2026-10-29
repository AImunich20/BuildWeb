"""One-click publishing of a site's static files to the internet.

Targets (settings per site in Site.publish, account tokens in config.json "publish"):
- github:  push the files to a branch of a GitHub repo (default gh-pages) through the REST API — no git
           needed — and switch GitHub Pages on. Cloudflare Pages / Vercel can build from that repo too.
- netlify: upload a zip with Netlify's deploy API (a new Netlify site is created the first time).
- ftp:     upload to any web hosting over FTP or FTPS.

Each publish runs in a background thread as a job whose log the UI polls. When the site has no "real
address" yet, the target's URL becomes Site.base_url so sitemap.xml / RSS / share links are right.
"""
import base64
import hashlib
import io
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm
from pathlib import PurePosixPath

from django.conf import settings
from django.db import close_old_connections

from buildweb import config

from .models import Site
from .render import build_files

GITHUB_API = "https://api.github.com"
NETLIFY_API = "https://api.netlify.com/api/v1"
TARGETS = ("github", "netlify", "ftp")
SERVER_TARGETS = ("server", "staging")  # BuildWeb servers: production and a test server

_jobs = {}
_lock = threading.Lock()


class PublishError(Exception):
    pass


# --- files ----------------------------------------------------------------------------------------

def site_files(site):
    """{relative path: bytes} of the exported site (published pages only)."""
    files, assets = build_files(site, "export")
    out = {rel: text.encode("utf-8") for rel, text in files.items()}
    for rel, media in assets.items():
        out[rel] = (settings.MEDIA_ROOT / media).read_bytes()
    return out


# --- HTTP -----------------------------------------------------------------------------------------

def http(method, url, token, data=None, raw=None, content_type=None, timeout=60):
    """JSON request → (status, parsed body). Network errors raise PublishError."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "BuildWeb"}
    body = None
    if raw is not None:
        body, headers["Content-Type"] = raw, content_type or "application/octet-stream"
    elif data is not None:
        body, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    if url.startswith(GITHUB_API):
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"message": text[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PublishError(f"เชื่อมต่อ {url.split('/')[2]} ไม่ได้: {getattr(e, 'reason', e)}") from e


def _msg(body):
    return (body or {}).get("message") or (body or {}).get("error") or ""


# --- GitHub ---------------------------------------------------------------------------------------

def git_blob_sha(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def publish_github(site, cfg, token, log):
    if not token:
        raise PublishError("ยังไม่ได้ใส่ GitHub token")
    st, me = http("GET", f"{GITHUB_API}/user", token)
    if st != 200:
        raise PublishError("GitHub token ใช้ไม่ได้ — สร้างใหม่ที่ github.com/settings/tokens (สิทธิ์ repo)")
    login = me["login"]
    repo = (cfg.get("repo") or site.slug).strip().strip("/")
    owner, _, name = repo.rpartition("/")
    owner = owner or login
    branch = (cfg.get("branch") or "gh-pages").strip()
    full = f"{owner}/{name}"
    base = f"{GITHUB_API}/repos/{full}"
    st, info = http("GET", base, token)
    if st == 404:
        if owner != login:
            raise PublishError(f"ไม่พบ repo {full} (สร้าง repo ในองค์กรให้เรียบร้อยก่อน)")
        log(f"สร้าง repo ใหม่ {full}")
        st, info = http("POST", f"{GITHUB_API}/user/repos", token, {
            "name": name, "description": f"{site.name} — สร้างด้วย BuildWeb", "auto_init": True,
            "homepage": cfg.get("url") or "", "private": False})
        if st not in (200, 201):
            raise PublishError(f"สร้าง repo ไม่สำเร็จ: {_msg(info)}")
        time.sleep(1.5)  # a brand-new repo needs a moment before its git data is ready
    elif st != 200:
        raise PublishError(f"เปิด repo {full} ไม่ได้: {_msg(info)}")

    url = f"https://{owner.lower()}.github.io/" if name.lower() == f"{owner.lower()}.github.io" else f"https://{owner.lower()}.github.io/{name}/"
    if not site.base_url:
        site.base_url = cfg.get("url") or url  # sitemap.xml / share links in this upload already
    files = dict(cfg.get("_files") or site_files(site))
    files[".nojekyll"] = b""
    if cfg.get("domain"):  # own domain (connected through Cloudflare): GitHub Pages reads it from this file
        files["CNAME"] = (cfg["domain"] + "\n").encode()  # serve folders/files starting with "_" as they are
    log(f"เตรียม {len(files)} ไฟล์")

    st, ref = http("GET", f"{base}/git/ref/heads/{branch}", token)
    parent, existing = None, {}
    if st == 200:
        parent = ref["object"]["sha"]
        st, commit = http("GET", f"{base}/git/commits/{parent}", token)
        st, tree = http("GET", f"{base}/git/trees/{commit['tree']['sha']}?recursive=1", token)
        existing = {t["path"]: t["sha"] for t in tree.get("tree", []) if t.get("type") == "blob"}
    elif st == 409 or (st == 404 and info.get("size", 1) == 0):
        # empty repo: the git data API needs a first commit
        http("PUT", f"{base}/contents/.nojekyll", token, {"message": "init", "content": "", "branch": branch})
        st, ref = http("GET", f"{base}/git/ref/heads/{branch}", token)
        if st == 200:
            parent = ref["object"]["sha"]

    tree_items, uploaded = [], 0
    for path, content in sorted(files.items()):
        sha = git_blob_sha(content)
        if existing.get(path) != sha:
            st, blob = http("POST", f"{base}/git/blobs", token,
                            {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            if st not in (200, 201):
                raise PublishError(f"อัปโหลด {path} ไม่สำเร็จ: {_msg(blob)}")
            sha = blob["sha"]
            uploaded += 1
            if uploaded % 20 == 0:
                log(f"อัปโหลดแล้ว {uploaded} ไฟล์…")
        tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
    log(f"ไฟล์ใหม่/เปลี่ยน {uploaded} · เหมือนเดิม {len(files) - uploaded}")
    if parent and uploaded == 0 and set(existing) == set(files):
        log("ไม่มีอะไรเปลี่ยน")
    else:
        st, tree = http("POST", f"{base}/git/trees", token, {"tree": tree_items})
        if st not in (200, 201):
            raise PublishError(f"สร้าง tree ไม่สำเร็จ: {_msg(tree)}")
        st, commit = http("POST", f"{base}/git/commits", token, {
            "message": f"เผยแพร่จาก BuildWeb {datetime.now():%Y-%m-%d %H:%M}", "tree": tree["sha"],
            "parents": [parent] if parent else []})
        if st not in (200, 201):
            raise PublishError(f"commit ไม่สำเร็จ: {_msg(commit)}")
        if parent:
            st, r = http("PATCH", f"{base}/git/refs/heads/{branch}", token, {"sha": commit["sha"], "force": True})
        else:
            st, r = http("POST", f"{base}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        if st not in (200, 201):
            raise PublishError(f"อัปเดต branch {branch} ไม่สำเร็จ: {_msg(r)}")
        log(f"push ไปที่ {full}@{branch} แล้ว")

    if cfg.get("pages", True):
        st, pages = http("GET", f"{base}/pages", token)
        source = {"branch": branch, "path": "/"}
        if st == 404:
            st, pages = http("POST", f"{base}/pages", token, {"source": source})
            if st in (200, 201):
                log("เปิด GitHub Pages แล้ว (ครั้งแรกใช้เวลา 1–2 นาที)")
            else:
                log(f"เปิด GitHub Pages ไม่สำเร็จ: {_msg(pages)} — เปิดเองได้ที่ Settings › Pages")
        elif st == 200 and (pages.get("source") or {}).get("branch") != branch:
            http("PUT", f"{base}/pages", token, {"source": source})
            log(f"ตั้ง GitHub Pages ให้ใช้ branch {branch}")
        if st in (200, 201) and pages.get("html_url"):
            url = pages["html_url"]
    return {"url": cfg.get("url") or url, "repo": full, "branch": branch, "files": len(files), "changed": uploaded}


# --- Netlify --------------------------------------------------------------------------------------

def publish_netlify(site, cfg, token, log):
    if not token:
        raise PublishError("ยังไม่ได้ใส่ Netlify token")
    site_id = cfg.get("site_id")
    if site_id:
        st, info = http("GET", f"{NETLIFY_API}/sites/{site_id}", token)
        if st == 404:
            site_id = None
        elif st != 200:
            raise PublishError(f"Netlify: {_msg(info) or st}")
    if not site_id:
        name = (cfg.get("name") or f"{site.slug}-{uuid.uuid4().hex[:5]}").lower()
        st, info = http("POST", f"{NETLIFY_API}/sites", token, {"name": name})
        if st == 422:  # name taken
            st, info = http("POST", f"{NETLIFY_API}/sites", token, {})
        if st not in (200, 201):
            raise PublishError("Netlify token ใช้ไม่ได้" if st == 401 else f"สร้างเว็บบน Netlify ไม่สำเร็จ: {_msg(info)}")
        site_id = info["id"]
        log(f"สร้างเว็บบน Netlify: {info.get('name')}")
    if not site.base_url and info.get("ssl_url"):
        site.base_url = info["ssl_url"] + "/"
    files = cfg.get("_files") or site_files(site)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in files.items():
            z.writestr(path, content)
    log(f"อัปโหลด {len(files)} ไฟล์ ({len(buf.getvalue()) // 1024:,} KB)")
    st, dep = http("POST", f"{NETLIFY_API}/sites/{site_id}/deploys", token, raw=buf.getvalue(),
                   content_type="application/zip", timeout=300)
    if st not in (200, 201):
        raise PublishError(f"อัปโหลดไป Netlify ไม่สำเร็จ: {_msg(dep) or st}")
    for _ in range(90):
        if dep.get("state") in ("ready", "error"):
            break
        time.sleep(2)
        st, dep = http("GET", f"{NETLIFY_API}/deploys/{dep['id']}", token)
    if dep.get("state") == "error":
        raise PublishError(f"Netlify แจ้งว่า deploy ไม่สำเร็จ: {dep.get('error_message', '')}")
    url = dep.get("ssl_url") or info.get("ssl_url") or dep.get("url") or info.get("url")
    log("Netlify พร้อมใช้งาน" if dep.get("state") == "ready" else "อัปโหลดแล้ว Netlify กำลังเตรียมเว็บ")
    return {"url": url, "site_id": site_id, "name": info.get("name") or cfg.get("name"), "files": len(files)}


# --- FTP ------------------------------------------------------------------------------------------

def ftp_connect(cfg):
    host = (cfg.get("host") or "").strip()
    if not host:
        raise PublishError("กรุณาใส่ host ของ FTP")
    ftp = FTP_TLS(timeout=30) if cfg.get("tls") else FTP(timeout=30)
    try:
        ftp.connect(host, int(cfg.get("port") or 21))
        ftp.login(cfg.get("user") or "anonymous", cfg.get("password") or "")
        if cfg.get("tls"):
            ftp.prot_p()
    except error_perm as e:
        raise PublishError(f"FTP: ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง ({e})") from e
    except OSError as e:
        raise PublishError(f"เชื่อมต่อ FTP {host} ไม่ได้: {e}") from e
    return ftp


def publish_ftp(site, cfg, token, log):
    files = cfg.get("_files") or site_files(site)
    ftp = ftp_connect(cfg)
    root = "/" + (cfg.get("path") or "").strip().strip("/")
    made = set()

    def ensure(folder):
        parts = [p for p in folder.split("/") if p]
        cur = ""
        for p in parts:
            cur += "/" + p
            if cur in made:
                continue
            try:
                ftp.mkd(cur)
            except error_perm:
                pass  # already there
            made.add(cur)

    try:
        ensure(root)
        log(f"อัปโหลด {len(files)} ไฟล์ไปที่ {cfg.get('host')}{root}")
        for i, (path, content) in enumerate(sorted(files.items()), 1):
            full = f"{root.rstrip('/')}/{path}"
            ensure(str(PurePosixPath(full).parent))
            ftp.storbinary(f"STOR {full}", io.BytesIO(content))
            if i % 20 == 0:
                log(f"อัปโหลดแล้ว {i}/{len(files)}")
    except (error_perm, OSError) as e:
        raise PublishError(f"FTP อัปโหลดไม่สำเร็จ: {e}") from e
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return {"url": cfg.get("url") or "", "files": len(files)}


# --- BuildWeb server (server.py on a VPS/Docker) ---------------------------------------------------

def server_call(cfg, method, path, raw=None, timeout=60, data=None):
    url = (cfg.get("url") or "").rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise PublishError("ใส่ที่อยู่เซิร์ฟเวอร์ เช่น https://myshop.com")
    token = cfg.get("token") or ""
    if not token:
        raise PublishError("ใส่ deploy token (BUILDWEB_DEPLOY_TOKEN ในไฟล์ .env ของเซิร์ฟเวอร์)")
    st, body = http(method, url + path, token, data=data, raw=raw, content_type="application/zip" if raw is not None else None,
                    timeout=timeout)
    if st == 401:
        raise PublishError("deploy token ไม่ถูกต้อง")
    if st == 404:
        raise PublishError("ไม่พบ BuildWeb server ที่ที่อยู่นี้ (ตรวจว่าใช้ชุดติดตั้งเซิร์ฟเวอร์และ docker compose ทำงานอยู่)")
    if st >= 400:
        raise PublishError(f"เซิร์ฟเวอร์ตอบ {st}: {_msg(body)}")
    return body


def publish_server(site, cfg, token, log):
    from . import backup

    info = server_call(cfg, "GET", "/__bw/health", timeout=20)
    log(f"เชื่อมต่อเซิร์ฟเวอร์ได้ (BuildWeb {info.get('version')}, ฐานข้อมูล {info.get('database', '?')})")
    data = cfg.get("_bundle") or backup.export_bytes(site)
    log(f"ส่งเว็บ {len(data) // 1024:,} KB")
    res = server_call(cfg, "POST", f"/__bw/deploy?site={site.slug}", raw=data, timeout=600)
    log(("สร้างเว็บใหม่บนเซิร์ฟเวอร์" if res.get("created") else "อัปเดตเว็บบนเซิร์ฟเวอร์") +
        f" · {res.get('pages')} หน้า · {res.get('collections')} ชุดข้อมูล (ข้อมูลที่เกิดบนเซิร์ฟเวอร์ไม่ถูกทับ)")
    return {"url": cfg.get("site_url") or cfg["url"].rstrip("/") + "/", "files": res.get("pages", 0)}


RUNNERS = {"github": publish_github, "netlify": publish_netlify, "ftp": publish_ftp, "server": publish_server,
           "staging": publish_server}


# --- settings & jobs ------------------------------------------------------------------------------

def tokens():
    return config.load().get("publish", {})


def run(site, target, log=lambda m: None, release=None):
    """Publish synchronously; returns the result dict (also stored in Site.publish[target]["last"]).
    With ``release`` the files come from that version's snapshot instead of the site as it is now."""
    from .crypto import decrypt

    cfg = dict((site.publish or {}).get(target) or {})
    for k in ("password", "token"):
        if cfg.get(k):
            cfg[k] = decrypt(cfg[k])
    token = tokens().get(f"{target}_token", "")
    if not site.base_url and cfg.get("url") and target != "staging":
        site.base_url = cfg["url"]  # so this very upload already has sitemap.xml / absolute share links
    try:
        if release is not None:
            from . import releases

            log(f"ใช้เวอร์ชัน {release.version}")
            if target in SERVER_TARGETS:
                cfg["_bundle"] = releases.path_of(release).read_bytes()
            else:
                cfg["_files"] = releases.files_of(release)
        result = RUNNERS[target](site, cfg, token, log)
    except Exception as e:
        if release is not None:
            releases.record(release, target, False, e)
        raise
    if release is not None:
        releases.record(release, target, True, result.get("url", ""))
    site.refresh_from_db()
    pub = dict(site.publish or {})
    t = dict(pub.get(target) or {})
    for k in ("site_id", "name", "repo", "branch"):
        if result.get(k):
            t[k] = result[k]
    if result.get("url"):
        t["url"] = t.get("url") or result["url"]
    t["last"] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": True, "url": result.get("url", ""),
                 "files": result.get("files", 0), "version": release.version if release is not None else ""}
    pub[target] = t
    site.publish = pub
    fields = ["publish"]
    if not site.base_url and t.get("url") and target != "staging":
        site.base_url = t["url"]
        fields.append("base_url")
        log(f"ตั้งที่อยู่เว็บจริงเป็น {t['url']}")
    site.save(update_fields=fields)
    return result


def start(site, target, release=None):
    if target not in RUNNERS:
        raise PublishError("ไม่รู้จักปลายทางนี้")
    with _lock:
        for j in _jobs.values():
            if j["site"] == site.id and j["state"] == "running":
                raise PublishError("กำลังเผยแพร่เว็บนี้อยู่ รอให้เสร็จก่อน")
        job = {"id": uuid.uuid4().hex[:12], "site": site.id, "target": target, "state": "running", "log": [],
               "url": "", "error": "", "started": time.time(), "version": release.version if release is not None else ""}
        _jobs[job["id"]] = job

    def log(msg):
        job["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")

    def work():
        close_old_connections()
        try:
            s = Site.objects.get(pk=site.id)
            log(f"เริ่มเผยแพร่ “{s.name}” → {LABELS[target]}")
            result = run(s, target, log, release=release)
            job["url"] = result.get("url", "")
            log("เสร็จแล้ว" + (f" → {job['url']}" if job["url"] else ""))
            job["state"] = "done"
        except PublishError as e:
            job["error"] = str(e)
            log(f"ผิดพลาด: {e}")
            job["state"] = "error"
        except Exception as e:  # never leave a job "running" forever
            job["error"] = f"{type(e).__name__}: {e}"
            log(f"ผิดพลาด: {job['error']}")
            job["state"] = "error"
        finally:
            close_old_connections()

    threading.Thread(target=work, daemon=True, name=f"publish-{target}").start()
    return job


def job(job_id):
    return _jobs.get(job_id)


LABELS = {"github": "GitHub Pages", "netlify": "Netlify", "ftp": "FTP", "server": "เซิร์ฟเวอร์ของฉัน",
          "staging": "เซิร์ฟเวอร์ทดสอบ (staging)"}
