# Remove an MCP server from the gateway. Run from repo root.
# Usage: .\scripts\mcp_remove.ps1 <server-name>
# Config is stored in data/mcp/servers.txt; gateway reloads in ~10s (no container restart).
param([Parameter(Mandatory=$true)][string]$Server)

$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Get-Location).Path }
$data = if ($env:DATA_PATH) { $env:DATA_PATH -replace '\\', '/' } else { Join-Path $base "data" }
$configFile = Join-Path $data "mcp\servers.txt"

if (-not (Test-Path $configFile)) {
    Write-Host "No MCP config found at $configFile" -ForegroundColor Red
    exit 1
}

$current = Get-Content $configFile -Raw -ErrorAction SilentlyContinue
$servers = $current -split '[,\r\n]' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -ne $Server } | Select-Object -Unique

$newValue = ($servers -join ',').Trim()
if (-not $newValue) { $newValue = "duckduckgo" }

Set-Content -Path $configFile -Value $newValue -NoNewline

Write-Host "Removed $Server. Gateway will reload in ~10s (no container restart)."
