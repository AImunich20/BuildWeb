# BuildWeb

<p align="center"><img src="src-tauri/icons/128x128@2x.png" width="128" alt="BuildWeb"></p>

A drag-and-drop website builder for macOS, in the spirit of Canva. You design pages visually, host them
from your Mac, and export plain HTML/CSS/JS. It ships as a `.dmg` and updates itself from GitHub Releases.

## Features

- **Drag-and-drop editor** (GrapesJS): 19 ready-made sections in Thai plus basic elements, forms, tabs,
  countdown and custom code. It has device previews, undo/redo, code view, HTML import (paste or a .html
  file), autosave, and a page history you can restore from.
- **Shared header & footer:** edit them once and every page changes. Menus fill themselves from the page
  list, with the current page highlighted and child pages shown as a dropdown. Each page can opt out, and
  older or imported sites can be converted with one click.
- **Import existing websites:** from `.html` files, a `.zip`, a whole folder, or a **GitHub repo**
  (public, or private with a token; branch and subfolder supported; build folders such as `dist/` are
  detected). Every page becomes editable. CSS, JS, images and fonts are kept, and links are rewritten.
- **Starter templates**, a **site theme** (colors, Thai Google Fonts, radius, width), and detailed
  **page management**: SEO, og:image, draft/published, parent pages, menu order, and per-page code.
- **File manager:** drag-and-drop upload, folders, rename and move (pages are updated), alt text, and
  in-use protection.
- **Forms:** submissions are stored in the database, viewable in the app and exportable as CSV. You get
  **notifications** for new submissions through macOS, Telegram, Discord, e-mail (SMTP) or a webhook.
- **Hosting several sites at once:**
  - Every published site is served at `/<slug>/` on the main port (8090).
  - Any site can also get **its own port** and be served at `/` there.
  - Sites can be reached on the LAN.
  - **Tailscale:** one switch publishes the sites as `https://<machine>.ts.net/` (`tailscale serve`,
    tailnet only) or, with Funnel, publicly on the internet. The links are taken down when the app quits.
- **Export:** a folder or `.zip` of HTML/CSS/JS/assets, written to Downloads, **XAMPP `htdocs`**, or any
  folder you choose. The optional `bw-form.php` saves submissions into XAMPP MySQL, and they show up in the
  app when it uses the same database.
- **Database:** SQLite, or switch with one click to **MySQL/MariaDB (XAMPP)**, which migrates and copies all
  data. If the database is unreachable, the app starts in a safe mode.
- **Admin:** the BuildWeb dashboard plus the full **Django Admin**. The UI is a minimal technical design
  with **light, dark and system** themes.
- **Mac app:** closing the window keeps BuildWeb in the menu bar, so hosted sites stay online. It can
  launch at login (hidden) and **auto-updates** from GitHub Releases, either by asking first or by
  installing on its own.

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

## Releasing an update: just push

Every push to `main` runs `.github/workflows/release.yml`:

1. Run the Django tests.
2. Set the next version (latest release + 1 patch, or the version in `package.json` if you raised it,
   e.g. `node scripts/set-version.js 0.2.0` for a minor release).
3. Build and sign on an Apple-silicon runner.
4. Publish the `.dmg`, `.app.tar.gz`, `.sig` and `latest.json` to **AImunich20/buildweb-releases**.
5. Commit the version bump back with `[skip ci]`.

The release notes are the commit messages. Installed apps check every hour and install the patch on their
own (they ask before restarting). Put `[skip release]` in a commit message to push without releasing.

Repository secrets (one-time setup):
- `TAURI_SIGNING_PRIVATE_KEY`: the contents of `~/.tauri/buildweb.key` (never commit the key file).
- `RELEASES_TOKEN`: a token that can create releases in `AImunich20/buildweb-releases`.

To release by hand instead, run `RELEASE_NOTES="..." npm run release -- --publish`.

## Data locations (installed app)

`~/Library/Application Support/com.buildweb.app/`
- `data/config.json`: database and hosting settings
- `data/db.sqlite3`: the SQLite database
- `data/media/`: uploaded files
- `backend.log`: server log
