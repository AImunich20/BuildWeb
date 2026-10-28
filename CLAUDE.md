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
- `src-tauri/src/lib.rs`: same pattern as ClearFrame (bundled uv → venv → run backend → updater).

## Rules
- Run tests with `cd backend && BUILDWEB_DATA=$(mktemp -d) .venv/bin/python manage.py test builder`.
- When running a dev server while testing, use a port other than 5050 if the installed app may be running.
- Releases: bump `package.json` and `src-tauri/Cargo.toml`, then `npm run release -- --publish`. Publishing is
  outward-facing, so confirm with the user first.
- On this Mac, XAMPP is x86-only and Rosetta is not installed, so XAMPP's MySQL/PHP cannot run here. Test
  MySQL with a throwaway Homebrew `mysqld` on another port.
