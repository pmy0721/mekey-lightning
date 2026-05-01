// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;
mod shortcuts;
mod tray;
mod obsidian;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // 已有实例时聚焦主窗口
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            obsidian::export_to_obsidian,
            obsidian::set_obsidian_vault_path,
            obsidian::get_obsidian_vault_path,
            shortcuts::register_shortcuts,
        ])
        .setup(|app| {
            // 启动 Python sidecar
            sidecar::spawn_sidecar(app.handle().clone())?;

            // 注册系统托盘
            tray::setup_tray(app.handle())?;

            // 注册全局快捷键
            shortcuts::setup_default_shortcuts(app.handle().clone())?;

            // 关闭窗口时隐藏到托盘
            if let Some(window) = app.get_webview_window("main") {
                let win = window.clone();
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        let _ = win.hide();
                        api.prevent_close();
                    }
                });
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
