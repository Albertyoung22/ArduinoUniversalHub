@echo off
chcp 65001 > nul
title ⚡ Arduino Universal Web Hub (Flask + Waitress + Cloudflare Tunnel)
echo =====================================================================
echo  ⚡ Arduino 萬能硬體控制中心 - Web 伺服器啟動中 (Flask + Waitress)...
echo  🏠 本地存取網址: http://127.0.0.1:5000
echo  🌐 將自動啟動 Cloudflare Tunnel 內網穿透並捕獲外網公開網址！
echo  📱 任何手機 / 平板皆可透過 trycloudflare.com 網址由外網直接連線！
echo =====================================================================
python universal_web.py
pause
