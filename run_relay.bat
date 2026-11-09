@echo off
chcp 65001 >nul
title Bestep ESP-01 雙路 Wi-Fi 繼電器控制中樞
cd /d "%~dp0"

echo ========================================================
echo   ⚡ Bestep ESP-01 雙路 Wi-Fi 繼電器控制中樞
echo ========================================================
echo.
echo 正在啟動圖形化控制面板...
python relay_controller.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 執行發生錯誤，請按任意鍵離開...
    pause >nul
)

