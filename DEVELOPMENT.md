# 开发指南

## 推荐的开发节奏

### Phase 0：环境准备（30 分钟）

1. **安装 Rust**
   ```powershell
   winget install Rustlang.Rustup
   # 重启终端后验证
   rustc --version
   ```

2. **安装 Microsoft C++ Build Tools**
   - 下载：https://visualstudio.microsoft.com/visual-cpp-build-tools/
   - 选择"使用 C++ 的桌面开发"工作负载

3. **安装 WebView2 Runtime**（Win11 已自带，Win10 可能需要手动装）
   - https://developer.microsoft.com/microsoft-edge/webview2

4. **验证 Node 和 Python**
   ```powershell
   node --version  # 需要 20+
   python --version  # 需要 3.10 或 3.11
   ```

5. **验证 CUDA**
   ```powershell
   nvidia-smi  # 应该显示 4080 和 CUDA 版本
   ```

### Phase 1：先验证 FunASR（最重要！1 小时）

不要先碰 Tauri，先确认 FunASR 在你的硬件上能跑：

```powershell
cd python-sidecar
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 装 PyTorch GPU 版（关键）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# 装其他依赖
pip install funasr modelscope sounddevice numpy

# 跑验证脚本
python test_streaming.py
```

**预期效果**：你说话，终端实时打印中文文字，延迟约 600ms。

如果这一步成功了，整个项目最大的不确定性就消除了。如果失败了，先解决这一步再继续。

### Phase 2：完整 Python 服务（30 分钟）

```powershell
# 装剩余依赖
pip install -r requirements.txt

# 配置 API Key
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY

# 启动完整服务
python src/transcribe_service.py
```

会看到：
```
🎤 Audio stream started @ 16000Hz
🚀 WebSocket server listening on ws://127.0.0.1:9527
READY
```

可以用浏览器或 wscat 测试 WebSocket：
```powershell
npx wscat -c ws://127.0.0.1:9527
> {"action":"start"}
# 说话
> {"action":"stop"}
```

### Phase 3：Tauri 应用（1-2 小时）

```powershell
cd ..  # 回到项目根目录
npm install

# 生成图标（需要一个 1024x1024 PNG 源图）
# 没有的话先从 https://github.com/tauri-apps/tauri/raw/dev/.github/icon.png 下一个测试
npx @tauri-apps/cli icon path/to/source.png

# 启动开发模式（会同时启动 sidecar 和前端）
npm run tauri dev
```

**注意**：开发模式下 Tauri 会尝试启动 sidecar，但 sidecar 可执行文件还没打包，所以你需要手动启动 Python 服务（Phase 2 的方式），或者先打包 sidecar。

#### 简化开发流程（推荐）

修改 `src-tauri/src/sidecar.rs`，在开发模式下跳过启动 sidecar：

```rust
pub fn spawn_sidecar(app: AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(debug_assertions)]
    {
        println!("[dev] Skip sidecar spawn, run python manually");
        let _ = app.emit("sidecar-ready", ());
        return Ok(());
    }
    // ... 原有代码
}
```

这样开发时只需要：
- 终端 1：`python python-sidecar/src/transcribe_service.py`
- 终端 2：`npm run tauri dev`

### Phase 4：打包发布（30 分钟）

```powershell
# 1. 打包 Python sidecar
cd python-sidecar
.\.venv\Scripts\Activate.ps1
.\build.ps1

# 输出：src-tauri/binaries/transcribe-service-x86_64-pc-windows-msvc.exe

# 2. 打包 Tauri 应用
cd ..
npm run tauri build

# 输出：src-tauri/target/release/bundle/msi/RealtimeTranscribe_0.1.0_x64_zh-CN.msi
```

**打包注意事项**：

PyInstaller 打包 PyTorch 后的 exe 会很大（~2-3GB），原因是 PyTorch GPU 版本包含了所有 CUDA 库。这是正常的。

如果想瘦身，可以考虑：
1. 使用 `--onedir` 而不是 `--onefile`（启动更快）
2. 排除不需要的 PyTorch 模块
3. 只在打包发布时考虑，开发期间不用关心

## 常见问题

### Q: WebSocket 连接失败
- 检查 Python sidecar 是否真的启动了（终端有没有 "READY"）
- 检查 9527 端口是否被占用：`netstat -ano | findstr 9527`
- 防火墙可能拦截，允许应用通过

### Q: 转录无内容
- 检查麦克风权限：Windows 设置 → 隐私 → 麦克风
- 检查默认录音设备：Windows 声音设置
- 用 Windows 自带录音机测试麦克风是否正常

### Q: GPU 没用上
```python
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 应该输出: True NVIDIA GeForce RTX 4080
```
如果是 False，说明装的是 CPU 版 PyTorch，重新装 GPU 版。

### Q: 显存爆了
- FunASR 大模型 + cache 累积可能在长时录音时增长
- 已在代码里加了定期 reset_cache，每次离线校正后清空
- 如果还是爆显存，可以减少 OFFLINE_REFRESH_CHUNKS（更频繁清理）

### Q: Tauri 快捷键无效
- 检查 capabilities/default.json 里的 global-shortcut 权限
- Windows 上有些组合可能被系统占用，换组合试试

### Q: Obsidian 导出找不到目录
- 路径用绝对路径，例如 `D:\Notes\MyVault\Transcripts`
- 目录必须事先存在
- 检查写入权限

## 调试技巧

### 查看 sidecar 日志
日志会写入 `%APPDATA%\Mekey Lightning\data\sidecar.log`，包含 DEBUG 级别信息。

### 前端 DevTools
开发模式下 Tauri 窗口右键 → "检查"，可以看 Console 和 Network。

### Rust 端日志
`println!` 会输出到运行 `npm run tauri dev` 的终端。

### WebSocket 消息调试
前端代码已加了 `console.log`，DevTools 里可以看到所有消息。

## 性能优化思路

如果你想进一步优化（项目跑通后再考虑）：

1. **降低延迟**：把 `chunk_size` 从 `[0,10,5]` 改成 `[0,8,4]`（480ms）
2. **减少抖动**：流式模型每次输出做差分，只显示新增部分
3. **热词优化**：在 ASREngine 里加 `hotword="HarmonyOS Transformer"` 参数
4. **批量润色**：累积更多文本再调 Claude，减少 API 调用
5. **前端虚拟滚动**：1 小时录音可能积累几百段，用 react-window 做虚拟列表
