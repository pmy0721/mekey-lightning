# One-click runtime installer for Mekey Lightning.
# Put this script next to:
#   - Mekey-Lightning-Runtime-<version>.tar.gz.part001
#   - Mekey-Lightning-Runtime-<version>.tar.gz.part002
#   - checksums-runtime-<version>.txt
# Then run it from PowerShell.

param(
    [string]$Version = "0.1.1",
    [string]$InstallRoot = (Join-Path $env:APPDATA "Mekey Lightning\runtime"),
    [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "Required command not found: $Name"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $WorkDir) {
    $WorkDir = Join-Path $scriptDir ".runtime-install-temp"
}
$archiveName = "Mekey-Lightning-Runtime-$Version.tar.gz"
$archivePath = Join-Path $scriptDir $archiveName
$checksumPath = Join-Path $scriptDir "checksums-runtime-$Version.txt"
$partPattern = "$archiveName.part*"
$parts = @(Get-ChildItem -Path $scriptDir -Filter $partPattern -File | Sort-Object Name)

Assert-Command "tar"

if ($parts.Count -eq 0) {
    Write-Error "No runtime parts found next to this script. Expected files like: $partPattern"
}

Write-Step "Found runtime parts"
$parts | Select-Object Name, @{n="SizeMB";e={[math]::Round($_.Length / 1MB, 1)}} | Format-Table -AutoSize

if (Test-Path $checksumPath) {
    Write-Step "Verifying SHA256 checksums"
    $expected = @{}
    Get-Content $checksumPath | ForEach-Object {
        if ($_ -match "^\s*([A-Fa-f0-9]{64})\s+(.+?)\s*$") {
            $expected[$matches[2]] = $matches[1].ToUpperInvariant()
        }
    }

    foreach ($part in $parts) {
        if (-not $expected.ContainsKey($part.Name)) {
            Write-Error "Missing checksum for $($part.Name)"
        }
        $actual = (Get-FileHash -Algorithm SHA256 $part.FullName).Hash.ToUpperInvariant()
        if ($actual -ne $expected[$part.Name]) {
            Write-Error "Checksum mismatch for $($part.Name)"
        }
        Write-Host "OK  $($part.Name)"
    }
} else {
    Write-Warning "Checksum file not found: $checksumPath"
    Write-Warning "Continuing without checksum verification."
}

$tempRoot = Join-Path $WorkDir ("Mekey-Lightning-Runtime-" + [guid]::NewGuid().ToString("N"))
$extractDir = Join-Path $tempRoot "extract"
New-Item -ItemType Directory -Force -Path $tempRoot, $extractDir | Out-Null

try {
    Write-Step "Combining runtime parts"
    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue
    $output = [System.IO.File]::Create($archivePath)
    try {
        $buffer = New-Object byte[] (4MB)
        foreach ($part in $parts) {
            Write-Host "Adding $($part.Name)"
            $input = [System.IO.File]::OpenRead($part.FullName)
            try {
                while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $read)
                }
            } finally {
                $input.Dispose()
            }
        }
    } finally {
        $output.Dispose()
    }

    Write-Step "Extracting runtime archive"
    tar -xzf $archivePath -C $extractDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "tar extraction failed"
    }

    $runtimeSource = Join-Path $extractDir "transcribe-service"
    if (-not (Test-Path (Join-Path $runtimeSource "transcribe-service.exe"))) {
        Write-Error "Extracted runtime is missing transcribe-service.exe"
    }

    Write-Step "Installing runtime"
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $targetRuntime = Join-Path $InstallRoot "transcribe-service"
    Remove-Item -Recurse -Force $targetRuntime -ErrorAction SilentlyContinue
    Copy-Item -Path $runtimeSource -Destination $targetRuntime -Recurse -Force

    Write-Step "Verifying installation"
    $installedExe = Join-Path $targetRuntime "transcribe-service.exe"
    if (-not (Test-Path $installedExe)) {
        Write-Error "Runtime installation failed: $installedExe not found"
    }

    Write-Host ""
    Write-Host "Mekey Lightning runtime installed successfully." -ForegroundColor Green
    Write-Host "Path: $targetRuntime"
} finally {
    Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue
}
