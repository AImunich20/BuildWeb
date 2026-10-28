"""App configuration stored as JSON in the data directory (outside the database, because it says
*which* database to use).

Data directory: $BUILDWEB_DATA, or backend/.data when running from source.
"""
import json
import os
import secrets
import threading
from copy import deepcopy
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("BUILDWEB_DATA") or BACKEND_DIR / ".data")
CONFIG_PATH = DATA_DIR / "config.json"
def _xampp():
    import sys

    if sys.platform == "darwin":
        base = Path("/Applications/XAMPP/xamppfiles")
        return base, base / "var/mysql/mysql.sock"
    if os.name == "nt":
        return Path(os.environ.get("XAMPP_HOME", r"C:\xampp")), Path("__no_socket__")
    return Path("/opt/lampp"), Path("/opt/lampp/var/mysql/mysql.sock")


XAMPP_DIR, XAMPP_SOCKET = _xampp()
XAMPP_HTDOCS = XAMPP_DIR / "htdocs"

DEFAULTS = {
    "db": {
        "engine": "sqlite",  # sqlite | mysql
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",
        "name": "buildweb",
        "socket": "",
    },
    "hosting": {
        "enabled": False,
        "port": 8090,
        "lan": True,  # listen on 0.0.0.0 so other devices on the network can open the sites
        "default_site": None,  # site slug served at "/"
        "tailscale": False,  # publish through `tailscale serve` (HTTPS on <machine>.ts.net)
        "tailscale_port": 443,
        "funnel": False,  # `tailscale funnel`: public internet instead of tailnet only
    },
    "notify": {
        "enabled": True,
        "mac": True,
        "telegram_token": "",
        "telegram_chat": "",
        "discord_webhook": "",
        "webhook_url": "",
        "email": {"enabled": False, "host": "", "port": 587, "user": "", "password": "", "from": "", "to": "", "tls": True},
    },
    "app": {
        "auto_update": True,  # read by the desktop shell: install patches without asking (then offer a restart)
    },
    "export": {
        "last_target": "downloads",
        "custom_path": "",
    },
    "publish": {
        "github_token": "",   # personal access token (repo scope) for GitHub Pages
        "netlify_token": "",  # personal access token from app.netlify.com/user/applications
    },
}

_lock = threading.Lock()


def _merge(base, extra):
    out = deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = {}
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        except (OSError, ValueError):
            raw = {}
    if not raw.get("secret_key"):
        # Only what the user set is stored, so new defaults in later versions still apply.
        raw["secret_key"] = secrets.token_urlsafe(48)
        _write(raw)
    return _merge(DEFAULTS, raw)


def _raw():
    try:
        return json.loads(CONFIG_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg):
    _write(cfg)


def _write(cfg):
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(CONFIG_PATH)


def update(section, values):
    raw = _raw()
    raw[section] = _merge(raw.get(section, {}), values)
    _write(raw)
    return load()


def django_database(db):
    """Translate the "db" config section into a Django DATABASES entry."""
    if db.get("engine") == "mysql":
        opts = {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"}
        entry = {
            "ENGINE": "builder.db.mysql",
            "NAME": db.get("name") or "buildweb",
            "USER": db.get("user") or "root",
            "PASSWORD": db.get("password") or "",
            "HOST": db.get("host") or "127.0.0.1",
            "PORT": str(db.get("port") or 3306),
            "OPTIONS": opts,
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
        if db.get("socket"):
            opts["unix_socket"] = db["socket"]
        return entry
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DATA_DIR / "db.sqlite3"),
        "OPTIONS": {"timeout": 20},
    }
