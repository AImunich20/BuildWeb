import json
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from . import data, exporter, render, sections, services
from .models import Asset, Collection, FormSubmission, Page, PageRevision, Record, Site

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
        header = services.set_header_managed(site, False)  # design the header freely
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
        self.assertEqual(self.c.get(f"/sites/{sid}/edit-shared/header/").status_code, 302)  # managed → navbar settings
        self.assertEqual(self.c.get(f"/sites/{sid}/edit-shared/footer/").status_code, 200)
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


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class NavbarAnimTests(TestCase):
    def setUp(self):
        self.site = services.create_site("Nav", "business")

    def test_managed_navbar_settings(self):
        from . import navbar

        home = self.site.home_page()
        out = render.render_page(home)
        self.assertIn("bw-nav--managed", out)
        self.assertIn('href="index.html" class="active"', out)
        self.site.nav = navbar.clean({
            "layout": "center-logo", "transparent": True, "autohide": True, "mobile": "fullscreen", "logo_image": "/media/x/logo.png",
            "menu_mode": "custom", "items": [{"label": "บริการ", "href": "services.html", "children": [{"label": "ราคา", "href": "services.html#price"}]},
                                              {"label": "Blog", "href": "https://example.com", "target": "_blank"}, {"label": ""}],
            "cta": {"show": True, "text": "จองเลย", "href": "#book"}, "topbar": {"show": True, "text": "โทร 02-123", "links": [{"label": "LINE", "href": "#"}]},
            "logo_height": 999,
        })
        self.site.save()
        out = render.render_page(self.site.pages.get(slug="services"))
        for cls in ("bw-nav--center-logo", "bw-nav--transparent", "bw-nav--autohide", "bw-nav--m-fullscreen"):
            self.assertIn(cls, out)
        self.assertIn('src="assets/x/logo.png"', out)
        self.assertIn("height:120px", out)  # clamped
        self.assertIn('class="bw-dd"><a href="services.html" class="active">บริการ</a>', out)
        self.assertIn('target="_blank" rel="noopener">Blog</a>', out)
        self.assertIn(">จองเลย</a>", out)
        self.assertIn("โทร 02-123", out)
        self.assertNotIn(">เกี่ยวกับเรา</a><a", out.split("<header")[1].split("</header>")[0])  # custom menu replaces auto

    def test_switch_to_free_design_and_back(self):
        sec = services.set_header_managed(self.site, False)
        self.assertFalse(sec.managed)
        self.assertIn("data-bw-auto-nav", sec.html)
        out = render.render_page(self.site.pages.get(slug="about"))
        self.assertIn('href="about.html" class="active"', out)  # auto menu still filled
        self.assertTrue(services.set_header_managed(self.site, True).managed)

    def test_navbar_api(self):
        c = Client()
        c.get("/")
        r = c.post(f"/api/sites/{self.site.id}/navbar", json.dumps({"settings": {"layout": "nope", "sticky": False}}),
                   content_type="application/json").json()
        self.assertEqual(r["settings"]["layout"], "split")
        self.assertFalse(r["settings"]["sticky"])
        self.assertTrue(r["managed"])

    def test_animation_assets_in_output(self):
        files, _ = render.build_files(self.site)
        self.assertIn("bw-anim", files["index.html"].split("</head>")[0])
        self.assertIn("[data-bw-anim]", files["css/site.css"])
        self.assertIn("IntersectionObserver", files["js/site.js"])
        self.assertIn("data-bw-nav", files["js/site.js"])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class V014Tests(TestCase):
    """Detail pages, forms → collections, search/paging, blog, SEO files, contact buttons, stats, publishing."""

    def setUp(self):
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("ร้านกาแฟ", "cafe")
        self.col = Collection.objects.create(site=self.site, name="สินค้า", slug="products", fields=[
            {"name": "name", "label": "ชื่อ", "type": "text"}, {"name": "price", "label": "ราคา", "type": "number"},
            {"name": "category", "label": "หมวด", "type": "text"}, {"name": "detail", "label": "รายละเอียด", "type": "longtext"},
            {"name": "image", "label": "รูป", "type": "image"}])
        for i, (n, p, cat) in enumerate([("Latte", 1250, "coffee"), ("Mocha", 65, "coffee"), ("ชาไทย", 50, "tea")]):
            Record.objects.create(collection=self.col, position=i, data={"name": n, "price": p, "category": cat,
                                                                          "detail": f"รายละเอียด {n} " * 5, "image": ""})

    def post(self, url, data=None):
        return self.c.post(url, json.dumps(data or {}), content_type="application/json")

    def test_detail_pages_and_links(self):
        from . import generate

        lst, detail = generate.create_pages_for(self.col, "เมนู")
        self.assertEqual((lst.slug, detail.slug), ("products", "product"))
        files, _ = render.build_files(self.site)
        self.assertIn("product/latte.html", files)
        self.assertIn("product/ชาไทย.html", files)
        self.assertNotIn("product.html", files)  # the template itself is not a page of the live site
        page = files["product/latte.html"]
        self.assertIn('<base href="../">', page)
        self.assertIn("<title>Latte | ร้านกาแฟ</title>", page)
        self.assertIn("1,250 บาท", page)
        self.assertIn('href="product/mocha.html"', page)  # next
        self.assertNotIn("bw-prev", page)  # first row: no "previous" link (data-bw-if)
        self.assertIn('href="product/latte.html"', files["products.html"])
        self.assertNotIn(">สินค้า (หน้ารายละเอียด)<", files["index.html"])  # not in the menu
        # hosted / preview
        r = self.c.get(f"/preview/{self.site.slug}/product/%E0%B8%8A%E0%B8%B2%E0%B9%84%E0%B8%97%E0%B8%A2.html")
        self.assertContains(r, "<h1>ชาไทย</h1>")
        self.assertEqual(self.c.get(f"/preview/{self.site.slug}/product/nope.html").status_code, 404)
        self.assertContains(self.c.get(f"/preview/{self.site.slug}/product.html"), "Latte")  # designer sees row 1

    def test_search_facet_paging_marks_and_filters(self):
        html = ('<div data-bw-repeat="products" data-bw-search="ค้นหา" data-bw-facet="category" data-bw-paginate="2">'
                '<div class="card"><b>{{name}}</b> {{price|number}} <i data-bw-if="!image">no image</i></div></div>')
        out = data.render_html(html, self.site)
        self.assertEqual(out.count("data-bw-item"), 3)
        self.assertIn('data-bw-c="tea"', out)
        self.assertIn("1,250", out)
        self.assertEqual(out.count("no image"), 3)
        self.assertIn("bw-pager", render.site_js(self.site) + render.site_css(self.site))
        multi = data.render_html('<ul data-bw-repeat="products" data-bw-search><li>{{name}}</li><li>x</li></ul>', self.site)
        self.assertIn('<div style="display:contents" data-bw-item', multi)
        self.assertEqual(data.apply_filter("2026-10-28", "date", ""), "28 ต.ค. 2569")
        self.assertEqual(data.apply_filter("<p>abc def ghi</p>", "truncate", "7"), "abc def…")

    def test_form_into_collection_with_approval(self):
        rev = Collection.objects.create(site=self.site, name="รีวิว", slug="reviews", fields=[
            {"name": "name", "label": "ชื่อ", "type": "text"}, {"name": "comment", "label": "ความเห็น", "type": "html"},
            {"name": "date", "label": "วันที่", "type": "date"}])
        url = f"/preview/{self.site.slug}/__form"
        r = self.c.post(url, {"_collection": "reviews", "name": "A", "comment": "<script>x</script>"})
        self.assertEqual(r.status_code, 400)  # forms not enabled for this collection
        rev.options = {"forms": True}
        rev.save()
        r = self.c.post(url, {"_collection": "reviews", "_form": "review", "name": "A", "comment": "<script>x</script>"})
        self.assertEqual(r.json(), {"ok": True, "pending": True})
        rec = rev.records.get()
        self.assertFalse(rec.approved)
        self.assertEqual(rec.data["comment"], "&lt;script&gt;x&lt;/script&gt;")
        self.assertTrue(rec.data["date"])
        self.assertEqual(data.render_html('<p data-bw-repeat="reviews">{{name}}</p>', self.site).count("A"), 0)
        self.post(f"/api/collections/{rev.id}/rows/approve", {"ids": [rec.id], "value": True})
        self.assertIn(">A</p>", data.render_html('<p data-bw-repeat="reviews">{{name}}</p>', self.site))
        self.assertEqual(FormSubmission.objects.filter(site=self.site).count(), 1)
        # honeypot: accepted silently, nothing stored
        self.c.post(url, {"_collection": "reviews", "name": "bot", "_hp": "x"})
        self.assertEqual(rev.records.count(), 1)

    def test_blog_rss_sitemap_robots(self):
        from . import generate

        col, lst, detail = generate.create_blog(self.site)
        r = self.c.get(f"/preview/{self.site.slug}/rss.xml")
        self.assertContains(r, "<item><title>ยินดีต้อนรับสู่บล็อกของเรา</title>")
        self.assertContains(r, f"http://testserver/preview/{self.site.slug}/post/welcome.html")
        sm = self.c.get(f"/preview/{self.site.slug}/sitemap.xml").content.decode()
        self.assertIn("post/writing-tips.html", sm)
        self.assertIn("<loc>http://testserver/preview/", sm)
        self.assertIn("Sitemap:", self.c.get(f"/preview/{self.site.slug}/robots.txt").content.decode())
        post = self.c.get(f"/preview/{self.site.slug}/post/welcome.html").content.decode()
        self.assertIn("<h2>เขียนบทความใหม่</h2>", post)  # html field rendered raw
        self.assertIn('type="application/rss+xml"', post)
        self.site.base_url = "https://shop.example/"
        self.site.save()
        files, _ = render.build_files(self.site)
        self.assertIn("https://shop.example/post/welcome.html", files["sitemap.xml"])
        self.assertIn('<link rel="canonical" href="https://shop.example/post/welcome.html">', files["post/welcome.html"])

    def test_seo_report(self):
        r = self.c.get(f"/api/sites/{self.site.id}/seo").json()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["pages"]), self.site.pages.count())
        for p in r["pages"]:
            self.assertTrue(0 <= p["score"] <= 100)
            self.assertTrue(p["checks"])

    def test_contact_buttons(self):
        self.post(f"/api/sites/{self.site.id}/update", {"contact": {"enabled": True, "phone": "081-234-5678", "line": "@mycafe",
                                                                     "whatsapp": "0812345678", "style": "bar"}})
        self.site.refresh_from_db()
        out = render.render_page(self.site.home_page())
        self.assertIn('href="tel:0812345678"', out)
        self.assertIn("https://line.me/R/ti/p/%40mycafe", out)
        self.assertIn("https://wa.me/66812345678", out)
        self.assertIn("bw-fab bar", out)

    def test_stats_count_public_hits_only(self):
        from . import stats

        ua = {"HTTP_USER_AGENT": "Mozilla/5.0 (iPhone) Safari"}
        pub = {"buildweb.public": True, **ua}
        self.c.get(f"/{self.site.slug}/", **pub)
        self.c.get(f"/{self.site.slug}/about.html", **pub)
        self.c.get(f"/{self.site.slug}/about.html", **{"buildweb.public": True, "HTTP_USER_AGENT": "Googlebot/2.1"})
        self.c.get(f"/preview/{self.site.slug}/", **ua)  # preview: not counted
        s = stats.summary(self.site, 7)
        self.assertEqual(s["total"]["views"], 2)
        self.assertEqual(s["total"]["visitors"], 1)
        self.assertEqual(s["devices"][0]["key"], "mobile")
        self.assertIn("/about.html", [p["key"] for p in s["pages"]])
        self.assertTrue(self.c.get("/").status_code == 200)  # dashboard with sparkline

    def test_publish_github_and_netlify_mocked(self):
        from unittest import mock

        from . import publish

        calls = []

        def fake(method, url, token, data=None, raw=None, content_type=None, timeout=60):
            calls.append((method, url.replace(publish.GITHUB_API, "").replace(publish.NETLIFY_API, "")))
            u = calls[-1][1]
            if u == "/user":
                return 200, {"login": "me"}
            if u == "/repos/me/shop":
                return 404, {}
            if u == "/user/repos":
                return 201, {"size": 0}
            if "/git/ref/heads/" in u:
                return 404, {}
            if u.endswith("/git/blobs"):
                return 201, {"sha": publish.git_blob_sha(base64.b64decode(data["content"]))}
            if u.endswith("/git/trees"):
                return 201, {"sha": "tree1"}
            if u.endswith("/git/commits"):
                return 201, {"sha": "c1"}
            if u.endswith("/git/refs"):
                return 201, {}
            if u.endswith("/pages") and method == "GET":
                return 404, {}
            if u.endswith("/pages"):
                return 201, {"html_url": "https://me.github.io/shop/"}
            if u == "/sites" and method == "POST":
                return 201, {"id": "n1", "name": "shop", "ssl_url": "https://shop.netlify.app"}
            if u == "/sites/n1/deploys":
                self.assertEqual(content_type, "application/zip")
                return 200, {"id": "d1", "state": "ready", "ssl_url": "https://shop.netlify.app"}
            return 200, {}

        import base64

        publish.config.update("publish", {"github_token": "t", "netlify_token": "n"})
        self.post(f"/api/sites/{self.site.id}/publish", {"target": "github", "repo": "shop"})
        self.site.refresh_from_db()
        with mock.patch.object(publish, "http", side_effect=fake), mock.patch.object(publish.time, "sleep"):
            res = publish.run(self.site, "github")
            self.assertEqual(res["url"], "https://me.github.io/shop/")
            self.site.refresh_from_db()
            self.assertEqual(self.site.base_url, "https://me.github.io/shop/")
            self.assertIn(("POST", "/repos/me/shop/pages"), calls)
            res = publish.run(self.site, "netlify")
            self.assertEqual(res["site_id"], "n1")
        self.site.refresh_from_db()
        self.assertEqual(self.site.publish["netlify"]["site_id"], "n1")
        self.assertTrue(self.site.publish["github"]["last"]["ok"])
        r = self.c.get(f"/api/sites/{self.site.id}/publish").json()
        self.assertEqual(r["tokens"], {"github": True, "netlify": True})
        self.assertNotIn("t", json.dumps(r["publish"].get("github", {}).get("token", "")))

    def test_publish_ftp_mocked(self):
        from unittest import mock

        from . import publish

        stored = {}

        class FakeFTP:
            def __init__(self, timeout=None):
                pass

            def connect(self, host, port):
                self.host = host

            def login(self, user, pw):
                pass

            def mkd(self, path):
                pass

            def storbinary(self, cmd, f):
                stored[cmd[5:]] = f.read()

            def quit(self):
                pass

        self.site.publish = {"ftp": {"host": "ftp.example", "user": "u", "password": "p", "path": "public_html"}}
        self.site.save()
        with mock.patch.object(publish, "FTP", FakeFTP):
            res = publish.run(self.site, "ftp")
        self.assertIn("/public_html/index.html", stored)
        self.assertEqual(res["files"], len(stored))
        self.assertNotIn("password", self.c.get(f"/api/sites/{self.site.id}/publish").json()["publish"]["ftp"])

    def test_duplicate_site_copies_collections_and_detail_pages(self):
        from . import generate

        generate.create_pages_for(self.col)
        copy = services.duplicate_site(self.site)
        self.assertEqual(copy.collections.count(), 1)
        detail = copy.pages.get(collection__isnull=False)
        self.assertEqual(detail.collection.site_id, copy.id)
        self.assertEqual(detail.collection.records.count(), 3)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class RestApiTests(TestCase):
    """v0.2: schema validation, relations, REST API, keys, rules, CORS, rate limit, OpenAPI, logs."""

    def setUp(self):
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("API Shop", "blank")
        self.site.api = {"enabled": True}
        self.site.save()
        self.authors = Collection.objects.create(site=self.site, name="ผู้เขียน", slug="authors", fields=[
            {"name": "name", "label": "ชื่อ", "type": "text", "required": True},
            {"name": "email", "label": "อีเมล", "type": "email", "unique": True, "hidden": True}])
        self.a1 = Record.objects.create(collection=self.authors, data={"name": "Ann", "email": "ann@x.io"})
        self.posts = Collection.objects.create(site=self.site, name="โพสต์", slug="posts", fields=[
            {"name": "title", "label": "หัวข้อ", "type": "text", "required": True, "max": 40},
            {"name": "price", "label": "ราคา", "type": "number", "min": 0},
            {"name": "status", "label": "สถานะ", "type": "select", "options": ["draft", "live"], "default": "draft"},
            {"name": "author", "label": "ผู้เขียน", "type": "relation", "relation": "authors"}])
        for i in range(25):
            Record.objects.create(collection=self.posts, position=i, data={"title": f"Post {i}", "price": i * 10,
                                                                           "status": "live", "author": self.a1.id})
        self.base = f"/{self.site.slug}/api/v1"
        self.pub = {"buildweb.public": True}

    def get(self, url, **kw):
        return self.c.get(url, **{**self.pub, **kw})

    def send(self, method, url, data=None, **kw):
        return getattr(self.c, method)(url, json.dumps(data or {}), content_type="application/json", **{**self.pub, **kw})

    def test_list_paging_sort_filter_expand(self):
        r = self.get(f"{self.base}/posts?per_page=10&page=2&sort=-price").json()
        self.assertEqual((r["total"], r["total_pages"], len(r["items"])), (25, 3, 10))
        self.assertEqual(r["items"][0]["price"], 140)
        r = self.get(f"{self.base}/posts?filter=price>=200&expand=author").json()
        self.assertEqual(r["total"], 5)
        self.assertEqual(r["items"][0]["author"]["name"], "Ann")
        self.assertNotIn("email", r["items"][0]["author"])  # hidden field never leaves through the API
        self.assertEqual(self.get(f"{self.base}/posts?q=post 7").json()["total"], 1)
        one = self.get(f"{self.base}/posts/{r['items'][0]['_id']}?fields=title").json()
        self.assertEqual(set(one) - {"_id", "_created", "_updated"}, {"title"})
        self.assertEqual(self.get(f"{self.base}/posts/999999").status_code, 404)

    def test_keys_rules_and_validation(self):
        from . import restapi

        self.assertEqual(self.send("post", f"{self.base}/posts", {"title": "x"}).status_code, 401)  # create needs a key
        ro, ro_plain = restapi.create_key(self.site, "read only")
        rw, rw_plain = restapi.create_key(self.site, "writer", write=True, collections=["posts"])
        self.assertEqual(self.send("post", f"{self.base}/posts", {"title": "x"}, HTTP_X_API_KEY=ro_plain).status_code, 403)
        self.assertEqual(self.get(f"{self.base}/posts", HTTP_X_API_KEY="bw_wrong").status_code, 401)
        bad = self.send("post", f"{self.base}/posts", {"title": "x" * 50, "price": -1, "status": "zzz", "author": 999},
                        HTTP_AUTHORIZATION=f"Bearer {rw_plain}")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(set(bad.json()["error"]["fields"]), {"title", "price", "status", "author"})
        new = self.send("post", f"{self.base}/posts", {"title": "Hello", "price": "1,250"}, HTTP_X_API_KEY=rw_plain)
        self.assertEqual(new.status_code, 201)
        body = new.json()
        self.assertEqual((body["price"], body["status"]), (1250, "draft"))  # coerced + default
        rid = body["_id"]
        p = self.send("patch", f"{self.base}/posts/{rid}", {"price": 99}, HTTP_X_API_KEY=rw_plain).json()
        self.assertEqual((p["title"], p["price"]), ("Hello", 99))
        self.assertEqual(self.send("put", f"{self.base}/posts/{rid}", {"price": 1}, HTTP_X_API_KEY=rw_plain).status_code, 422)
        self.assertEqual(self.send("delete", f"{self.base}/posts/{rid}", HTTP_X_API_KEY=rw_plain).status_code, 204)
        # the writer key is limited to "posts"
        self.assertEqual(self.send("post", f"{self.base}/authors", {"name": "B"}, HTTP_X_API_KEY=rw_plain).status_code, 403)
        # unique
        Collection.objects.filter(pk=self.authors.pk).update(options={"api": {"create": "public"}})
        dup = self.send("post", f"{self.base}/authors", {"name": "C", "email": "ANN@x.io"})
        self.assertEqual(dup.json()["error"]["fields"], {"email": "ค่านี้มีอยู่แล้ว (ต้องไม่ซ้ำ)"})
        # rules: off
        Collection.objects.filter(pk=self.posts.pk).update(options={"api": {"list": "off"}})
        self.assertEqual(self.get(f"{self.base}/posts").status_code, 403)
        ro.revoked = True
        ro.save()
        self.assertEqual(self.get(f"{self.base}/authors", HTTP_X_API_KEY=ro_plain).status_code, 401)

    def test_disabled_cors_rate_openapi_logs_owner(self):
        r = self.c.options(f"{self.base}/posts", HTTP_ORIGIN="https://app.example", **self.pub)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        spec = self.get(f"{self.base}/openapi.json").json()
        self.assertIn("/posts/{id}", spec["paths"])
        self.assertEqual(spec["paths"]["/posts"]["post"]["security"], [{"ApiKey": []}, {"Bearer": []}])
        self.assertNotIn("email", spec["components"]["schemas"]["Authors"]["properties"])
        self.site.api = {"enabled": True, "rate": 3, "cors": "https://ok.example"}
        self.site.save()
        codes = [self.get(f"{self.base}/posts", HTTP_ORIGIN="https://ok.example", REMOTE_ADDR="10.0.0.7").status_code
                 for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        r = self.get(f"{self.base}/", HTTP_ORIGIN="https://evil.example", REMOTE_ADDR="10.0.0.9")
        self.assertNotIn("Access-Control-Allow-Origin", r)
        self.site.api = {"enabled": False}
        self.site.save()
        self.assertEqual(self.get(f"{self.base}/posts", REMOTE_ADDR="10.0.0.8").status_code, 404)
        # the owner (in-app preview) still has full access, hidden fields included
        own = self.c.get(f"/preview/{self.site.slug}/api/v1/authors").json()
        self.assertEqual(own["items"][0]["email"], "ann@x.io")
        logs = self.c.get(f"/api/sites/{self.site.id}/restapi/logs").json()["logs"]
        self.assertTrue(any(x["status"] == 429 for x in logs))

    def test_admin_keys_rules_and_row_validation(self):
        r = self.c.post(f"/api/sites/{self.site.id}/restapi/keys", json.dumps({"name": "app", "write": True}),
                        content_type="application/json").json()
        self.assertTrue(r["plain"].startswith("bw_"))
        self.assertNotIn(r["plain"], json.dumps(self.c.get(f"/api/sites/{self.site.id}/restapi").json()))
        self.c.post(f"/api/sites/{self.site.id}/restapi", json.dumps({"rules": {"posts": {"delete": "off"}}}),
                    content_type="application/json")
        self.posts.refresh_from_db()
        self.assertEqual(self.posts.options["api"]["delete"], "off")
        bad = self.c.post(f"/api/collections/{self.posts.id}/rows/save", json.dumps({"data": {"price": "abc"}}),
                          content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("ราคา", bad.json()["error"])

    def test_relation_placeholders_and_sdk(self):
        out = data.render_html('<p data-bw-repeat="posts" data-bw-limit="1">{{title}} by {{author.name}} #{{_id}}</p>', self.site)
        self.assertIn("Post 0 by Ann #", out)
        self.assertIn("window.bw", render.site_js(self.site))


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class MembersTests(TestCase):
    """v0.2 phase 2: sign up / log in / reset, sessions, members-only pages, user & owner rules."""

    def setUp(self):
        from . import generate, notify

        notify.OUTBOX.clear()
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Club", "blank")
        self.site.api = {"enabled": True}
        self.site.auth = {"enabled": True, "roles": ["member", "vip"]}
        self.site.save()
        generate.create_member_pages(self.site)
        self.site.refresh_from_db()
        self.notes = Collection.objects.create(site=self.site, name="โน้ต", slug="notes", fields=[
            {"name": "text", "label": "ข้อความ", "type": "text", "required": True}],
            options={"api": {"list": "owner", "view": "owner", "create": "user", "update": "owner", "delete": "owner"}})
        self.root = f"/{self.site.slug}/"
        self.pub = {"buildweb.public": True}

    def api(self, method, path, data=None, client=None, **kw):
        cl = client or self.c
        if method == "get":
            return cl.get(f"{self.root}api/v1/{path}", **{**self.pub, **kw})
        return getattr(cl, method)(f"{self.root}api/v1/{path}", json.dumps(data or {}), content_type="application/json",
                                   **{**self.pub, **kw})

    def test_register_login_session_logout(self):
        r = self.api("post", "auth/register", {"email": "A@x.io", "password": "secret123", "name": "Ann"})
        self.assertEqual(r.status_code, 201)
        self.assertIn(f"bw_u{self.site.id}", r.cookies)
        self.assertTrue(r.cookies[f"bw_u{self.site.id}"]["httponly"])
        self.assertEqual(self.api("get", "auth/me").json()["user"]["email"], "a@x.io")
        self.assertEqual(self.api("post", "auth/register", {"email": "a@x.io", "password": "secret123"}).status_code, 409)
        self.assertEqual(self.api("post", "auth/register", {"email": "b@x.io", "password": "123"}).status_code, 422)
        self.api("post", "auth/logout")
        self.assertEqual(self.api("get", "auth/me").status_code, 401)
        self.assertEqual(self.api("post", "auth/login", {"email": "a@x.io", "password": "nope"}).status_code, 401)
        tok = self.api("post", "auth/login", {"email": "a@x.io", "password": "secret123"}).json()["token"]
        app = Client()  # an app using the bearer token instead of the cookie
        me = app.get(f"{self.root}api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {tok}", **self.pub)
        self.assertEqual(me.json()["user"]["name"], "Ann")

    def test_forgot_reset_and_verify(self):
        from . import members, notify

        members.create_user(self.site, "c@x.io", "secret123", "C", verified=True)
        r = self.api("post", "auth/forgot", {"email": "c@x.io"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.api("post", "auth/forgot", {"email": "nobody@x.io"}).json(), r.json())  # no probing
        link = notify.OUTBOX[-1]["text"].split("\n")[3]
        token = link.split("token=")[1]
        self.assertIn("reset.html?token=", link)
        self.assertEqual(self.api("post", "auth/reset", {"token": token, "password": "newpass123"}).status_code, 200)
        self.assertEqual(self.api("post", "auth/reset", {"token": token, "password": "again1234"}).status_code, 400)  # one-time
        self.assertEqual(self.api("post", "auth/login", {"email": "c@x.io", "password": "newpass123"}).status_code, 200)
        # email verification
        self.site.auth = {**self.site.auth, "verify_email": True}
        self.site.save()
        r = self.api("post", "auth/register", {"email": "v@x.io", "password": "secret123"}, client=Client())
        self.assertTrue(r.json()["verify"])
        self.assertEqual(self.api("post", "auth/login", {"email": "v@x.io", "password": "secret123"}, client=Client()).status_code, 403)
        vlink = notify.OUTBOX[-1]["text"].split("\n")[3]
        r = Client().get(vlink.replace("http://testserver", ""), **self.pub)
        self.assertIn("verified=1", r["Location"])
        self.assertEqual(self.api("post", "auth/login", {"email": "v@x.io", "password": "secret123"}, client=Client()).status_code, 200)

    def test_members_only_pages_and_roles(self):
        from . import members

        acc = self.c.get(f"{self.root}account.html", **self.pub)
        self.assertEqual(acc.status_code, 302)
        self.assertIn("login.html?next=account.html", acc["Location"])
        vip = self.site.pages.create(title="VIP", slug="vip", html="<h1>VIP {{user.name}}</h1>", access="role:vip")
        members.create_user(self.site, "m@x.io", "secret123", "Mem", role="member", verified=True)
        self.api("post", "auth/login", {"email": "m@x.io", "password": "secret123"})
        page = self.c.get(f"{self.root}account.html", **self.pub).content.decode()
        self.assertIn("สวัสดีคุณMem", page)
        self.assertEqual(self.c.get(f"{self.root}vip.html", **self.pub).status_code, 403)
        u = self.site.members.get(email="m@x.io")
        u.role = "vip"
        u.save()
        self.assertContains(self.c.get(f"{self.root}vip.html", **self.pub), "VIP Mem")
        files, _ = render.build_files(self.site)  # static exports never contain members-only pages
        self.assertNotIn("account.html", files)
        self.assertNotIn("vip.html", files)
        self.assertIn("login.html", files)
        self.assertNotIn(vip.slug, render.sitemap_xml(self.site, "https://x.io/"))

    def test_owner_rules_and_mine(self):
        from . import members

        a = Client()
        b = Client()
        for cl, em in ((a, "a@x.io"), (b, "b@x.io")):
            members.create_user(self.site, em, "secret123", em[0], verified=True)
            self.api("post", "auth/login", {"email": em, "password": "secret123"}, client=cl)
        self.assertEqual(self.api("post", "notes", {"text": "x"}, client=Client()).status_code, 401)  # needs login
        n1 = self.api("post", "notes", {"text": "A's note"}, client=a).json()
        self.api("post", "notes", {"text": "B's note"}, client=b)
        self.assertEqual([x["text"] for x in self.api("get", "notes", client=a).json()["items"]], ["A's note"])
        self.assertTrue(self.api("get", f"notes/{n1['_id']}", client=a).json()["_mine"])
        self.assertEqual(self.api("get", f"notes/{n1['_id']}", client=b).status_code, 404)
        self.assertEqual(self.api("patch", f"notes/{n1['_id']}", {"text": "hack"}, client=b).status_code, 404)
        self.assertEqual(self.api("delete", f"notes/{n1['_id']}", client=a).status_code, 204)
        html = data.render_html('<p data-bw-repeat="notes" data-bw-mine>{{text}}</p>', self.site,
                                user=self.site.members.get(email="b@x.io"))
        self.assertIn("B&#x27;s note", html)
        self.assertNotIn("A's", html)

    def test_admin_members_api(self):
        r = self.c.post(f"/api/sites/{self.site.id}/members/create",
                        json.dumps({"email": "new@x.io", "password": "secret123", "role": "vip"}), content_type="application/json")
        mid = r.json()["member"]["id"]
        link = self.c.post(f"/api/members/{mid}/reset-link", "{}", content_type="application/json").json()
        self.assertIn("reset.html?token=bwu_", link["link"])
        self.c.post(f"/api/members/{mid}/update", json.dumps({"is_active": False}), content_type="application/json")
        self.assertEqual(self.api("post", "auth/login", {"email": "new@x.io", "password": "secret123"}).status_code, 403)
        s = self.c.get(f"/api/sites/{self.site.id}/members/settings").json()
        self.assertTrue(all(s["pages"].values()))
        self.assertEqual(s["roles"], ["admin", "member", "vip"])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class LogicTests(TestCase):
    """v0.4 phase 3: secrets, webhooks, connectors, functions, scheduled jobs."""

    def setUp(self):
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Logic", "blank")
        self.site.api = {"enabled": True}
        self.site.secrets = {"HOOK_TOKEN": "s3cret", "GREETING": "สวัสดี"}
        self.site.save()
        self.col = Collection.objects.create(site=self.site, name="Orders", slug="orders", fields=[
            {"name": "item", "label": "item", "type": "text", "required": True}],
            options={"api": {"create": "public"}})

    def post(self, url, d):
        return self.c.post(url, json.dumps(d), content_type="application/json")

    def test_webhook_signed_with_secrets(self):
        from unittest import mock

        from . import logic

        self.post(f"/api/sites/{self.site.id}/logic/webhooks", {"name": "n8n", "url": "https://hooks.example/x",
                  "events": ["record.created"], "headers": "Authorization: Bearer {{secret.HOOK_TOKEN}}", "signing_secret": "k1"})
        sent = []
        with mock.patch.object(logic, "http_request", side_effect=lambda m, u, h, b, timeout=20: sent.append((u, h, b)) or (200, "ok")):
            r = self.c.post(f"/{self.site.slug}/api/v1/orders", json.dumps({"item": "latte"}), content_type="application/json",
                            **{"buildweb.public": True})
        self.assertEqual(r.status_code, 201)
        url, headers, raw = sent[0]
        self.assertEqual(headers["Authorization"], "Bearer s3cret")
        self.assertEqual(headers["X-BuildWeb-Signature"], logic.signature("k1", raw))
        body = json.loads(raw)
        self.assertEqual((body["event"], body["data"]["item"]), ("record.created", "latte"))
        log = self.c.get(f"/api/sites/{self.site.id}/logic/logs?kind=webhook").json()["logs"][0]
        self.assertTrue(log["ok"])
        self.assertNotIn("s3cret", json.dumps(self.c.get(f"/api/sites/{self.site.id}/logic").json()["secrets"]))

    def test_connector_preview_run_and_upsert(self):
        from unittest import mock

        from . import logic

        payload = {"data": {"items": [{"code": "A1", "name": "Latte", "price": {"amount": 65}}, {"code": "B2", "name": "Mocha", "price": {"amount": 70}}]}}
        self.post(f"/api/sites/{self.site.id}/logic/connectors", {"name": "เมนูจาก POS", "url": "https://pos.example/api?key={{secret.HOOK_TOKEN}}",
                                                                 "items_path": "data.items", "key_field": "code"})
        conn = self.site.connectors.get()
        calls = []
        with mock.patch.object(logic, "http_request", side_effect=lambda m, u, h, b, timeout=20: calls.append(u) or (200, json.dumps(payload))):
            prev = self.c.post(f"/api/logic/connector/{conn.id}/preview", "{}", content_type="application/json").json()
            self.assertEqual(prev["columns"], ["code", "name", "price_amount"])
            self.c.post(f"/api/logic/connector/{conn.id}/run", "{}", content_type="application/json")
            payload["data"]["items"][0]["name"] = "Latte Hot"
            payload["data"]["items"].append({"code": "C3", "name": "Tea", "price": {"amount": 50}})
            self.c.post(f"/api/logic/connector/{conn.id}/run", "{}", content_type="application/json")
        self.assertIn("key=s3cret", calls[0])
        conn.refresh_from_db()
        rows = sorted(r["name"] for r in conn.collection.records.values_list("data", flat=True))
        self.assertEqual(rows, ["Latte Hot", "Mocha", "Tea"])

    def test_function_runs_in_subprocess(self):
        code = ('def handler(request, bw):\n'
                '    print("log line")\n'
                '    return {"hi": bw.secret("GREETING") + " " + request["query"].get("name", ""), "m": request["method"]}\n')
        r = self.post(f"/api/sites/{self.site.id}/logic/functions", {"slug": "hello", "code": code, "access": "public"})
        self.assertEqual(r.status_code, 200)
        out = self.c.get(f"/{self.site.slug}/api/v1/fn/hello?name=Ann", **{"buildweb.public": True})
        self.assertEqual(out.json(), {"hi": "สวัสดี Ann", "m": "GET"})
        fn = self.site.functions.get()
        t = self.c.post(f"/api/logic/function/{fn.id}/test", json.dumps({"query": {"name": "B"}}), content_type="application/json").json()
        self.assertIn("log line", t["logs"])
        bad = self.post(f"/api/sites/{self.site.id}/logic/functions", {"slug": "bad", "code": "def handler(:\n"})
        self.assertIn("บรรทัด", bad.json()["error"])
        self.post(f"/api/sites/{self.site.id}/logic/functions", {"slug": "slow", "timeout": 1, "access": "public",
                  "code": "import time\ndef handler(r, bw):\n    time.sleep(5)\n"})
        self.assertEqual(self.c.get(f"/{self.site.slug}/api/v1/fn/slow", **{"buildweb.public": True}).status_code, 504)
        self.post(f"/api/sites/{self.site.id}/logic/functions", {"slug": "err", "access": "public",
                  "code": "def handler(r, bw):\n    return (418, {'tea': True})\n"})
        self.assertEqual(self.c.get(f"/{self.site.slug}/api/v1/fn/err", **{"buildweb.public": True}).status_code, 418)
        self.post(f"/api/sites/{self.site.id}/logic/functions", {"slug": "locked", "access": "key", "code": code})
        self.assertEqual(self.c.get(f"/{self.site.slug}/api/v1/fn/locked", **{"buildweb.public": True}).status_code, 401)

    def test_schedules_and_jobs(self):
        from datetime import datetime, timedelta
        from unittest import mock

        from django.utils import timezone

        from . import logic

        base = timezone.make_aware(datetime(2026, 10, 29, 10, 0))  # a Thursday
        self.assertEqual(logic.next_run("every 15m", base), base + timedelta(minutes=15))
        self.assertEqual(logic.next_run("daily 09:00", base).day, 30)
        self.assertEqual(logic.next_run("daily 11:30", base).hour, 11)
        self.assertEqual(logic.next_run("weekly mon 08:00", base).weekday(), 0)
        for bad in ("every 1m", "daily 25:00", "sometimes"):
            with self.assertRaises(ValueError):
                logic.parse_schedule(bad)
        old = Record.objects.create(collection=self.col, data={"item": "old"})
        Record.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        Record.objects.create(collection=self.col, data={"item": "new"})
        r = self.post(f"/api/sites/{self.site.id}/logic/jobs", {"name": "ล้างคำสั่งซื้อเก่า", "schedule": "daily 03:00",
                      "action": "purge_rows", "params": {"collection": "orders", "days": 30}}).json()
        job = r["jobs"][0]
        self.assertTrue(job["next_run"])
        res = self.c.post(f"/api/logic/job/{job['id']}/run", "{}", content_type="application/json").json()
        self.assertEqual(res["message"], "ลบ 1 แถวที่เก่ากว่า 30 วัน")
        self.assertEqual(self.col.records.count(), 1)
        self.post(f"/api/sites/{self.site.id}/logic/jobs", {"name": "ping", "schedule": "every 30m", "action": "call_url",
                  "params": {"url": "https://ping.example/{{secret.HOOK_TOKEN}}"}})
        ping = self.site.jobs.get(name="ping")
        with mock.patch.object(logic, "http_request", return_value=(200, "pong")) as h:
            ok, msg = logic.run_job(ping)
        self.assertTrue(ok)
        self.assertEqual(h.call_args[0][1], "https://ping.example/s3cret")
