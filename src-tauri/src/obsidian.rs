use chrono::Local;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

const VAULT_CONFIG_FILE: &str = "obsidian_vault.txt";

#[derive(Serialize, Deserialize)]
pub struct ExportPayload {
    pub title: String,
    pub content: String,
    pub tags: Vec<String>,
    pub session_id: String,
    pub duration_seconds: f64,
}

fn get_config_dir(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map_err(|e| format!("Failed to get config dir: {}", e))
}

#[tauri::command]
pub async fn set_obsidian_vault_path(app: AppHandle, path: String) -> Result<(), String> {
    let config_dir = get_config_dir(&app)?;
    fs::create_dir_all(&config_dir).map_err(|e| e.to_string())?;
    fs::write(config_dir.join(VAULT_CONFIG_FILE), path).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn get_obsidian_vault_path(app: AppHandle) -> Result<Option<String>, String> {
    let config_dir = get_config_dir(&app)?;
    let path = config_dir.join(VAULT_CONFIG_FILE);
    if !path.exists() {
        return Ok(None);
    }
    let content = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    Ok(Some(content.trim().to_string()))
}

#[tauri::command]
pub async fn export_to_obsidian(
    app: AppHandle,
    payload: ExportPayload,
) -> Result<String, String> {
    let vault_path = get_obsidian_vault_path(app.clone()).await?;
    let vault_path = vault_path.ok_or_else(|| {
        "尚未配置 Obsidian Vault 路径，请在设置中配置".to_string()
    })?;

    let vault = PathBuf::from(&vault_path);
    if !vault.exists() {
        return Err(format!("Vault 路径不存在: {}", vault_path));
    }

    // 生成文件名：YYYY-MM-DD-HHmm-标题.md
    let now = Local::now();
    let date_prefix = now.format("%Y-%m-%d-%H%M").to_string();
    let safe_title = sanitize_filename(&payload.title);
    let filename = format!("{}-{}.md", date_prefix, safe_title);
    let file_path = vault.join(&filename);

    // 构建 frontmatter
    let tags_str = if payload.tags.is_empty() {
        String::new()
    } else {
        payload
            .tags
            .iter()
            .map(|t| format!("  - {}", t))
            .collect::<Vec<_>>()
            .join("\n")
    };

    let duration_min = (payload.duration_seconds / 60.0).round() as i64;

    let frontmatter = format!(
        r#"---
title: "{}"
created: {}
duration_minutes: {}
session_id: {}
source: RealtimeTranscribe
tags:
  - 转录
  - 口述
{}
---

"#,
        payload.title,
        now.format("%Y-%m-%d %H:%M:%S"),
        duration_min,
        payload.session_id,
        tags_str,
    );

    let final_content = format!("{}{}", frontmatter, payload.content);

    fs::write(&file_path, final_content).map_err(|e| format!("写入失败: {}", e))?;

    Ok(file_path.to_string_lossy().to_string())
}

fn sanitize_filename(name: &str) -> String {
    let invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|'];
    let trimmed: String = name
        .chars()
        .map(|c| if invalid_chars.contains(&c) { '-' } else { c })
        .collect();
    let trimmed = trimmed.trim().to_string();
    if trimmed.is_empty() {
        "未命名".to_string()
    } else if trimmed.chars().count() > 60 {
        trimmed.chars().take(60).collect()
    } else {
        trimmed
    }
}
