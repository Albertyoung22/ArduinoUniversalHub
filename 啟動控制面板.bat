@echo off
cd /d "%~dp0"
title Arduino Uno USB 即時控制面板
echo 正在啟動 Arduino 控制面板...
start "" "python" "gui_controller.py"

