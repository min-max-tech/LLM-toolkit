# Copies workspace templates (SOUL.md, AGENTS.md, TOOLS.md) to data/openclaw/workspace
# if they don't already exist. Run after ensure_dirs.ps1.
$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$data = if ($env:DATA_PATH) { $env:DATA_PATH -replace '\\', '/' } else { Join-Path $base "data" }
$workspace = Join-Path $data "openclaw\workspace"
$templates = Join-Path $base "openclaw\workspace"

$files = @("SOUL.md", "AGENTS.md", "TOOLS.md")
foreach ($f in $files) {
    $src = Join-Path $templates $f
    $dst = Join-Path $workspace $f
    if (Test-Path $src) {
        if (-not (Test-Path $dst)) {
            Copy-Item $src $dst -Force
            Write-Host "Copied $f to workspace"
        }
    }
}
Write-Host "OpenClaw workspace ready."
