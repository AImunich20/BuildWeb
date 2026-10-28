import re
from pathlib import PurePosixPath

from django.db import models
from django.utils import timezone

DEFAULT_THEME = {
    "primary": "#7c3aed",
    "secondary": "#06b6d4",
    "accent": "#f59e0b",
    "text": "#1f2937",
    "muted": "#6b7280",
    "background": "#ffffff",
    "surface": "#f5f3ff",
    "font_heading": "Prompt",
    "font_body": "Sarabun",
    "radius": "14px",
    "max_width": "1140px",
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify_th(text, fallback="page"):
    """Slug for URLs/file names. Thai titles have no ASCII letters, so fall back to a generic name."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or fallback


class Site(models.Model):
    name = models.CharField("ชื่อเว็บ", max_length=200)
    slug = models.SlugField("ชื่อในลิงก์", max_length=80, unique=True)
    description = models.TextField("คำอธิบาย", blank=True)
    language = models.CharField("ภาษา", max_length=10, default="th")
    theme = models.JSONField("ธีม", default=dict, blank=True)
    nav = models.JSONField("ตั้งค่าแถบเมนู", default=dict, blank=True)
    favicon = models.CharField("ไอคอนเว็บ (favicon)", max_length=500, blank=True)
    head_code = models.TextField("โค้ดใน <head> ทุกหน้า", blank=True)
    custom_css = models.TextField("CSS ทุกหน้า", blank=True)
    custom_js = models.TextField("JavaScript ทุกหน้า", blank=True)
    form_endpoint = models.CharField(
        "ที่ส่งฟอร์ม (เมื่อส่งออกเป็นไฟล์)", max_length=500, blank=True,
        help_text="เว้นว่าง = ใช้ตัวรับฟอร์มของ BuildWeb เมื่อโฮสต์ หรือ bw-form.php เมื่อส่งออกไป XAMPP",
    )
    published = models.BooleanField("เผยแพร่", default=True)
    host_port = models.PositiveIntegerField(
        "พอร์ตเฉพาะของเว็บนี้", null=True, blank=True, unique=True,
        help_text="เว้นว่าง = เปิดที่ /<ชื่อในลิงก์>/ บนพอร์ตโฮสติ้งหลัก · ใส่พอร์ต = เปิดเว็บนี้ที่ / ของพอร์ตนั้นด้วย",
    )
    use_base_styles = models.BooleanField(
        "ใช้สไตล์พื้นฐานของ BuildWeb", default=True,
        help_text="ปิดสำหรับเว็บที่นำเข้า เพื่อให้หน้าตาเหมือนต้นฉบับ (ไม่ใส่ฟอนต์/รีเซ็ต CSS ของธีม)",
    )
    base_url = models.CharField(
        "ที่อยู่เว็บจริง", max_length=300, blank=True,
        help_text="เช่น https://myshop.com/ — ใช้ใน sitemap.xml, RSS และลิงก์ตอนแชร์ (ตั้งให้เองหลังเผยแพร่ครั้งแรก)",
    )
    contact = models.JSONField("ปุ่มติดต่อลอย", default=dict, blank=True)
    publish = models.JSONField("ปลายทางเผยแพร่", default=dict, blank=True)  # {"github": {...}, "netlify": {...}, "ftp": {...}}
    api = models.JSONField("ตั้งค่า REST API", default=dict, blank=True)  # {"enabled", "cors", "rate", "log"}
    auth = models.JSONField("ตั้งค่าสมาชิก", default=dict, blank=True)  # see members.SETTINGS
    secrets = models.JSONField("ค่าลับ", default=dict, blank=True)  # {"NAME": "value"} used as {{secret.NAME}} server-side
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "เว็บไซต์"
        verbose_name_plural = "เว็บไซต์"

    def __str__(self):
        return self.name

    def get_theme(self):
        return {**DEFAULT_THEME, **(self.theme or {})}

    def home_page(self):
        return self.pages.filter(is_home=True).first() or self.pages.order_by("nav_order", "id").first()

    def touch(self):
        Site.objects.filter(pk=self.pk).update(updated_at=timezone.now())


class Page(models.Model):
    DRAFT, PUBLISHED = "draft", "published"
    STATUS = [(DRAFT, "ฉบับร่าง"), (PUBLISHED, "เผยแพร่แล้ว")]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="pages")
    title = models.CharField("ชื่อหน้า", max_length=200)
    slug = models.SlugField("ชื่อไฟล์/ลิงก์", max_length=80)
    is_home = models.BooleanField("หน้าแรก", default=False)
    status = models.CharField("สถานะ", max_length=12, choices=STATUS, default=PUBLISHED)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children",
                               verbose_name="อยู่ใต้หน้า")
    show_in_nav = models.BooleanField("แสดงในเมนู", default=True)
    use_header = models.BooleanField("ใช้ส่วนหัวร่วม", default=True)
    use_footer = models.BooleanField("ใช้ส่วนท้ายร่วม", default=True)
    nav_label = models.CharField("ชื่อในเมนู", max_length=100, blank=True)
    nav_order = models.IntegerField("ลำดับ", default=0)
    seo_title = models.CharField("SEO: ชื่อเรื่อง", max_length=200, blank=True)
    seo_description = models.TextField("SEO: คำอธิบาย", blank=True)
    seo_keywords = models.CharField("SEO: คีย์เวิร์ด", max_length=300, blank=True)
    og_image = models.CharField("รูปตอนแชร์ (og:image)", max_length=500, blank=True)
    noindex = models.BooleanField("ไม่ให้ Google เก็บหน้า", default=False)
    head_code = models.TextField("โค้ดใน <head>", blank=True)
    body_class = models.CharField("คลาสของ <body>", max_length=300, blank=True)
    custom_css = models.TextField("CSS เฉพาะหน้า", blank=True)
    custom_js = models.TextField("JavaScript เฉพาะหน้า", blank=True)
    project_data = models.JSONField(default=dict, blank=True)  # GrapesJS project (components + styles)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)  # scripts of interactive components (tabs, countdown, ...)
    # Detail page: rendered once per row of ``collection`` at <slug>/<row>.html, with {{field}} = that row.
    collection = models.ForeignKey("Collection", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="detail_pages", verbose_name="หน้ารายละเอียดของชุดข้อมูล")
    detail_field = models.CharField("ฟิลด์ที่ใช้ตั้งชื่อลิงก์", max_length=60, blank=True)
    # "" = everyone · "members" = signed-in site users · "role:vip,staff" = those roles only
    access = models.CharField("ใครเปิดหน้านี้ได้", max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nav_order", "id"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="unique_page_slug")]
        verbose_name = "หน้า"
        verbose_name_plural = "หน้า"

    def __str__(self):
        return f"{self.site.name} / {self.title}"

    @property
    def filename(self):
        return "index.html" if self.is_home else f"{self.slug}.html"

    @property
    def is_detail(self):
        return self.collection_id is not None

    @property
    def menu_label(self):
        return self.nav_label or self.title

    @property
    def is_published(self):
        return self.status == self.PUBLISHED

    def make_home(self):
        Page.objects.filter(site=self.site).exclude(pk=self.pk).update(is_home=False)
        if not self.is_home:
            self.is_home = True
            self.save(update_fields=["is_home"])


class SharedSection(models.Model):
    """Header/footer shown on every page of a site (edited once, in its own editor)."""

    HEADER, FOOTER = "header", "footer"
    KINDS = [(HEADER, "ส่วนหัวร่วม"), (FOOTER, "ส่วนท้ายร่วม")]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="shared_sections")
    kind = models.CharField(max_length=10, choices=KINDS)
    enabled = models.BooleanField("เปิดใช้", default=True)
    # Header only: generated from Site.nav settings (True) or designed freely in the editor (False).
    managed = models.BooleanField("สร้างจากตัวตั้งค่าแถบเมนู", default=False)
    project_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "kind"], name="unique_shared_kind")]
        verbose_name = "ส่วนหัว/ท้ายร่วม"
        verbose_name_plural = "ส่วนหัว/ท้ายร่วม"

    def __str__(self):
        return f"{self.site.name} / {self.get_kind_display()}"

    @property
    def label(self):
        return self.get_kind_display()


class PageRevision(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="revisions")
    note = models.CharField(max_length=200, blank=True)
    project_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    KEEP = 40

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "เวอร์ชันของหน้า"
        verbose_name_plural = "เวอร์ชันของหน้า"

    @classmethod
    def snapshot(cls, page, note=""):
        rev = cls.objects.create(page=page, note=note, project_data=page.project_data, html=page.html, css=page.css,
                                 js=page.js)
        old = cls.objects.filter(page=page).values_list("id", flat=True)[cls.KEEP:]
        cls.objects.filter(id__in=list(old)).delete()
        return rev


def asset_upload_to(instance, filename):
    folder = instance.folder.strip("/")
    parts = ["sites", instance.site.slug] + ([folder] if folder else []) + [filename]
    return "/".join(parts)


class Asset(models.Model):
    KINDS = [("image", "รูปภาพ"), ("video", "วิดีโอ"), ("audio", "เสียง"), ("document", "เอกสาร"), ("other", "อื่นๆ")]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="assets")
    file = models.FileField(upload_to=asset_upload_to, max_length=500)
    name = models.CharField(max_length=255)
    folder = models.CharField(max_length=255, blank=True, default="")
    kind = models.CharField(max_length=12, choices=KINDS, default="other")
    size = models.BigIntegerField(default=0)
    alt = models.CharField("คำอธิบายรูป (alt)", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["folder", "name"]
        verbose_name = "ไฟล์"
        verbose_name_plural = "ไฟล์"

    def __str__(self):
        return self.name

    @property
    def url(self):
        return self.file.url

    @staticmethod
    def kind_for(name):
        ext = PurePosixPath(name).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".ico", ".bmp"}:
            return "image"
        if ext in {".mp4", ".webm", ".mov", ".m4v", ".ogv"}:
            return "video"
        if ext in {".mp3", ".wav", ".ogg", ".m4a", ".aac"}:
            return "audio"
        if ext in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".zip"}:
            return "document"
        return "other"


class AssetFolder(models.Model):
    """Folders exist implicitly through Asset.folder; this keeps empty ones the user created."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="folders")
    path = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "path"], name="unique_asset_folder")]


class FormSubmission(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="submissions")
    page = models.ForeignKey(Page, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions")
    form_name = models.CharField(max_length=200, blank=True)
    data = models.JSONField(default=dict)
    ip = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ข้อมูลจากฟอร์ม"
        verbose_name_plural = "ข้อมูลจากฟอร์ม"


class DataConnection(models.Model):
    """A MySQL/MariaDB server (usually XAMPP) that collections can import from or read live."""

    name = models.CharField("ชื่อการเชื่อมต่อ", max_length=100)
    host = models.CharField(max_length=200, default="127.0.0.1")
    port = models.PositiveIntegerField(default=3306)
    user = models.CharField(max_length=100, default="root")
    password = models.CharField(max_length=200, blank=True)
    database = models.CharField(max_length=100, blank=True)
    socket = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "การเชื่อมต่อฐานข้อมูล"
        verbose_name_plural = "การเชื่อมต่อฐานข้อมูล"

    def __str__(self):
        return f"{self.name} ({self.user}@{self.host}:{self.port}/{self.database})"

    def as_config(self, database=None):
        return {"host": self.host, "port": self.port, "user": self.user, "password": self.password,
                "name": database if database is not None else self.database, "socket": self.socket}


class Collection(models.Model):
    """A table of data a site's pages can show (repeat blocks, {{placeholders}})."""

    COPY, LIVE = "copy", "live"
    MODES = [(COPY, "เก็บไว้ใน BuildWeb"), (LIVE, "เชื่อมสดกับ MySQL")]
    FIELD_TYPES = ["text", "longtext", "html", "number", "bool", "date", "datetime", "email", "link", "image", "select",
                   "relation", "json"]  # labels and validation: schema.py

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="collections")
    name = models.CharField("ชื่อ", max_length=120)
    slug = models.SlugField("ชื่อที่ใช้อ้างอิง", max_length=60)
    fields = models.JSONField(default=list, blank=True)  # [{"name", "label", "type"}]
    mode = models.CharField(max_length=8, choices=MODES, default=COPY)
    connection = models.ForeignKey(DataConnection, null=True, blank=True, on_delete=models.SET_NULL, related_name="collections")
    source_database = models.CharField(max_length=100, blank=True)
    source_table = models.CharField(max_length=100, blank=True)
    live_order = models.CharField(max_length=100, blank=True)
    live_desc = models.BooleanField(default=False)
    live_limit = models.PositiveIntegerField(default=500)
    # {"forms": accept form posts, "auto_approve": show them without review, "rss": include in rss.xml}
    options = models.JSONField(default=dict, blank=True)
    last_synced = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="unique_collection_slug")]
        verbose_name = "ชุดข้อมูล"
        verbose_name_plural = "ชุดข้อมูล"

    def __str__(self):
        return f"{self.site.name} / {self.name}"

    @property
    def field_names(self):
        return [f["name"] for f in self.fields]

    def opt(self, key):
        return bool((self.options or {}).get(key))


class Record(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="records")
    data = models.JSONField(default=dict)
    position = models.IntegerField(default=0)
    approved = models.BooleanField("แสดงบนเว็บ", default=True)  # rows sent from a form wait for approval
    owner = models.ForeignKey("SiteUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="records",
                              verbose_name="เจ้าของแถว")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "แถวข้อมูล"
        verbose_name_plural = "แถวข้อมูล"


class Stat(models.Model):
    """Visitor counts of the hosting server, aggregated per day.
    kind: views (key ""), visitors (key ""), page (key = path), ref (key = referrer host), device (mobile/desktop)."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="stats")
    day = models.DateField()
    kind = models.CharField(max_length=10)
    key = models.CharField(max_length=200, blank=True, default="")
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "day", "kind", "key"], name="unique_stat")]
        indexes = [models.Index(fields=["site", "day"])]
        verbose_name = "สถิติผู้เข้าชม"
        verbose_name_plural = "สถิติผู้เข้าชม"


class ApiKey(models.Model):
    """A key for a site's REST API. Only a SHA-256 hash is stored; the key is shown once when created."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField("ชื่อ", max_length=100)
    prefix = models.CharField(max_length=16, db_index=True)  # first characters, to find the key and show it
    key_hash = models.CharField(max_length=64)
    write = models.BooleanField("เขียนข้อมูลได้", default=False)
    collections = models.JSONField(default=list, blank=True)  # [] = every collection
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API key"
        verbose_name_plural = "API keys"

    def __str__(self):
        return f"{self.site.name} / {self.name} ({self.prefix}…)"

    def allows(self, collection_slug, write=False):
        if self.revoked or (write and not self.write):
            return False
        return not self.collections or collection_slug in self.collections


class ApiLog(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="api_logs")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    status = models.PositiveSmallIntegerField()
    ms = models.PositiveIntegerField(default=0)
    key = models.ForeignKey(ApiKey, null=True, blank=True, on_delete=models.SET_NULL)
    ip = models.CharField(max_length=64, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "บันทึกการเรียก API"
        verbose_name_plural = "บันทึกการเรียก API"


class SiteUser(models.Model):
    """A member of one site (visitors who sign up on the site) — not a user of the BuildWeb app."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="members")
    email = models.EmailField("อีเมล")
    name = models.CharField("ชื่อ", max_length=150, blank=True)
    password = models.CharField(max_length=200, blank=True)  # Django password hash
    role = models.CharField("บทบาท", max_length=40, default="member")
    is_active = models.BooleanField("ใช้งานได้", default=True)
    email_verified = models.BooleanField("ยืนยันอีเมลแล้ว", default=False)
    profile = models.JSONField(default=dict, blank=True)  # extra fields (phone, address...)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["site", "email"], name="unique_member_email")]
        verbose_name = "สมาชิกของเว็บ"
        verbose_name_plural = "สมาชิกของเว็บ"

    def __str__(self):
        return f"{self.email} ({self.site.slug})"


class UserToken(models.Model):
    """Session / email-verification / password-reset tokens of site users (only a SHA-256 hash is stored)."""

    SESSION, VERIFY, RESET = "session", "verify", "reset"
    user = models.ForeignKey(SiteUser, on_delete=models.CASCADE, related_name="tokens")
    kind = models.CharField(max_length=10, default=SESSION)
    token_hash = models.CharField(max_length=64, db_index=True)
    expires = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)


class Webhook(models.Model):
    """POST a JSON event to a URL when data changes (n8n, Make, Zapier, LINE bots, your own server)."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="webhooks")
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=500)
    events = models.JSONField(default=list, blank=True)       # [] = every event
    collections = models.JSONField(default=list, blank=True)  # [] = every collection
    headers = models.JSONField(default=dict, blank=True)      # values may use {{secret.NAME}}
    signing_secret = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Connector(models.Model):
    """Pull rows from an external JSON API into a collection (on demand or on a schedule)."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="connectors")
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=1000)
    method = models.CharField(max_length=8, default="GET")
    headers = models.JSONField(default=dict, blank=True)
    body = models.TextField(blank=True)
    items_path = models.CharField(max_length=200, blank=True)  # e.g. "data.items"; empty = the response itself
    collection = models.ForeignKey("Collection", null=True, blank=True, on_delete=models.SET_NULL, related_name="connectors")
    key_field = models.CharField(max_length=100, blank=True)  # update rows with the same key instead of replacing all
    last_run = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Function(models.Model):
    """A server function written in Python, served at <site>/api/v1/fn/<slug>."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="functions")
    slug = models.SlugField(max_length=60)
    name = models.CharField(max_length=100, blank=True)
    code = models.TextField(blank=True)
    access = models.CharField(max_length=10, default="key")  # public | user | key | off
    timeout = models.PositiveSmallIntegerField(default=10)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="unique_function_slug")]


class Job(models.Model):
    """Something to run on a schedule: "every 15m", "every 2h", "daily 09:00", "weekly mon 09:00"."""

    ACTIONS = ["call_url", "sync_mysql", "run_connector", "run_function", "purge_rows"]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="jobs")
    name = models.CharField(max_length=100)
    schedule = models.CharField(max_length=60, default="daily 09:00")
    action = models.CharField(max_length=20, default="call_url")
    params = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)
    last_ok = models.BooleanField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class RunLog(models.Model):
    """History of webhook deliveries, scheduled jobs, connector syncs and function calls."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="run_logs")
    kind = models.CharField(max_length=12)  # webhook | job | connector | function
    ref = models.CharField(max_length=100, blank=True)  # name of the webhook/job/...
    ok = models.BooleanField(default=True)
    status = models.CharField(max_length=40, blank=True)
    ms = models.PositiveIntegerField(default=0)
    message = models.CharField(max_length=300, blank=True)
    detail = models.TextField(blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-at"]
