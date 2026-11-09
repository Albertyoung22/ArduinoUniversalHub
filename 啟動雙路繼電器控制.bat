@echo off
chcp 65001 >nul
title Bestep ESP-01 雙路 Wi-Fi 繼電器控制中樞
cd /d "%~dp0"
python relay_controller.py
pause

