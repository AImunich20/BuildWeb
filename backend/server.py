"""BuildWeb as a server (Docker/VPS): serves the published sites, their REST API, members and functions,
and receives deploys from the desktop app. The editor itself stays in the desktop app.

Environment:
  BUILDWEB_DEPLOY_TOKEN     required for deploys (the desktop app sends it)
  BUILDWEB_ADMIN_PASSWORD   password of the "admin" user of /__bw/admin/ (Django admin: rows, members...)
  BUILDWEB_DATABASE_URL     postgres://… · mysql://… · sqlite:////data/db.sqlite3 (default: SQLite in /data)
  BUILDWEB_DOMAINS          shop.com=my-shop,blog.com=my-blog  (which site answers on which domain)
  BUILDWEB_DEFAULT_SITE     site served at / when the domain is not listed
  PORT                      default 8090 (BUILDWEB_HOST: listen address, default 0.0.0.0)
  BUILDWEB_DATA             default /data (config.json, media, backups)
"""
import logging
import os
import sys
from pathlib import Path

os.environ["BUILDWEB_SERVER"] = "1"
os.environ.setdefault("BUILDWEB_DATA", "/data")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "buildweb.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django  # noqa: E402

django.setup()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("buildweb")


def ensure_admin():
    from django.contrib.auth import get_user_model

    pw = os.environ.get("BUILDWEB_ADMIN_PASSWORD", "")
    User = get_user_model()
    user = User.objects.filter(username="admin").first()
    if not pw:
        log.warning("BUILDWEB_ADMIN_PASSWORD is not set: /__bw/admin/ is locked")
        return
    if user is None:
        User.objects.create_superuser("admin", "", pw)
    elif not user.check_password(pw):
        user.set_password(pw)
        user.save()


def import_seeds():
    """Sites shipped with the server kit (seed/*.bwsite) are created on the first start."""
    from builder import backup
    from builder.models import Site

    seed = Path(__file__).parent / "seed"
    for f in sorted(seed.glob("*.bwsite")) if seed.exists() else []:
        try:
            _, d = backup.read_bundle(f)
            if not Site.objects.filter(slug=d["site"]["slug"]).exists():
                backup.import_site(f, mode="new", slug=d["site"]["slug"])
                log.info("imported %s", f.name)
        except Exception as e:
            log.warning("seed %s: %s", f.name, e)


def main():
    from django.conf import settings
    from django.core.management import call_command

    for d in (settings.MEDIA_ROOT,):
        Path(d).mkdir(parents=True, exist_ok=True)
    call_command("migrate", interactive=False, verbosity=0)
    ensure_admin()
    import_seeds()
    if os.environ.get("BUILDWEB_DEFAULT_SITE"):
        from buildweb import config

        config.update("hosting", {"default_site": os.environ["BUILDWEB_DEFAULT_SITE"]})
    from builder import logic
    from builder.middleware import PUBLIC_ENV_KEY

    logic.start_scheduler()
    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    django_app = get_wsgi_application()

    def app(environ, start_response):
        environ[PUBLIC_ENV_KEY] = True
        return django_app(environ, start_response)

    port = int(os.environ.get("PORT", "8090"))
    log.info("BuildWeb server %s on port %s (db: %s)", settings.VERSION, port, settings.DB_ENGINE)
    serve(app, host=os.environ.get("BUILDWEB_HOST", "0.0.0.0"), port=port, threads=16, ident="BuildWeb", max_request_body_size=4 * 1024 ** 3,
          trusted_proxy="*", trusted_proxy_headers="x-forwarded-for x-forwarded-proto x-forwarded-host",
          clear_untrusted_proxy_headers=True)


if __name__ == "__main__":
    main()
