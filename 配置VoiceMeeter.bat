@echo off
chcp 65001 >nul 2>&1
echo 正在以 32 位 PowerShell 配置 VoiceMeeter Banana 路由 ...
echo.
"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Configure-Voicemeeter.ps1"
