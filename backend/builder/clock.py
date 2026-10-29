"""Server time: the time zone used for scheduled jobs, scheduled releases, order times, statistics days and
backups. Set in the app (config "app.timezone") or, on a server, from the desktop app through /__bw/config.
Changing it applies at once (no restart): Django's default zone, the process TZ, and the next run of jobs."""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.utils import timezone

COMMON = ["Asia/Bangkok", "Asia/Ho_Chi_Minh", "Asia/Jakarta", "Asia/Singapore", "Asia/Kuala_Lumpur", "Asia/Manila",
          "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Taipei", "Asia/Tokyo", "Asia/Seoul", "Asia/Kolkata", "Asia/Dubai",
          "Australia/Sydney", "Europe/London", "Europe/Berlin", "Europe/Paris", "America/New_York", "America/Chicago",
          "America/Los_Angeles", "UTC"]


def valid(name):
    try:
        return bool(name) and bool(ZoneInfo(name))
    except Exception:
        return False


def zones():
    try:
        rest = sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/", "right/")))
    except Exception:
        rest = []
    return COMMON + [z for z in rest if z not in COMMON]


def apply(name):
    """Switch the running process to ``name``; returns the zone in use."""
    if not valid(name):
        raise ValueError("ไม่รู้จักเขตเวลานี้")
    settings.TIME_ZONE = name
    timezone.get_default_timezone.cache_clear()
    os.environ["TZ"] = name
    if hasattr(time, "tzset"):  # not on Windows
        time.tzset()
    from .models import Job
    from . import logic

    for job in Job.objects.filter(enabled=True):  # "daily 09:00" now means 09:00 in the new zone
        try:
            job.next_run = logic.next_run(job.schedule)
            job.save(update_fields=["next_run"])
        except ValueError:
            pass
    return name


def info():
    now = timezone.localtime()
    off = now.utcoffset().total_seconds() / 3600
    return {"timezone": settings.TIME_ZONE, "now": now.isoformat(timespec="seconds"),
            "utc_offset": f"UTC{'+' if off >= 0 else '-'}{int(abs(off)):02d}:{int(abs(off) * 60) % 60:02d}",
            "epoch": time.time()}


def drift(remote_iso, sent_at, received_at):
    """Seconds the remote clock is ahead of ours (negative = behind), from one request's round trip."""
    try:
        remote = datetime.fromisoformat(remote_iso).timestamp()
    except (TypeError, ValueError):
        return None
    return round(remote - (sent_at + received_at) / 2, 1)
