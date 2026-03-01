# Creates data directories for bind mounts. Run before first docker compose up.
$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Get-Location).Path }
$data = if ($env:DATA_PATH) { $env:DATA_PATH -replace '\\', '/' } else { Join-Path $base "data" }
$dirs = @(
    (Join-Path $data "ollama"),
    (Join-Path $data "mcp"),
    (Join-Path $data "ops-controller"),
    (Join-Path $data "open-webui"),
    (Join-Path $data "comfyui-storage"),
    (Join-Path $data "comfyui-output"),
    (Join-Path $data "n8n-data"),
    (Join-Path $data "n8n-files"),
    (Join-Path $data "openclaw"),
    (Join-Path $data "openclaw\workspace"),
    (Join-Path $base "models\comfyui\checkpoints"),
    (Join-Path $base "models\comfyui\loras"),
    (Join-Path $base "models\comfyui\latent_upscale_models"),
    (Join-Path $base "models\comfyui\text_encoders")
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Write-Host "OK $d"
}

# Bootstrap openclaw.json with Ollama provider if config doesn't exist
$openclawConfig = Join-Path $data "openclaw\openclaw.json"
$openclawConfigExample = Join-Path $base "openclaw\openclaw.json.example"
if (-not (Test-Path $openclawConfig) -and (Test-Path $openclawConfigExample)) {
    Copy-Item $openclawConfigExample $openclawConfig -Force
    Write-Host "OK openclaw config (Ollama provider)"
}

# Ensure root .env has OPENCLAW_GATEWAY_TOKEN (required for OpenClaw service)
$rootEnv = Join-Path $base ".env"
$rootExample = Join-Path $base ".env.example"
$needsCreate = -not (Test-Path $rootEnv)
$needsToken = $false
if ((Test-Path $rootEnv)) {
    $existing = Get-Content $rootEnv -Raw -ErrorAction SilentlyContinue
    $needsToken = $existing -and ($existing -match 'OPENCLAW_GATEWAY_TOKEN=change-me|OPENCLAW_GATEWAY_TOKEN=\s*$' -or -not ($existing -match 'OPENCLAW_GATEWAY_TOKEN=.+'))
}
if ($needsCreate -or $needsToken) {
    $token = -join ((1..32 | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }))
    if ($needsCreate -and (Test-Path $rootExample)) {
        Copy-Item $rootExample $rootEnv -Force
    }
    if (Test-Path $rootEnv) {
        $content = Get-Content $rootEnv -Raw
        if ($content -match 'OPENCLAW_GATEWAY_TOKEN=') {
            $content = $content -replace 'OPENCLAW_GATEWAY_TOKEN=[^\r\n]*', "OPENCLAW_GATEWAY_TOKEN=$token"
        } else {
            $content = $content.TrimEnd() + "`n# OpenClaw gateway auth (pinned; do not change unless re-pairing all devices)`nOPENCLAW_GATEWAY_TOKEN=$token`n"
        }
        Set-Content -Path $rootEnv -Value $content -NoNewline
    } else {
        Set-Content -Path $rootEnv -Value @"
BASE_PATH=$($base -replace '\\', '/')
OPENCLAW_GATEWAY_TOKEN=$token
"@
    }
    Write-Host "OK .env ($(if ($needsCreate) { 'created' } else { 'OPENCLAW_GATEWAY_TOKEN set' }))"
}

# Auto-detect GPU and generate docker-compose.compute.yml
$detectScript = Join-Path $base "scripts\detect_hardware.py"
if (Test-Path $detectScript) {
    $env:BASE_PATH = $base -replace '\\', '/'
    python $detectScript 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "OK Hardware detected (docker-compose.compute.yml)" }
}

Write-Host "Directories ready."
