import json
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from . import exporter, render, sections, services
from .models import Asset, Collection, FormSubmission, Page, PageRevision, Site

TMP_MEDIA = Path(tempfile.mkdtemp(prefix="bw-media-"))


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class BuildWebTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.c = Client()
        self.c.get("/")  # auto sign-in + CSRF cookie

    def post(self, url, data=None):
        return self.c.post(url, json.dumps(data or {}), content_type="application/json")

    # --- templates & services ---------------------------------------------------------------------

    def test_every_template_builds(self):
        for tpl in sections.TEMPLATES:
            site = services.create_site(f"เว็บ {tpl['id']}", tpl["id"])
            self.assertEqual(site.pages.count(), len(tpl["pages"]))
            self.assertEqual(site.pages.filter(is_home=True).count(), 1)
            files, _ = render.build_files(site)
            self.assertIn("index.html", files)
            self.assertIn("css/site.css", files)

    def test_template_menu_points_at_real_pages(self):
        site = services.create_site("ร้านกาแฟ", "cafe")
        home = site.home_page()
        self.assertNotIn("bw-nav", home.html)  # header lives in the shared section now
        out = render.render_page(home)
        self.assertIn('href="about.html">เกี่ยวกับเรา', out)
        self.assertIn('href="index.html" class="active">หน้าแรก', out)
        self.assertIn("ร้านกาแฟ</a>", out)  # logo uses the site name
        self.assertIn("bw-footer", out)

    def test_shared_sections_edit_once_and_opt_out(self):
        site = services.create_site("Shared", "business")
        header = site.shared_sections.get(kind="header")
        services.save_shared(header, {}, '<header class="x">NEW HEADER <span data-bw-auto-nav>old</span></header>', ".x{color:red}")
        about = site.pages.get(slug="about")
        out = render.render_page(about)
        self.assertIn("NEW HEADER", out)
        self.assertIn('href="about.html" class="active"', out)
        self.assertIn(".x{color:red}", render.site_css(site))
        about.use_header = False
        about.save()
        self.assertNotIn("NEW HEADER", render.render_page(about))
        header.enabled = False
        header.save()
        self.assertNotIn("NEW HEADER", render.render_page(site.home_page()))

    def test_child_pages_become_dropdown(self):
        site = services.create_site("Menu", "business")
        about = site.pages.get(slug="about")
        services.create_page(site, "ทีมงาน", "team", parent_id=about.id)
        out = render.render_page(site.home_page())
        self.assertIn('class="bw-dd"><a href="about.html">', out)
        self.assertIn('href="team.html">ทีมงาน', out)

    def test_extract_shared_from_legacy_pages(self):
        site = services.create_site("Legacy", "blank")
        html, css = sections.compose(["navbar", "hero", "footer"], shared=False)
        for i, slug in enumerate(["home", "about"]):
            Page.objects.update_or_create(site=site, slug=slug, defaults={"title": slug, "html": html, "css": css,
                                                                          "is_home": i == 0})
        changed = services.extract_shared(site)
        self.assertEqual(changed, 2)
        for p in site.pages.all():
            self.assertNotIn("<header", p.html)
            self.assertNotIn("<footer", p.html)
        out = render.render_page(site.pages.get(slug="about"))
        self.assertEqual(out.count("<header"), 1)
        self.assertIn('href="about.html" class="active"', out)

    def test_thai_site_name_gets_ascii_slug(self):
        a = services.create_site("ร้านของฉัน")
        b = services.create_site("ร้านของฉัน")
        self.assertEqual(a.slug, "site")
        self.assertEqual(b.slug, "site-2")

    def test_page_slug_rules(self):
        site = services.create_site("Test")
        self.assertTrue(services.validate_page_slug(site, "css"))
        self.assertTrue(services.validate_page_slug(site, "Bad Slug"))
        self.assertTrue(services.validate_page_slug(site, "home"))  # taken
        self.assertEqual(services.validate_page_slug(site, "about-us"), "")

    def test_delete_home_promotes_next_page(self):
        site = services.create_site("Biz", "business")
        services.delete_page(site.home_page())
        self.assertEqual(site.pages.filter(is_home=True).count(), 1)

    def test_revisions_and_restore(self):
        site = services.create_site("Rev", "landing")
        page = site.home_page()
        services.save_editor(page, {"pages": []}, "<body><p>v2</p></body>", "p{}")
        self.assertEqual(page.revisions.count(), 1)
        rev = page.revisions.first()
        services.restore_revision(rev)
        page.refresh_from_db()
        self.assertNotIn("v2", page.html)
        self.assertEqual(page.revisions.count(), 2)

    # --- rendering ---------------------------------------------------------------------------------

    def test_render_page_document(self):
        site = services.create_site("Doc", "blank")
        page = site.home_page()
        page.html = '<body id="x"><h1>สวัสดี</h1><img src="/media/sites/doc/a.png"></body>'
        page.seo_description = 'คำอธิบาย "พิเศษ"'
        page.js = "console.log(1)"
        page.save()
        out = render.render_page(page, "__form")
        self.assertIn('<html lang="th">', out)
        self.assertIn("<h1>สวัสดี</h1>", out)
        self.assertNotIn("<body id", out)
        self.assertIn('src="assets/sites/doc/a.png"', out)
        self.assertIn("&quot;พิเศษ&quot;", out)
        self.assertIn('data-bw-form="__form"', out)
        self.assertIn("console.log(1)", out)
        self.assertIn("--bw-primary", render.site_css(site))

    def test_drafts_hidden_unless_included(self):
        site = services.create_site("Draft", "business")
        Page.objects.filter(site=site, slug="about").update(status=Page.DRAFT)
        self.assertNotIn("about.html", render.build_files(site)[0])
        self.assertIn("about.html", render.build_files(site, include_drafts=True)[0])

    # --- export ------------------------------------------------------------------------------------

    def test_export_folder_and_zip_with_assets(self):
        site = services.create_site("Export", "business")
        a = Asset(site=site, name="logo.png", kind="image", size=3)
        a.file.save("logo.png", SimpleUploadedFile("logo.png", b"png"), save=False)
        a.save()
        th = Asset(site=site, name="ไฟล์ ไทย.pdf", kind="document", size=3)
        th.file.save("ไฟล์ ไทย.pdf", SimpleUploadedFile("x.pdf", b"pdf"), save=False)
        th.save()
        home = site.home_page()
        home.html += f'<img src="{a.url}"><a href="{th.url}">pdf</a>'
        home.save()
        out = Path(tempfile.mkdtemp())
        try:
            dest, count = exporter.export_folder(site, out / "export", php_forms=True)
            self.assertTrue((dest / "index.html").exists())
            self.assertTrue((dest / "bw-form.php").exists())
            self.assertTrue((dest / "assets" / a.file.name).exists())
            self.assertTrue((dest / "assets" / th.file.name).exists())
            self.assertIn('data-bw-form="bw-form.php"', (dest / "index.html").read_text())
            # re-export over our own folder works; over a foreign folder is refused
            exporter.export_folder(site, dest)
            foreign = out / "foreign"
            foreign.mkdir()
            (foreign / "keep.txt").write_text("x")
            with self.assertRaises(ValueError):
                exporter.export_folder(site, foreign)
            data, _ = exporter.export_zip_bytes(site)
            names = zipfile.ZipFile(BytesIO(data)).namelist()
            self.assertIn(f"{site.slug}/index.html", names)
            self.assertIn(f"{site.slug}/js/site.js", names)
        finally:
            shutil.rmtree(out)

    # --- preview / hosting / forms -----------------------------------------------------------------

    def test_preview_and_form_submission(self):
        site = services.create_site("Forms", "business")
        self.assertEqual(self.c.get(f"/preview/{site.slug}").status_code, 302)
        self.assertEqual(self.c.get(f"/preview/{site.slug}/").status_code, 200)
        self.assertEqual(self.c.get(f"/preview/{site.slug}/contact.html").status_code, 200)
        self.assertEqual(self.c.get(f"/preview/{site.slug}/css/contact.css").status_code, 200)
        self.assertEqual(self.c.get(f"/preview/{site.slug}/nope.html").status_code, 404)
        r = Client(enforce_csrf_checks=True).post(f"/preview/{site.slug}/__form", {"name": "สมชาย", "_form": "contact", "_page": "contact"})
        self.assertEqual(r.status_code, 200)
        sub = FormSubmission.objects.get()
        self.assertEqual(sub.data, {"name": "สมชาย"})
        self.assertEqual(sub.page.slug, "contact")
        csv = self.c.get(f"/sites/{site.id}/forms.csv").content.decode("utf-8-sig")
        self.assertIn("สมชาย", csv)

    def test_public_server_isolation(self):
        site = services.create_site("Pub", "business")
        hidden = services.create_site("Hidden", "blank")
        hidden.published = False
        hidden.save()
        Page.objects.filter(site=site, slug="about").update(status=Page.DRAFT)
        pub = Client(**{"buildweb.public": True})
        self.assertEqual(pub.get(f"/{site.slug}/").status_code, 200)
        self.assertEqual(pub.get(f"/{site.slug}/about.html").status_code, 404)  # draft
        self.assertEqual(pub.get(f"/{hidden.slug}/").status_code, 404)
        self.assertEqual(pub.get("/django-admin/").status_code, 404)
        self.assertEqual(pub.get(f"/api/sites/{site.id}/pages").status_code, 404)
        self.assertEqual(pub.post(f"/{site.slug}/__form", {"a": "1"}).status_code, 200)

    # --- API ---------------------------------------------------------------------------------------

    def test_api_site_and_page_lifecycle(self):
        r = self.post("/api/sites/create", {"name": "API Site", "template": "business"}).json()
        sid = r["site"]["id"]
        r = self.post(f"/api/sites/{sid}/pages/create", {"title": "ราคา", "slug": "pricing", "layout": "services",
                                                        "seo_description": "ราคาสินค้า", "status": "draft"}).json()
        self.assertTrue(r["ok"], r)
        pid = r["page"]["id"]
        self.assertEqual(r["page"]["status"], "draft")
        bad = self.post(f"/api/sites/{sid}/pages/create", {"title": "x", "slug": "pricing"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["field"], "slug")
        self.assertTrue(self.post(f"/api/pages/{pid}/update", {"slug": "prices", "is_home": True}).json()["ok"])
        self.assertTrue(Page.objects.get(pk=pid).is_home)
        save = self.post(f"/api/pages/{pid}/project", {"project": {"pages": [1]}, "html": "<p>x</p>", "css": "", "js": ""})
        self.assertTrue(save.json()["ok"])
        self.assertEqual(self.c.get(f"/api/pages/{pid}/project").json()["project"], {"pages": [1]})
        about = self.c.get(f"/preview/{Site.objects.get(pk=sid).slug}/about.html").content.decode()
        self.assertIn('href="index.html">ราคา', about)  # "prices" is the home page now, menu follows
        self.assertIn('href="home.html">หน้าแรก', about)
        sec = Site.objects.get(pk=sid).shared_sections.get(kind="header")
        self.assertTrue(self.post(f"/api/shared/{sec.id}/project", {"project": {}, "html": "<header>H</header>"}).json()["ok"])
        self.assertEqual(self.c.get(f"/sites/{sid}/edit-shared/header/").status_code, 200)
        self.assertFalse(self.post(f"/api/shared/{sec.id}/update", {"enabled": False}).json()["shared"]["enabled"])
        ids = list(Site.objects.get(pk=sid).pages.values_list("id", flat=True))[::-1]
        self.assertTrue(self.post(f"/api/sites/{sid}/pages/reorder", {"ids": ids}).json()["ok"])
        for path in ("", "files/", "forms/", "settings/", "export/", f"edit/{pid}/"):
            self.assertEqual(self.c.get(f"/sites/{sid}/{path}").status_code, 200, path)
        self.assertTrue(self.post(f"/api/sites/{sid}/update", {"theme": {"primary": "#ff0000", "bogus": 1}}).json()["ok"])
        self.assertEqual(Site.objects.get(pk=sid).theme["primary"], "#ff0000")
        self.assertNotIn("bogus", Site.objects.get(pk=sid).theme)
        self.assertTrue(self.post(f"/api/sites/{sid}/delete").json()["ok"])
        self.assertFalse(Site.objects.filter(pk=sid).exists())

    def test_api_files(self):
        site = services.create_site("Files")
        up = self.c.post(f"/api/sites/{site.id}/assets/upload", {"files": SimpleUploadedFile("รูป ภาพ.png", b"x"), "folder": "img/../a"})
        a = up.json()["data"][0]
        self.assertEqual(a["folder"], "img/a")
        home = site.home_page()
        home.html = f'<img src="{a["url"]}">'
        home.save()
        r = self.post(f"/api/assets/{a['id']}/update", {"name": "logo.png", "folder": "brand"}).json()
        self.assertTrue(r["ok"], r)
        home.refresh_from_db()
        self.assertIn("/media/sites/files/brand/logo.png", home.html)
        self.assertIn("assets/sites/files/brand/logo.png", render.build_files(site)[1])
        self.assertEqual(self.post(f"/api/assets/{a['id']}/delete").status_code, 409)  # in use
        self.assertTrue(self.post(f"/api/assets/{a['id']}/delete", {"force": True}).json()["ok"])
        self.assertTrue(self.post(f"/api/sites/{site.id}/folders/create", {"path": "docs"}).json()["ok"])
        self.assertIn("docs", self.c.get(f"/api/sites/{site.id}/assets").json()["folders"])

    def test_pages_render(self):
        for url in ("/", "/settings/", "/settings/database/", "/django-admin/"):
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_revision_cap(self):
        site = services.create_site("Cap", "landing")
        page = site.home_page()
        for _ in range(PageRevision.KEEP + 5):
            PageRevision.snapshot(page)
        self.assertEqual(page.revisions.count(), PageRevision.KEEP)


def make_zip(files):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


NAV = '<header class="top"><a href="index.html">Home</a> <a href="about.html">About</a></header>'
FOOT = "<footer>© Demo</footer>"


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ImporterTests(TestCase):
    def bundle(self):
        from . import importer

        return importer.from_zip(make_zip({
            "demo-main/index.html": f"""<!doctype html><html><head><title>Demo Home</title>
                <meta name="description" content="หน้าแรกเดโม">
                <link rel="stylesheet" href="css/style.css"><link rel="stylesheet" href="https://cdn.example.com/x.css">
                <script src="https://cdn.example.com/lib.js"></script><style>.hero{{color:red}}</style></head>
                <body class="home dark">{NAV}<header class="hero">Hero</header><img src="img/a.png" srcset="img/a.png 1x, img/a.png 2x">
                <a href="sub/page.html#top">Sub</a><script src="js/app.js"></script><script>console.log('inline')</script>{FOOT}</body></html>""",
            "demo-main/about.html": f"<html><head><title>About</title></head><body>{NAV}<p>about</p>{FOOT}</body></html>",
            "demo-main/sub/page.html": "<html><body><a href='../index.html'>back</a><img src='/img/a.png'></body></html>",
            "demo-main/css/style.css": "body{background:url('../img/bg.jpg')}@import 'more.css';",
            "demo-main/css/more.css": ".more{font-family:x}",
            "demo-main/img/a.png": b"png",
            "demo-main/img/bg.jpg": b"jpg",
            "demo-main/js/app.js": "console.log('app')",
            "demo-main/../evil.txt": "nope",
            "demo-main/.git/config": "x",
        }))

    def test_import_zip_site(self):
        from . import importer

        b = self.bundle()
        self.assertNotIn("../evil.txt", b.files)
        self.assertFalse(any(p.startswith(".git") for p in b.files))
        r = importer.import_bundle(b, name="Demo")
        site = Site.objects.get(pk=r["site_id"])
        self.assertEqual(r["pages"], 3)
        self.assertFalse(site.use_base_styles)
        home = site.home_page()
        self.assertEqual(home.title, "Demo Home")
        self.assertEqual(home.seo_description, "หน้าแรกเดโม")
        self.assertEqual(home.body_class, "home dark")
        self.assertIn("https://cdn.example.com/x.css", home.head_code)
        self.assertIn("https://cdn.example.com/lib.js", home.head_code)
        self.assertIn("console.log('app')", home.custom_js)
        self.assertIn("console.log('inline')", home.custom_js)
        self.assertIn(".hero{color:red}", home.css)
        self.assertIn('href="sub-page.html#top"', home.html)
        self.assertIn("/media/sites/", home.html)
        self.assertNotIn("<script", home.html)
        # repeated header/footer became shared; the one-off hero header stayed in the page
        self.assertTrue(site.shared_sections.get(kind="header").enabled)
        self.assertNotIn('class="top"', home.html)
        self.assertIn('class="hero"', home.html)
        self.assertNotIn("<footer", site.pages.get(slug="about").html)
        sub = site.pages.get(slug="sub-page")
        self.assertIn("href='index.html'", sub.html)
        self.assertIn("/media/sites/", sub.html)  # root-relative /img/a.png
        self.assertIn(".more{font-family:x}", site.custom_css)
        self.assertIn('url("/media/sites/', site.custom_css)
        files, assets = render.build_files(site)
        self.assertIn('url("../assets/sites/', files["css/site.css"])
        self.assertIn("assets/sites/" + site.slug + "/imported/img/bg.jpg", assets)
        self.assertIn('class="home dark"', files["index.html"])
        self.assertEqual(files["index.html"].count('class="top"'), 1)

    def test_import_into_existing_site_and_errors(self):
        from . import importer

        site = services.create_site("Mine", "business")
        r = importer.import_bundle(self.bundle(), site=site)
        self.assertFalse(r["created"])
        self.assertEqual(site.pages.filter(is_home=True).count(), 1)
        self.assertEqual(site.home_page().slug, "home")  # existing home kept
        self.assertTrue(site.pages.filter(slug="home-2").exists() or site.pages.filter(title="Demo Home").exists())
        with self.assertRaises(importer.ImportErrorTH):
            importer.find_root(importer.from_zip(make_zip({"app/package.json": "{}", "app/src/main.js": ""})))
        with self.assertRaises(importer.ImportErrorTH):
            importer.from_zip(b"not a zip")
        self.assertEqual(importer.parse_github("https://github.com/o/r/tree/main/docs"), ("o", "r", "main", "docs"))
        self.assertEqual(importer.parse_github("o/r")[:2], ("o", "r"))
        with self.assertRaises(importer.ImportErrorTH):
            importer.parse_github("https://gitlab.com/o/r")

    def test_import_api_upload_folder(self):
        c = Client()
        c.get("/")
        files = [SimpleUploadedFile("index.html", b"<html><body><h1>Hi</h1><img src='a.png'></body></html>"),
                 SimpleUploadedFile("a.png", b"png")]
        r = c.post("/api/import/upload", {"files": files, "paths": ["mysite/index.html", "mysite/a.png"], "name": ""})
        d = r.json()
        self.assertTrue(d["ok"], d)
        site = Site.objects.get(pk=d["site_id"])
        self.assertEqual(site.name, "mysite")
        self.assertIn("/media/sites/", site.home_page().html)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class HostingNotifyTests(TestCase):
    def test_site_pinned_to_its_own_port(self):
        a = services.create_site("Alpha", "business")
        services.create_site("Beta", "landing")
        pinned = Client(**{"buildweb.public": True, "buildweb.site": a.slug})
        r = pinned.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<title>Alpha", r.content.decode())
        self.assertEqual(pinned.get("/about.html").status_code, 200)
        self.assertEqual(pinned.get("/beta/").status_code, 404)  # only its own site on that port
        a.published = False
        a.save()
        self.assertEqual(pinned.get("/").status_code, 404)

    def test_site_port_validation(self):
        c = Client()
        c.get("/")
        a = services.create_site("A")
        b = services.create_site("B")
        post = lambda sid, d: c.post(f"/api/sites/{sid}/update", json.dumps(d), content_type="application/json")  # noqa: E731
        self.assertEqual(post(a.id, {"host_port": 8101}).status_code, 200)
        self.assertEqual(post(b.id, {"host_port": 8101}).json()["field"], "host_port")  # taken
        self.assertEqual(post(b.id, {"host_port": 5050}).status_code, 400)  # the app's own port
        self.assertEqual(post(a.id, {"host_port": ""}).status_code, 200)
        self.assertIsNone(Site.objects.get(pk=a.id).host_port)

    def test_notify_summary_and_channels(self):
        from . import notify

        text = notify.summary("ร้าน", "contact", "ติดต่อ", {"name": "สมชาย", "tags": ["a", "b"]})
        self.assertIn("ร้าน", text)
        self.assertIn("tags: a, b", text)
        cfg = {"mac": False, "telegram_token": "t", "telegram_chat": "", "discord_webhook": "https://d",
               "webhook_url": "", "email": {"enabled": True, "host": "smtp", "to": "x@y"}}
        self.assertEqual(notify.channels(cfg), ["discord", "email"])

    def test_notify_settings_api_hides_secrets(self):
        c = Client()
        c.get("/")
        r = c.post("/api/settings/notify", json.dumps({"mac": False, "email": {"enabled": True, "host": "smtp.x", "password": "pw"}}),
                   content_type="application/json").json()
        self.assertNotIn("password", r["notify"]["email"])
        self.assertTrue(r["notify"]["email"]["password_set"])
        bad = c.post("/api/settings/notify", json.dumps({"webhook_url": "ftp://x"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)


SQL_DUMP = """-- phpMyAdmin SQL Dump
CREATE TABLE `products` (
  `id` int(11) NOT NULL,
  `name` varchar(100) NOT NULL,
  `price` decimal(10,2) DEFAULT NULL,
  `image` varchar(255) DEFAULT NULL,
  `note` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `products` (`id`, `name`, `price`, `image`, `note`) VALUES
(1, 'ลาเต้', 65.00, 'latte.jpg', 'it\\'s \\"hot\\"'),
(2, 'ชาไทย', 55.50, 'tea.jpg', NULL),
(3, 'Cake, cheese', 95.00, 'cake.jpg', 'line1\\nline2');
INSERT INTO `staff` VALUES (1,'Ann'),(2,'Bo');
"""


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class DataTests(TestCase):
    def setUp(self):
        from . import data

        self.data = data
        self.site = services.create_site("Data", "blank")

    def test_parse_sql_dump(self):
        t = self.data.parse_sql_dump(SQL_DUMP)
        self.assertEqual(t["products"]["columns"], ["id", "name", "price", "image", "note"])
        rows = t["products"]["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "ลาเต้")
        self.assertEqual(rows[0]["note"], 'it\'s "hot"')
        self.assertEqual(rows[1]["note"], "")
        self.assertEqual(rows[1]["price"], 55.5)
        self.assertEqual(rows[2]["name"], "Cake, cheese")
        self.assertEqual(rows[2]["note"], "line1\nline2")
        self.assertEqual(len(t["staff"]["rows"]), 2)

    def test_collection_types_and_render(self):
        t = self.data.parse_sql_dump(SQL_DUMP)["products"]
        col = self.data.create_collection(self.site, "products", t["columns"], t["rows"], sql_types=t["types"])
        types = {f["name"]: f["type"] for f in col.fields}
        self.assertEqual(types["price"], "number")
        self.assertEqual(types["image"], "image")
        self.assertEqual(types["note"], "longtext")
        html = ('<p>{{products.count}} รายการ · {{site.name}} · {{unknown}} · {{ vue.thing }}</p>'
                '<div class="grid" data-bw-repeat="products" data-bw-sort="price" data-bw-order="desc" data-bw-limit="2">'
                '<div class="card"><h3>{{#}}. {{name}}</h3><img src="{{image}}"><span>{{price}}</span><div><b>x</b></div></div></div>')
        out = self.data.render_html(html, self.site)
        self.assertIn("<p>3 รายการ · Data · {{unknown}} · {{ vue.thing }}</p>", out)
        self.assertEqual(out.count('class="card"'), 2)
        self.assertLess(out.index("Cake, cheese"), out.index("ลาเต้"))  # sorted by price desc
        self.assertNotIn("ชาไทย", out)  # limit 2
        self.assertIn("<h3>1. Cake, cheese</h3>", out)
        self.assertIn('src="cake.jpg"', out)

    def test_filters_escape_and_empty(self):
        self.data.create_collection(self.site, "items", ["name", "cat", "n"], [
            {"name": "<b>A</b>", "cat": "x", "n": 5}, {"name": "B", "cat": "y", "n": 10}, {"name": "C", "cat": "x", "n": 20}])
        out = self.data.render_html('<ul data-bw-repeat="items" data-bw-filter="cat=x;n>=10"><li>{{name}}</li></ul>', self.site)
        self.assertEqual(out.count("<li>"), 1)
        self.assertIn("<li>C</li>", out)
        out = self.data.render_html('<ul data-bw-repeat="items" data-bw-filter="name~a"><li>{{name}}|{{{name}}}</li></ul>', self.site)
        self.assertIn("&lt;b&gt;A&lt;/b&gt;|<b>A</b>", out)
        out = self.data.render_html('<ul data-bw-repeat="items" data-bw-filter="cat=z" data-bw-empty="ไม่มีข้อมูล"><li>{{name}}</li></ul>', self.site)
        self.assertIn("ไม่มีข้อมูล", out)
        self.assertNotIn("<li>", out)
        # unknown collection: template stays visible
        out = self.data.render_html('<div data-bw-repeat="nope"><i>{{x}}</i></div>', self.site)
        self.assertIn("<i>{{x}}</i>", out)

    def test_bound_page_renders_through_site(self):
        self.data.create_collection(self.site, "Menu", ["title"], [{"title": "กาแฟ"}, {"title": "ชา"}])
        page = self.site.home_page()
        page.html = '<section data-bw-repeat="menu"><h2>{{title}}</h2></section>'
        page.save()
        files, _ = render.build_files(self.site)
        self.assertIn("<h2>กาแฟ</h2>", files["index.html"])
        self.assertIn("<h2>ชา</h2>", files["index.html"])

    def test_csv_and_api(self):
        c = Client()
        c.get("/")
        csv_file = SimpleUploadedFile("สินค้า.csv", "ชื่อ,ราคา\nกาแฟ,50\nชา,40\n".encode("utf-8-sig"))
        r = c.post(f"/api/sites/{self.site.id}/collections/import-file", {"file": csv_file}).json()
        self.assertTrue(r["ok"], r)
        col = r["collections"][0]
        self.assertEqual([f["name"] for f in col["fields"]], ["ชื่อ", "ราคา"])
        self.assertEqual(col["count"], 2)
        sql = SimpleUploadedFile("dump.sql", SQL_DUMP.encode())
        prev = c.post(f"/api/sites/{self.site.id}/collections/import-file", {"file": sql, "preview": "1"}).json()
        self.assertEqual({t["name"] for t in prev["tables"]}, {"products", "staff"})
        sql = SimpleUploadedFile("dump.sql", SQL_DUMP.encode())
        r = c.post(f"/api/sites/{self.site.id}/collections/import-file", {"file": sql, "tables": ["products"]}).json()
        self.assertEqual(len(r["collections"]), 1)
        cid = r["collections"][0]["id"]
        post = lambda u, d: c.post(u, json.dumps(d), content_type="application/json").json()  # noqa: E731
        row = post(f"/api/collections/{cid}/rows/save", {"data": {"name": "ใหม่", "price": 10}})["row"]
        self.assertEqual(row["name"], "ใหม่")
        self.assertEqual(c.get(f"/api/collections/{cid}").json()["collection"]["count"], 4)
        res = post(f"/api/collections/{cid}/rows/delete", {"ids": [row["_id"]]})
        self.assertEqual(res.get("deleted"), 1, res)
        r = post(f"/api/collections/{cid}/update", {"slug": "menu", "fields": [{"name": "title", "label": "ชื่อ"}],
                                                   "renames": [{"from": "name", "to": "title"}]})
        self.assertEqual(r["collection"]["slug"], "menu")
        self.assertEqual(Collection.objects.get(pk=cid).records.first().data["title"], "ลาเต้")
        self.assertIn("ลาเต้", c.get(f"/api/collections/{cid}/export.csv").content.decode("utf-8-sig"))
        self.assertEqual(c.get(f"/sites/{self.site.id}/data/").status_code, 200)
        self.assertTrue(post(f"/api/collections/{cid}/delete", {})["ok"])
