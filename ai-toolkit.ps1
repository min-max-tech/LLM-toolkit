# ai-toolkit -- project management CLI
# Usage: .\ai-toolkit.ps1 <command>
#
# Commands:
#   initialize   Bootstrap directories, generate tokens, detect hardware, start services
#   help         Show this help

param([string]$Command = "help")

$ErrorActionPreference = "Stop"
$base = if ($env:BASE_PATH) { $env:BASE_PATH -replace '\\', '/' } else { (Get-Location).Path -replace '\\', '/' }
$data = if ($env:DATA_PATH) { $env:DATA_PATH -replace '\\', '/' } else { "$base/data" }

function ok($msg)      { Write-Host "  [ok] $msg" -ForegroundColor Green }
function info($msg)    { Write-Host "  [--] $msg" -ForegroundColor Cyan }
function warn($msg)    { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function err($msg)     { Write-Host "  [xx] $msg" -ForegroundColor Red }
function section($n, $t) { Write-Host "`n=== $n $t" -ForegroundColor White }

function Invoke-Initialize {
    Write-Host ""
    Write-Host "   ___    ___   _____           _ _    _ _   " -ForegroundColor Yellow
    Write-Host "  / _ \  |_ _| |_   _|__   ___ | | | _(_) |_ " -ForegroundColor Yellow
    Write-Host " / /_\ \  | |    | |/ _ \ / _ \| | |/ / | __|" -ForegroundColor Yellow
    Write-Host "/  _  /  | |    | | (_) | (_) | |   <| | |_ " -ForegroundColor Yellow
    Write-Host "\_| |_/ |___|   |_|\___/ \___/|_|_|\_\_|\__|" -ForegroundColor Yellow
    Write-Host "base=$base  data=$data" -ForegroundColor DarkGray

    # 1. Directories
    section "1/4" "Creating directories"
    $dirs = @(
        "$base/models/ollama",
        "$data/mcp",
        "$data/ops-controller",
        "$data/open-webui",
        "$data/comfyui-storage",
        "$data/comfyui-output",
        "$data/n8n-data",
        "$data/n8n-files",
        "$data/dashboard",
        "$data/qdrant",
        "$data/openclaw",
        "$data/openclaw/workspace",
        "$base/models/comfyui/checkpoints",
        "$base/models/comfyui/loras",
        "$base/models/comfyui/latent_upscale_models",
        "$base/models/comfyui/text_encoders",
        "$base/models/comfyui/unet",
        "$base/models/comfyui/vae"
    )
    foreach ($d in $dirs) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        ok ($d -replace [regex]::Escape($base + "/"), "")
    }

    # 2. Config files
    section "2/4" "Bootstrapping config"

    $mcpServers  = "$data/mcp/servers.txt"
    $mcpRegistry = "$data/mcp/registry-custom.yaml"

    if (-not (Test-Path $mcpServers)) {
        Set-Content -Path $mcpServers -Value "n8n,playwright,comfyui" -NoNewline
        ok "data/mcp/servers.txt  ->  n8n, playwright, comfyui"
    } else {
        info "data/mcp/servers.txt  (exists: $(Get-Content $mcpServers))"
    }

    $registryTemplate = "$base/mcp/registry-custom.yaml"
    if (-not (Test-Path $mcpRegistry) -and (Test-Path $registryTemplate)) {
        Copy-Item $registryTemplate $mcpRegistry -Force
        ok "data/mcp/registry-custom.yaml  (copied)"
    } elseif (Test-Path $mcpRegistry) {
        info "data/mcp/registry-custom.yaml  (exists)"
    }

    $openclawConfig  = "$data/openclaw/openclaw.json"
    $openclawExample = "$base/openclaw/openclaw.json.example"
    if (-not (Test-Path $openclawConfig) -and (Test-Path $openclawExample)) {
        Copy-Item $openclawExample $openclawConfig -Force
        ok "data/openclaw/openclaw.json  (initialized from example)"
    } elseif (Test-Path $openclawConfig) {
        info "data/openclaw/openclaw.json  (exists)"
    }

    # Auth token
    $rootEnv     = "$base/.env"
    $rootExample = "$base/.env.example"
    $needsCreate = -not (Test-Path $rootEnv)
    $needsToken  = $false
    if (Test-Path $rootEnv) {
        $existing = Get-Content $rootEnv -Raw -ErrorAction SilentlyContinue
        $needsToken = $existing -and (
            $existing -match 'OPENCLAW_GATEWAY_TOKEN=change-me|OPENCLAW_GATEWAY_TOKEN=\s*$' -or
            -not ($existing -match 'OPENCLAW_GATEWAY_TOKEN=.+')
        )
    }
    if ($needsCreate -or $needsToken) {
        $token = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })
        if ($needsCreate -and (Test-Path $rootExample)) {
            Copy-Item $rootExample $rootEnv -Force
        }
        if (Test-Path $rootEnv) {
            $content = Get-Content $rootEnv -Raw
            if ($content -match 'OPENCLAW_GATEWAY_TOKEN=') {
                $content = $content -replace 'OPENCLAW_GATEWAY_TOKEN=[^\r\n]*', "OPENCLAW_GATEWAY_TOKEN=$token"
            } else {
                $content = $content.TrimEnd() + "`n`n# OpenClaw gateway auth`nOPENCLAW_GATEWAY_TOKEN=$token`n"
            }
            Set-Content -Path $rootEnv -Value $content -NoNewline
        } else {
            Set-Content -Path $rootEnv -Value "BASE_PATH=$base`nOPENCLAW_GATEWAY_TOKEN=$token"
        }
        ok ".env  ->  OPENCLAW_GATEWAY_TOKEN=$($token.Substring(0,8))..."
    } else {
        $match = Select-String '^OPENCLAW_GATEWAY_TOKEN=(.+)' $rootEnv
        $token = if ($match) { $match.Matches[0].Groups[1].Value } else { "" }
        info ".env  (exists, token=$($token.Substring(0,[Math]::Min(8,$token.Length)))...)"
    }

    # 3. Hardware detection
    section "3/4" "Detecting hardware"
    $detectScript = "$base/scripts/detect_hardware.py"
    if (Test-Path $detectScript) {
        $env:BASE_PATH = $base
        python $detectScript 2>$null
        if ($LASTEXITCODE -eq 0) {
            $computeYml = "$base/overrides/compute.yml"
            $mode = if (Test-Path $computeYml) {
                $m = Select-String 'COMPUTE_MODE=(\S+)' $computeYml
                if ($m) { $m.Matches[0].Groups[1].Value } else { "cpu" }
            } else { "cpu" }
            ok "compute.yml  ->  $mode"
        } else {
            warn "Hardware detection failed -- defaulting to CPU"
        }
    } else {
        warn "detect_hardware.py not found -- skipping"
    }

    if (Get-Command claude -ErrorAction SilentlyContinue) {
        $port = if ($env:MODEL_GATEWAY_PORT) { $env:MODEL_GATEWAY_PORT } else { "11435" }
        [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "local", "User")
        [System.Environment]::SetEnvironmentVariable("ANTHROPIC_BASE_URL", "http://localhost:$port", "User")
        ok "Claude Code  ->  http://localhost:$port  (restart terminal to apply)"
    }

    # 4. Start services
    section "4/4" "Starting services"
    $env:BASE_PATH = $base
    docker compose up -d

    # Summary
    Write-Host "`nReady" -ForegroundColor Green
    Write-Host ""
    $urls = @(
        @("Dashboard",     "http://localhost:8080"),
        @("Open WebUI",    "http://localhost:3000"),
        @("ComfyUI",       "http://localhost:8188"),
        @("N8N",           "http://localhost:5678"),
        @("OpenClaw",      "http://localhost:6682"),
        @("Model Gateway", "http://localhost:11435")
    )
    foreach ($u in $urls) {
        Write-Host ("  {0,-22}" -f $u[0]) -ForegroundColor White -NoNewline
        Write-Host $u[1]
    }
    Write-Host ""
    Write-Host "  Pull Ollama models:   docker compose run --rm model-puller" -ForegroundColor DarkGray
    Write-Host "  Pull ComfyUI models:  docker compose --profile comfyui-models run --rm comfyui-model-puller" -ForegroundColor DarkGray
    Write-Host ""
}

# ── dispatch
switch ($Command) {
    { $_ -in "initialize", "init" } { Invoke-Initialize }
    { $_ -in "help", "--help", "-h" } {
        Get-Content $MyInvocation.MyCommand.Path |
            Where-Object { $_ -match '^#' } |
            ForEach-Object { $_ -replace '^# ?', '' } |
            Select-Object -Skip 1
    }
    default {
        err "Unknown command: $Command"
        Write-Host "  Run .\ai-toolkit.ps1 help for usage."
        exit 1
    }
}
