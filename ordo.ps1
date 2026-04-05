# Ordo short launcher
param([Parameter(ValueFromRemainingArguments)][string[]]$Args)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Args -or $Args.Count -eq 0) {
    & (Join-Path $scriptDir "ordo-ai-stack.ps1") launch
} else {
    & (Join-Path $scriptDir "ordo-ai-stack.ps1") @Args
}
