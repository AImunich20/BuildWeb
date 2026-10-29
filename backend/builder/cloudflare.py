"""Connect a site's own domain through Cloudflare DNS (API token with Zone:Read + DNS:Edit).

connect() points the domain at where the site is published and finishes the setup on that side:
  server / staging  A record → the server's IP; the server is told which site answers on the domain
                    (/__bw/config) and Caddy gets its certificate on the first visit
  github            CNAME → <owner>.github.io; the CNAME file goes into every publish (GitHub Pages custom domain)
  netlify           CNAME → <name>.netlify.app; the domain is set as the Netlify site's custom domain
  ftp / other       A or CNAME to an address you give
Existing records with the same name are only replaced when asked (replace=True), and every change is listed
in the result. The token is stored encrypted in config.json ("publish.cloudflare_token").
"""
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from buildweb import config

from . import publish
from .crypto import decrypt, encrypt

API = "https://api.cloudflare.com/client/v4"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


LAN = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")]


class CloudflareError(Exception):
    pass


def token():
    return decrypt(config.load()["publish"].get("cloudflare_token", ""))


def save_token(value):
    config.update("publish", {"cloudflare_token": encrypt(value.strip()) if value.strip() else ""})


def call(method, path, data=None, tok=None):
    tok = tok or token()
    if not tok:
        raise CloudflareError("ยังไม่ได้ใส่ Cloudflare API token")
    try:
        st, body = publish.http(method, API + path, tok, data=data, timeout=30)
    except publish.PublishError as e:
        raise CloudflareError(str(e))
    if st >= 400 or not (body or {}).get("success", st < 400):
        errs = "; ".join(f"{e.get('message')}" for e in (body or {}).get("errors", [])) or f"HTTP {st}"
        if st in (401, 403):
            errs = f"token ไม่มีสิทธิ์ ({errs}) — ต้องมีสิทธิ์ Zone:Read และ DNS:Edit"
        raise CloudflareError(f"Cloudflare: {errs}")
    return body.get("result")


def verify(tok):
    r = call("GET", "/user/tokens/verify", tok=tok)
    if (r or {}).get("status") != "active":
        raise CloudflareError("token นี้ยังไม่เปิดใช้งาน")
    return zones(tok)


def zones(tok=None):
    return [{"id": z["id"], "name": z["name"], "status": z["status"], "name_servers": z.get("name_servers", [])}
            for z in call("GET", "/zones?per_page=50", tok=tok) or []]


def clean_domain(d):
    d = (d or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].rstrip(".")
    if not DOMAIN_RE.match(d):
        raise CloudflareError("โดเมนไม่ถูกต้อง ใส่เช่น myshop.com หรือ www.myshop.com")
    return d


def zone_for(domain, all_zones):
    best = None
    for z in all_zones:
        if domain == z["name"] or domain.endswith("." + z["name"]):
            if not best or len(z["name"]) > len(best["name"]):
                best = z
    if not best:
        raise CloudflareError(f"ไม่พบโดเมน {domain} ในบัญชี Cloudflare นี้ — เพิ่มโดเมนใน Cloudflare ก่อน (Add a site) "
                              "แล้วเปลี่ยน name server ที่ผู้ให้บริการโดเมนตามที่ Cloudflare บอก")
    return best


def _host(url):
    return (urlparse(url).hostname or "").lower()


def _ip_of(host):
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except OSError:
        raise CloudflareError(f"หา IP ของ {host} ไม่ได้ — ใส่ IP ของเซิร์ฟเวอร์เอง")
    return infos[0][4][0]


def plan(site, domain, target, content=""):
    """The DNS record(s) the domain needs: [{"type", "name", "content"}]."""
    cfg = (site.publish or {}).get(target) or {}
    content = (content or "").strip()
    if target in publish.SERVER_TARGETS:
        if not cfg.get("url") and not content:
            raise CloudflareError("ตั้งที่อยู่เซิร์ฟเวอร์ก่อน (เซิร์ฟเวอร์ของฉัน)")
        ip = _ip_of(content or _host(cfg["url"]))
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback or addr.is_link_local or any(addr in n for n in LAN if n.version == addr.version):
            raise CloudflareError(f"{ip} เป็น IP ภายใน ใช้กับโดเมนสาธารณะไม่ได้ — ใส่ IP สาธารณะของเซิร์ฟเวอร์")
        return [{"type": "AAAA" if ":" in ip else "A", "name": domain, "content": ip}]
    if target == "github":
        url = (cfg.get("last") or {}).get("url") or ""
        host = _host(url) if url.endswith(".github.io/") or ".github.io/" in url else ""
        if not host:
            raise CloudflareError("เผยแพร่ไป GitHub Pages ให้สำเร็จหนึ่งครั้งก่อน แล้วค่อยเชื่อมโดเมน")
        return [{"type": "CNAME", "name": domain, "content": host}]
    if target == "netlify":
        url = (cfg.get("last") or {}).get("url") or ""
        host = _host(url) if ".netlify.app" in url else (f"{cfg['name']}.netlify.app" if cfg.get("name") else "")
        if not host or not cfg.get("site_id"):
            raise CloudflareError("เผยแพร่ไป Netlify ให้สำเร็จหนึ่งครั้งก่อน แล้วค่อยเชื่อมโดเมน")
        return [{"type": "CNAME", "name": domain, "content": host}]
    if not content:
        raise CloudflareError("ใส่ IP หรือชื่อโฮสต์ปลายทาง (เช่น IP ของโฮสติ้งที่เช่า)")
    try:
        ip = str(ipaddress.ip_address(content))
        return [{"type": "AAAA" if ":" in ip else "A", "name": domain, "content": ip}]
    except ValueError:
        return [{"type": "CNAME", "name": domain, "content": clean_domain(content)}]


def records(zone_id, name):
    return [r for r in call("GET", f"/zones/{zone_id}/dns_records?name={name}&per_page=100") or []
            if r["type"] in ("A", "AAAA", "CNAME")]


def connect(site, domain, target, proxied=False, www=False, replace=False, content=""):
    """Create/update the records and finish the setup at the target. Returns {"changes", "notes", "url"}."""
    domain = clean_domain(domain)
    if target not in publish.RUNNERS:
        raise CloudflareError("เลือกปลายทาง")
    zone = zone_for(domain, zones())
    wanted = plan(site, domain, target, content)
    if www and not domain.startswith("www."):
        wanted.append({"type": "CNAME", "name": "www." + domain, "content": domain})
    changes, notes = [], []
    # check everything first, change nothing when a record would have to be overwritten without permission
    existing = {w["name"]: records(zone["id"], w["name"]) for w in wanted}
    conflicts = [r for w in wanted for r in existing[w["name"]] if (r["type"], r["content"]) != (w["type"], w["content"])]
    if conflicts and not replace:
        raise CloudflareError("มี DNS record ชื่อนี้อยู่แล้ว: " + ", ".join(f"{r['name']} {r['type']} {r['content']}" for r in conflicts)
                              + " — ติ๊ก “แทนที่ record เดิม” ถ้าต้องการชี้มาที่เว็บนี้")
    for w in wanted:
        body = {"type": w["type"], "name": w["name"], "content": w["content"], "ttl": 1, "proxied": bool(proxied),
                "comment": f"BuildWeb: {site.name}"[:100]}
        cur = existing[w["name"]]
        same = next((r for r in cur if r["type"] == w["type"]), None)
        for r in cur:
            if r is not same:
                call("DELETE", f"/zones/{zone['id']}/dns_records/{r['id']}")
                changes.append(f"ลบ {r['name']} {r['type']} {r['content']}")
        if same:
            call("PUT", f"/zones/{zone['id']}/dns_records/{same['id']}", body)
            changes.append(f"แก้ {w['name']} {w['type']} → {w['content']}")
        else:
            call("POST", f"/zones/{zone['id']}/dns_records", body)
            changes.append(f"เพิ่ม {w['name']} {w['type']} → {w['content']}")
    if proxied:
        try:
            call("PATCH", f"/zones/{zone['id']}/settings/ssl", {"value": "strict"})
            notes.append("ตั้ง SSL/TLS ของ Cloudflare เป็น Full (strict)")
        except CloudflareError:
            notes.append("ตั้ง SSL/TLS ใน Cloudflare เป็น Full (strict) เอง (token ไม่มีสิทธิ์ Zone Settings)")
    notes += finish_target(site, domain, target, www)
    url = f"https://{domain}/"
    pub = dict(site.publish or {})
    pub["domain"] = {"domain": domain, "target": target, "zone": zone["name"], "zone_id": zone["id"], "proxied": bool(proxied),
                     "www": bool(www), "records": wanted}
    if target != "staging":
        tc = dict(pub.get(target) or {})
        tc["domain"] = domain
        if target in ("github", "netlify", "ftp"):
            tc["url"] = url
        elif target == "server":
            tc["site_url"] = url
        pub[target] = tc
        site.base_url = url
    site.publish = pub
    site.save(update_fields=["publish", "base_url"])
    if zone["status"] != "active":
        notes.append(f"โดเมน {zone['name']} ใน Cloudflare ยังไม่ active — เปลี่ยน name server ที่ผู้ให้บริการโดเมนเป็น "
                     + ", ".join(zone["name_servers"]))
    return {"changes": changes, "notes": notes, "url": url, "zone": zone["name"]}


def finish_target(site, domain, target, www):
    notes = []
    names = [domain] + (["www." + domain] if www and not domain.startswith("www.") else [])
    if target in publish.SERVER_TARGETS:
        from .api import server_cfg

        cfg = server_cfg(site, target)
        try:
            publish.server_call(cfg, "POST", "/__bw/config", timeout=20, data={"domains": {n: site.slug for n in names}})
            notes.append("บอกเซิร์ฟเวอร์แล้วว่าโดเมนนี้คือเว็บนี้ — HTTPS พร้อมภายในไม่กี่นาทีหลังเปิดครั้งแรก")
        except publish.PublishError as e:
            notes.append(f"ตั้งโดเมนบนเซิร์ฟเวอร์ไม่สำเร็จ ({e}) — Deploy เว็บก่อนแล้วกดเชื่อมอีกครั้ง")
    elif target == "github":
        cfg = (site.publish or {}).get("github") or {}
        tok = publish.tokens().get("github_token", "")
        repo = cfg.get("repo") or ""
        if tok and "/" in repo:
            st, body = publish.http("PUT", f"{publish.GITHUB_API}/repos/{repo}/pages", tok, {"cname": domain})
            notes.append("ตั้ง custom domain ใน GitHub Pages แล้ว" if st < 300 else f"ตั้ง custom domain ใน GitHub ไม่สำเร็จ: {publish._msg(body)}")
        notes.append("กด “เผยแพร่” ไป GitHub Pages อีกครั้งเพื่อใส่ไฟล์ CNAME · เปิด Enforce HTTPS ในหน้า Settings › Pages เมื่อพร้อม")
    elif target == "netlify":
        cfg = (site.publish or {}).get("netlify") or {}
        tok = publish.tokens().get("netlify_token", "")
        if tok and cfg.get("site_id"):
            data = {"custom_domain": domain}
            if len(names) > 1:
                data["domain_aliases"] = names[1:]
            st, body = publish.http("PATCH", f"{publish.NETLIFY_API}/sites/{cfg['site_id']}", tok, data)
            notes.append("ตั้งโดเมนใน Netlify แล้ว (Netlify ขอ HTTPS ให้เอง)" if st < 300 else f"ตั้งโดเมนใน Netlify ไม่สำเร็จ: {publish._msg(body)}")
    else:
        notes.append("ตั้งโดเมนนี้ในแผงควบคุมของโฮสติ้งด้วย (Addon/Parked domain) และเปิด SSL ที่นั่น")
    return notes


def check(site):
    """Where the connected domain stands: records in Cloudflare and whether https:// answers."""
    d = (site.publish or {}).get("domain") or {}
    if not d.get("domain"):
        return {"connected": False}
    out = {"connected": True, **d, "records_now": [], "https": None}
    try:
        for w in d.get("records") or [{"name": d["domain"]}]:
            out["records_now"] += [{"name": r["name"], "type": r["type"], "content": r["content"], "proxied": r.get("proxied")}
                                   for r in records(d["zone_id"], w["name"])]
    except CloudflareError as e:
        out["error"] = str(e)
    try:
        req = urllib.request.Request(f"https://{d['domain']}/", method="HEAD", headers={"User-Agent": "BuildWeb"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out["https"] = {"ok": True, "status": r.status}
    except urllib.error.HTTPError as e:
        out["https"] = {"ok": e.code < 500, "status": e.code}
    except Exception as e:
        out["https"] = {"ok": False, "error": str(getattr(e, "reason", e))[:200]}
    return out


def disconnect(site, remove_records=False):
    d = (site.publish or {}).get("domain") or {}
    changes = []
    if remove_records and d.get("zone_id"):
        for w in d.get("records") or []:
            for r in records(d["zone_id"], w["name"]):
                if (r["type"], r["content"]) == (w["type"], w["content"]):
                    call("DELETE", f"/zones/{d['zone_id']}/dns_records/{r['id']}")
                    changes.append(f"ลบ {r['name']} {r['type']} {r['content']}")
    if d.get("target") in publish.SERVER_TARGETS:
        from .api import server_cfg

        names = [w["name"] for w in d.get("records") or []] or [d.get("domain")]
        try:
            publish.server_call(server_cfg(site, d["target"]), "POST", "/__bw/config", timeout=20, data={"remove_domains": names})
            changes.append("เอาโดเมนออกจากเซิร์ฟเวอร์แล้ว")
        except publish.PublishError:
            pass
    pub = dict(site.publish or {})
    pub.pop("domain", None)
    for t in ("github", "netlify", "ftp", "server"):
        if isinstance(pub.get(t), dict):
            pub[t] = {k: v for k, v in pub[t].items() if k != "domain"}
    site.publish = pub
    site.save(update_fields=["publish"])
    return {"changes": changes}

