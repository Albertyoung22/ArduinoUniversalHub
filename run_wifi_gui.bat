@echo off
cd /d "%~dp0"
echo =======================================================
echo  Starting Arduino Universal Hub - Wi-Fi Controller
echo =======================================================
python wifi_controller.py
pause
