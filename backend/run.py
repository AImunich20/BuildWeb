"""BuildWeb backend entry point (started by the desktop app, or by hand for development).

    python run.py                       editor on http://127.0.0.1:5050
    BUILDWEB_PORT=5051 python run.py    another port

Starts the editor/admin server on 127.0.0.1 and, if enabled in settings, the hosting server for
published sites. Exits when the desktop app that started it goes away.
"""
import logging
import os
import signal
import sys
import threading
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "buildweb.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from buildweb import config  # noqa: E402

log = logging.getLogger("buildweb")


def check_database():
    """If MySQL is configured but unreachable, start in safe mode instead of crashing."""
    db = config.load()["db"]
    if db.get("engine") != "mysql":
        os.environ.pop("BUILDWEB_DB_FAILED", None)
        return
    from builder.dbtools import test_mysql

    last = ""
    for _ in range(3):
        try:
            test_mysql(db)
            os.environ.pop("BUILDWEB_DB_FAILED", None)
            return
        except RuntimeError as e:
            last = str(e)
            time.sleep(1)
    os.environ["BUILDWEB_DB_FAILED"] = last


def shutdown(*_):
    """Stop hosting (and take Tailscale links down) before exiting."""
    try:
        from builder.hosting import server as hosting

        hosting.shutdown()
    except Exception:
        pass
    os._exit(0)


def watch_parent():
    ppid = os.environ.get("BUILDWEB_PARENT_PID")
    if not ppid:
        return
    from builder.system import process_alive

    def loop():
        while True:
            time.sleep(2)
            if not process_alive(ppid):
                shutdown()

    threading.Thread(target=loop, daemon=True).start()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    check_database()

    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    for d in (settings.MEDIA_ROOT, settings.EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    call_command("migrate", interactive=False, verbosity=0)
    if settings.DB_FAILED:
        log.warning("MySQL unreachable, safe mode: %s", settings.DB_FAILED)
    else:
        from builder.hosting import server as hosting

        hosting.apply_config()
        hosting.watch_tailscale()

    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    watch_parent()
    port = settings.ADMIN_PORT
    log.info("BuildWeb %s on http://127.0.0.1:%s (db: %s)", settings.VERSION, port, settings.DB_ENGINE)
    serve(get_wsgi_application(), host="127.0.0.1", port=port, threads=12, ident="BuildWeb",
          max_request_body_size=1024 * 1024 * 1024)


if __name__ == "__main__":
    main()
