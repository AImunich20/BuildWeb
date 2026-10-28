"""Tailscale integration: show the machine's tailnet addresses and publish the hosting server through
`tailscale serve` (HTTPS for devices in your tailnet) or `tailscale funnel` (HTTPS on the public internet).
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from .system import NO_WINDOW, WINDOWS, tailscale_candidates

CANDIDATES = tailscale_candidates()
FUNNEL_PORTS = (443, 8443, 10000)  # the only HTTPS ports Funnel allows


def binary():
    for c in CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("tailscale") or ""


def run(args, timeout=20):
    b = binary()
    if not b:
        raise RuntimeError("ไม่พบ Tailscale ในเครื่อง — ติดตั้งจาก tailscale.com/download")
    # Launched from Finder (no terminal), the macOS app binary would try to open its GUI instead of acting
    # as the CLI; TAILSCALE_BE_CLI forces CLI mode.
    env = {**os.environ, "TAILSCALE_BE_CLI": "1"}
    r = subprocess.run([b, *args], capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL,
                       start_new_session=not WINDOWS, creationflags=NO_WINDOW)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        low = msg.lower()
        if "funnel not available" in low or ("funnel" in low and "not" in low and "enabled" in low):
            msg = "บัญชี Tailscale นี้ยังไม่เปิด Funnel — เปิดได้ที่หน้า Access controls ของ Tailscale admin (nodeAttrs: funnel) " + msg
        elif "HTTPS" in msg and "not enabled" in msg:
            msg = "tailnet นี้ยังไม่เปิด HTTPS certificates — เปิดที่ Tailscale admin › DNS › Enable HTTPS " + msg
        raise RuntimeError(msg[:400] or f"tailscale {' '.join(args)} ล้มเหลว")
    return r.stdout


def status():
    b = binary()
    if not b:
        return {"installed": False}
    try:
        d = json.loads(run(["status", "--json"], timeout=8))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        return {"installed": True, "running": False, "error": str(e)[:200]}
    me = d.get("Self") or {}
    dns = (me.get("DNSName") or "").rstrip(".")
    ips = me.get("TailscaleIPs") or []
    return {
        "installed": True, "running": d.get("BackendState") == "Running", "state": d.get("BackendState"),
        "dns_name": dns, "ipv4": next((i for i in ips if "." in i), ""), "ips": ips,
        "magic_dns": bool(d.get("MagicDNSSuffix")), "serve": serve_status(),
    }


def serve_status():
    """{https_port: {"target": "http://127.0.0.1:8090", "funnel": bool}} from `tailscale serve status --json`."""
    try:
        d = json.loads(run(["serve", "status", "--json"], timeout=8) or "{}")
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return {}
    out = {}
    funnel = {k.rsplit(":", 1)[-1] for k, v in (d.get("AllowFunnel") or {}).items() if v}
    for host, cfg in (d.get("Web") or {}).items():
        port = host.rsplit(":", 1)[-1]
        handlers = (cfg or {}).get("Handlers") or {}
        target = (handlers.get("/") or next(iter(handlers.values()), {})).get("Proxy", "")
        out[port] = {"target": target, "funnel": port in funnel}
    return out


def publish(local_port, https_port=443, funnel=False):
    """Expose http://127.0.0.1:<local_port> as https://<machine>.ts.net[:https_port]."""
    https_port = int(https_port)
    if funnel and https_port not in FUNNEL_PORTS:
        raise RuntimeError(f"Funnel ใช้ได้เฉพาะพอร์ต {', '.join(map(str, FUNNEL_PORTS))}")
    target = f"http://127.0.0.1:{int(local_port)}"
    cmd = "funnel" if funnel else "serve"
    run([cmd, "--bg", f"--https={https_port}", target])
    return url(https_port)


def unpublish(https_port=443):
    https_port = int(https_port)
    for cmd in ("funnel", "serve"):
        try:
            run([cmd, f"--https={https_port}", "off"])
        except RuntimeError:
            pass


def url(https_port=443):
    s = status()
    host = s.get("dns_name") or ""
    if not host:
        return ""
    return f"https://{host}/" if int(https_port) == 443 else f"https://{host}:{int(https_port)}/"


def connect():
    """`tailscale up` (uses the existing login). Raises with a hint when a login in the app is needed."""
    try:
        run(["up", "--timeout=20s"], timeout=30)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Tailscale ใช้เวลานานเกินไป — เปิดแอป Tailscale แล้วกด Connect") from e
    except RuntimeError as e:
        if "login" in str(e).lower() or "auth" in str(e).lower():
            raise RuntimeError("ต้องล็อกอิน Tailscale ก่อน — เปิดแอป Tailscale แล้วล็อกอิน") from e
        raise
    return status()


def open_app():
    import sys

    from .system import popen

    if sys.platform == "darwin":
        popen(["open", "-a", "Tailscale"])
    elif WINDOWS:
        popen([binary().replace("tailscale.exe", "tailscale-ipn.exe")])
    else:
        raise RuntimeError("บน Linux ให้รัน `sudo tailscale up` ในเทอร์มินัล")
