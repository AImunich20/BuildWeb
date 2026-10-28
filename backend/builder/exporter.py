"""Export a site as a folder or .zip of static files (HTML + CSS + JS + assets).

Targets: ~/Downloads/BuildWeb, XAMPP htdocs (served by Apache at http://localhost/<slug>/), or a custom
folder. For XAMPP an optional bw-form.php stores form submissions in the XAMPP MySQL database.
"""
import io
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings

from buildweb import config

from .render import build_files

PHP_FORM = r"""<?php
// BuildWeb form receiver for XAMPP.
// If BuildWeb itself uses this MySQL database, submissions go straight into its table and show up in the
// app's "ข้อมูลจากฟอร์ม" tab; otherwise they are kept in `bw_form_submissions`.
$cfg = json_decode(%(cfg)s, true);
$site = %(site)s;
header('Content-Type: application/json; charset=utf-8');
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo '{"ok":false}'; exit; }
mysqli_report(MYSQLI_REPORT_OFF);
$db = @new mysqli($cfg['host'], $cfg['user'], $cfg['password'], '', (int)$cfg['port']);
if ($db->connect_errno) { http_response_code(500); echo json_encode(['ok'=>false,'error'=>'db']); exit; }
$db->set_charset('utf8mb4');
$name = str_replace('`', '', $cfg['name']);
$db->query("CREATE DATABASE IF NOT EXISTS `$name` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
$db->select_db($name);
$data = $_POST; $form = substr($data['_form'] ?? '', 0, 200); $page = $data['_page'] ?? '';
unset($data['_form'], $data['_page']);
$json = json_encode($data, JSON_UNESCAPED_UNICODE);
$ip = substr($_SERVER['REMOTE_ADDR'] ?? '', 0, 64); $ua = substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 300);
$ok = false;
$st = $db->prepare('SELECT id FROM builder_site WHERE slug = ?');
if ($st) {
  $st->bind_param('s', $site); $st->execute(); $st->bind_result($siteId);
  $found = $st->fetch(); $st->close();
  if ($found) {
    $pageId = null;
    $pg = $db->prepare('SELECT id FROM builder_page WHERE site_id = ? AND slug = ?');
    $pg->bind_param('is', $siteId, $page); $pg->execute(); $pg->bind_result($pid);
    if ($pg->fetch()) { $pageId = $pid; } $pg->close();
    $ins = $db->prepare('INSERT INTO builder_formsubmission (site_id, page_id, form_name, data, ip, user_agent, is_read, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, UTC_TIMESTAMP(6))');
    $ins->bind_param('iissss', $siteId, $pageId, $form, $json, $ip, $ua);
    $ok = $ins->execute();
  }
}
if (!$ok) {
  $db->query("CREATE TABLE IF NOT EXISTS bw_form_submissions (
    id INT AUTO_INCREMENT PRIMARY KEY, site VARCHAR(80), page VARCHAR(80), form_name VARCHAR(200),
    data LONGTEXT, ip VARCHAR(64), created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  ) CHARACTER SET utf8mb4");
  $ins = $db->prepare('INSERT INTO bw_form_submissions (site, page, form_name, data, ip) VALUES (?, ?, ?, ?, ?)');
  $ins->bind_param('sssss', $site, $page, $form, $json, $ip);
  $ok = $ins->execute();
}
echo json_encode(['ok' => (bool)$ok]);
"""


def php_form_handler(site):
    db = config.load()["db"]
    cfg = {"host": db["host"] or "127.0.0.1", "port": int(db["port"] or 3306), "user": db["user"] or "root",
           "password": db["password"] or "", "name": db["name"] or "buildweb"}
    return PHP_FORM % {"cfg": php_str(json.dumps(cfg)), "site": php_str(site.slug)}


def php_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def collect(site, include_drafts=False, php_forms=False):
    files, assets = build_files(site, "export", include_drafts=include_drafts, php_forms=php_forms)
    if php_forms:
        files["bw-form.php"] = php_form_handler(site)
    return files, assets


def target_dir(target, site, custom_path=""):
    if target == "xampp":
        return config.XAMPP_HTDOCS / site.slug
    if target == "custom":
        if not custom_path:
            raise ValueError("กรุณาระบุโฟลเดอร์ปลายทาง")
        return Path(custom_path).expanduser() / site.slug
    return Path.home() / "Downloads" / "BuildWeb" / site.slug


def export_folder(site, dest, include_drafts=False, php_forms=False):
    files, assets = collect(site, include_drafts, php_forms)
    dest = Path(dest)
    if dest.exists():
        # Only clear what a previous export wrote, never an unrelated folder the user pointed at.
        marker = dest / ".buildweb"
        if any(dest.iterdir()) and not marker.exists():
            raise ValueError(f"โฟลเดอร์ {dest} มีไฟล์อื่นอยู่แล้ว กรุณาเลือกที่อื่น")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel, text in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    for rel, media in assets.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings.MEDIA_ROOT / media, p)
    (dest / ".buildweb").write_text(json.dumps({"site": site.slug, "exported": datetime.now().isoformat()}), "utf-8")
    return dest, len(files) + len(assets)


def export_zip_bytes(site, include_drafts=False, php_forms=False):
    files, assets = collect(site, include_drafts, php_forms)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, text in files.items():
            z.writestr(f"{site.slug}/{rel}", text)
        for rel, media in assets.items():
            z.write(settings.MEDIA_ROOT / media, f"{site.slug}/{rel}")
    return buf.getvalue(), len(files) + len(assets)


def export_zip(site, folder, include_drafts=False, php_forms=False):
    data, count = export_zip_bytes(site, include_drafts, php_forms)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{site.slug}-{datetime.now():%Y%m%d-%H%M}.zip"
    path.write_bytes(data)
    return path, count
