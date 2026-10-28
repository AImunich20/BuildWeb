//! BuildWeb desktop shell.
//!
//! The Django backend (editor, admin, hosting server) ships inside the app as a resource. On launch we:
//! 1. create/refresh a private Python env in ~/Library/Application Support with the bundled `uv`
//!    (first run downloads Python + Django; later runs reinstall only when requirements.txt changes),
//! 2. start `run.py` on 127.0.0.1:5050 (the editor is local only; published sites can be hosted on the
//!    LAN by the backend's separate hosting server),
//! 3. point the window at it, and
//! 4. check GitHub Releases for a signed update (at start and every hour; installs on its own when
//!    "auto update" is on in the app's settings).
//!
//! Closing the window only hides it: the app keeps running in the menu bar so hosted sites stay online.
//! Quit from the menu-bar icon or ⌘Q. With "launch at login" it starts hidden (`--hidden`).

use std::fs;
#[cfg(not(target_os = "macos"))]
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, MenuItemKind, PredefinedMenuItem};
use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewWindow, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

/// Editor/backend port. BUILDWEB_PORT overrides it (for testing next to an installed copy).
static PORT: std::sync::LazyLock<u16> =
    std::sync::LazyLock::new(|| std::env::var("BUILDWEB_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(5050));
const UPDATE_INTERVAL: Duration = Duration::from_secs(60 * 60);

struct Backend(Mutex<Option<Child>>);

/// True only when this app instance started the backend (so quitting never stops another instance's).
static STARTED_BACKEND: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn js(win: &WebviewWindow, func: &str, msg: &str) {
    let arg = serde_json::to_string(msg).unwrap_or_default();
    let _ = win.eval(format!("window.{func} && window.{func}({arg})"));
}

fn port_open() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], *PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// Finder-launched apps get a minimal PATH; add Homebrew for any tools the backend shells out to.
fn path_env() -> String {
    let path = std::env::var("PATH").unwrap_or_default();
    if cfg!(target_os = "macos") {
        format!("/opt/homebrew/bin:/usr/local/bin:{path}")
    } else {
        path
    }
}

/// A command for a helper process; on Windows it must not flash a console window.
fn command(program: &Path) -> Command {
    #[allow(unused_mut)]
    let mut c = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    c
}

fn venv_python(venv: &Path) -> PathBuf {
    if cfg!(windows) { venv.join("Scripts").join("python.exe") } else { venv.join("bin").join("python") }
}

/// Run a command, streaming its output lines into the loading screen's log.
fn run_logged(win: &WebviewWindow, mut cmd: Command) -> Result<(), String> {
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd.spawn().map_err(|e| format!("เริ่มคำสั่งไม่ได้: {e}"))?;
    let stderr = child.stderr.take().expect("piped stderr");
    let w = win.clone();
    let errs = thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            js(&w, "addLog", &line);
        }
    });
    if let Some(out) = child.stdout.take() {
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            js(win, "addLog", &line);
        }
    }
    let _ = errs.join();
    let status = child.wait().map_err(|e| e.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("คำสั่งล้มเหลว ({status})"))
    }
}

/// Make sure the private venv exists and matches the bundled requirements.txt.
fn ensure_env(win: &WebviewWindow, backend: &Path, uv: &Path, data: &Path) -> Result<PathBuf, String> {
    let venv = data.join("venv");
    let py = venv_python(&venv);
    let req_path = backend.join("requirements.txt");
    let req = fs::read_to_string(&req_path).map_err(|e| format!("ไม่พบ requirements.txt: {e}"))?;
    let stamp = data.join("requirements.installed");
    if py.exists() && fs::read_to_string(&stamp).ok().as_deref() == Some(req.as_str()) {
        return Ok(py);
    }
    let uv_cmd = || {
        let mut c = command(uv);
        c.env("PATH", path_env())
            .env("UV_PYTHON_INSTALL_DIR", data.join("python"))
            .env("UV_CACHE_DIR", data.join("uv-cache"));
        c
    };
    if !py.exists() {
        js(win, "setStatus", "กำลังติดตั้ง Python (ครั้งแรกเท่านั้น)…");
        let mut c = uv_cmd();
        c.args(["venv", "--python", "3.11"]).arg(&venv);
        run_logged(win, c)?;
    }
    js(win, "setStatus", "กำลังติดตั้งส่วนประกอบ (Django, ตัวเชื่อม MySQL) – ครั้งแรกใช้เวลาประมาณหนึ่งนาที…");
    let mut c = uv_cmd();
    c.args(["pip", "install", "--python"]).arg(&py).arg("-r").arg(&req_path);
    run_logged(win, c)?;
    fs::write(&stamp, req).map_err(|e| e.to_string())?;
    Ok(py)
}

fn start_backend(app: &AppHandle, win: &WebviewWindow) -> Result<(), String> {
    if port_open() {
        js(win, "addLog", "พบ BuildWeb ที่รันอยู่แล้ว – เชื่อมต่อเลย");
        return Ok(());
    }
    let res = app.path().resource_dir().map_err(|e| e.to_string())?;
    let backend = res.join("backend");
    let uv = res.join("bin").join(if cfg!(windows) { "uv.exe" } else { "uv" });
    let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data).map_err(|e| e.to_string())?;
    let py = ensure_env(win, &backend, &uv, &data)?;

    js(win, "setStatus", "กำลังเริ่มระบบ…");
    STARTED_BACKEND.store(true, std::sync::atomic::Ordering::SeqCst);
    let log_path = data.join("backend.log");
    let envs: Vec<(&str, String)> = vec![
        ("PATH", path_env()),
        ("PYTHONUNBUFFERED", "1".into()),
        ("BUILDWEB_PORT", PORT.to_string()),
        ("BUILDWEB_VERSION", app.package_info().version.to_string()),
        ("BUILDWEB_PARENT_PID", std::process::id().to_string()),
        ("BUILDWEB_DATA", data.join("data").to_string_lossy().into_owned()),
    ];
    #[cfg(target_os = "macos")]
    launchd::start(&py, &backend, &data, &log_path, &envs)?;
    #[cfg(not(target_os = "macos"))]
    {
        let log = File::create(&log_path).map_err(|e| e.to_string())?;
        let mut cmd = command(&py);
        cmd.arg(backend.join("run.py")).current_dir(&backend);
        for (k, v) in &envs {
            cmd.env(k, v);
        }
        let child = cmd
            .stdout(log.try_clone().map_err(|e| e.to_string())?)
            .stderr(log)
            .spawn()
            .map_err(|e| format!("เริ่ม backend ไม่ได้: {e}"))?;
        *app.state::<Backend>().0.lock().unwrap() = Some(child);
    }

    for _ in 0..360 {
        if port_open() {
            return Ok(());
        }
        if let Some(status) = backend_exited(app) {
            let tail = fs::read_to_string(&log_path).unwrap_or_default();
            let tail: String = tail.lines().rev().take(15).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
            return Err(format!("backend หยุดทำงาน ({status})\n{tail}"));
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!("backend ไม่ตอบสนองภายใน 3 นาที – ดู log ที่ {}", log_path.display()))
}

/// Ask the backend to stop over HTTP (works on every OS; it takes Tailscale links down), then make sure it
/// is gone.
fn request_shutdown() {
    use std::io::{Read, Write};
    let addr = SocketAddr::from(([127, 0, 0, 1], *PORT));
    if let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) {
        let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
        let _ = s.write_all(b"POST /api/system/shutdown HTTP/1.0\r\nHost: 127.0.0.1\r\nX-BuildWeb: 1\r\nContent-Length: 0\r\n\r\n");
        let mut buf = [0u8; 256];
        let _ = s.read(&mut buf);
    }
}

fn stop_backend(app: &AppHandle) {
    if !STARTED_BACKEND.swap(false, std::sync::atomic::Ordering::SeqCst) {
        return; // attached to a backend some other instance runs
    }
    #[cfg(target_os = "macos")]
    {
        let _ = app;
        request_shutdown();
        for _ in 0..30 {
            if !port_open() {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        launchd::stop();
        return;
    }
    #[allow(unreachable_code)]
    if let Some(mut c) = app.state::<Backend>().0.lock().unwrap().take() {
        request_shutdown();
        for _ in 0..30 {
            if let Ok(Some(_)) = c.try_wait() {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = c.kill();
        let _ = c.wait();
    }
}

/// The backend's JSON config (data/config.json), for settings the shell needs (auto update, ports).
fn backend_config(app: &AppHandle) -> serde_json::Value {
    app.path()
        .app_data_dir()
        .ok()
        .and_then(|d| fs::read_to_string(d.join("data/config.json")).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(serde_json::Value::Null)
}

/// On macOS the backend runs as its own launchd job instead of a child process: macOS may freeze the app
/// (and everything in its process coalition) while its window is closed, which would take the hosted sites
/// down with it. As a launchd job the backend keeps serving no matter what happens to the window.
#[cfg(target_os = "macos")]
mod launchd {
    use std::fs;
    use std::path::Path;
    use std::process::Command;

    const LABEL: &str = "com.buildweb.backend";

    fn domain() -> String {
        let uid = Command::new("id").arg("-u").output().ok()
            .and_then(|o| String::from_utf8(o.stdout).ok()).map(|s| s.trim().to_string())
            .unwrap_or_else(|| "501".into());
        format!("gui/{uid}")
    }

    fn esc(s: &str) -> String {
        s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
    }

    pub fn start(py: &Path, backend: &Path, data: &Path, log: &Path, envs: &[(&str, String)]) -> Result<(), String> {
        stop();
        let env_xml: String = envs.iter().map(|(k, v)| format!("<key>{}</key><string>{}</string>", esc(k), esc(v))).collect();
        let plist = format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array><string>{}</string><string>{}</string></array>
<key>WorkingDirectory</key><string>{}</string>
<key>EnvironmentVariables</key><dict>{env_xml}</dict>
<key>StandardOutPath</key><string>{}</string>
<key>StandardErrorPath</key><string>{}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
<key>ProcessType</key><string>Interactive</string>
</dict></plist>"#,
            esc(&py.to_string_lossy()), esc(&backend.join("run.py").to_string_lossy()), esc(&backend.to_string_lossy()),
            esc(&log.to_string_lossy()), esc(&log.to_string_lossy()),
        );
        let path = data.join(format!("{LABEL}.plist"));
        let _ = fs::write(log, b"");
        fs::write(&path, plist).map_err(|e| e.to_string())?;
        let out = Command::new("launchctl").arg("bootstrap").arg(domain()).arg(&path).output().map_err(|e| e.to_string())?;
        if !out.status.success() {
            return Err(format!("เริ่ม backend ไม่ได้ (launchctl): {}", String::from_utf8_lossy(&out.stderr)));
        }
        Ok(())
    }

    pub fn stop() {
        let _ = Command::new("launchctl").arg("bootout").arg(format!("{}/{LABEL}", domain())).output();
    }

    /// Some(exit status) once the job has exited, None while it runs (or has not been seen yet).
    pub fn exited() -> Option<String> {
        let out = Command::new("launchctl").arg("list").arg(LABEL).output().ok()?;
        let text = String::from_utf8_lossy(&out.stdout);
        if text.contains("\"PID\" =") || !out.status.success() {
            return None;
        }
        text.lines().find(|l| l.contains("LastExitStatus")).map(|l| l.trim().trim_end_matches(';').to_string())
    }
}

#[cfg(target_os = "macos")]
fn backend_exited(_app: &AppHandle) -> Option<String> {
    launchd::exited()
}

#[cfg(not(target_os = "macos"))]
fn backend_exited(app: &AppHandle) -> Option<String> {
    app.state::<Backend>().0.lock().unwrap().as_mut()
        .and_then(|c| c.try_wait().ok().flatten()).map(|s| s.to_string())
}



/// macOS freezes apps that keep running without a visible window (RunningBoard "after-life"), which would
/// stop the backend and every hosted site. Hold a user-initiated activity for the app's whole lifetime.
#[cfg(target_os = "macos")]
fn keep_running() {
    use objc2_foundation::{NSActivityOptions, NSProcessInfo, NSString};
    let reason = NSString::from_str("BuildWeb hosts websites in the background");
    let opts = NSActivityOptions::UserInitiatedAllowingIdleSystemSleep | NSActivityOptions::LatencyCritical;
    let token = NSProcessInfo::processInfo().beginActivityWithOptions_reason(opts, &reason);
    std::mem::forget(token); // never ended: lasts until the app quits
}

#[cfg(not(target_os = "macos"))]
fn keep_running() {}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn notify(app: &AppHandle, kind: MessageDialogKind, msg: String) {
    app.dialog().message(msg).title("อัพเดท BuildWeb").kind(kind).show(|_| {});
}

/// Check GitHub Releases for a signed update. `manual` = user asked (button / menu): always report
/// the outcome and ignore a previously declined version.
async fn check_update(app: AppHandle, declined: &mut Option<String>, manual: bool) {
    let result = match app.updater() {
        Ok(updater) => updater.check().await,
        Err(e) => Err(e),
    };
    let update = match result {
        Ok(Some(u)) => u,
        Ok(None) => {
            if manual {
                let v = app.package_info().version.to_string();
                notify(&app, MessageDialogKind::Info, format!("BuildWeb v{v} เป็นเวอร์ชันล่าสุดแล้ว"));
            }
            return;
        }
        Err(e) => {
            if manual {
                notify(&app, MessageDialogKind::Warning, format!("ตรวจสอบอัพเดทไม่ได้\n\n{e}"));
            }
            return;
        }
    };
    if !manual && declined.as_deref() == Some(update.version.as_str()) {
        return;
    }
    let auto = backend_config(&app)["app"]["auto_update"].as_bool().unwrap_or(true);
    if auto && !manual {
        // Install quietly, then offer a restart (the new version also starts on the next launch).
        if update.download_and_install(|_, _| {}, || {}).await.is_err() {
            return;
        }
        *declined = Some(update.version.clone());
        let app2 = app.clone();
        let v = update.version.clone();
        let restart = tauri::async_runtime::spawn_blocking(move || {
            app2.dialog()
                .message(format!("ติดตั้ง BuildWeb v{v} เรียบร้อยแล้ว\n\nเปิดโปรแกรมใหม่ตอนนี้เพื่อใช้เวอร์ชันใหม่?"))
                .title("อัพเดท BuildWeb")
                .kind(MessageDialogKind::Info)
                .buttons(MessageDialogButtons::OkCancelCustom("เปิดใหม่ตอนนี้".into(), "ภายหลัง".into()))
                .blocking_show()
        })
        .await
        .unwrap_or(false);
        if restart {
            stop_backend(&app);
            app.restart();
        }
        return;
    }
    let msg = format!(
        "มีเวอร์ชันใหม่ {} (ตอนนี้ {})\n\n{}",
        update.version,
        update.current_version,
        update.body.clone().unwrap_or_default()
    );
    let app2 = app.clone();
    let ok = tauri::async_runtime::spawn_blocking(move || {
        app2.dialog()
            .message(msg)
            .title("อัพเดท BuildWeb")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancelCustom("อัพเดทเลย".into(), "ภายหลัง".into()))
            .blocking_show()
    })
    .await
    .unwrap_or(false);
    if !ok {
        *declined = Some(update.version.clone());
        return;
    }
    match update.download_and_install(|_, _| {}, || {}).await {
        Ok(()) => {
            stop_backend(&app);
            app.restart();
        }
        Err(e) => notify(&app, MessageDialogKind::Error, format!("อัพเดทไม่สำเร็จ: {e}")),
    }
}

fn manual_check(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        check_update(app, &mut None, true).await;
    });
}

/// Called from the UI's "อัพเดท" button (the page at 127.0.0.1 is allowed IPC via capabilities).
#[tauri::command]
fn check_for_updates(app: AppHandle) {
    manual_check(&app);
}

#[tauri::command]
fn get_autostart(app: AppHandle) -> Result<bool, String> {
    app.autolaunch().is_enabled().map_err(|e| e.to_string())
}

#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<(), String> {
    let l = app.autolaunch();
    if enabled { l.enable() } else { l.disable() }.map_err(|e| e.to_string())
}

/// Menu-bar icon: open the window, open the hosted sites, check for updates, quit.
fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "tray_open", "เปิด BuildWeb", true, None::<&str>)?;
    let sites = MenuItem::with_id(app, "tray_sites", "เปิดเว็บที่โฮสต์อยู่", true, None::<&str>)?;
    let update = MenuItem::with_id(app, "check_updates", "ตรวจสอบอัพเดท…", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "tray_quit", "ออกจาก BuildWeb", true, None::<&str>)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &sites, &sep1, &update, &sep2, &quit])?;
    TrayIconBuilder::with_id("main")
        .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
        .icon_as_template(true)
        .tooltip("BuildWeb")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, ev| match ev.id().as_ref() {
            "tray_open" => show_main(app),
            "tray_sites" => {
                let port = backend_config(app)["hosting"]["port"].as_u64().unwrap_or(8090);
                let _ = app.opener().open_url(format!("http://127.0.0.1:{port}/"), None::<&str>);
            }
            "check_updates" => manual_check(app),
            "tray_quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, ev| {
            if let TrayIconEvent::DoubleClick { button: MouseButton::Left, .. } = ev {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

/// Default macOS menu plus "ตรวจสอบอัพเดท…" under the app menu.
fn build_menu(app: &tauri::App) -> tauri::Result<()> {
    let menu = Menu::default(app.handle())?;
    if let Some(MenuItemKind::Submenu(sub)) = menu.items()?.first() {
        let item = MenuItem::with_id(app, "check_updates", "ตรวจสอบอัพเดท…", true, None::<&str>)?;
        sub.insert(&item, 1)?;
    }
    app.set_menu(menu)?;
    app.on_menu_event(|app, ev| {
        if ev.id() == "check_updates" {
            manual_check(app);
        }
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec!["--hidden"])))
        .manage(Backend(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_for_updates, get_autostart, set_autostart])
        .on_window_event(|window, event| {
            // Closing the window keeps BuildWeb (and the hosted sites) running in the menu bar.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            keep_running();
            build_menu(app)?;
            build_tray(app)?;
            let handle = app.handle().clone();
            let win = app.get_webview_window("main").expect("main window");
            if std::env::args().any(|a| a == "--hidden") {
                let _ = win.hide();
            }
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(400)); // let the loading page register its JS hooks
                match start_backend(&handle, &win) {
                    Ok(()) => {
                        let url = Url::parse(&format!("http://127.0.0.1:{}/", *PORT)).unwrap();
                        let _ = win.navigate(url);
                    }
                    Err(e) => js(&win, "setError", &e),
                }
            });
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut declined = None;
                loop {
                    check_update(handle.clone(), &mut declined, false).await;
                    tokio_sleep(UPDATE_INTERVAL).await;
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building BuildWeb");

    app.run(|handle, event| match event {
        // Dock icon clicked while the window is hidden.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main(handle),
        RunEvent::Exit => stop_backend(handle),
        _ => {}
    });
}

async fn tokio_sleep(d: Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || thread::sleep(d)).await;
}
