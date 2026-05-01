# Package the directory-style Python runtime for GitHub Releases.
# The output is split into parts smaller than GitHub's per-asset limit.

param(
    [string]$Version = "0.1.0",
    [int]$PartSizeMB = 500
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeSource = Join-Path $repoRoot "src-tauri\resources\transcribe-service"
$releaseDir = Join-Path $repoRoot "release"
$stagingDir = Join-Path $releaseDir "runtime-package-files"
$archiveBase = Join-Path $releaseDir "Mekey-Lightning-Runtime-$Version.tar.gz"
$manifest = Join-Path $releaseDir "checksums-runtime-$Version.txt"
$installerSource = Join-Path $PSScriptRoot "Install-Mekey-Lightning-Runtime.ps1"
$installerOutput = Join-Path $releaseDir "Install-Mekey-Lightning-Runtime.ps1"

if (-not (Test-Path $runtimeSource)) {
    Write-Error "Runtime source not found: $runtimeSource. Run python-sidecar\build.ps1 first."
}

Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null

$installScript = Join-Path $stagingDir "Install-Runtime.ps1"
@'
$ErrorActionPreference = "Stop"
$target = Join-Path $env:APPDATA "Mekey Lightning\runtime"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path "$PSScriptRoot\transcribe-service" -Destination $target -Recurse -Force
Write-Host "Mekey Lightning runtime installed to: $target" -ForegroundColor Green
'@ | Set-Content -Encoding ASCII $installScript

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Remove-Item -Force $archiveBase, "$archiveBase.part*" -ErrorAction SilentlyContinue
Copy-Item -Path $installerSource -Destination $installerOutput -Force

$partSize = [int64]$PartSizeMB * 1MB
$buffer = New-Object byte[] (4MB)
$tarArgs = @(
    "-czf",
    "-",
    "-C",
    (Split-Path $runtimeSource -Parent),
    "transcribe-service",
    "-C",
    $stagingDir,
    "Install-Runtime.ps1"
)

$process = New-Object System.Diagnostics.Process
$process.StartInfo.FileName = "tar"
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.Arguments = ($tarArgs | ForEach-Object {
    if ($_ -match '[\s"]') {
        '"' + ($_ -replace '"', '\"') + '"'
    } else {
        $_
    }
}) -join " "

[void]$process.Start()

$part = 1
$outputStream = $null
$written = [int64]0
try {
    $inputStream = $process.StandardOutput.BaseStream
    try {
        while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $offset = 0
            while ($offset -lt $read) {
                if ($null -eq $outputStream) {
                    $partPath = "{0}.part{1:D3}" -f $archiveBase, $part
                    $outputStream = [System.IO.File]::Create($partPath)
                    $written = 0
                    $part++
                }
                $remainingInPart = $partSize - $written
                $toWrite = [Math]::Min($read - $offset, $remainingInPart)
                $outputStream.Write($buffer, $offset, [int]$toWrite)
                $written += $toWrite
                $offset += $toWrite
                if ($written -ge $partSize) {
                    $outputStream.Dispose()
                    $outputStream = $null
                }
            }
        }
    } finally {
        if ($null -ne $outputStream) {
            $outputStream.Dispose()
        }
    }
} finally {
    $process.WaitForExit()
}

$tarError = $process.StandardError.ReadToEnd()
if ($process.ExitCode -ne 0) {
    Write-Error "tar failed with exit code $($process.ExitCode): $tarError"
}

Remove-Item -Force $manifest -ErrorAction SilentlyContinue
Get-ChildItem $releaseDir -File |
    Where-Object { $_.Name -like "Mekey-Lightning-Runtime-$Version.tar.gz*" } |
    Sort-Object Name |
    ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 $_.FullName
        "{0}  {1}" -f $hash.Hash, $_.Name
    } | Set-Content -Encoding ASCII $manifest

Write-Host "Runtime package output:" -ForegroundColor Green
Get-ChildItem $releaseDir -File |
    Where-Object { $_.Name -like "Mekey-Lightning-Runtime-$Version.tar.gz*" -or $_.Name -eq "checksums-runtime-$Version.txt" -or $_.Name -eq "Install-Mekey-Lightning-Runtime.ps1" } |
    Select-Object Name, Length |
    Format-Table -AutoSize
