@echo off
chcp 65001 >nul
title Arduino Universal Hub - 全無線 Wi-Fi 控制中樞
cd /d "%~dp0"
echo =======================================================
echo ⚡ 正在啟動 Arduino Universal Hub - 全無線 Wi-Fi 控制中樞
echo 📱 無需 USB 傳輸線，透過 Wi-Fi 區域網路無線連線操控！
echo =======================================================
python wifi_controller.py
pause

