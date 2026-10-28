"""Notifications for new form submissions: macOS notification, Telegram, Discord, e-mail, generic webhook.

Sent from a background thread so a slow channel never delays the visitor's form response.
"""
import json
import logging
import smtplib
import threading
import urllib.request
from email.message import EmailMessage

from buildweb import config

log = logging.getLogger("buildweb")


def settings():
    return config.load()["notify"]


def summary(site_name, form_name, page_title, data, limit=12):
    lines = [f"📩 ฟอร์มใหม่จาก {site_name}"]
    meta = " · ".join(x for x in (form_name, page_title) if x)
    if meta:
        lines.append(meta)
    for i, (k, v) in enumerate(data.items()):
        if i >= limit:
            lines.append("…")
            break
        v = ", ".join(v) if isinstance(v, list) else str(v)
        lines.append(f"{k}: {v[:300]}")
    return "\n".join(lines)


def _post_json(url, payload, timeout=8):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json",
                                                                     "User-Agent": "BuildWeb"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def send_mac(title, text):
    """Desktop notification (macOS / Windows toast / Linux notify-send); the setting is still called "mac"."""
    from .system import desktop_notify

    desktop_notify(title, text)


def send_telegram(cfg, text):
    url = f"https://api.telegram.org/bot{cfg['telegram_token'].strip()}/sendMessage"
    _post_json(url, {"chat_id": cfg["telegram_chat"].strip(), "text": text, "disable_web_page_preview": True})


def send_discord(cfg, text):
    _post_json(cfg["discord_webhook"].strip(), {"content": text[:1900], "username": "BuildWeb"})


def send_webhook(cfg, payload):
    _post_json(cfg["webhook_url"].strip(), payload)


def send_email(cfg, subject, text):
    e = cfg["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = e.get("from") or e["user"]
    msg["To"] = e["to"]
    msg.set_content(text)
    port = int(e.get("port") or 587)
    if port == 465:
        server = smtplib.SMTP_SSL(e["host"], port, timeout=15)
    else:
        server = smtplib.SMTP(e["host"], port, timeout=15)
        if e.get("tls", True):
            server.starttls()
    with server:
        if e.get("user"):
            server.login(e["user"], e.get("password", ""))
        server.send_message(msg)


def channels(cfg):
    out = []
    if cfg.get("mac"):
        out.append("mac")
    if cfg.get("telegram_token") and cfg.get("telegram_chat"):
        out.append("telegram")
    if cfg.get("discord_webhook"):
        out.append("discord")
    if cfg.get("webhook_url"):
        out.append("webhook")
    e = cfg.get("email") or {}
    if e.get("enabled") and e.get("host") and e.get("to"):
        out.append("email")
    return out


def deliver(cfg, site_name, text, payload, only=None):
    """Send to every configured channel (or just ``only``). Returns {channel: "ok" | error message}."""
    results = {}
    for ch in channels(cfg):
        if only and ch != only:
            continue
        try:
            if ch == "mac":
                send_mac(f"BuildWeb · {site_name}", text.split("\n", 1)[-1])
            elif ch == "telegram":
                send_telegram(cfg, text)
            elif ch == "discord":
                send_discord(cfg, text)
            elif ch == "webhook":
                send_webhook(cfg, payload)
            elif ch == "email":
                send_email(cfg, f"[BuildWeb] ฟอร์มใหม่จาก {site_name}", text)
            results[ch] = "ok"
        except Exception as ex:  # report every channel; one failing must not stop the others
            results[ch] = str(ex)[:200]
            log.warning("notify %s failed: %s", ch, ex)
    return results


def submission_payload(sub):
    return {
        "event": "form_submission", "site": sub.site.slug, "site_name": sub.site.name,
        "page": sub.page.slug if sub.page else "", "form": sub.form_name, "data": sub.data,
        "created_at": sub.created_at.isoformat(),
    }


def notify_submission(sub):
    from django.conf import settings as dj

    if dj.TESTING:
        return
    cfg = settings()
    if not cfg.get("enabled", True) or not channels(cfg):
        return
    text = summary(sub.site.name, sub.form_name, sub.page.title if sub.page else "", sub.data)
    payload = submission_payload(sub)
    threading.Thread(target=deliver, args=(cfg, sub.site.name, text, payload), daemon=True).start()
