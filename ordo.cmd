@echo off
REM Short Windows launcher for Ordo
set "SCRIPT=%~dp0"
if "%~1"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%ordo.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%ordo.ps1" %*
)
