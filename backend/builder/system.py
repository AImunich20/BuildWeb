"""Small OS-specific helpers so the backend runs the same on macOS, Windows and Linux."""
import os
import subprocess
import sys
from pathlib import Path

MAC, WINDOWS = sys.platform == "darwin", os.name == "nt"
NO_WINDOW = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW: no console flash for helper processes


def popen(args, **kw):
    if WINDOWS:
        kw.setdefault("creationflags", NO_WINDOW)
    return subprocess.Popen(args, **kw)


def run(args, **kw):
    if WINDOWS:
        kw.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(args, **kw)


def open_target(target):
    """Open a URL, file or folder with the default app."""
    if MAC:
        popen(["open", str(target)])
    elif WINDOWS:
        os.startfile(str(target))  # noqa: S606 - local path/URL chosen by the user
    else:
        popen(["xdg-open", str(target)])


def reveal(path):
    """Show a file/folder in Finder / Explorer / the file manager."""
    p = Path(path)
    if MAC:
        popen(["open", "-R", str(p)])
    elif WINDOWS:
        popen(["explorer", "/select,", str(p)])
    else:
        popen(["xdg-open", str(p if p.is_dir() else p.parent)])


def process_alive(pid):
    """True while ``pid`` exists. (os.kill(pid, 0) would *terminate* the process on Windows.)"""
    if WINDOWS:
        import ctypes

        SYNCHRONIZE, WAIT_TIMEOUT = 0x00100000, 0x102
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def desktop_notify(title, text):
    if MAC:
        import json

        script = f"display notification {json.dumps(text[:240])} with title {json.dumps(title)} sound name \"Glass\""
        run(["osascript", "-e", script], timeout=5, capture_output=True)
    elif WINDOWS:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$x = $t.GetElementsByTagName('text'); $x.Item(0).AppendChild($t.CreateTextNode($env:BW_TITLE)) > $null;"
            "$x.Item(1).AppendChild($t.CreateTextNode($env:BW_TEXT)) > $null;"
            "$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=15, capture_output=True,
            env={**os.environ, "BW_TITLE": title, "BW_TEXT": text[:240]})
    else:
        run(["notify-send", "-a", "BuildWeb", title, text[:240]], timeout=5, capture_output=True)


def xampp_dirs():
    """(install dir, htdocs, mysql socket) for the platform's default XAMPP location."""
    if MAC:
        base = Path("/Applications/XAMPP/xamppfiles")
        return base, base / "htdocs", base / "var/mysql/mysql.sock"
    if WINDOWS:
        base = Path(os.environ.get("XAMPP_HOME", r"C:\xampp"))
        return base, base / "htdocs", None
    base = Path("/opt/lampp")
    return base, base / "htdocs", base / "var/mysql/mysql.sock"


def xampp_manager():
    base, _, _ = xampp_dirs()
    if MAC:
        return base / "manager-osx.app"
    if WINDOWS:
        return base / "xampp-control.exe"
    return base / "manager-linux-x64.run"


def tailscale_candidates():
    if MAC:
        return ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"]
    if WINDOWS:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        return [os.path.join(pf, "Tailscale", "tailscale.exe")]
    return ["/usr/bin/tailscale", "/usr/local/bin/tailscale", "/usr/sbin/tailscale"]
