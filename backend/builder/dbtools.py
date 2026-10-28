"""Database connection tools: test a MySQL/MariaDB (XAMPP) connection, create the database, and switch
the app between SQLite and MySQL, copying all data across."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pymysql

from buildweb import config

BACKEND = config.BACKEND_DIR
DUMP_EXCLUDE = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]


def connect_kwargs(db, with_db=False):
    kw = {
        "host": db.get("host") or "127.0.0.1",
        "port": int(db.get("port") or 3306),
        "user": db.get("user") or "root",
        "password": db.get("password") or "",
        "charset": "utf8mb4",
        "connect_timeout": 5,
    }
    if db.get("socket"):
        kw["unix_socket"] = db["socket"]
    if with_db:
        kw["database"] = db.get("name") or "buildweb"
    return kw


def test_mysql(db):
    """Return a dict describing the server, or raise with a Thai explanation."""
    try:
        conn = pymysql.connect(**connect_kwargs(db))
    except pymysql.err.OperationalError as e:
        code = e.args[0] if e.args else 0
        if code == 1045:
            raise RuntimeError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง") from e
        if code in (2003, 2002):
            raise RuntimeError(
                "เชื่อมต่อ MySQL ไม่ได้ — ตรวจสอบว่าเปิด MySQL Database ใน XAMPP (manager-osx) แล้ว "
                f"และพอร์ต {db.get('port') or 3306} ถูกต้อง"
            ) from e
        raise RuntimeError(f"เชื่อมต่อไม่ได้: {e}") from e
    try:
        with conn.cursor() as c:
            c.execute("SELECT VERSION()")
            version = c.fetchone()[0]
            c.execute("SHOW DATABASES")
            dbs = [r[0] for r in c.fetchall()]
        name = db.get("name") or "buildweb"
        return {"version": version, "databases": dbs, "exists": name in dbs, "name": name,
                "mariadb": "mariadb" in version.lower()}
    finally:
        conn.close()


def create_database(db):
    name = (db.get("name") or "buildweb").replace("`", "")
    conn = pymysql.connect(**connect_kwargs(db))
    try:
        with conn.cursor() as c:
            c.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
        conn.close()


def table_count(db):
    conn = pymysql.connect(**connect_kwargs(db, with_db=True))
    try:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name LIKE 'builder\\_%%'",
                      (db.get("name") or "buildweb",))
            return c.fetchone()[0]
    finally:
        conn.close()


def manage(args, db=None, timeout=600):
    env = dict(os.environ)
    env.pop("BUILDWEB_DB_FAILED", None)
    if db is not None:
        env["BUILDWEB_DB_OVERRIDE"] = json.dumps(db)
    r = subprocess.run([sys.executable, str(BACKEND / "manage.py"), *args], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "manage.py ล้มเหลว")
    return r.stdout


def switch_database(target, copy_data=True, current=None, replace=False):
    """Migrate the target database and (optionally) copy every record from the current one.

    Steps: create DB (MySQL) → migrate target → dumpdata current → flush target → loaddata → save config.
    Returns a list of log lines. The caller restarts the app so the new connection takes effect.
    """
    current = current or config.load()["db"]
    steps = []
    if target.get("engine") != "mysql" and current.get("engine") != "mysql":
        copy_data = False  # SQLite -> the same SQLite file

    if target.get("engine") == "mysql":
        test_mysql(target)
        create_database(target)
        steps.append("สร้างฐานข้อมูล (ถ้ายังไม่มี) เรียบร้อย")
        if copy_data and not replace and table_count(target) and has_sites(target):
            raise RuntimeError("ฐานข้อมูลปลายทางมีข้อมูลเว็บอยู่แล้ว — เลือก “แทนที่ข้อมูลปลายทาง” หรือ “ใช้ข้อมูลที่มีอยู่”")
    manage(["migrate", "--noinput"], db=target)
    steps.append("สร้างตาราง (migrate) เรียบร้อย")
    if copy_data:
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "data.json"
            excludes = [arg for app in DUMP_EXCLUDE for arg in ("--exclude", app)]
            manage(["dumpdata", "--natural-foreign", "--natural-primary", *excludes, "-o", str(dump)], db=current)
            manage(["flush", "--noinput"], db=target)
            manage(["loaddata", str(dump)], db=target)
        steps.append("คัดลอกข้อมูลทั้งหมดไปฐานข้อมูลใหม่เรียบร้อย")
    config.update("db", target)
    steps.append("บันทึกการตั้งค่าแล้ว — กำลังรีสตาร์ท")
    return steps


def has_sites(db):
    conn = pymysql.connect(**connect_kwargs(db, with_db=True))
    try:
        with conn.cursor() as c:
            try:
                c.execute("SELECT COUNT(*) FROM builder_site")
            except pymysql.err.ProgrammingError:
                return False
            return c.fetchone()[0] > 0
    finally:
        conn.close()


def restart_soon(delay=0.8):
    """Re-exec this process (same PID, so the desktop shell keeps tracking it) after the response is sent."""

    def go():
        time.sleep(delay)
        os.environ.pop("BUILDWEB_DB_FAILED", None)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=go, daemon=True).start()


def xampp_info():
    installed = config.XAMPP_DIR.exists()
    return {
        "installed": installed,
        "socket": str(config.XAMPP_SOCKET) if config.XAMPP_SOCKET.exists() else "",
        "htdocs": str(config.XAMPP_HTDOCS) if config.XAMPP_HTDOCS.exists() else "",
        "manager": str(config.XAMPP_DIR / "manager-osx.app") if installed else "",
        "phpmyadmin": "http://localhost/phpmyadmin/",
    }
