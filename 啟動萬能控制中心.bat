@echo off
chcp 65001 >nul
title Arduino Universal Hub
cd /d "%~dp0"
"C:\Users\ALBERT\AppData\Local\Programs\Python\Python312\python.exe" universal_gui.py
pause

