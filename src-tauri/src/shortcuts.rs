use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

pub fn setup_default_shortcuts(app: AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let toggle_recording = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::KeyR,
    );
    let polish_now = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::KeyP,
    );
    let export_now = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::KeyE,
    );

    let app_clone = app.clone();
    if let Err(e) = app.global_shortcut().on_shortcut(toggle_recording, move |_app, _shortcut, event| {
        if event.state == ShortcutState::Pressed {
            // 把窗口拉到前台 + 发事件给前端
            if let Some(window) = app_clone.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            let _ = app_clone.emit("shortcut:toggle-recording", ());
        }
    }) {
        eprintln!("Failed to register Ctrl+Shift+R: {}", e);
    }

    let app_clone = app.clone();
    if let Err(e) = app.global_shortcut().on_shortcut(polish_now, move |_app, _shortcut, event| {
        if event.state == ShortcutState::Pressed {
            let _ = app_clone.emit("shortcut:polish-now", ());
        }
    }) {
        eprintln!("Failed to register Ctrl+Shift+P: {}", e);
    }

    let app_clone = app.clone();
    if let Err(e) = app.global_shortcut().on_shortcut(export_now, move |_app, _shortcut, event| {
        if event.state == ShortcutState::Pressed {
            let _ = app_clone.emit("shortcut:export-now", ());
        }
    }) {
        eprintln!("Failed to register Ctrl+Shift+E: {}", e);
    }

    Ok(())
}

#[tauri::command]
pub fn register_shortcuts(_app: AppHandle) -> Result<(), String> {
    // 预留：用于未来从前端动态修改快捷键
    Ok(())
}
