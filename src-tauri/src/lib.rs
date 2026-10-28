//! BuildWeb desktop shell.
//!
//! The Django backend (editor, admin, hosting server) ships inside the app as a resource. On launch we:
//! 1. create/refresh a private Python env in ~/Library/Application Support with the bundled `uv`
//!    (first run downloads Python + Django; later runs reinstall only when requirements.txt changes),
//! 2. start `run.py` on 127.0.0.1:5050 (the editor is local only; published sites can be hosted on the
//!    LAN by the backend's separate hosting server),
//! 3. point the window at it, and
//! 4. check GitHub Releases for a signed update (at start and every 6 hours).

use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem, MenuItemKind};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewWindow};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

const PORT: u16 = 5050;
const UPDATE_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);

struct Backend(Mutex<Option<Child>>);

fn js(win: &WebviewWindow, func: &str, msg: &str) {
    let arg = serde_json::to_string(msg).unwrap_or_default();
    let _ = win.eval(format!("window.{func} && window.{func}({arg})"));
}

fn port_open() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// Finder-launched apps get a minimal PATH; add Homebrew for any tools the backend shells out to.
fn path_env() -> String {
    format!("/opt/homebrew/bin:/usr/local/bin:{}", std::env::var("PATH").unwrap_or_default())
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
    let py = venv.join("bin/python");
    let req_path = backend.join("requirements.txt");
    let req = fs::read_to_string(&req_path).map_err(|e| format!("ไม่พบ requirements.txt: {e}"))?;
    let stamp = data.join("requirements.installed");
    if py.exists() && fs::read_to_string(&stamp).ok().as_deref() == Some(req.as_str()) {
        return Ok(py);
    }
    let uv_cmd = || {
        let mut c = Command::new(uv);
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
        js(win, "addLog", "พบ BuildWeb ที่รันอยู่แล้วบนพอร์ต 5050 – เชื่อมต่อเลย");
        return Ok(());
    }
    let res = app.path().resource_dir().map_err(|e| e.to_string())?;
    let backend = res.join("backend");
    let uv = res.join("bin/uv");
    let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&data).map_err(|e| e.to_string())?;
    let py = ensure_env(win, &backend, &uv, &data)?;

    js(win, "setStatus", "กำลังเริ่มระบบ…");
    let log_path = data.join("backend.log");
    let log = File::create(&log_path).map_err(|e| e.to_string())?;
    let child = Command::new(&py)
        .arg(backend.join("run.py"))
        .current_dir(&backend)
        .env("PATH", path_env())
        .env("PYTHONUNBUFFERED", "1")
        .env("BUILDWEB_PORT", PORT.to_string())
        .env("BUILDWEB_VERSION", app.package_info().version.to_string())
        .env("BUILDWEB_PARENT_PID", std::process::id().to_string())
        .env("BUILDWEB_DATA", data.join("data"))
        .stdout(log.try_clone().map_err(|e| e.to_string())?)
        .stderr(log)
        .spawn()
        .map_err(|e| format!("เริ่ม backend ไม่ได้: {e}"))?;
    *app.state::<Backend>().0.lock().unwrap() = Some(child);

    for _ in 0..360 {
        if port_open() {
            return Ok(());
        }
        if let Some(c) = app.state::<Backend>().0.lock().unwrap().as_mut() {
            if let Ok(Some(status)) = c.try_wait() {
                let tail = fs::read_to_string(&log_path).unwrap_or_default();
                let tail: String = tail.lines().rev().take(15).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
                return Err(format!("backend หยุดทำงาน ({status})\n{tail}"));
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!("backend ไม่ตอบสนองภายใน 3 นาที – ดู log ที่ {}", log_path.display()))
}

fn stop_backend(app: &AppHandle) {
    if let Some(mut c) = app.state::<Backend>().0.lock().unwrap().take() {
        let _ = c.kill();
        let _ = c.wait();
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
        .manage(Backend(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_for_updates])
        .setup(|app| {
            build_menu(app)?;
            let handle = app.handle().clone();
            let win = app.get_webview_window("main").expect("main window");
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(400)); // let the loading page register its JS hooks
                match start_backend(&handle, &win) {
                    Ok(()) => {
                        let url = Url::parse(&format!("http://127.0.0.1:{PORT}/")).unwrap();
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

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(handle);
        }
    });
}

async fn tokio_sleep(d: Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || thread::sleep(d)).await;
}
