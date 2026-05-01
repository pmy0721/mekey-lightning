use tauri::{AppHandle, Emitter};
#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use std::{
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Command, Stdio},
    thread,
};

#[cfg(debug_assertions)]
pub fn spawn_sidecar(app: AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    println!("[dev] Skip sidecar spawn, run python manually");
    let _ = app.emit("sidecar-ready", ());
    Ok(())
}

#[cfg(not(debug_assertions))]
pub fn spawn_sidecar(app: AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let sidecar_path = match resolve_sidecar_path(&app) {
        Ok(path) => path,
        Err(e) => {
            eprintln!("[sidecar:error] {}", e);
            let _ = app.emit("sidecar-error", e.to_string());
            return Ok(());
        }
    };
    let sidecar_dir = sidecar_path
        .parent()
        .ok_or("sidecar executable has no parent directory")?
        .to_path_buf();

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut child = match Command::new(&sidecar_path)
            .current_dir(&sidecar_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(e) => {
                eprintln!("[sidecar:error] failed to spawn {:?}: {}", sidecar_path, e);
                let _ = app_handle.emit("sidecar-error", e.to_string());
                return;
            }
        };

        if let Some(stdout) = child.stdout.take() {
            let app_handle = app_handle.clone();
            thread::spawn(move || {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    println!("[sidecar] {}", line);
                    if line.contains("READY") {
                        let _ = app_handle.emit("sidecar-ready", ());
                    }
                }
            });
        }

        if let Some(stderr) = child.stderr.take() {
            let app_handle = app_handle.clone();
            thread::spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    eprintln!("[sidecar:err] {}", line);
                    let _ = app_handle.emit("sidecar-log", line);
                }
            });
        }

        let status = child.wait();
        eprintln!("[sidecar] terminated: {:?}", status);
        let _ = app_handle.emit("sidecar-terminated", ());
    });

    Ok(())
}

#[cfg(not(debug_assertions))]
fn resolve_sidecar_path(app: &AppHandle) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let exe_name = "transcribe-service.exe";
    let runtime_path = app
        .path()
        .app_data_dir()?
        .join("runtime")
        .join("transcribe-service")
        .join(exe_name);
    if runtime_path.exists() {
        return Ok(runtime_path);
    }

    if let Some(appdata) = std::env::var_os("APPDATA") {
        let named_runtime_path = PathBuf::from(appdata)
            .join("Mekey Lightning")
            .join("runtime")
            .join("transcribe-service")
            .join(exe_name);
        if named_runtime_path.exists() {
            return Ok(named_runtime_path);
        }
    }

    let exe_dir = std::env::current_exe()?
        .parent()
        .ok_or("current executable has no parent directory")?
        .to_path_buf();
    let portable_dir_path = exe_dir.join("transcribe-service").join(exe_name);
    if portable_dir_path.exists() {
        return Ok(portable_dir_path);
    }

    let portable_file_path = exe_dir.join(exe_name);
    if portable_file_path.exists() {
        return Ok(portable_file_path);
    }

    Err(format!(
        "sidecar not found at {:?}, {:?}, or {:?}",
        runtime_path, portable_dir_path, portable_file_path
    )
    .into())
}
