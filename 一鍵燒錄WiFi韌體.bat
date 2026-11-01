@echo off
chcp 65001 >nul
title 🛠️ 一鍵燒錄 Wi-Fi 韌體至 Arduino Uno (jupiter)

echo ========================================================
echo  🛠️ Arduino Uno + Webduino Fly 一鍵 Wi-Fi 韌體燒錄工具
echo ========================================================
echo.
echo [Wi-Fi 設定已就緒]
echo   - SSID     : jupiter
echo   - 密碼     : 1019b1019b
echo   - 目標連接埠: COM5
echo.
echo --------------------------------------------------------
echo ⚠️【硬體關鍵步驟 - 必看】：
echo   Webduino Fly 的 Wi-Fi 晶片佔用 Uno 的 Pin 0/1。
echo   請執行以下二選一操作：
echo     ▶ 方式 1：用手指【按住 Webduino Fly 板上的 ESP RESET 小按鈕】不要放開。
echo     ▶ 方式 2：或者先將上面那片黑色的 Webduino Fly 擴充板拔起。
echo --------------------------------------------------------
echo.
echo 準備好後，請按任意鍵立即開始燒錄...
pause >nul

echo.
echo ⏳ 正在終止殘留進程並開始燒錄...
taskkill /F /IM avrdude.exe >nul 2>&1

"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" upload -p COM5 --fqbn arduino:avr:uno "d:\PythonTest\AduinoTest\wifi_firmware\wifi_firmware.ino"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo 🎉 燒錄成功！恭喜！
    echo 現在您可以放開 ESP RESET 按鈕（或插回擴充板）。
    echo 板子正在自動連接 Wi-Fi [jupiter]...
    echo 當 Webduino Fly 上的紅燈熄滅時，代表已成功連上 Wi-Fi！
    echo ========================================================
) else (
    echo.
    echo ❌ 燒錄失敗！
    echo 原因通常是燒錄時未按住【ESP RESET】按鈕導致訊號打架。
    echo 請重新執行此檔案，並在按下任意鍵前【緊按住 ESP RESET】再試一次！
)

echo.
pause

