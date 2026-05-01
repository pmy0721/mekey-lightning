# PowerShell script to build Python sidecar as a directory bundle.
# Run from the python-sidecar/ directory.

$ErrorActionPreference = "Stop"

# Ensure the virtual environment is active.
if (-not $env:VIRTUAL_ENV) {
    Write-Error "Please activate venv first: .\.venv\Scripts\Activate.ps1"
}

# Get the target triple required by Tauri sidecar naming.
$rustcOutput = rustc -Vv
$targetTriple = ($rustcOutput | Where-Object { $_ -like "host:*" } | Select-Object -First 1) -replace "^host:\s*", ""
if (-not $targetTriple) {
    Write-Error "Unable to determine Rust target triple from rustc -Vv"
}
$targetTriple = $targetTriple.Trim()
Write-Host "Target triple: $targetTriple" -ForegroundColor Cyan

# Clean old build output.
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# Build the Python sidecar as a directory instead of one huge executable.
pyinstaller `
    --name "transcribe-service" `
    --onedir `
    --noconsole `
    --collect-all funasr `
    --collect-all modelscope `
    --collect-all torch `
    --collect-all torchaudio `
    --collect-data sounddevice `
    --hidden-import=aiosqlite `
    --hidden-import=anthropic `
    --hidden-import=websockets.server `
    src/transcribe_service.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed"
}

# Copy the directory into Tauri resources.
$src = "dist/transcribe-service"
$dst = "../src-tauri/resources/transcribe-service"

Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "../src-tauri/resources" | Out-Null
Copy-Item -Path $src -Destination $dst -Recurse -Force

Write-Host ""
Write-Host "Sidecar built: $dst" -ForegroundColor Green
$sizeBytes = (Get-ChildItem $dst -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host "  Size: $([math]::Round($sizeBytes / 1MB, 1)) MB" -ForegroundColor Gray
