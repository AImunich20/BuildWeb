import json
import re
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

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

        calls, blobs = [], []

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
                blobs.append(base64.b64decode(data["content"]))
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
            self.assertNotIn(b"www.shop.example\n", blobs)
            self.site.publish["github"]["domain"] = "www.shop.example"  # connected through Cloudflare
            self.site.save()
            publish.run(self.site, "github")
            self.assertIn(b"www.shop.example\n", blobs)  # the CNAME file keeps the GitHub Pages custom domain
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


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ServerTests(TestCase):
    """v0.5 phase 4: encrypted secrets, backups, deploy to a server, server kit, database URLs."""

    def setUp(self):
        from . import generate

        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Deploy Shop", "business")
        self.authors = Collection.objects.create(site=self.site, name="A", slug="authors", fields=[{"name": "name", "type": "text"}])
        a = Record.objects.create(collection=self.authors, data={"name": "Ann"})
        self.posts = Collection.objects.create(site=self.site, name="P", slug="posts", fields=[
            {"name": "title", "type": "text"}, {"name": "author", "type": "relation", "relation": "authors"}])
        Record.objects.create(collection=self.posts, data={"title": "Hello", "author": a.id})
        self.orders = Collection.objects.create(site=self.site, name="Orders", slug="orders", fields=[{"name": "item", "type": "text"}],
                                                options={"forms": True})
        Record.objects.create(collection=self.orders, data={"item": "desktop test order"})
        generate.create_pages_for(self.posts)
        from . import members

        members.create_user(self.site, "m@x.io", "secret123", "M", verified=True)
        self.c.post(f"/api/sites/{self.site.id}/logic/secrets", json.dumps({"name": "TOKEN", "value": "abc123"}), content_type="application/json")
        self.c.post(f"/api/sites/{self.site.id}/logic/functions", json.dumps({"slug": "hi", "code": "def handler(r, bw):\n    return {}\n"}),
                    content_type="application/json")
        up = self.c.post(f"/api/sites/{self.site.id}/assets/upload", {"file": SimpleUploadedFile("logo.png", b"\x89PNG fake", "image/png")})
        self.assertEqual(up.status_code, 200)
        self.site.refresh_from_db()

    def test_secrets_are_encrypted_at_rest(self):
        from . import crypto, logic

        stored = Site.objects.get(pk=self.site.pk).secrets["TOKEN"]
        self.assertTrue(stored.startswith("enc:"))
        self.assertNotIn("abc123", stored)
        self.assertEqual(logic.fill_secrets(self.site, "x {{secret.TOKEN}}"), "x abc123")
        self.assertEqual(crypto.decrypt("enc:garbage"), "")
        self.assertEqual(crypto.decrypt("plain"), "plain")  # values from older versions still work

    def test_backup_roundtrip_new_and_replace(self):
        from . import backup

        data = backup.export_bytes(self.site)
        copy = backup.import_site(BytesIO(data), mode="new")
        self.assertNotEqual(copy.slug, self.site.slug)
        self.assertEqual(copy.pages.count(), self.site.pages.count())
        self.assertEqual(copy.members.get().email, "m@x.io")
        self.assertEqual(copy.functions.get().slug, "hi")
        self.assertEqual(crypto_value(copy, "TOKEN"), "abc123")
        post = copy.collections.get(slug="posts").records.get()
        self.assertEqual(copy.collections.get(slug="authors").records.get().id, post.data["author"])  # relation remapped
        self.assertTrue(copy.pages.filter(collection__slug="posts", collection__site=copy).exists())
        asset = copy.assets.get()
        self.assertTrue((TMP_MEDIA / asset.file.name).is_file())
        # replace = restore in place
        self.site.pages.update(html="<p>broken</p>")
        restored = backup.import_site(BytesIO(data), mode="replace")
        self.assertEqual(restored.slug, self.site.slug)
        self.assertNotIn("broken", restored.home_page().html)
        self.assertEqual(Site.objects.filter(slug=self.site.slug).count(), 1)

    def test_deploy_keeps_server_data(self):
        from . import backup, members

        backup.import_site(BytesIO(backup.export_bytes(self.site)), mode="deploy")  # the same DB plays the server
        live = Site.objects.get(slug=self.site.slug)
        Record.objects.create(collection=live.collections.get(slug="orders"), data={"item": "real customer order"})
        members.create_user(live, "customer@x.io", "secret123", "C", verified=True)
        home = live.home_page()
        home.html = "<h1>NEW DESIGN</h1>"
        home.save()
        live.collections.get(slug="posts").records.update(data={"title": "Edited post", "author": None})
        bundle = backup.export_bytes(live)
        # meanwhile the live site took one more order
        Record.objects.create(collection=live.collections.get(slug="orders"), data={"item": "late order"})
        site = backup.import_site(BytesIO(bundle), mode="deploy")
        self.assertIn("NEW DESIGN", site.home_page().html)
        self.assertEqual(site.collections.get(slug="posts").records.get().data["title"], "Edited post")
        items = sorted(r["item"] for r in site.collections.get(slug="orders").records.values_list("data", flat=True))
        self.assertIn("late order", items)  # server-side rows survive the deploy
        self.assertTrue(site.members.filter(email="customer@x.io").exists())

    def test_server_api_and_publish_server(self):
        import os
        from unittest import mock

        from django.test import RequestFactory

        from . import backup, publish, server_api

        rf = RequestFactory()
        bundle = backup.export_bytes(self.site)
        with mock.patch.dict(os.environ, {"BUILDWEB_DEPLOY_TOKEN": "t" * 32}):
            bad = server_api.deploy(rf.post("/__bw/deploy", bundle, content_type="application/zip", HTTP_AUTHORIZATION="Bearer nope"))
            self.assertEqual(bad.status_code, 401)
            ok = server_api.deploy(rf.post("/__bw/deploy", bundle, content_type="application/zip", HTTP_AUTHORIZATION="Bearer " + "t" * 32))
            self.assertEqual(json.loads(ok.content)["site"], self.site.slug)
            h = json.loads(server_api.health(rf.get("/__bw/health", HTTP_AUTHORIZATION="Bearer " + "t" * 32)).content)
            self.assertIn(self.site.slug, [s["slug"] for s in h["sites"]])
            pulled = json.loads(server_api.pull(rf.get(f"/__bw/pull?site={self.site.slug}", HTTP_AUTHORIZATION="Bearer " + "t" * 32)).content)
            self.assertEqual(list(pulled["collections"]), ["orders"])
            self.assertNotIn("password", json.dumps(pulled.get("secrets", {})))
        # desktop side: deploy through publish.run with the HTTP layer mocked
        self.c.post(f"/api/sites/{self.site.id}/publish", json.dumps({"target": "server", "url": "https://shop.example", "token": "t" * 32}),
                    content_type="application/json")
        self.site.refresh_from_db()
        self.assertTrue(self.site.publish["server"]["token"].startswith("enc:"))
        calls = []

        def fake(method, url, token, data=None, raw=None, content_type=None, timeout=60):
            calls.append((method, url, token))
            return (200, {"version": "x", "database": "postgresql"}) if url.endswith("/health") else (200, {"site": self.site.slug, "pages": 3, "collections": 3})

        with mock.patch.object(publish, "http", side_effect=fake):
            res = publish.run(self.site, "server")
        self.assertEqual(res["url"], "https://shop.example/")
        self.assertEqual(calls[1][2], "t" * 32)
        apply = backup.apply_pull(self.site, pulled)
        self.assertEqual(apply["rows"], 1)

    def test_server_kit_and_database_urls(self):
        import zipfile

        from buildweb import config

        r = self.c.get(f"/api/sites/{self.site.id}/server/kit.zip?domain=shop.example")
        z = zipfile.ZipFile(BytesIO(r.content))
        names = z.namelist()
        for n in ("buildweb-server/Dockerfile", "buildweb-server/docker-compose.yml", "buildweb-server/Caddyfile",
                  "buildweb-server/backend/server.py", f"buildweb-server/seed/{self.site.slug}.bwsite"):
            self.assertIn(n, names)
        self.assertFalse(any(n.endswith("tests.py") or "/.venv/" in n for n in names))
        env = z.read("buildweb-server/.env").decode()
        self.assertIn(f"BUILDWEB_DOMAINS=shop.example={self.site.slug}", env)
        self.assertRegex(env, r"BUILDWEB_DEPLOY_TOKEN=\S{30,}")
        pg = config.database_from_url("postgres://bw:p%40ss@db:5432/shop")
        self.assertEqual((pg["ENGINE"], pg["PASSWORD"], pg["HOST"], pg["NAME"]), ("django.db.backends.postgresql", "p@ss", "db", "shop"))
        self.assertEqual(config.database_from_url("mysql://root@127.0.0.1:3307/bw")["ENGINE"], "builder.db.mysql")
        self.assertEqual(config.database_from_url("sqlite:////data/x.sqlite3")["NAME"], "/data/x.sqlite3")

    def test_backups_api(self):
        r = self.c.post(f"/api/sites/{self.site.id}/backups", json.dumps({"action": "create"}), content_type="application/json").json()
        self.assertEqual(len(r["backups"]), 1)
        name = r["backups"][0]["name"]
        self.assertEqual(self.c.get(f"/api/sites/{self.site.id}/backups/{name}").status_code, 200)
        dl = self.c.get(f"/api/sites/{self.site.id}/backup.bwsite")
        up = self.c.post("/api/import/bwsite", {"file": SimpleUploadedFile("x.bwsite", dl.content)}).json()
        self.assertTrue(up["ok"])
        self.assertEqual(Site.objects.count(), 2)


def crypto_value(site, name):
    from . import crypto

    return crypto.decrypt(site.secrets[name])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class TeamTests(TestCase):
    """v0.6 phase 5: team access with roles, CMS mode, audit log, saved blocks."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from .models import TeamMember

        from . import members

        members._attempts.clear()
        Client().get("/")  # creates the owner account
        self.a = services.create_site("Client A", "business")
        self.b = services.create_site("Client B", "business")
        self.col = Collection.objects.create(site=self.a, name="ข่าว", slug="news", fields=[{"name": "title", "type": "text"}])
        User = get_user_model()
        for name, role in (("ed", "editor"), ("dev", "developer")):
            u = User.objects.create_user(name, password="secret123")
            TeamMember.objects.create(user=u, role=role, sites=[self.a.id])
        self.team = {"buildweb.team": True}

    def client_for(self, username):
        c = Client()
        r = c.post("/login", {"username": username, "password": "secret123"}, **self.team)
        self.assertEqual(r.status_code, 302)
        c.get("/", **self.team)
        return c

    def jpost(self, c, url, d=None):
        return c.post(url, json.dumps(d or {}), content_type="application/json", **self.team)

    def test_login_required_on_team_server(self):
        c = Client()
        self.assertEqual(c.get("/", **self.team)["Location"], "/login?next=/")
        self.assertEqual(c.get(f"/api/sites/{self.a.id}/pages", **self.team).status_code, 401)
        self.assertEqual(c.get("/").status_code, 200)  # the owner's local server still needs no login
        self.assertEqual(c.post("/login", {"username": "ed", "password": "wrong"}, **self.team).status_code, 200)

    def test_editor_is_content_only_and_site_scoped(self):
        c = self.client_for("ed")
        dash = c.get("/", **self.team).content.decode()
        self.assertIn("Client A", dash)
        self.assertNotIn("Client B", dash)
        self.assertEqual(c.get(f"/sites/{self.a.id}/data/", **self.team).status_code, 200)
        self.assertNotIn(f'/sites/{self.a.id}/logic/', c.get(f"/sites/{self.a.id}/", **self.team).content.decode())
        for url in (f"/sites/{self.a.id}/logic/", f"/sites/{self.b.id}/", "/settings/", "/django-admin/"):
            self.assertEqual(c.get(url, **self.team).status_code, 403, url)
        self.assertEqual(self.jpost(c, f"/api/collections/{self.col.id}/rows/save", {"data": {"title": "ข่าวใหม่"}}).status_code, 200)
        self.assertEqual(self.jpost(c, f"/api/collections/{self.col.id}/update", {"name": "x"}).status_code, 403)
        home = self.a.home_page()
        self.assertEqual(self.jpost(c, f"/api/pages/{home.id}/delete").status_code, 403)
        self.assertEqual(self.jpost(c, f"/api/pages/{self.b.home_page().id}/project", {"html": "x"}).status_code, 403)
        self.assertEqual(self.jpost(c, f"/api/pages/{home.id}/project", {"project": {}, "html": "<p>edited</p>", "css": ""}).status_code, 200)
        from .models import AuditLog

        self.assertTrue(AuditLog.objects.filter(user="ed", path__contains="/rows/save", status=200).exists())

    def test_developer_and_admin_endpoints(self):
        c = self.client_for("dev")
        self.assertEqual(c.get(f"/sites/{self.a.id}/logic/", **self.team).status_code, 200)
        self.assertEqual(self.jpost(c, f"/api/sites/{self.a.id}/restapi", {"settings": {"enabled": True}}).status_code, 200)
        self.assertEqual(c.get("/api/team", **self.team).status_code, 403)
        self.assertEqual(self.jpost(c, "/api/sites/create", {"name": "x"}).status_code, 403)
        owner = Client()
        owner.get("/")
        r = owner.post("/api/team/members", json.dumps({"username": "new.person", "password": "secret123", "role": "editor",
                                                        "sites": [self.b.id]}), content_type="application/json").json()
        self.assertIn("new.person", [m["username"] for m in r["members"]])

    def test_saved_blocks(self):
        c = Client()
        c.get("/")
        r = c.post("/api/blocks", json.dumps({"name": "การ์ดราคา", "html": "<div class=p>฿99</div>", "css": ".p{color:red}"}),
                   content_type="application/json").json()
        self.assertEqual(r["blocks"][0]["name"], "การ์ดราคา")
        r = c.post(f"/api/blocks/{r['blocks'][0]['id']}/delete", "{}", content_type="application/json").json()
        self.assertEqual(r["blocks"], [])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ShopTests(TestCase):
    """v0.7 phase 6: shop pages, checkout with server-side prices, stock, PromptPay, slips, Stripe, orders admin."""

    def setUp(self):
        from . import generate, notify

        notify.SENT.clear()
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Shop", "blank")
        generate.create_shop(self.site)
        self.site.refresh_from_db()
        from . import shop

        shop.save_settings(self.site, {"promptpay": "081-234-5678", "bank": "กสิกร 123", "cod": True, "shipping": 50, "free_over": 1000})
        self.prod = shop.products_col(self.site)
        self.tee = self.prod.records.get(data__slug="t-shirt")
        self.pub = {"buildweb.public": True}

    def checkout(self, items, payment="promptpay", **extra):
        d = {"items": items, "payment": payment, "customer": "สมชาย", "phone": "0812345678", "address": "กรุงเทพ", **extra}
        return self.c.post(f"/{self.site.slug}/api/v1/shop/checkout", json.dumps(d), content_type="application/json", **self.pub)

    def test_promptpay_payload(self):
        from . import shop

        self.assertEqual(shop.crc16("123456789"), "29B1")  # CRC-16/CCITT-FALSE check value
        p = shop.promptpay_payload("0812345678", 440)
        self.assertTrue(p.startswith("000201010212"))
        self.assertIn("0016A000000677010111" + "01130066812345678", p)
        self.assertIn("5406440.00", p)
        self.assertEqual(p[-4:], shop.crc16(p[:-4]))
        self.assertIn("0213" + "1234567890123", shop.promptpay_payload("1-2345-67890-12-3"))
        with self.assertRaises(ValueError):
            shop.promptpay_payload("123")

    def test_checkout_uses_server_prices_and_stock(self):
        r = self.checkout([{"id": self.tee.id, "qty": 2, "price": 1}])  # a tampered price is ignored
        self.assertEqual(r.status_code, 201, r.content)
        o = r.json()
        self.assertEqual(o["total"], 830.0)  # 2 × 390 + 50 shipping
        self.assertIn("5406830.00", o["promptpay"])
        self.tee.refresh_from_db()
        self.assertEqual(self.tee.data["stock"], 23)
        view = self.c.get(f"/{self.site.slug}/api/v1/shop/orders/{o['number']}?t={o['token']}", **self.pub).json()
        self.assertEqual((view["status"], view["items"][0]["qty"]), ("pending", 2))
        self.assertEqual(self.c.get(f"/{self.site.slug}/api/v1/shop/orders/{o['number']}?t=wrong", **self.pub).status_code, 404)
        free = self.checkout([{"id": self.tee.id, "qty": 3}]).json()
        self.assertEqual(free["total"], 1170.0)  # free shipping over 1000
        bag = self.prod.records.get(data__slug="tote-bag")
        self.assertEqual(self.checkout([{"id": bag.id, "qty": 1}]).status_code, 409)  # stock 0
        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1}], payment="stripe").status_code, 400)  # not enabled
        bad = self.checkout([{"id": self.tee.id, "qty": 1}], customer="")
        self.assertEqual(bad.json()["error"]["fields"], {"customer": "จำเป็นต้องกรอก"})
        from . import notify

        self.assertTrue(any(o["number"] in t for t in notify.SENT))

    def test_slip_status_cancel_restores_stock(self):
        o = self.checkout([{"id": self.tee.id, "qty": 5}], payment="transfer").json()
        slip = SimpleUploadedFile("slip.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")
        r = self.c.post(f"/{self.site.slug}/api/v1/shop/orders/{o['number']}/slip?t={o['token']}", {"slip": slip}, **self.pub)
        self.assertTrue(r.json()["has_slip"])
        orders = self.c.get(f"/api/sites/{self.site.id}/shop/orders").json()["orders"]
        self.assertTrue(orders[0]["slip"])
        self.assertNotIn("token", orders[0])
        self.c.post(f"/api/sites/{self.site.id}/shop/orders/{orders[0]['_id']}", json.dumps({"status": "cancelled"}), content_type="application/json")
        self.tee.refresh_from_db()
        self.assertEqual(self.tee.data["stock"], 25)
        summary = self.c.get(f"/api/sites/{self.site.id}/shop").json()["summary"]
        self.assertEqual(summary["pending"], 0)

    def test_stripe_session_and_webhook(self):
        import hashlib
        import hmac
        import time
        from unittest import mock

        from . import logic, shop

        shop.save_settings(self.site, {"stripe": True})
        self.c.post(f"/api/sites/{self.site.id}/logic/secrets", json.dumps({"name": "STRIPE_SECRET_KEY", "value": "sk_test_x"}), content_type="application/json")
        self.c.post(f"/api/sites/{self.site.id}/logic/secrets", json.dumps({"name": "STRIPE_WEBHOOK_SECRET", "value": "whsec_y"}), content_type="application/json")
        sent = {}

        def fake(method, url, headers=None, body=None, timeout=20):
            sent.update(url=url, auth=headers["Authorization"], body=body)
            return 200, json.dumps({"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})

        with mock.patch.object(logic, "http_request", side_effect=fake):
            o = self.checkout([{"id": self.tee.id, "qty": 1}], payment="stripe").json()
        self.assertEqual(o["redirect"], "https://checkout.stripe.com/c/cs_1")
        self.assertEqual(sent["auth"], "Bearer sk_test_x")
        self.assertIn("unit_amount%5D=39000", sent["body"])
        event = json.dumps({"type": "checkout.session.completed", "data": {"object": {"metadata": {"order": o["number"]},
                                                                                       "payment_status": "paid"}}}).encode()
        ts = str(int(time.time()))
        sig = hmac.new(b"whsec_y", ts.encode() + b"." + event, hashlib.sha256).hexdigest()
        url = f"/{self.site.slug}/api/v1/shop/stripe-webhook"
        self.assertEqual(self.c.post(url, event, content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={ts},v1=bad", **self.pub).status_code, 400)
        self.assertEqual(self.c.post(url, event, content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}", **self.pub).status_code, 200)
        rec = shop.orders_col(self.site).records.get(data__number=o["number"])
        self.assertEqual(rec.data["status"], "paid")

    def test_shop_pages_and_member_orders(self):
        files, _ = render.build_files(self.site)
        for f in ("shop.html", "cart.html", "checkout.html", "order.html", "product/t-shirt.html"):
            self.assertIn(f, files)
        self.assertIn('data-bw-add-to-cart="', files["shop.html"])
        self.assertIn("bw-cartfab", files["shop.html"])
        self.assertIn("bwCart", files["js/site.js"])
        from . import members

        self.site.auth = {"enabled": True}
        self.site.save()
        members.create_user(self.site, "buyer@x.io", "secret123", "B", verified=True)
        self.c.post(f"/{self.site.slug}/api/v1/auth/login", json.dumps({"email": "buyer@x.io", "password": "secret123"}),
                    content_type="application/json", **self.pub)
        self.checkout([{"id": self.tee.id, "qty": 1}])
        mine = self.c.get(f"/{self.site.slug}/api/v1/shop/my-orders", **self.pub).json()["items"]
        self.assertEqual(len(mine), 1)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class HardeningTests(TestCase):
    """v0.8: security fixes, coupons, product options, customer emails, images, API paging."""

    def setUp(self):
        from . import generate, notify, shop

        notify.OUTBOX.clear()
        notify.SENT.clear()
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Harden", "blank")
        generate.create_shop(self.site)
        self.site.refresh_from_db()
        shop.save_settings(self.site, {"promptpay": "0812345678", "cod": True, "shipping": 0, "low_stock": 22})
        self.prod = shop.products_col(self.site)
        self.tee = self.prod.records.get(data__slug="t-shirt")
        self.tee.data["options"] = "ไซซ์: S, M, L"
        self.tee.save()
        self.pub = {"buildweb.public": True}

    def checkout(self, items, **extra):
        d = {"items": items, "payment": "cod", "customer": "A", "phone": "0811111111", "address": "x", **extra}
        return self.c.post(f"/{self.site.slug}/api/v1/shop/checkout", json.dumps(d), content_type="application/json", **self.pub)

    def test_slip_must_really_be_an_image(self):
        o = self.checkout([{"id": self.tee.id, "qty": 1, "options": {"ไซซ์": "M"}}], payment="promptpay").json()
        evil = SimpleUploadedFile("x.html", b"<script>alert(1)</script>", "image/png")
        r = self.c.post(f"/{self.site.slug}/api/v1/shop/orders/{o['number']}/slip?t={o['token']}", {"slip": evil}, **self.pub)
        self.assertEqual(r.status_code, 400)
        good = SimpleUploadedFile("anything.html", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "text/html")
        self.c.post(f"/{self.site.slug}/api/v1/shop/orders/{o['number']}/slip?t={o['token']}", {"slip": good}, **self.pub)
        from .models import Asset

        self.assertTrue(Asset.objects.filter(site=self.site, folder="slips").first().name.endswith(".png"))

    def test_team_editor_is_not_owner_on_preview_api_and_login_is_throttled(self):
        from django.contrib.auth import get_user_model

        from .models import TeamMember

        u = get_user_model().objects.create_user("ed", password="secret123")
        TeamMember.objects.create(user=u, role="editor", sites=[self.site.id])
        notes = Collection.objects.create(site=self.site, name="n", slug="notes", fields=[{"name": "t", "type": "text", "hidden": True}],
                                          options={"api": {"list": "off"}})
        Record.objects.create(collection=notes, data={"t": "secret"})
        team = {"buildweb.team": True}
        ed = Client()
        ed.post("/login", {"username": "ed", "password": "secret123"}, **team)
        self.assertEqual(ed.get(f"/preview/{self.site.slug}/api/v1/notes", **team).json()["error"]["code"], "api_disabled")
        self.site.api = {"enabled": True}
        self.site.save()
        self.assertEqual(ed.get(f"/preview/{self.site.slug}/api/v1/notes", **team).status_code, 403)
        owner = Client()
        owner.get("/")
        self.assertEqual(owner.get(f"/preview/{self.site.slug}/api/v1/notes").json()["items"][0]["t"], "secret")
        attacker = Client()
        codes = [attacker.post("/login", {"username": "ed", "password": f"wrong{i}"}, **team).status_code for i in range(9)]
        self.assertEqual(codes[-1], 429)
        from . import members

        members._attempts.clear()

    def test_options_coupons_emails_low_stock(self):
        from . import notify, shop

        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1}]).status_code, 400)  # size not chosen
        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1, "options": {"ไซซ์": "XXL"}}]).status_code, 400)
        r = self.c.post(f"/api/sites/{self.site.id}/shop/coupons", json.dumps({"coupons": [
            {"code": "sale10", "type": "percent", "value": 10, "min": 500, "limit": 1, "active": True},
            {"code": "OLD", "type": "amount", "value": 50, "expires": "2020-01-01"}]}), content_type="application/json").json()
        self.assertEqual(r["coupons"][0]["code"], "SALE10")
        prev = self.c.get(f"/{self.site.slug}/api/v1/shop/coupon?code=SALE10&subtotal=1170", **self.pub).json()
        self.assertEqual(prev["discount"], 117.0)
        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1, "options": {"ไซซ์": "M"}}], coupon="SALE10").status_code, 400)  # min 500
        from unittest import mock

        with mock.patch.object(notify, "smtp_ready", return_value=True):
            o = self.checkout([{"id": self.tee.id, "qty": 3, "options": {"ไซซ์": "L"}}], coupon="sale10", email="c@x.io").json()
        self.assertEqual(o["total"], 1053.0)  # 1170 − 10%
        rec = shop.orders_col(self.site).records.get(data__number=o["number"])
        self.assertEqual(rec.data["items"][0]["options"], {"ไซซ์": "L"})
        self.assertIn("(ไซซ์: L)", rec.data["items"][0]["name"])
        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1, "options": {"ไซซ์": "S"}}], coupon="SALE10").status_code, 400)  # limit 1
        self.assertEqual(self.checkout([{"id": self.tee.id, "qty": 1, "options": {"ไซซ์": "S"}}], coupon="OLD").status_code, 400)  # expired
        self.assertTrue(any("ยืนยันคำสั่งซื้อ" in m["subject"] and m["to"] == "c@x.io" for m in notify.OUTBOX))
        self.assertTrue(any("สินค้าใกล้หมด" in t for t in notify.SENT))  # stock 25 → 22 ≤ 22
        with mock.patch.object(notify, "smtp_ready", return_value=True):
            self.c.post(f"/api/sites/{self.site.id}/shop/orders/{rec.id}", json.dumps({"status": "shipped"}), content_type="application/json")
        self.assertTrue(any("จัดส่งแล้ว" in m["subject"] for m in notify.OUTBOX))
        csv_text = self.c.get(f"/api/sites/{self.site.id}/shop/orders.csv").content.decode("utf-8-sig")
        self.assertIn(o["number"], csv_text)
        self.assertIn("SALE10", csv_text)
        orders = self.c.get(f"/api/sites/{self.site.id}/shop/orders").json()["orders"]
        self.assertIn("print=1", orders[0]["print_url"])

    def test_image_optimisation(self):
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (3000, 2000), (200, 120, 40)).save(buf, "PNG")
        up = self.c.post(f"/api/sites/{self.site.id}/assets/upload", {"files": SimpleUploadedFile("big.png", buf.getvalue(), "image/png")}).json()
        a = up["assets"][0]
        self.assertTrue(a["name"].endswith(".webp"))
        img = Image.open(TMP_MEDIA / self.site.assets.get(pk=a["id"]).file.name)
        self.assertEqual(max(img.size), 2000)
        svg = self.c.post(f"/api/sites/{self.site.id}/assets/upload", {"files": SimpleUploadedFile("i.svg", b"<svg/>", "image/svg+xml")}).json()
        self.assertTrue(svg["assets"][0]["name"].endswith(".svg"))

    def test_api_paging_fast_path_and_missing_fields(self):
        self.site.api = {"enabled": True}
        self.site.save()
        col = Collection.objects.create(site=self.site, name="big", slug="big", fields=[{"name": "n", "type": "number"}, {"name": "extra", "type": "text"}])
        Record.objects.bulk_create([Record(collection=col, data={"n": i}, position=i) for i in range(450)])
        r = self.c.get(f"/{self.site.slug}/api/v1/big?page=3&per_page=200", **self.pub).json()
        self.assertEqual((r["total"], r["total_pages"], len(r["items"]), r["items"][0]["n"]), (450, 3, 50, 400))
        html = data.render_html('<i data-bw-repeat="big" data-bw-limit="1">[{{extra}}]</i>', self.site)
        self.assertIn("[]", html)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ShopReuseTests(TestCase):
    def test_existing_detail_page_gets_a_buy_box(self):
        from . import generate

        site = services.create_site("Menu", "blank")
        col = Collection.objects.create(site=site, name="สินค้า", slug="products", fields=[{"name": "name", "type": "text"}, {"name": "price", "type": "number"}])
        Record.objects.create(collection=col, data={"name": "Latte", "price": 65})
        _, detail = generate.create_pages_for(col)
        generate.create_shop(site)
        self.assertEqual(col.detail_pages.count(), 1)
        detail.refresh_from_db()
        self.assertIn("data-bw-add-to-cart", detail.html)
        files, _ = render.build_files(site)
        self.assertIn('data-bw-add-to-cart="', files["product/latte.html"])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ReleaseTests(TestCase):
    """v0.9: server time zone, site versions (releases, staging, scheduled deploys, rollback), Cloudflare domains."""

    def setUp(self):
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Version Shop", "business")
        self.orders = Collection.objects.create(site=self.site, name="Orders", slug="orders", fields=[{"name": "item", "type": "text"}],
                                                options={"forms": True})
        self.home = self.site.home_page()
        self.home.html = "<h1>VERSION ONE</h1>"
        self.home.save()

    def tearDown(self):
        from . import clock

        clock.apply("Asia/Bangkok")

    def post(self, url, d):
        return self.c.post(url, json.dumps(d), content_type="application/json")

    def test_time_zone_applies_at_once_and_reschedules_jobs(self):
        from django.utils import timezone

        from . import clock
        from .models import Job

        job = Job.objects.create(site=self.site, name="morning", schedule="daily 09:00", action="call_url", params={}, enabled=True,
                                 next_run=timezone.now())
        r = self.post("/api/settings/app", {"timezone": "Asia/Tokyo"}).json()
        self.assertEqual(r["clock"]["timezone"], "Asia/Tokyo")
        self.assertEqual(r["clock"]["utc_offset"], "UTC+09:00")
        job.refresh_from_db()
        self.assertEqual(timezone.localtime(job.next_run).hour, 9)
        self.assertEqual(str(timezone.localtime(job.next_run).tzinfo), "Asia/Tokyo")
        self.assertEqual(self.post("/api/settings/app", {"timezone": "Mars/Base"}).status_code, 400)
        self.assertIn("Asia/Bangkok", self.c.get("/api/settings/app?zones=1").json()["zones"])
        self.assertAlmostEqual(clock.drift(timezone.now().isoformat(), __import__("time").time() - 1, __import__("time").time() + 1), 0, delta=2)

    def test_versions_diff_restore_and_static_deploy_from_snapshot(self):
        from unittest import mock

        from . import publish, releases

        r1 = self.post(f"/api/sites/{self.site.id}/releases", {"action": "create", "version": "1.0.0", "notes": "first"}).json()
        self.assertEqual(r1["suggest"], {"patch": "1.0.1", "minor": "1.1.0", "major": "2.0.0", "latest": "1.0.0"})
        v1 = self.site.releases.get(version="1.0.0")
        self.assertEqual(self.post(f"/api/sites/{self.site.id}/releases", {"action": "create", "version": "1.0.0"}).status_code, 400)
        # edit the site, then version 1.1.0
        self.home.html = "<h1>VERSION TWO</h1>"
        self.home.save()
        services.create_page(self.site, "โปรโมชัน", slug="promo") if hasattr(services, "create_page") else Page.objects.create(
            site=self.site, title="โปรโมชัน", slug="promo", html="<p>promo</p>")
        Record.objects.create(collection=self.orders, data={"item": "order from a visitor"})
        cur = self.c.get(f"/api/releases/{v1.id}/diff?against=current").json()["diff"]
        self.assertIn("promo", [p["slug"] for p in cur["pages"]["added"]])
        self.assertIn(self.home.slug, [p["slug"] for p in cur["pages"]["changed"]])
        self.assertFalse(cur["collections"]["changed"])  # server-data rows are not part of a version
        v2 = releases.create(self.site, "1.1.0", "promo page")
        self.assertTrue(v2.summary["total"] >= 2)
        # static deploy of the OLD version builds files from its snapshot
        stored = {}

        class FakeFTP:
            def __init__(self, timeout=None):
                pass

            def connect(self, host, port):
                pass

            def login(self, user, pw):
                pass

            def mkd(self, path):
                pass

            def storbinary(self, cmd, f):
                stored[cmd[5:]] = f.read()

            def quit(self):
                pass

        self.site.publish = {"ftp": {"host": "ftp.example", "user": "u", "password": "p", "path": "www"}}
        self.site.save()
        n_sites = Site.objects.count()
        with mock.patch.object(publish, "FTP", FakeFTP):
            publish.run(self.site, "ftp", release=v1)
        self.assertIn(b"VERSION ONE", stored["/www/index.html"])
        self.assertNotIn("/www/promo.html", stored)
        self.assertEqual(Site.objects.count(), n_sites)  # the temporary copy left nothing behind
        v1.refresh_from_db()
        self.assertTrue(v1.deploys[-1]["ok"])
        self.site.refresh_from_db()
        self.assertEqual(self.site.publish["ftp"]["last"]["version"], "1.0.0")
        self.assertEqual(releases.live_versions(self.site), {"ftp": "1.0.0"})
        # restore v1 in the app: design back, visitor data and publish settings stay
        site = releases.restore(v1)
        self.assertIn("VERSION ONE", site.home_page().html)
        self.assertFalse(site.pages.filter(slug="promo").exists())
        self.assertEqual(site.collections.get(slug="orders").records.count(), 1)
        self.assertEqual(site.publish["ftp"]["host"], "ftp.example")
        self.assertEqual(site.releases.count(), 2)

    def test_staging_scheduled_deploy_and_rollback_to_server(self):
        from datetime import timedelta
        from unittest import mock

        from django.utils import timezone

        from . import publish, releases

        for t, url in (("server", "https://shop.example"), ("staging", "https://test.shop.example")):
            self.post(f"/api/sites/{self.site.id}/publish", {"target": t, "url": url, "token": "t" * 32})
        self.site.refresh_from_db()
        v1 = releases.create(self.site, "1.0.0")
        sent = []

        def fake(method, url, token, data=None, raw=None, content_type=None, timeout=60):
            if url.endswith("/health"):
                return 200, {"version": "x"}
            sent.append((url, raw))
            return 200, {"site": self.site.slug, "pages": 1, "collections": 1}

        with mock.patch.object(publish, "http", side_effect=fake):
            publish.run(self.site, "staging", release=v1)
        self.assertTrue(sent[0][0].startswith("https://test.shop.example/__bw/deploy"))
        self.assertEqual(sent[0][1], releases.path_of(v1).read_bytes())  # the snapshot itself goes to the server
        self.site.refresh_from_db()
        self.assertEqual(self.site.base_url, "")  # a test server never becomes the site's address
        # schedule the same version for production
        r = self.post(f"/api/sites/{self.site.id}/releases", {"action": "schedule", "id": v1.id, "targets": ["server"],
                                                               "at": (timezone.localtime() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.post(f"/api/sites/{self.site.id}/releases", {"action": "schedule", "id": v1.id, "targets": ["server"],
                                                                           "at": "2001-01-01T00:00"}).status_code, 400)
        with mock.patch.object(publish, "http", side_effect=fake):
            releases.run_due()
            self.assertEqual(len(sent), 1)  # not yet
            self.site.releases.update(scheduled_at=timezone.now() - timedelta(seconds=1))
            releases.run_due()
        self.assertTrue(sent[1][0].startswith("https://shop.example/__bw/deploy"))
        v1.refresh_from_db()
        self.assertIsNone(v1.scheduled_at)
        self.assertEqual([d["target"] for d in v1.deploys], ["staging", "server"])
        # a failing deploy is recorded on the version
        with mock.patch.object(publish, "http", return_value=(401, {})):
            with self.assertRaises(publish.PublishError):
                publish.run(self.site, "server", release=v1)
        v1.refresh_from_db()
        self.assertFalse(v1.deploys[-1]["ok"])

    def test_server_config_time_zone_and_domains(self):
        import os
        from unittest import mock

        from django.test import RequestFactory

        from . import public, server_api

        rf = RequestFactory()
        auth = {"HTTP_AUTHORIZATION": "Bearer " + "t" * 32}
        with mock.patch.dict(os.environ, {"BUILDWEB_DEPLOY_TOKEN": "t" * 32}):
            self.assertEqual(server_api.server_config(rf.get("/__bw/config")).status_code, 401)
            r = json.loads(server_api.server_config(rf.post("/__bw/config", json.dumps({"timezone": "Europe/London",
                                                                                        "domains": {"Shop.Example": self.site.slug}}),
                                                            content_type="application/json", **auth)).content)
            self.assertEqual(r["timezone"], "Europe/London")
            self.assertEqual(r["domains"], {"shop.example": self.site.slug})
            bad = server_api.server_config(rf.post("/__bw/config", json.dumps({"domains": {"x.example": "nope"}}),
                                                   content_type="application/json", **auth))
            self.assertEqual(bad.status_code, 400)
            h = json.loads(server_api.health(rf.get("/__bw/health")).content)
            self.assertEqual(h["timezone"], "Europe/London")
        self.assertEqual(server_api.domain_check(rf.get("/__bw/domain-check?domain=shop.example")).status_code, 200)
        self.assertEqual(server_api.domain_check(rf.get("/__bw/domain-check?domain=evil.example")).status_code, 404)
        with override_settings(SERVER_MODE=True):
            self.assertEqual(public.domain_site(rf.get("/", HTTP_HOST="shop.example")), self.site.slug)
        self.assertIsNone(public.domain_site(rf.get("/", HTTP_HOST="shop.example")))  # desktop hosting ignores them
        with mock.patch.dict(os.environ, {"BUILDWEB_DEPLOY_TOKEN": "t" * 32}):
            server_api.server_config(rf.post("/__bw/config", json.dumps({"remove_domains": ["shop.example"]}),
                                             content_type="application/json", **auth))
        self.assertEqual(server_api.saved_domains(), {})

    def test_cloudflare_connect(self):
        from unittest import mock

        from . import cloudflare, publish

        self.post(f"/api/sites/{self.site.id}/publish", {"target": "server", "url": "https://203.0.113.10", "token": "t" * 32})
        dns = [{"id": "old", "type": "A", "name": "shop.example", "content": "198.51.100.1", "proxied": False}]
        calls = []

        def fake(method, url, token, data=None, raw=None, content_type=None, timeout=60):
            calls.append((method, url, data))
            if "api.cloudflare.com" in url:
                self.assertEqual(token, "cf-token-123")
                path = url.split("/client/v4")[1]
                if path == "/user/tokens/verify":
                    return 200, {"success": True, "result": {"status": "active"}}
                if path.startswith("/zones?"):
                    return 200, {"success": True, "result": [{"id": "z1", "name": "shop.example", "status": "active", "name_servers": []}]}
                if "dns_records?name=" in path:
                    name = path.split("name=")[1].split("&")[0]
                    return 200, {"success": True, "result": [r for r in dns if r["name"] == name]}
                if method in ("POST", "PUT"):
                    return 200, {"success": True, "result": {"id": "new"}}
                if method == "PATCH":
                    return 403, {"success": False, "errors": [{"message": "no permission"}]}
                return 200, {"success": True, "result": {}}
            return 200, {"ok": True, "domains": {}}  # the BuildWeb server's /__bw/config

        with mock.patch.object(publish, "http", side_effect=fake):
            r = self.post(f"/api/sites/{self.site.id}/domain", {"action": "token", "token": "cf-token-123"}).json()
            self.assertEqual(r["zones"][0]["name"], "shop.example")
            from buildweb import config

            self.assertTrue(config.load()["publish"]["cloudflare_token"].startswith("enc:"))
            # an existing record with another IP is not overwritten without permission
            bad = self.post(f"/api/sites/{self.site.id}/domain", {"action": "connect", "domain": "shop.example", "target": "server"})
            self.assertEqual(bad.status_code, 400)
            self.assertIn("198.51.100.1", bad.json()["error"])
            self.assertFalse([c for c in calls if c[0] in ("POST", "PUT", "DELETE") and "cloudflare" in c[1]])
            ok = self.post(f"/api/sites/{self.site.id}/domain", {"action": "connect", "domain": "https://shop.example/", "target": "server",
                                                                  "replace": True, "www": True, "proxied": True}).json()
        self.assertIn("แก้ shop.example A → 203.0.113.10", ok["result"]["changes"])
        self.assertIn("เพิ่ม www.shop.example CNAME → shop.example", ok["result"]["changes"])
        put = [c for c in calls if c[0] == "PUT" and "dns_records/old" in c[1]][0]
        self.assertTrue(put[2]["proxied"])
        srv = [c for c in calls if c[1].endswith("/__bw/config")][0]
        self.assertEqual(srv[2]["domains"], {"shop.example": self.site.slug, "www.shop.example": self.site.slug})
        self.site.refresh_from_db()
        self.assertEqual(self.site.base_url, "https://shop.example/")
        self.assertEqual(self.site.publish["domain"]["zone"], "shop.example")
        with self.assertRaises(cloudflare.CloudflareError):
            cloudflare.clean_domain("not a domain")
        with self.assertRaises(cloudflare.CloudflareError):  # a LAN address cannot serve a public domain
            cloudflare.plan(Site(publish={"server": {"url": "http://192.168.1.5:8090"}}), "x.example", "server")

    def test_team_editor_cannot_release_or_connect_domains(self):
        from django.contrib.auth import get_user_model

        from . import members, releases
        from .models import TeamMember

        members._attempts.clear()
        u = get_user_model().objects.create_user("ed2", password="secret123")
        TeamMember.objects.create(user=u, role="editor", sites=[self.site.id])
        v = releases.create(self.site, "1.0.0")
        c = Client()
        c.post("/login", {"username": "ed2", "password": "secret123"}, **{"buildweb.team": True})
        self.assertEqual(c.get(f"/api/sites/{self.site.id}/releases", **{"buildweb.team": True}).status_code, 403)
        self.assertEqual(c.get(f"/api/releases/{v.id}/file.bwsite", **{"buildweb.team": True}).status_code, 403)
        self.assertEqual(c.post(f"/api/sites/{self.site.id}/domain", "{}", content_type="application/json", **{"buildweb.team": True}).status_code, 403)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class SpecialPageTests(TestCase):
    """v0.9: pages only members who meet conditions may open (Page.access == "rules")."""

    def setUp(self):
        from . import generate, members

        members._attempts.clear()
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Club", "blank")
        self.site.auth = {"enabled": True, "roles": ["member", "vip", "gold"]}
        self.site.save()
        generate.create_member_pages(self.site)
        self.page = self.site.pages.create(title="Pro", slug="pro", html="<h1>PRO {{user.name}}</h1>")
        self.pricing = self.site.pages.create(title="แพ็กเกจ", slug="pricing", html="<h1>pricing</h1>")
        self.root = f"/{self.site.slug}/"
        self.pub = {"buildweb.public": True}
        self.user = members.create_user(self.site, "ann@corp.co.th", "secret123", "Ann", role="member", verified=True)

    def set_rules(self, rules):
        r = self.c.post(f"/api/pages/{self.page.id}/update", json.dumps({"access": "rules", "access_rules": rules}),
                        content_type="application/json")
        self.page.refresh_from_db()
        return r

    def login(self, client, email="ann@corp.co.th"):
        client.post(f"{self.root}api/v1/auth/login", json.dumps({"email": email, "password": "secret123"}),
                    content_type="application/json", **self.pub)

    def test_conditions_all_any_and_deny(self):
        from . import access

        r = self.set_rules({"match": "all", "conditions": [
            {"type": "role", "values": ["vip", "gold"]}, {"type": "field", "field": "plan", "op": "eq", "value": "pro"}],
            "deny": {"message": "สำหรับ VIP <b>เท่านั้น</b>"}})
        self.assertEqual(r.status_code, 200, r.content)
        anon = Client().get(f"{self.root}pro.html", **self.pub)
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login.html?next=pro.html", anon["Location"])
        cl = Client()
        self.login(cl)
        denied = cl.get(f"{self.root}pro.html", **self.pub)
        self.assertEqual(denied.status_code, 403)
        self.assertIn("สำหรับ VIP &lt;b&gt;เท่านั้น&lt;/b&gt;", denied.content.decode())  # owner text is escaped
        self.user.role = "vip"
        self.user.save()
        self.assertEqual(cl.get(f"{self.root}pro.html", **self.pub).status_code, 403)  # plan still missing
        self.user.profile = {"plan": "PRO"}
        self.user.save()
        self.assertContains(cl.get(f"{self.root}pro.html", **self.pub), "PRO Ann")
        # "any" + redirect for those who don't qualify
        self.set_rules({"match": "any", "conditions": [{"type": "email_domain", "values": ["@school.ac.th"]},
                                                       {"type": "member_days", "value": 30}], "deny": {"redirect": "pricing"}})
        r = cl.get(f"{self.root}pro.html", **self.pub)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/pricing.html"))
        self.user.created_at = self.user.created_at - __import__("datetime").timedelta(days=31)
        self.user.save()
        self.assertEqual(cl.get(f"{self.root}pro.html", **self.pub).status_code, 200)
        # menu: hidden for those who can't open it, admins see everything
        self.assertTrue(access.evaluate(self.page, self.user)[0])
        self.user.role = "admin"
        self.user.created_at = __import__("django.utils.timezone", fromlist=["now"]).now()
        self.user.save()
        self.assertTrue(access.evaluate(self.page, self.user)[0])
        files, _ = render.build_files(self.site)
        self.assertNotIn("pro.html", files)  # never in static exports
        self.assertIn("pricing.html", files)

    def test_purchase_list_date_and_profile_expiry(self):
        from datetime import timedelta

        from django.utils import timezone

        from . import access, shop

        prod, orders = shop.ensure_collections(self.site)
        course = Record.objects.create(collection=prod, data={"name": "คอร์ส A", "price": 990, "active": True})
        other = Record.objects.create(collection=prod, data={"name": "เสื้อ", "price": 200, "active": True})
        page = self.page
        page.access = "rules"
        page.access_rules = access.clean({"conditions": [{"type": "purchased", "product": str(course.id)}]}, self.site)
        self.assertFalse(access.evaluate(page, self.user)[0])
        Record.objects.create(collection=orders, data={"number": "1", "status": "pending", "email": "ANN@corp.co.th",
                                                       "items": [{"id": course.id, "qty": 1}]})
        self.assertFalse(access.evaluate(page, self.user)[0])  # not paid yet
        Record.objects.create(collection=orders, data={"number": "2", "status": "paid", "items": [{"id": other.id, "qty": 1}]},
                              owner=self.user)
        self.assertFalse(access.evaluate(page, self.user)[0])  # paid, but another product
        Record.objects.create(collection=orders, data={"number": "3", "status": "paid", "items": [{"id": course.id, "qty": 1}]},
                              owner=self.user)
        self.assertTrue(access.evaluate(page, self.user)[0])
        # an email list kept as a collection
        vip = Collection.objects.create(site=self.site, name="VIP", slug="vip-list", fields=[{"name": "email", "type": "email"}])
        page.access_rules = access.clean({"conditions": [{"type": "in_collection", "collection": "vip-list", "field": "email"}]}, self.site)
        self.assertFalse(access.evaluate(page, self.user)[0])
        Record.objects.create(collection=vip, data={"email": "Ann@Corp.co.th"})
        self.assertTrue(access.evaluate(page, self.user)[0])
        # subscription that expires: profile date in the future
        page.access_rules = access.clean({"conditions": [{"type": "field", "field": "expires", "op": "future"}]}, self.site)
        self.user.profile = {"expires": (timezone.localdate() - timedelta(days=1)).isoformat()}
        self.assertFalse(access.evaluate(page, self.user)[0])
        self.user.profile = {"expires": (timezone.localdate() + timedelta(days=10)).isoformat()}
        self.assertTrue(access.evaluate(page, self.user)[0])
        # a page open only during a period needs no login
        now = timezone.localtime()
        page.access_rules = access.clean({"conditions": [{"type": "date_between", "from": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                                                          "to": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")}]}, self.site)
        self.assertTrue(access.evaluate(page, None)[0])
        self.assertFalse(access.needs_login(page))
        page.save()
        self.assertEqual(Client().get(f"{self.root}pro.html", **self.pub).status_code, 200)
        page.access_rules = access.clean({"conditions": [{"type": "date_between", "from": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")}],
                                          "deny": {"message": "เปิดพรุ่งนี้"}}, self.site)
        page.save()
        r = Client().get(f"{self.root}pro.html", **self.pub)
        self.assertEqual(r.status_code, 403)
        self.assertIn("เปิดพรุ่งนี้", r.content.decode())

    def test_validation_tester_and_backup(self):
        from io import BytesIO

        from . import backup

        self.assertEqual(self.set_rules({"conditions": []}).status_code, 400)
        self.assertEqual(self.set_rules({"conditions": [{"type": "field", "field": "a b", "op": "eq"}]}).status_code, 400)
        self.assertEqual(self.set_rules({"conditions": [{"type": "in_collection", "collection": "nope"}]}).status_code, 400)
        self.assertEqual(self.set_rules({"conditions": [{"type": "hack"}]}).status_code, 400)
        self.assertEqual(self.set_rules({"conditions": [{"type": "verified"}], "deny": {"redirect": "missing"}}).status_code, 400)
        home = self.site.home_page()
        r = self.c.post(f"/api/pages/{home.id}/update", json.dumps({"access": "rules", "access_rules": {"conditions": [{"type": "verified"}]}}),
                        content_type="application/json")
        self.assertEqual(r.status_code, 400)  # the home page stays open to everyone
        self.assertEqual(self.set_rules({"conditions": [{"type": "role", "values": ["vip"]}]}).status_code, 200)
        info = self.c.get(f"/api/pages/{self.page.id}/access").json()
        self.assertIn("purchased", info["types"])
        t = self.c.post(f"/api/pages/{self.page.id}/access", json.dumps({"email": "ann@corp.co.th"}), content_type="application/json").json()
        self.assertFalse(t["allowed"])
        self.assertEqual(t["results"][0]["text"], "บทบาท vip")
        t = self.c.post(f"/api/pages/{self.page.id}/access", json.dumps({"email": "ann@corp.co.th", "access_rules": {
            "conditions": [{"type": "verified"}]}}), content_type="application/json").json()
        self.assertTrue(t["allowed"])  # try rules before saving them
        copy = backup.import_site(BytesIO(backup.export_bytes(self.site)), mode="new")
        self.assertEqual(copy.pages.get(slug="pro").access_rules["conditions"], [{"type": "role", "values": ["vip"]}])


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class MemberFormTests(TestCase):
    """v0.9: member form builder (extra sign-up/account fields), shown in the app, the data tab and CSV."""

    def setUp(self):
        from . import generate, members

        members._attempts.clear()
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Gym", "blank")
        self.site.auth = {"enabled": True, "roles": ["member"]}
        self.site.save()
        generate.create_member_pages(self.site)
        self.root = f"/{self.site.slug}/"
        self.pub = {"buildweb.public": True}
        self.fields = [
            {"label": "เบอร์โทร", "name": "phone", "type": "phone", "required": True},
            {"label": "เพศ", "name": "gender", "type": "select", "options": "ชาย, หญิง, ไม่ระบุ"},
            {"label": "วันเกิด", "name": "birthday", "type": "date"},
            {"label": "รับข่าวสาร", "name": "newsletter", "type": "bool"},
            {"label": "แพ็กเกจ", "name": "plan", "type": "select", "options": ["free", "pro"], "register": False, "account": False},
        ]

    def save_fields(self, fields):
        return self.c.post(f"/api/sites/{self.site.id}/members/settings", json.dumps({"settings": {"fields": fields}}),
                           content_type="application/json")

    def auth(self, client, path, d, method="post"):
        return getattr(client, method)(f"{self.root}api/v1/auth/{path}", json.dumps(d), content_type="application/json", **self.pub)

    def test_builder_forms_signup_account_and_owner_only_fields(self):
        r = self.save_fields(self.fields)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["settings"]["fields"][1]["options"], ["ชาย", "หญิง", "ไม่ระบุ"])
        self.assertEqual(self.save_fields([{"name": "email", "label": "x"}]).status_code, 400)  # reserved
        self.assertEqual(self.save_fields([{"name": "a b"}]).status_code, 400)
        # the forms on the site follow the field list
        reg = self.c.get(f"{self.root}register.html", **self.pub).content.decode()
        self.assertIn('name="phone"', reg)
        self.assertIn('type="tel"', reg)
        self.assertIn('<option value="หญิง">', reg)
        self.assertIn('<input type="hidden" name="newsletter" value="">', reg)
        self.assertNotIn('name="plan"', reg)  # owner-only
        # sign up: required + validation, values stored in the profile
        bad = self.auth(Client(), "register", {"email": "a@x.io", "password": "secret123", "name": "A", "gender": "หญิง"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("phone", bad.json()["error"]["fields"])
        self.assertFalse(self.site.members.exists())  # nothing created on a failed sign-up
        bad = self.auth(Client(), "register", {"email": "a@x.io", "password": "secret123", "phone": "081-234-5678", "gender": "อื่น"})
        self.assertEqual(bad.status_code, 422)
        cl = Client()
        ok = self.auth(cl, "register", {"email": "a@x.io", "password": "secret123", "name": "Ann", "phone": "081-234-5678",
                                        "gender": "หญิง", "birthday": "1995-04-01", "newsletter": "on", "plan": "pro"})
        self.assertEqual(ok.status_code, 201, ok.content)
        u = self.site.members.get()
        self.assertEqual(u.profile, {"phone": "081-234-5678", "gender": "หญิง", "birthday": "1995-04-01", "newsletter": True})
        # account page shows the member's values; members can't give themselves owner-only fields
        acc = cl.get(f"{self.root}account.html", **self.pub).content.decode()
        self.assertIn('value="081-234-5678"', acc)
        self.assertIn('<option value="หญิง" selected>', acc)
        self.assertNotIn('name="plan"', acc)
        r = self.auth(cl, "me", {"name": "Ann B", "newsletter": "", "plan": "pro", "profile": {"plan": "pro"}}, method="patch")
        self.assertEqual(r.status_code, 200, r.content)
        u.refresh_from_db()
        self.assertEqual(u.name, "Ann B")
        self.assertIs(u.profile["newsletter"], False)
        self.assertNotIn("plan", u.profile)
        # the owner sets it in the app
        r = self.c.post(f"/api/members/{u.id}/update", json.dumps({"profile": {"plan": "pro", "phone": "02-111-2222"}}),
                        content_type="application/json")
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertEqual((u.profile["plan"], u.profile["phone"]), ("pro", "02-111-2222"))
        self.assertEqual(self.c.post(f"/api/members/{u.id}/update", json.dumps({"profile": {"plan": "gold"}}),
                                     content_type="application/json").status_code, 400)

    def test_values_are_escaped_and_never_bound(self):
        from . import members

        self.save_fields([{"label": "บริษัท", "name": "company", "type": "text"}])
        members.create_user(self.site, "x@x.io", "secret123", "X", verified=True, profile={"company": '"><script>alert(1)</script>{{user.email}}'})
        cl = Client()
        self.auth(cl, "login", {"email": "x@x.io", "password": "secret123"})
        html = cl.get(f"{self.root}account.html", **self.pub).content.decode()
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&quot;&gt;&lt;script&gt;", html)
        self.assertIn("{{user.email}}", html)  # shown as typed, not replaced

    def test_existing_pages_get_the_slot_shown_in_data_tab_and_csv(self):
        from . import members

        reg = self.site.pages.get(slug="register")
        reg.html = reg.html.replace('<div data-bw-member-fields="register"></div>', "")  # a page made before v0.9
        reg.project_data = {"x": 1}
        reg.save()
        r = self.save_fields(self.fields[:1]).json()
        self.assertEqual(r["forms_updated"], [reg.title])
        reg.refresh_from_db()
        self.assertIn('data-bw-member-fields="register"', reg.html)
        self.assertEqual(reg.project_data, {})
        members.create_user(self.site, "b@x.io", "secret123", "Bee", verified=True, profile={"phone": "=1+2"})
        d = self.c.get(f"/api/sites/{self.site.id}/collections").json()["members"]
        self.assertEqual((d["enabled"], d["count"], d["fields"][0]["name"]), (True, 1, "phone"))
        csv_text = self.c.get(f"/api/sites/{self.site.id}/members.csv").content.decode("utf-8-sig")
        self.assertIn("เบอร์โทร", csv_text.splitlines()[0])
        self.assertIn("'=1+2", csv_text)  # no spreadsheet formulas

    def test_sites_without_fields_keep_profile_but_guard_rule_fields(self):
        from . import access, members

        members.create_user(self.site, "c@x.io", "secret123", "C", verified=True)
        page = self.site.pages.create(title="Pro", slug="pro", access="rules",
                                      access_rules=access.clean({"conditions": [{"type": "field", "field": "plan", "op": "eq", "value": "pro"}]}, self.site))
        cl = Client()
        self.auth(cl, "login", {"email": "c@x.io", "password": "secret123"})
        self.auth(cl, "me", {"profile": {"plan": "pro", "city": "BKK"}}, method="patch")
        u = self.site.members.get(email="c@x.io")
        self.assertEqual(u.profile, {"city": "BKK"})  # "plan" decides a special page: members can't set it
        self.assertFalse(access.evaluate(page, u)[0])


class _FakeProgram:
    """A small HarmoMed-like program on a random local port (real HTTP, so plugins.http is exercised as is)."""

    JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64

    def __init__(self, openapi=False, manifest=None):
        import http.server
        import threading

        outer = self
        self.calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                p = self.path
                if p == "/" and not openapi:
                    return self.send(200, b"<html><title>HarmoMed Grading</title></html>", "text/html")
                if p == "/.well-known/buildweb-plugin.json" and manifest:
                    return self.send(200, manifest)
                if p == "/openapi.json" and openapi:
                    return self.send(200, {"openapi": "3.0.0", "info": {"title": "Echo API"}, "paths": {
                        "/echo/{word}": {"get": {"operationId": "echoWord", "summary": "ทวนคำ",
                                                 "parameters": [{"name": "word", "in": "path", "required": True, "schema": {"type": "string"}},
                                                                {"name": "times", "in": "query", "schema": {"type": "integer"}}]}},
                        "/sum": {"post": {"operationId": "sum", "requestBody": {"content": {"application/json": {"schema": {
                            "type": "object", "required": ["a"], "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}}}}}}}})
                if p.startswith("/echo/"):
                    return self.send(200, {"word": p.split("/")[2].split("?")[0], "query": p.partition("?")[2]})
                if p == "/api/indicators" and not openapi:
                    return self.send(200, [{"name": "pink", "path": "indicators/pink.jpg"}])
                if p == "/api/runs" and not openapi:
                    return self.send(200, [{"filename": "7", "time": "10:00", "status": "ok", "full": "results/7_full.jpg",
                                            "plot": "results/7_plot.jpg",
                                            "report": {"metrics": {"quality": "ok", "signal": {"hex": "#ed8272", "L": 65.74}},
                                                       "study": {"sample_id": "S-1"}}}])
                if p.startswith("/files/results/"):
                    return self.send(200, outer.JPEG, "image/jpeg")
                return self.send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                outer.calls.append((self.path, self.headers.get("Content-Type", ""), raw))
                if self.path == "/sum":
                    d = json.loads(raw)
                    return self.send(200, {"total": d["a"] + d.get("b", 0)})
                if self.path == "/api/grade":
                    if b'name="target"; filename=' not in raw:
                        return self.send(400, {"error": "กรุณาเลือกภาพ target"})
                    return self.send(200, {"filename": "8", "report": {
                        "metrics": {"quality": "warn", "indicator": "pink", "signal": {"hex": "#ed8272", "L": 65.7409, "a": 39.5, "b": 26.7},
                                    "deltaE_before": 19.789, "deltaE_after": 8.67, "issues": [{"level": "warn", "message": "แสงน้อย"}]},
                        "full_result": "results/8_full.jpg", "plot": "results/8_plot.jpg"}})
                return self.send(404, {"error": "not found"})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class PluginTests(TestCase):
    """v0.10: plugins — connect a site to another program (HarmoMed preset, manifest, OpenAPI)."""

    def setUp(self):
        self.c = Client()
        self.c.get("/")
        self.site = services.create_site("Lab", "blank")
        self.prog = _FakeProgram()
        self.addCleanup(self.prog.close)
        self.root = f"/{self.site.slug}/"
        self.pub = {"buildweb.public": True}

    def connect(self, **extra):
        from . import plugins

        found = plugins.probe(self.prog.url)
        r = self.c.post(f"/api/sites/{self.site.id}/plugins", json.dumps({"found": found, **extra}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json(), self.site.plugins.get()

    def test_probe_recognises_harmomed_and_syncs_runs_with_images(self):
        from . import plugins

        found = plugins.probe(self.prog.url)
        self.assertEqual((found["how"], found["kind"]), ("preset", "harmomed"))
        self.assertIn("grade", found["manifest"]["actions"])
        d, p = self.connect(syncs=["runs"])
        self.assertTrue(any("1 แถว" in x for x in d["report"]), d["report"])
        conn = self.site.connectors.get(plugin=p.slug)
        row = conn.collection.records.get().data
        self.assertEqual((row["filename"], row["quality"], row["signal_hex"], row["sample_id"]), ("7", "ok", "#ed8272", "S-1"))
        self.assertTrue(row["image"].startswith("/media/sites/") and row["image"].endswith(".jpg"), row)
        self.assertTrue(self.site.jobs.filter(action="run_connector", params__connector=conn.id).exists())
        self.assertTrue(p.last_ok)
        # a second run reuses the copied images and updates by key
        n_assets = self.site.assets.count()
        from . import logic

        self.assertEqual(logic.run_connector(conn), 1)
        self.assertEqual((self.site.assets.count(), conn.collection.records.count()), (n_assets, 1))

    def test_call_action_from_app_with_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        _, p = self.connect()
        r = self.c.post(f"/api/plugins/{p.id}/call?key=grade", {"target": SimpleUploadedFile("a.jpg", b"img", "image/jpeg"),
                                                                 "white_point": "standard", "concentration": "2.5"})
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        show = {s["label"]: s["value"] for s in out["show"]}
        self.assertEqual((show["L*"], show["ข้อควรระวัง"], show["สีสัญญาณ (หลังปรับ)"]), (65.74, "แสงน้อย", "#ed8272"))
        self.assertEqual(len(out["images"]), 2)
        self.assertTrue(out["images"][0]["src"].startswith("data:image/jpeg;base64,"))
        path, ctype, raw = self.prog.calls[-1]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(b'name="concentration"\r\n\r\n2.5', raw)
        self.assertIn(b'filename="a.jpg"', raw)
        # required file / bad select / program errors come back as messages
        r = self.c.post(f"/api/plugins/{p.id}/call?key=grade", {"white_point": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(self.site.run_logs.filter(kind="plugin", ok=True).exists())

    def test_public_form_access_save_and_render(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        _, p = self.connect()
        url = f"{self.root}api/v1/plugins/{p.slug}/grade"
        img = lambda: SimpleUploadedFile("a.jpg", b"img", "image/jpeg")  # noqa: E731
        self.assertEqual(Client().post(url, {"target": img()}, **self.pub).status_code, 403)
        page = self.site.pages.create(title="ตรวจ", slug="check", html=f'<section>{plugins_block(p)}</section>')
        html = Client().get(f"{self.root}check.html", **self.pub).content.decode()
        self.assertIn("ยังไม่เปิดให้ผู้เข้าชมใช้", html)
        r = self.c.post(f"/api/plugins/{p.id}/save", json.dumps({"access": {"grade": "public"}, "save": {"grade": "new"}}),
                        content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        html = Client().get(f"{self.root}check.html", **self.pub).content.decode()
        self.assertIn(f'data-bw-plugin-form="{p.slug}/grade"', html)
        self.assertIn('<option value="pink">pink</option>', html)  # choices read from the program
        self.assertIn('type="file" name="target"', html)
        js = Client().get(f"{self.root}js/site.js", **self.pub).content.decode()
        self.assertIn("data-bw-plugin-form", js)
        bad = Client().post(url, {"target": SimpleUploadedFile("a.exe", b"x")}, **self.pub)
        self.assertEqual(bad.status_code, 400)
        r = Client().post(url, {"target": img(), "sample_id": "<b>S</b>"}, **self.pub)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("data", r.json())  # visitors get the shown values only
        p.refresh_from_db()
        col = self.site.collections.get(slug=p.settings["save"]["grade"])
        row = col.records.get().data
        self.assertIn("<b>S</b>", row.values())
        self.assertTrue(any(str(v).startswith("/media/") for v in row.values()))
        # members only
        self.c.post(f"/api/plugins/{p.id}/save", json.dumps({"access": {"grade": "user"}}), content_type="application/json")
        self.assertEqual(Client().post(url, {"target": img()}, **self.pub).status_code, 401)

    def test_openapi_and_well_known_manifest(self):
        from . import plugins

        api_prog = _FakeProgram(openapi=True)
        self.addCleanup(api_prog.close)
        found = plugins.probe(api_prog.url)
        self.assertEqual(found["how"], "openapi")
        acts = found["manifest"]["actions"]
        self.assertEqual(acts["echoword"]["inputs"][0]["in"], "path")
        p, _ = plugins.setup(self.site, found)
        out = plugins.call(p, "echoword", {"word": "สวัสดี", "times": "3"})
        self.assertEqual(out["data"]["word"], "%E0%B8%AA%E0%B8%A7%E0%B8%B1%E0%B8%AA%E0%B8%94%E0%B8%B5")
        self.assertEqual(out["data"]["query"], "times=3")
        self.assertEqual(plugins.call(p, "sum", {"a": "2", "b": "3.5"})["data"]["total"], 5.5)
        with self.assertRaises(plugins.PluginError):
            plugins.call(p, "sum", {"b": "1"})
        own = _FakeProgram(manifest={"name": "Mine", "actions": {"ping": {"path": "/api/indicators"}}})
        self.addCleanup(own.close)
        self.assertIsNone(plugins._safe_probe("not a url ://"))
        found = plugins.probe(own.url)
        self.assertEqual((found["how"], found["manifest"]["name"]), ("manifest", "Mine"))  # its own manifest wins over a preset
        with self.assertRaises(plugins.PluginError):
            plugins.clean_manifest({"syncs": {"bad": {"path": "http://evil/x"}}})
        self.assertIsNone(plugins.fill("/files/{a}", {"a": "../../etc/passwd"}))
        self.assertEqual(plugins.fill("/files/{a}", {"a": "results/1 x.jpg"}), "/files/results/1%20x.jpg")

    def test_discover_backup_and_team_rules(self):
        from . import backup, plugins, team

        port = int(self.prog.url.rsplit(":", 1)[1])
        with mock.patch.object(plugins, "SCAN_PORTS", (port, 1)):
            found = plugins.discover()
        self.assertEqual([f["kind"] for f in found], ["harmomed"])
        _, p = self.connect(syncs=["runs"], pages=["grade"])
        self.assertEqual(p.settings["access"]["grade"], "public")
        self.assertTrue(self.site.pages.filter(html__contains=f'data-bw-plugin="{p.slug}/grade"').exists())
        d = backup.site_dict(self.site)
        self.assertEqual(d["plugins"][0]["slug"], p.slug)
        self.assertEqual(d["connectors"][0]["plugin"], p.slug)
        self.assertTrue(any(re.search(rx, f"/api/plugins/{p.id}/save") for rx in team.EDITOR_DENY))
        self.assertTrue(any(re.search(rx, f"/api/sites/{self.site.id}/plugins") for rx in team.EDITOR_DENY))
        r = self.c.post(f"/api/plugins/{p.id}/delete", json.dumps({}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.site.connectors.exists() or self.site.jobs.exists())


def plugins_block(p):
    from . import plugins

    return plugins.block_html(p, "grade")
