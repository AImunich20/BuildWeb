fn main() {
    // Declare app commands so capabilities can grant them to the backend page (a remote origin).
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["check_for_updates"])),
    )
    .expect("failed to run tauri-build");
}
