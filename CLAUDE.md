# BuildWeb — notes for Claude

Drag-and-drop website builder: a Tauri 2 shell around a Django backend with a GrapesJS editor. Reply to the
user in Thai. The UI copy is in Thai.

## Layout
- `backend/run.py`: entry point. It checks MySQL (falls back to safe mode), migrates, starts the hosting
  server and serves the editor on 127.0.0.1:$BUILDWEB_PORT (5050).
- `backend/buildweb/config.py`: JSON config (db/hosting/export) in `$BUILDWEB_DATA`, not in the DB.
- `backend/builder/`
  - `render.py`: Site → files. **One renderer** is shared by preview, hosting and export. Paths are relative
    (`about.html`, `assets/...`); `/media/...` is rewritten to `assets/...`.
  - `sections.py`: the section blocks and starter templates (single source; the editor gets them as JSON).
    In section CSS, theme vars (`var(--bw-*)`) in shorthands need the PostCSS parser plugin, which is loaded.
  - `services.py`: site/page operations; `api.py`: JSON API; `public.py`: preview and hosting views.
  - `hosting.py`: a second waitress server; the WSGI environ flag `buildweb.public` switches the urlconf to
    `urls_public` (published content only).
  - `dbtools.py`: MySQL test, create, switch (`manage.py` subprocess with `BUILDWEB_DB_OVERRIDE`), and restart
    via `os.execv` (same PID, so the Tauri shell keeps tracking it).
  - `db/mysql`: a PyMySQL-based backend that allows MariaDB 10.4 (XAMPP 8.x).
  - `middleware.py`: auto sign-in for localhost, safe mode, and the friendly page shown when the DB goes down.
  - Shared header/footer: `SharedSection`. The renderer wraps every page with them. Elements marked
    `data-bw-auto-nav` are filled with the menu at render time. In the editor they are shown as
    non-saved `bw-shared` components (`toHTML()` returns '').
  - `importer.py`: html/zip/folder/GitHub → pages and assets. Archives are untrusted (paths are sanitised,
    sizes capped, nothing is executed). Imported sites get `use_base_styles=False`.
  - `notify.py`: notification channels (macOS osascript, Telegram, Discord, SMTP, webhook), sent from a
    background thread and disabled in tests.
  - `tailscale.py`: wraps the `tailscale serve`/`funnel` CLI. `hosting.py` runs the main server, one server
    per `Site.host_port`, and the Tailscale publications (taken down on SIGTERM).
  - `data.py` + `Collection`/`Record`/`DataConnection`: site data. Collections are imported from MySQL/XAMPP
    (copy mode, or live mode read on every render with a 15 s cache), from `.sql` dumps or from CSV.
    `Binder` renders `data-bw-repeat` blocks and `{{field}}` placeholders at render time. Unresolved
    placeholders are left as-is, because imported Vue/Handlebars sites use `{{ }}` too. API rows use `_id`
    for the record id (tables often have their own `id`).
  - Detail pages: `Page.collection` renders one file per row at `<page.slug>/<row>.html` with `<base href="../">`
    (`render.detail_items`, `data.row_slugs`); the template page itself is not exported. `generate.py` builds
    list/detail pages, the blog and collection forms. `widgets.py` holds the browser-side search/facet/paging
    JS and the floating contact buttons (`Site.contact`). Forms with `data-bw-collection` go through
    `forms.py` (only collections with `options.forms`, rows wait in `Record.approved=False`).
  - `seo.py` (scores), `stats.py` (hosting-server visit counters in `Stat`, buffered), `publish.py` (GitHub
    Pages via the git data API, Netlify zip deploy, FTP; background jobs; tokens in config.json "publish").
    Never publish to real GitHub/Netlify accounts in tests: `publish.http`/`FTP` are mocked.
  - `system.py`: OS helpers (open/reveal, desktop notifications, XAMPP/Tailscale paths). Never call
    `os.kill(pid, 0)` directly, because on Windows it terminates the process.
- `src-tauri/src/lib.rs`: same pattern as ClearFrame (bundled uv → venv → run backend → updater), plus
  a tray icon, hide-on-close, autostart (`--hidden`), auto-install when `app.auto_update` is set in the
  backend config, and a graceful stop on quit (HTTP POST /api/system/shutdown with header `X-BuildWeb: 1`).
  - **macOS:** the backend runs as the launchd job `com.buildweb.backend` (plist in the app data dir), not
    as a child process. macOS 26+ RunningBoard freezes windowless apps together with their children, which
    used to stop the backend and hosting. `NSAppSleepDisabled` and an NSProcessInfo activity are also set.
  - Only a backend this instance started is stopped on quit (`STARTED_BACKEND`). `BUILDWEB_PORT` overrides
    the port, which is useful for testing next to the installed app.
  - Tailscale CLI calls need `TAILSCALE_BE_CLI=1`; without it, the macOS app binary tries to open its GUI
    when launched from Finder.
- CI (`.github/workflows/release.yml`) builds darwin-aarch64, darwin-x86_64 (cross-compiled, with an x64 uv),
  windows-x86_64 (NSIS) and linux-x86_64 (AppImage + deb). Each platform runs `scripts/collect.js`, then
  `scripts/publish.js` writes one latest.json plus fixed-name downloads (BuildWeb.dmg, BuildWeb-Intel.dmg,
  BuildWeb-Setup.exe, BuildWeb.AppImage, BuildWeb.deb).
- Theme: tokens in `app.css` (`:root` and `[data-theme=dark]`). `_head.html` applies the saved theme before
  first paint.

## Rules
- Run tests with `cd backend && BUILDWEB_DATA=$(mktemp -d) .venv/bin/python manage.py test builder`.
- When running a dev server while testing, use a port other than 5050 if the installed app may be running.
- Releases: every push to main publishes a patch (`.github/workflows/release.yml`), so pushing is itself a
  release and is outward-facing; confirm with the user first. Use `[skip release]` for non-release pushes.
  Versions are set with `node scripts/set-version.js` (it updates package.json and Cargo.toml).
- When testing Tailscale publishing, use a spare HTTPS port and turn it off afterwards. Never enable
  Funnel (public internet) without asking the user.
- On this Mac, XAMPP is x86-only and Rosetta is not installed, so XAMPP's MySQL/PHP cannot run here. Test
  MySQL with a throwaway Homebrew `mysqld` on another port.
