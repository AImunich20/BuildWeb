"""Visitor statistics of the hosting server — counted on this machine, no Google Analytics, no cookies.

Every page served by the hosting server (LAN, own ports, Tailscale) adds to per-day counters: views,
visitors (a hash of IP + browser + day, kept in memory only), pages, referrer sites and device type.
Hits are buffered in memory and written in batches so serving stays fast. Bots and the in-app preview are
not counted.
"""
import hashlib
import re
import threading
import time
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import Stat

BOT_RE = re.compile(r"bot|crawl|spider|slurp|facebookexternalhit|line-poker|preview|curl|wget|python|headless|monitor|lighthouse", re.I)
MOBILE_RE = re.compile(r"Mobi|Android|iPhone|iPad|iPod", re.I)
FLUSH_EVERY = 5  # seconds

_buf = Counter()
_seen = {}  # (site_id, day) -> set of visitor hashes
_lock = threading.Lock()
_last_flush = [time.time()]


def hit(site, request, path):
    if request.method != "GET":
        return
    ua = request.META.get("HTTP_USER_AGENT", "")
    if not ua or BOT_RE.search(ua):
        return
    day = timezone.localdate()
    ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()
    visitor = hashlib.sha1(f"{ip}|{ua}|{day}".encode()).hexdigest()[:16]
    page = "/" + (path.strip("/") or "")
    ref = urlparse(request.META.get("HTTP_REFERER", "")).hostname or ""
    if ref and ref == request.get_host().split(":")[0]:
        ref = ""  # moving around inside the site
    with _lock:
        seen = _seen.setdefault((site.id, day), set())
        _buf[(site.id, day, "views", "")] += 1
        if visitor not in seen:
            seen.add(visitor)
            _buf[(site.id, day, "visitors", "")] += 1
            _buf[(site.id, day, "device", "mobile" if MOBILE_RE.search(ua) else "desktop")] += 1
            _buf[(site.id, day, "ref", (ref or "")[:200])] += 1
        _buf[(site.id, day, "page", page[:200])] += 1
        for key in [k for k in _seen if k[1] < day]:  # yesterday's visitors are no longer needed
            _seen.pop(key, None)
        due = time.time() - _last_flush[0] > FLUSH_EVERY
    if due:
        flush()


def flush():
    with _lock:
        items = list(_buf.items())
        _buf.clear()
        _last_flush[0] = time.time()
    for (site_id, day, kind, key), n in items:
        try:
            with transaction.atomic():
                if not Stat.objects.filter(site_id=site_id, day=day, kind=kind, key=key).update(count=F("count") + n):
                    Stat.objects.create(site_id=site_id, day=day, kind=kind, key=key, count=n)
        except IntegrityError:  # created by another thread in between
            Stat.objects.filter(site_id=site_id, day=day, kind=kind, key=key).update(count=F("count") + n)
        except Exception:  # the site was deleted, DB down...: statistics are never worth an error
            pass


def summary(site, days=30):
    flush()
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    qs = Stat.objects.filter(site=site, day__gte=start)
    per_day = {start + timedelta(days=i): {"views": 0, "visitors": 0} for i in range(days)}
    for s in qs.filter(kind__in=("views", "visitors")):
        per_day[s.day][s.kind] = s.count

    def top(kind, n=10):
        return [{"key": r["key"], "count": r["n"]} for r in
                qs.filter(kind=kind).values("key").annotate(n=Sum("count")).order_by("-n")[:n]]

    series = [{"day": d.isoformat(), **v} for d, v in sorted(per_day.items())]
    half = days // 2
    prev = sum(x["views"] for x in series[:half])
    cur = sum(x["views"] for x in series[half:])
    return {
        "days": series,
        "total": {"views": sum(x["views"] for x in series), "visitors": sum(x["visitors"] for x in series),
                  "today": series[-1]["views"], "trend": round((cur - prev) / prev * 100) if prev else None},
        "pages": top("page"), "refs": top("ref"), "devices": top("device", 3),
    }


def sparkline(site, days=14):
    """Views per day for the dashboard cards."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    counts = dict(Stat.objects.filter(site=site, kind="views", day__gte=start).values_list("day", "count"))
    return [counts.get(start + timedelta(days=i), 0) for i in range(days)]
