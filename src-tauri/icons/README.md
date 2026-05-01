# 应用图标

Tauri 需要以下图标文件放在 `src-tauri/icons/` 目录：

- `32x32.png`
- `128x128.png`
- `128x128@2x.png` (256x256)
- `icon.ico` (Windows)
- `icon.icns` (macOS, 可选)

## 自动生成

把一个 1024x1024 的 PNG 源图（推荐有透明背景）放到任意位置，运行：

```powershell
cd src-tauri
npx @tauri-apps/cli icon path/to/your/source.png
```

会自动生成所有需要的尺寸到 `src-tauri/icons/`。

## 或者手动创建占位图标

如果只是开发测试，可以从任意 emoji 截图或在线工具生成一个 1024x1024 PNG，
放在 `src-tauri/icons/source.png`，然后运行上面的命令。
