@echo off
chcp 65001 >nul
title ⚡ Arduino Uno 萬能互動韌體一鍵重刷工具

echo ========================================================
echo  ⚡ Arduino Uno 萬能互動韌體 (universal_firmware) 一鍵重刷
echo ========================================================
echo.
echo 說明：
echo   - 本工具使用本機內建 AVR-GCC / avrdude 編譯工具鏈
echo   - 自動偵測 Arduino Uno COM 埠並將萬能韌體直接固化至晶片
echo   - 燒錄完成後立即恢復與 Block Studio / Web 控制台的即時通訊！
echo.
echo --------------------------------------------------------
echo 正在釋放可能被佔用之序列埠進程...
taskkill /F /IM avrdude.exe >nul 2>&1
echo --------------------------------------------------------
echo.
python "%~dp0avr_flasher.py" "%~dp0universal_firmware\universal_firmware.ino" auto
echo.
pause

