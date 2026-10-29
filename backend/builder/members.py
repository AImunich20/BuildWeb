"""Members of a site: visitors who sign up and log in on the site itself (not users of the BuildWeb app).

- Passwords use Django's hashers (PBKDF2). Sessions, email-verification and password-reset links are random
  tokens of which only a SHA-256 hash is stored.
- Browsers keep the session in an HttpOnly, SameSite=Lax cookie (``bw_u<site id>``); apps send
  ``Authorization: Bearer bwu_…``.
- Pages can be limited to members or to roles (Page.access); collection API rules can be "user" (any signed-in
  member) or "owner" (only the member who created the row).
- Endpoints live under <site>/api/v1/auth/ (see restapi.route_auth). They work whether or not the collections
  API is switched on, but only when members are enabled for the site.
"""
import hashlib
import re
import secrets
import threading
import time
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import SiteUser, UserToken

SETTINGS = {
    "enabled": False,
    "signup": True,           # anyone may register (off = members are added in the app only)
    "verify_email": False,    # new members must click the link in an email before they can log in
    "roles": ["member"],      # roles the owner hands out; "admin" always exists and may do everything
    "default_role": "member",
    "min_password": 8,
    "after_login": "",        # page to go to after logging in (default: account page or home)
    "pages": {},              # {"login": "login.html", "register": ..., "forgot": ..., "reset": ..., "account": ...}
}
SESSION_DAYS = 30
TOKEN_TTL = {UserToken.SESSION: timedelta(days=SESSION_DAYS), UserToken.VERIFY: timedelta(days=3),
             UserToken.RESET: timedelta(hours=2)}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLE_RE = re.compile(r"^[a-z0-9_-]{1,40}$")

_attempts = {}
_lock = threading.Lock()


class AuthError(Exception):
    def __init__(self, status, code, message, fields=None):
        super().__init__(message)
        self.status, self.code, self.fields = status, code, fields


def settings(site):
    s = {**SETTINGS, **(site.auth or {})}
    s["pages"] = {**default_pages(), **(s.get("pages") or {})}
    roles = [r for r in (s.get("roles") or []) if ROLE_RE.match(r)] or ["member"]
    s["roles"] = roles
    if s["default_role"] not in roles:
        s["default_role"] = roles[0]
    return s


def default_pages():
    return {"login": "login.html", "register": "register.html", "forgot": "forgot.html", "reset": "reset.html",
            "account": "account.html"}


def all_roles(site):
    return ["admin"] + [r for r in settings(site)["roles"] if r != "admin"]


def user_json(u, full=False):
    out = {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "email_verified": u.email_verified,
           "profile": u.profile or {}, "created_at": u.created_at.isoformat(timespec="seconds")}
    if full:
        out.update({"is_active": u.is_active, "last_login": u.last_login.isoformat(timespec="seconds") if u.last_login else None})
    return out


# --- tokens ---------------------------------------------------------------------------------------

def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue(user, kind=UserToken.SESSION, user_agent=""):
    plain = "bwu_" + secrets.token_urlsafe(32)
    UserToken.objects.create(user=user, kind=kind, token_hash=_hash(plain), expires=timezone.now() + TOKEN_TTL[kind],
                             user_agent=(user_agent or "")[:200])
    if kind == UserToken.SESSION:  # forget expired sessions now and then
        UserToken.objects.filter(user=user, expires__lt=timezone.now()).delete()
    return plain


def consume(site, plain, kind, delete=False):
    """The user a token belongs to (None when unknown/expired). ``delete``: one-time tokens."""
    if not plain or not plain.startswith("bwu_"):
        return None
    tok = (UserToken.objects.select_related("user").filter(token_hash=_hash(plain), kind=kind, user__site=site,
                                                            expires__gt=timezone.now()).first())
    if not tok or not tok.user.is_active:
        return None
    user = tok.user
    if delete:
        tok.delete()
    elif not tok.last_used or (timezone.now() - tok.last_used).total_seconds() > 300:
        UserToken.objects.filter(pk=tok.pk).update(last_used=timezone.now())
    return user


def cookie_name(site):
    return f"bw_u{site.id}"


def request_token(request, site):
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth.lower().startswith("bearer ") and auth[7:].strip().startswith("bwu_"):
        return auth[7:].strip()
    return request.COOKIES.get(cookie_name(site), "")


def current_user(request, site):
    """The signed-in member of ``site`` for this request (cached on the request), or None."""
    cache = getattr(request, "_bw_users", None)
    if cache is None:
        cache = request._bw_users = {}
    if site.id not in cache:
        cache[site.id] = None
        if settings(site)["enabled"]:
            cache[site.id] = consume(site, request_token(request, site), UserToken.SESSION)
    return cache[site.id]


# --- access ---------------------------------------------------------------------------------------

def page_roles(page):
    a = (page.access or "").strip()
    if a.startswith("role:"):
        return [r.strip() for r in a[5:].split(",") if r.strip()]
    return None


def can_view(page, user):
    a = (page.access or "").strip()
    if not a:
        return True
    if a == "rules":
        from . import access

        return access.evaluate(page, user)[0]
    if user is None:
        return False
    if a == "members" or user.role == "admin":
        return True
    roles = page_roles(page)
    return roles is None or user.role in roles


# --- throttling -----------------------------------------------------------------------------------

def throttle(key, limit=8, window=300):
    """Allow ``limit`` failed attempts per ``window`` seconds for ``key`` (an IP or an email)."""
    now = time.time()
    with _lock:
        hits = [t for t in _attempts.get(key, []) if now - t < window]
        _attempts[key] = hits
        if len(hits) >= limit:
            raise AuthError(429, "too_many_attempts", "ลองหลายครั้งเกินไป กรุณารอ 5 นาทีแล้วลองใหม่")


def failed(key):
    with _lock:
        _attempts.setdefault(key, []).append(time.time())


# --- actions --------------------------------------------------------------------------------------

def check_password_rules(site, password):
    n = settings(site)["min_password"]
    if len(password or "") < n:
        raise AuthError(422, "validation", f"รหัสผ่านต้องยาวอย่างน้อย {n} ตัวอักษร", {"password": f"อย่างน้อย {n} ตัวอักษร"})
    if password.isdigit() and len(set(password)) <= 2:
        raise AuthError(422, "validation", "รหัสผ่านเดาง่ายเกินไป", {"password": "เดาง่ายเกินไป"})


def clean_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError(422, "validation", "อีเมลไม่ถูกต้อง", {"email": "อีเมลไม่ถูกต้อง"})
    return email


def create_user(site, email, password="", name="", role=None, verified=False, profile=None):
    email = clean_email(email)
    if site.members.filter(email=email).exists():
        raise AuthError(409, "exists", "อีเมลนี้สมัครไว้แล้ว", {"email": "อีเมลนี้สมัครไว้แล้ว"})
    if password:
        check_password_rules(site, password)
    role = role if role in all_roles(site) else settings(site)["default_role"]
    return SiteUser.objects.create(site=site, email=email, name=(name or "").strip()[:150], role=role,
                                   password=make_password(password) if password else "", email_verified=verified,
                                   profile=profile or {})


def register(site, d, ip):
    s = settings(site)
    if not s["signup"]:
        raise AuthError(403, "signup_closed", "ปิดรับสมัครสมาชิก")
    throttle(f"reg:{site.id}:{ip}", limit=10, window=3600)
    failed(f"reg:{site.id}:{ip}")  # counts every registration from this IP
    user = create_user(site, d.get("email"), d.get("password") or "", d.get("name"),
                       verified=not s["verify_email"], profile=clean_profile(d.get("profile")))
    return user


def login(site, email, password, ip):
    email = (email or "").strip().lower()
    for k in (f"ip:{site.id}:{ip}", f"em:{site.id}:{email}"):
        throttle(k)
    user = site.members.filter(email=email).first()
    if not user or not user.password or not check_password(password or "", user.password):
        failed(f"ip:{site.id}:{ip}")
        failed(f"em:{site.id}:{email}")
        raise AuthError(401, "invalid_login", "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    if not user.is_active:
        raise AuthError(403, "inactive", "บัญชีนี้ถูกระงับ")
    if settings(site)["verify_email"] and not user.email_verified:
        raise AuthError(403, "unverified", "กรุณายืนยันอีเมลก่อน (ดูลิงก์ในอีเมลที่ส่งไป)")
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return user


def logout(site, request):
    plain = request_token(request, site)
    if plain:
        UserToken.objects.filter(token_hash=_hash(plain), kind=UserToken.SESSION).delete()


def clean_profile(p):
    if not isinstance(p, dict):
        return {}
    return {str(k)[:40]: str(v)[:500] for k, v in list(p.items())[:30] if not isinstance(v, (dict, list))}


def update_me(user, d):
    if "name" in d:
        user.name = str(d["name"] or "").strip()[:150]
    if "profile" in d:
        user.profile = {**(user.profile or {}), **clean_profile(d["profile"])}
    if d.get("new_password"):
        if user.password and not check_password(d.get("current_password") or "", user.password):
            raise AuthError(422, "validation", "รหัสผ่านปัจจุบันไม่ถูกต้อง", {"current_password": "ไม่ถูกต้อง"})
        check_password_rules(user.site, d["new_password"])
        user.password = make_password(d["new_password"])
        UserToken.objects.filter(user=user, kind=UserToken.SESSION).delete()  # log out everywhere else
    user.save()
    return user


def reset_password(site, token, password):
    user = consume(site, token, UserToken.RESET, delete=True)
    if not user:
        raise AuthError(400, "invalid_token", "ลิงก์ตั้งรหัสผ่านหมดอายุหรือถูกใช้ไปแล้ว ขอลิงก์ใหม่ได้ที่หน้าลืมรหัสผ่าน")
    check_password_rules(site, password)
    user.password = make_password(password)
    user.email_verified = True  # they proved they own the mailbox
    user.save(update_fields=["password", "email_verified"])
    UserToken.objects.filter(user=user, kind__in=(UserToken.SESSION, UserToken.RESET)).delete()
    return user


def verify_email(site, token):
    user = consume(site, token, UserToken.VERIFY, delete=True)
    if user:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    return user


# --- emails ---------------------------------------------------------------------------------------

def page_url(site, base, key, token=""):
    return base.rstrip("/") + "/" + settings(site)["pages"][key] + (f"?token={token}" if token else "")


def send_reset(site, user, base):
    token = issue(user, UserToken.RESET)
    link = page_url(site, base, "reset", token)
    mail(site, user.email, f"ตั้งรหัสผ่านใหม่ · {site.name}",
         f"สวัสดีคุณ{user.name or ''}\n\nกดลิงก์นี้เพื่อตั้งรหัสผ่านใหม่ (ใช้ได้ 2 ชั่วโมง):\n{link}\n\n"
         f"ถ้าคุณไม่ได้ขอ ไม่ต้องทำอะไร รหัสผ่านเดิมยังใช้ได้\n\n— {site.name}")
    return link


def send_verify(site, user, base):
    token = issue(user, UserToken.VERIFY)
    link = base.rstrip("/") + f"/api/v1/auth/verify?token={token}"
    mail(site, user.email, f"ยืนยันอีเมล · {site.name}",
         f"ยินดีต้อนรับสู่ {site.name}\n\nกดลิงก์นี้เพื่อยืนยันอีเมลของคุณ (ใช้ได้ 3 วัน):\n{link}\n\n— {site.name}")
    return link


def mail(site, to, subject, text):
    from . import notify

    notify.send_mail_to(to, subject, text, from_name=site.name)
