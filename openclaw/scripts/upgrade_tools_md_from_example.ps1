# Upgrade data/openclaw/workspace/TOOLS.md from openclaw/workspace/TOOLS.md.example when missing or stale
# (short stub without MCP contract markers). Idempotent if already current.
# Set OPENCLAW_SKIP_TOOLS_MD_UPGRADE=1 to skip.
param([string]$Base = $null)

$ErrorActionPreference = "Stop"
if ($env:OPENCLAW_SKIP_TOOLS_MD_UPGRADE -eq "1") { return }

if (-not $Base) {
    $Base = if ($env:BASE_PATH) { $env:BASE_PATH } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
}
$data = if ($env:DATA_PATH) { $env:DATA_PATH } else { Join-Path $Base "data" }
$workspace = Join-Path $data "openclaw\workspace"
$example = Join-Path $Base "openclaw\workspace\TOOLS.md.example"
$dest = Join-Path $workspace "TOOLS.md"

if (-not (Test-Path $example)) { return }

New-Item -ItemType Directory -Force -Path $workspace | Out-Null

$need = $false
if (-not (Test-Path $dest)) {
    $need = $true
} else {
    $raw = Get-Content $dest -Raw -ErrorAction SilentlyContinue
    if ($raw -notmatch 'gateway__tavily_search') {
        $need = $true
    }
}
if ($need) {
    Copy-Item -LiteralPath $example -Destination $dest -Force
    Write-Host "Upgraded TOOLS.md from TOOLS.md.example (missing or stale stub)."
}
