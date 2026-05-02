# Mekey Lightning

Mekey Lightning is a Windows desktop app for realtime Chinese speech transcription.
It uses Tauri 2 + React for the desktop UI and a Python runtime sidecar for
FunASR-based speech recognition.

## Status

This project is currently in alpha. The app installer and the speech runtime are
distributed separately so GitHub Releases can host the large runtime files.

## Install From Release

Download these files from the latest GitHub Release:

- `Mekey-Lightning-Setup-0.1.1-x64.exe`
- `Install-Mekey-Lightning-Runtime.ps1`
- all files matching `Mekey-Lightning-Runtime-0.1.1.tar.gz.part*`
- `checksums-runtime-0.1.1.txt`

Install the app first, then put the runtime files in the same folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-Mekey-Lightning-Runtime.ps1
```

The runtime installer verifies SHA256 checksums, combines the runtime parts,
extracts them, and installs the sidecar runtime to:

```text
%APPDATA%\Mekey Lightning\runtime\transcribe-service
```

## Development

Install frontend dependencies:

```powershell
npm install
```

Install Python dependencies:

```powershell
cd python-sidecar
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

Run in development mode:

```powershell
npm run tauri dev
```

Build the Python runtime:

```powershell
cd python-sidecar
.\.venv\Scripts\Activate.ps1
.\build.ps1
```

Build the app installer:

```powershell
npm run tauri build
```

Package runtime release assets:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-runtime.ps1 -Version 0.1.1
```

## Requirements

- Windows 10/11 x64
- NVIDIA GPU recommended
- CUDA-compatible PyTorch runtime
- Microphone permission enabled

## License

No license has been selected yet.
