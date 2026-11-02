@echo off
chcp 65001 >nul
title Cloudflare Tunnel 內網穿透工具
cd /d "%~dp0"

echo =======================================================
echo ⚡ Arduino Universal Hub - Cloudflare 內網穿透快速啟動器
echo 🌐 免費將本地 Web 服務公開至全球網際網路 (trycloudflare.com)
echo =======================================================
echo.
set /p TARGET_PORT="請輸入要穿透的本地通訊埠 [直接按 Enter 預設為 5000]: "
if "%TARGET_PORT%"=="" set TARGET_PORT=5000

echo.
echo 🎯 目標通訊埠: %TARGET_PORT%
echo 🚀 正在啟動 Cloudflare Tunnel...
echo.

python cloudflare_tunnel.py --port %TARGET_PORT% --copy --open

pause
