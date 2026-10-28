# BuildWeb

<p align="center"><img src="src-tauri/icons/128x128@2x.png" width="128" alt="BuildWeb"></p>

A drag-and-drop website builder for macOS, in the spirit of Canva. You design pages visually, host them
from your Mac, and export plain HTML/CSS/JS. It ships as a `.dmg` and updates itself from GitHub Releases.

## Features

- **Drag-and-drop editor** (GrapesJS): 19 ready-made sections in Thai (hero, features, pricing, reviews,
  team, FAQ, contact form, map, YouTube, menu/products, footer …) plus basic elements, forms, tabs,
  countdown and custom code. It has device previews (desktop/tablet/mobile), undo/redo, code view, HTML
  import, autosave, and a page history you can restore from.
- **Starter templates:** business, café/restaurant, portfolio, landing page, or blank.
- **Site theme:** colors, Thai Google Fonts, corner radius and content width. Every section follows the
  theme.
- **Detailed page management:** title, file name, draft/published, parent page, menu label and order (drag
  to reorder), SEO title, description and keywords, og:image, noindex, and per-page `<head>`/CSS/JS. You can
  duplicate a page, set the home page, and rebuild the menu on every page with one click.
- **File manager:** upload by drag-and-drop with a progress bar, folders, search and filter, rename and move
  (pages that use the file are updated), alt text, and a warning before deleting a file that is in use.
- **Forms that work:** submissions are stored in the database. You can read them, mark them as read, delete
  them, and download them as CSV (Excel-friendly, Thai-safe).
- **Hosting:** a separate server on your LAN (default port 8090) serves only published sites. The editor
  and admin stay on `127.0.0.1`. You can choose a default site at `/`.
- **Export:** a folder or `.zip` with `index.html`, `<page>.html`, `css/`, `js/site.js` and `assets/`. You can
  export to `~/Downloads/BuildWeb`, straight into **XAMPP `htdocs`** (`http://localhost/<site>/`), or to any
  folder you choose. The optional `bw-form.php` saves form submissions into XAMPP MySQL.
- **Database:** SQLite by default, or one click to switch to **MySQL/MariaDB (XAMPP)**. The switch tests
  the connection, creates the database (utf8mb4), migrates and copies every record, then restarts the app.
  If MySQL is down when the app starts, BuildWeb opens in a safe mode where you can fix the connection.
- **Admin:** the BuildWeb dashboard plus the full **Django Admin** at `/django-admin/`. You are signed in
  automatically, because the admin only listens on localhost.
- **Auto-update:** the app checks GitHub Releases at start and every 6 hours. Click “อัพเดทเลย” and it
  installs the update and restarts. You can also check manually from the app menu or Settings.

## Stack

| Part | Tech |
|---|---|
| Desktop shell | Tauri 2 (Rust): starts the backend, shows the window, runs the updater |
| Backend | Django 5.2 LTS + waitress, PyMySQL (custom backend accepts XAMPP's MariaDB 10.4) |
| Editor | GrapesJS 0.23 + plugins (vendored in `backend/builder/static/vendor/grapesjs`) |
| Python env | Bundled `uv` creates a private venv in `~/Library/Application Support/com.buildweb.app` on first run |

## Development

```sh
cd backend
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run.py                 # http://127.0.0.1:5050  (data in backend/.data)
BUILDWEB_PORT=5051 .venv/bin/python run.py
.venv/bin/python manage.py test builder # test suite
```

Desktop app: run `npm install`, then `npm run dev`, or `npm run dmg` for a local `.dmg` (copied to `release/`).
To update GrapesJS, bump the versions in `package.json` and run `npm run vendor`.

## Releasing an update

1. Bump `version` in `package.json` **and** `src-tauri/Cargo.toml`.
2. `RELEASE_NOTES="..." npm run release -- --publish`

This builds and signs the app (key: `~/.tauri/buildweb.key`, never commit it) and uploads the `.dmg`,
`.app.tar.gz`, `.sig` and `latest.json` to **AImunich20/buildweb-releases**. Installed apps then pick up the
update.

## Data locations (installed app)

`~/Library/Application Support/com.buildweb.app/`
- `data/config.json`: database and hosting settings
- `data/db.sqlite3`: the SQLite database
- `data/media/`: uploaded files
- `backend.log`: server log
