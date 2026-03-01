# Run OpenClaw CLI via Docker with gateway URL and token so it reaches openclaw-gateway.
# Usage: from repo root, .\openclaw\scripts\run-cli.ps1 devices list
#        .\openclaw\scripts\run-cli.ps1 devices approve DEVICE_ID
# With gateway.mode=local the CLI uses local discovery (wrong in Docker); --url forces the target.
param([Parameter(ValueFromRemainingArguments = $true)] $CliArgs)
$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$envPath = Join-Path $base "openclaw\.env"
if (-not (Test-Path $envPath)) {
    Write-Error "openclaw\.env not found at $envPath. Create it from openclaw\.env.example and set OPENCLAW_GATEWAY_TOKEN."
}
$line = Get-Content $envPath -Raw | Select-String -Pattern 'OPENCLAW_GATEWAY_TOKEN=(.+)' -AllMatches
if (-not $line -or -not $line.Matches.Groups[1].Value) {
    Write-Error "OPENCLAW_GATEWAY_TOKEN not found in openclaw\.env"
}
$token = $line.Matches.Groups[1].Value.Trim()
$gatewayUrl = "ws://openclaw-gateway:18789"
$dockerArgs = @("compose", "--profile", "openclaw-cli", "run", "--rm", "openclaw-cli") + @($CliArgs) + @("--url", $gatewayUrl, "--token", $token)
Push-Location $base
try {
    & docker @dockerArgs
} finally {
    Pop-Location
}
