# Add an MCP server to the gateway. Run from repo root.
# Usage: .\scripts\mcp_add.ps1 <server-name>
# Example: .\scripts\mcp_add.ps1 fetch
# Config is stored in data/mcp/servers.txt; gateway reloads in ~10s (no container restart).
param([Parameter(Mandatory=$true)][string]$Server)

$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Get-Location).Path }
$data = if ($env:DATA_PATH) { $env:DATA_PATH -replace '\\', '/' } else { Join-Path $base "data" }
$configFile = Join-Path $data "mcp\servers.txt"

$configDir = Split-Path $configFile
if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Force -Path $configDir | Out-Null }
if (-not (Test-Path $configFile)) { Set-Content -Path $configFile -Value "duckduckgo" -NoNewline }

$current = Get-Content $configFile -Raw -ErrorAction SilentlyContinue
$servers = $current -split '[,\r\n]' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique

if ($servers -contains $Server) {
    Write-Host "Server '$Server' is already enabled."
    exit 0
}

$servers = @($servers) + $Server
$newValue = $servers -join ','
Set-Content -Path $configFile -Value $newValue -NoNewline

Write-Host "Added $Server. Gateway will reload in ~10s (no container restart)."
Write-Host "$Server is available at http://localhost:8811/mcp"
