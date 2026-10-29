"""The "server kit": everything needed to run BuildWeb on a Linux server with Docker — the backend code, a
Dockerfile, docker-compose.yml (BuildWeb + Caddy for automatic HTTPS, PostgreSQL optional), a .env with fresh
random tokens, the site itself as a seed, and a Thai README. The desktop app then deploys to it."""
import io
import secrets
import zipfile
from pathlib import Path

from buildweb import config

from . import backup

SKIP_DIRS = {".venv", ".data", "__pycache__", "node_modules", ".pytest_cache"}
SKIP_FILES = {"tests.py", ".DS_Store"}

DOCKERFILE = """FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 BUILDWEB_SERVER=1 BUILDWEB_DATA=/data PORT=8090
WORKDIR /app
COPY backend/requirements.txt backend/requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-server.txt
COPY backend/ /app/
COPY seed/ /app/seed/
RUN useradd -r -u 1000 buildweb && mkdir -p /data && chown -R buildweb /data /app
USER buildweb
VOLUME /data
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/__bw/health')"
CMD ["python", "server.py"]
"""

COMPOSE = """services:
  buildweb:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - buildweb-data:/data
    # with PostgreSQL: uncomment the "db" service below and set BUILDWEB_DATABASE_URL in .env
    # depends_on: [db]
  caddy:
    image: caddy:2
    restart: unless-stopped
    env_file: .env
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    depends_on: [buildweb]
  # db:
  #   image: postgres:16
  #   restart: unless-stopped
  #   environment:
  #     POSTGRES_DB: buildweb
  #     POSTGRES_USER: buildweb
  #     POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  #   volumes:
  #     - pg-data:/var/lib/postgresql/data
volumes:
  buildweb-data:
  caddy-data:
  caddy-config:
  # pg-data:
"""

CADDYFILE = """# Caddy gets and renews HTTPS certificates automatically.
# - domains in SITE_DOMAINS (.env): at start
# - domains connected later from the app (เผยแพร่ › โดเมน / Cloudflare): on their first visit, after BuildWeb
#   confirms the domain belongs to one of its sites (/__bw/domain-check), so nobody else can make Caddy ask for certificates
# Without a domain (testing by IP) change the SITE_DOMAINS line in .env to  :80
{
\ton_demand_tls {
\t\task http://buildweb:8090/__bw/domain-check
\t}
}

{$SITE_DOMAINS} {
\tencode zstd gzip
\treverse_proxy buildweb:8090
}

https:// {
\ttls {
\t\ton_demand
\t}
\tencode zstd gzip
\treverse_proxy buildweb:8090
}
"""

README = """# BuildWeb Server — {name}

เซิร์ฟเวอร์สำหรับเว็บ “{name}” ที่มี backend ครบ: REST API, ระบบสมาชิก, ฟอร์ม, ฟังก์ชัน, งานตั้งเวลา
ออกแบบเว็บต่อในแอป BuildWeb บนเครื่องคุณ แล้วกด “Deploy” ข้อมูลที่เกิดบนเซิร์ฟเวอร์ (คำสั่งซื้อ สมาชิก ข้อความจากฟอร์ม) จะไม่ถูกทับ

## สิ่งที่ต้องมี
- เซิร์ฟเวอร์ Linux (VPS) RAM 1 GB ขึ้นไป เช่น DigitalOcean, Vultr, Linode, AWS Lightsail, หรือ VPS ไทย
- โดเมนที่ชี้ A record มาที่ IP ของเซิร์ฟเวอร์ ({domain})
- เปิดพอร์ต 80 และ 443

## ติดตั้ง (ครั้งเดียว)
```bash
# 1) ติดตั้ง Docker
curl -fsSL https://get.docker.com | sh

# 2) อัปโหลดโฟลเดอร์นี้ขึ้นเซิร์ฟเวอร์ แล้วเข้าไปในโฟลเดอร์
scp -r buildweb-server root@<IP>:/opt/
ssh root@<IP>
cd /opt/buildweb-server

# 3) ตรวจไฟล์ .env (โดเมน, รหัสผ่าน) แล้วเริ่มทำงาน
docker compose up -d --build
```
เปิด https://{domain}/ ได้ภายใน 1–2 นาที (Caddy ขอใบรับรอง HTTPS ให้เอง)

## เชื่อมกับแอป
แอป BuildWeb › เว็บนี้ › เผยแพร่ & ส่งออก › “เซิร์ฟเวอร์ของฉัน”
- ที่อยู่เซิร์ฟเวอร์: `https://{domain}`
- Deploy token: ค่า `BUILDWEB_DEPLOY_TOKEN` ในไฟล์ .env

## หลังบ้านบนเซิร์ฟเวอร์
https://{domain}/__bw/admin/ — ผู้ใช้ `admin` รหัสผ่านคือ `BUILDWEB_ADMIN_PASSWORD` ใน .env

## งานประจำ
```bash
docker compose logs -f buildweb          # ดู log
docker compose pull && docker compose up -d --build   # อัปเดต
docker compose exec buildweb ls /data/backups         # สำรองอัตโนมัติวันละครั้ง (เก็บ 14 ชุดต่อเว็บ)
```
## เวลาเซิร์ฟเวอร์และโดเมนเพิ่ม
- เขตเวลา: ตั้งจากแอป (เผยแพร่ › เซิร์ฟเวอร์ของฉัน › เวลา & โดเมน) หรือค่า `BUILDWEB_TZ` ใน .env ({tz})
- โดเมนเพิ่ม: เชื่อมจากแอปผ่าน Cloudflare ได้เลย ไม่ต้องแก้ไฟล์บนเซิร์ฟเวอร์ (Caddy ขอ HTTPS ให้ตอนมีคนเปิดครั้งแรก)
- ใช้ proxy ของ Cloudflare (เมฆสีส้ม): ตั้ง SSL/TLS เป็น Full (strict) — แอปตั้งให้เมื่อ token มีสิทธิ์

ใช้ PostgreSQL: เปิดบริการ `db` ใน docker-compose.yml แล้วตั้ง
`BUILDWEB_DATABASE_URL=postgres://buildweb:<POSTGRES_PASSWORD>@db:5432/buildweb` ใน .env
"""


def env_file(site, domain, tz="Asia/Bangkok"):
    return "\n".join([
        "# ตั้งค่าเซิร์ฟเวอร์ BuildWeb — เก็บไฟล์นี้เป็นความลับ",
        f"SITE_DOMAINS={domain or ':80'}",
        f"BUILDWEB_DOMAINS={','.join(f'{d}={site.slug}' for d in domain.split()) if domain else ''}",
        f"BUILDWEB_DEFAULT_SITE={site.slug}",
        f"BUILDWEB_DEPLOY_TOKEN={secrets.token_urlsafe(32)}",
        f"BUILDWEB_ADMIN_PASSWORD={secrets.token_urlsafe(12)}",
        f"BUILDWEB_HTTPS={'1' if domain else '0'}",
        f"BUILDWEB_TZ={tz}",
        f"TZ={tz}",
        "# BUILDWEB_DATABASE_URL=postgres://buildweb:CHANGE_ME@db:5432/buildweb",
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(18)}",
        "",
    ])


def build_kit(site, domain=""):
    """The kit as zip bytes (folder "buildweb-server/")."""
    domain = " ".join(d.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
                      for d in (domain or "").replace(",", " ").split() if d.strip())
    root = "buildweb-server/"
    buf = io.BytesIO()
    backend = config.BACKEND_DIR
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(backend.rglob("*")):
            rel = p.relative_to(backend)
            if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.name in SKIP_FILES or p.suffix == ".pyc":
                continue
            z.write(p, root + "backend/" + str(Path(rel).as_posix()))
        z.writestr(root + "Dockerfile", DOCKERFILE)
        z.writestr(root + "docker-compose.yml", COMPOSE)
        z.writestr(root + "Caddyfile", CADDYFILE)
        from django.conf import settings

        tz = settings.TIME_ZONE
        z.writestr(root + ".env", env_file(site, domain, tz))
        z.writestr(root + ".dockerignore", ".env\n")
        z.writestr(root + "README.md", README.format(name=site.name, domain=domain.split()[0] if domain else "<โดเมน>", tz=tz))
        z.writestr(root + f"seed/{site.slug}.bwsite", backup.export_bytes(site))
    return buf.getvalue()
