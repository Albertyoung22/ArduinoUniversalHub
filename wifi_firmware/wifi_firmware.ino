/*
 * Arduino Universal Wi-Fi Hardware Engine (全無線 Wi-Fi 韌體)
 * ============================================================
 * 專為 Arduino Uno + Webduino Fly (ESP8266 擴充板) 打造
 * 
 * 功能特點：
 * 1. 透過序列埠 (Pin 0 RX / Pin 1 TX) 驅動 ESP8266 Wi-Fi 模組
 * 2. 自動偵測 ESP8266 通訊鮑率 (115200 / 57600 / 9600)
 * 3. 內建 STA (連線家中路由器) 與 AP (熱點回退模式: Arduino_WiFi)
 * 4. 內建輕量化 HTTP REST API (Port 80) 與 Web 控制儀表板
 * 5. 支援完整萬能硬體 RPC 指令集：
 *    - 數位輸出 (LED/繼電器): DWRITE,pin,val
 *    - PWM 類比輸出 (調光/調速): AWRITE,pin,val
 *    - 伺服舵機 (Servo 0~180度): SERVO,pin,angle
 *    - 複合雙 RGB LED: RGB,rPin,gPin,bPin,isAnode,r,g,b
 *    - MAX7219 8x8 點陣: MATRIX_ALL, MATRIX_ROW, MATRIX_CLEAR
 *    - 心跳測試: PING
 */

#include <Arduino.h>
#include <Servo.h>
#include <EEPROM.h>

// ==========================
// 預設 Wi-Fi 連線設定 (可在此修改或透過網頁設定)
// ==========================
const char DEFAULT_SSID[] = "WIFI_NAME";     // 請替換為您的 Wi-Fi 名稱 (2.4GHz)
const char DEFAULT_PASS[] = "WIFI_PASSWORD"; // 請替換為您的 Wi-Fi 密碼

#define AP_SSID "Arduino_Universal_WiFi"
#define AP_PASS "12345678"

// 舵機最大插槽
#define MAX_SERVOS 6
struct ServoSlot {
  uint8_t pin;
  Servo servo;
  bool active;
};
ServoSlot servoSlots[MAX_SERVOS];

// ESP8266 狀態
String localIP = "0.0.0.0";
bool isConnectedWiFi = false;
long activeBaudRate = 115200;

void saveWiFiCredentials(String ssid, String pass) {
  EEPROM.write(0, 0xAA);
  uint8_t slen = min((uint8_t)ssid.length(), (uint8_t)32);
  uint8_t plen = min((uint8_t)pass.length(), (uint8_t)32);
  EEPROM.write(1, slen);
  for (uint8_t i = 0; i < slen; i++) EEPROM.write(2 + i, ssid[i]);
  EEPROM.write(35, plen);
  for (uint8_t i = 0; i < plen; i++) EEPROM.write(36 + i, pass[i]);
}

bool loadWiFiCredentials(String &ssid, String &pass) {
  if (EEPROM.read(0) != 0xAA) return false;
  uint8_t slen = EEPROM.read(1);
  if (slen == 0 || slen > 32) return false;
  ssid = "";
  for (uint8_t i = 0; i < slen; i++) ssid += (char)EEPROM.read(2 + i);
  uint8_t plen = EEPROM.read(35);
  pass = "";
  for (uint8_t i = 0; i < plen && i < 32; i++) pass += (char)EEPROM.read(36 + i);
  return (ssid.length() > 0);
}

// MAX7219 驅動輔助函數
void max7219_write(uint8_t din, uint8_t cs, uint8_t clk, uint8_t reg, uint8_t data) {
  digitalWrite(cs, LOW);
  shiftOut(din, clk, MSBFIRST, reg);
  shiftOut(din, clk, MSBFIRST, data);
  digitalWrite(cs, HIGH);
}

void max7219_init(uint8_t din, uint8_t cs, uint8_t clk) {
  pinMode(din, OUTPUT);
  pinMode(cs, OUTPUT);
  pinMode(clk, OUTPUT);
  digitalWrite(cs, HIGH);
  digitalWrite(clk, LOW);
  digitalWrite(din, LOW);

  max7219_write(din, cs, clk, 0x0F, 0x00); // 正常顯示
  max7219_write(din, cs, clk, 0x0B, 0x07); // 8 掃描行
  max7219_write(din, cs, clk, 0x09, 0x00); // 無解碼
  max7219_write(din, cs, clk, 0x0A, 0x05); // 亮度 (0~15)
  max7219_write(din, cs, clk, 0x0C, 0x01); // 開啟顯示
}

// ==========================
// ESP8266 AT 指令通訊輔助
// ==========================
bool sendAT(String cmd, String expected, unsigned long timeout = 2500) {
  while (Serial.available()) Serial.read(); // 清空接收緩衝區
  Serial.println(cmd);
  
  unsigned long start = millis();
  String resp = "";
  while (millis() - start < timeout) {
    if (Serial.available()) {
      char c = Serial.read();
      resp += c;
      if (resp.indexOf(expected) != -1) {
        return true;
      }
      if (resp.indexOf(F("ERROR")) != -1 || resp.indexOf(F("FAIL")) != -1) {
        return false;
      }
    }
  }
  return false;
}

String getATResponse(String cmd, unsigned long timeout = 2500) {
  while (Serial.available()) Serial.read();
  Serial.println(cmd);
  
  unsigned long start = millis();
  String resp = "";
  while (millis() - start < timeout) {
    if (Serial.available()) {
      resp += (char)Serial.read();
    }
  }
  return resp;
}

// 自動探測 ESP8266 鮑率
bool detectBaudRate() {
  const long bauds[] = {115200, 57600, 9600};
  for (int i = 0; i < 3; i++) {
    Serial.begin(bauds[i]);
    delay(50);
    if (sendAT(F("AT"), F("OK"), 800)) {
      activeBaudRate = bauds[i];
      return true;
    }
  }
  // 預設採用 115200
  Serial.begin(115200);
  activeBaudRate = 115200;
  return false;
}

// 初始化 Wi-Fi 連線
void initWiFi() {
  detectBaudRate();
  delay(100);

  // 關閉回顯以提升傳輸效率
  sendAT(F("ATE0"), F("OK"), 1000);

  // 設置模式為 STA + AP 雙模
  sendAT(F("AT+CWMODE=3"), F("OK"), 1500);

  // 讀取 EEPROM 中的 Wi-Fi 設定，若無則採用預設值
  String curSSID = String(DEFAULT_SSID);
  String curPASS = String(DEFAULT_PASS);
  String epSSID, epPASS;
  if (loadWiFiCredentials(epSSID, epPASS)) {
    curSSID = epSSID;
    curPASS = epPASS;
  }

  // 嘗試連線指定 Wi-Fi
  String joinCmd = "AT+CWJAP=\"" + curSSID + "\",\"" + curPASS + "\"";
  if (sendAT(joinCmd, F("OK"), 12000)) {
    isConnectedWiFi = true;
  } else {
    isConnectedWiFi = false;
    // 啟動熱點保護
    String apCmd = "AT+CWSAP=\"" + String(AP_SSID) + "\",\"" + String(AP_PASS) + "\",5,3";
    sendAT(apCmd, F("OK"), 3000);
  }

  // 獲取 IP 地址
  String ipResp = getATResponse(F("AT+CIFSR"), 2000);
  int idx = ipResp.indexOf(F("STAIP,\""));
  if (idx != -1) {
    int endIdx = ipResp.indexOf(F("\""), idx + 7);
    if (endIdx != -1) {
      localIP = ipResp.substring(idx + 7, endIdx);
    }
  }

  // 啟用多連線模式
  sendAT(F("AT+CIPMUX=1"), F("OK"), 1500);

  // 開啟 Port 80 HTTP 伺服器
  sendAT(F("AT+CIPSERVER=1,80"), F("OK"), 2000);
}

// 快速回應用戶端 HTTP 內容
void sendHTTPResponse(int linkId, String content, String contentType = "application/json") {
  String header = "HTTP/1.1 200 OK\r\nContent-Type: " + contentType + "\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n";
  String full = header + content;
  int len = full.length();

  String sendCmd = "AT+CIPSEND=" + String(linkId) + "," + String(len);
  if (sendAT(sendCmd, F(">"), 1500)) {
    Serial.print(full);
    delay(20);
    sendAT("AT+CIPCLOSE=" + String(linkId), F("OK"), 1000);
  } else {
    sendAT("AT+CIPCLOSE=" + String(linkId), F("OK"), 500);
  }
}

// ==========================
// 核心萬能硬體 RPC 指令執行器
// ==========================
String executeCommand(String line) {
  line.trim();
  if (line.length() == 0) return "ERR:EMPTY";

  if (line == "PING") {
    return "PONG:WIFI_V1," + localIP;
  }

  // 掃描周遭 Wi-Fi AP (供 USB 程式一鍵獲取清單)
  if (line == "SCAN_WIFI" || line == "SCAN_AP") {
    sendAT(F("AT+CWMODE=1"), F("OK"), 800);
    Serial.println(F("AT+CWLAP"));
    unsigned long start = millis();
    while (millis() - start < 5000) {
      if (Serial.available()) {
        String l = Serial.readStringUntil('\n');
        l.trim();
        if (l.indexOf(F("+CWLAP:")) != -1) {
          int q1 = l.indexOf('"');
          int q2 = l.indexOf('"', q1 + 1);
          if (q1 != -1 && q2 != -1) {
            String ssid = l.substring(q1 + 1, q2);
            Serial.print(F("WIFI_AP:"));
            Serial.println(ssid);
          }
        }
        if (l.indexOf(F("OK")) != -1) break;
      }
    }
    return "OK:SCAN_DONE";
  }

  char buf[128];
  line.toCharArray(buf, sizeof(buf));
  char* parts[16];
  int count = 0;
  char* tok = strtok(buf, ",");
  while (tok != NULL && count < 16) {
    parts[count++] = tok;
    tok = strtok(NULL, ",");
  }

  if (count == 0) return "ERR:PARSE";
  String cmd = String(parts[0]);
  cmd.toUpperCase();

  // 1. 數位開關: DWRITE,pin,val
  if (cmd == "DWRITE" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    uint8_t val = atoi(parts[2]) > 0 ? HIGH : LOW;
    pinMode(pin, OUTPUT);
    digitalWrite(pin, val);
    return "OK:DWRITE," + String(pin) + "," + String(val);
  }

  // 2. PWM / 類比輸出: AWRITE,pin,val (0~255)
  if ((cmd == "AWRITE" || cmd == "PWM") && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    int val = constrain(atoi(parts[2]), 0, 255);
    pinMode(pin, OUTPUT);
    analogWrite(pin, val);
    return "OK:PWM," + String(pin) + "," + String(val);
  }

  // 3. 舵機角度: SERVO,pin,angle (0~180)
  if (cmd == "SERVO" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    int angle = constrain(atoi(parts[2]), 0, 180);
    int slot = -1;
    for (int i = 0; i < MAX_SERVOS; i++) {
      if (servoSlots[i].active && servoSlots[i].pin == pin) {
        slot = i;
        break;
      }
    }
    if (slot == -1) {
      for (int i = 0; i < MAX_SERVOS; i++) {
        if (!servoSlots[i].active) {
          slot = i;
          servoSlots[slot].pin = pin;
          servoSlots[slot].servo.attach(pin);
          servoSlots[slot].active = true;
          break;
        }
      }
    }
    if (slot != -1) {
      servoSlots[slot].servo.write(angle);
      return "OK:SERVO," + String(pin) + "," + String(angle);
    }
    return "ERR:MAX_SERVOS";
  }

  // 4. RGB LED: RGB,rPin,gPin,bPin,isAnode(0|1),r,g,b
  if (cmd == "RGB" && count >= 8) {
    uint8_t rPin = atoi(parts[1]);
    uint8_t gPin = atoi(parts[2]);
    uint8_t bPin = atoi(parts[3]);
    bool isAnode = (atoi(parts[4]) == 1);
    uint8_t r = constrain(atoi(parts[5]), 0, 255);
    uint8_t g = constrain(atoi(parts[6]), 0, 255);
    uint8_t b = constrain(atoi(parts[7]), 0, 255);

    pinMode(rPin, OUTPUT);
    pinMode(gPin, OUTPUT);
    pinMode(bPin, OUTPUT);

    analogWrite(rPin, isAnode ? 255 - r : r);
    analogWrite(gPin, isAnode ? 255 - g : g);
    analogWrite(bPin, isAnode ? 255 - b : b);
    return "OK:RGB";
  }

  // 5. MAX7219 全矩陣繪製: MATRIX_ALL,din,cs,clk,b0..b7
  if (cmd == "MATRIX_ALL" && count >= 12) {
    uint8_t din = atoi(parts[1]);
    uint8_t cs = atoi(parts[2]);
    uint8_t clk = atoi(parts[3]);
    max7219_init(din, cs, clk);
    for (int r = 0; r < 8; r++) {
      uint8_t val = (uint8_t)strtoul(parts[4 + r], NULL, 0);
      max7219_write(din, cs, clk, r + 1, val);
    }
    return "OK:MATRIX_ALL";
  }

  // 6. MAX7219 清除: MATRIX_CLEAR,din,cs,clk
  if (cmd == "MATRIX_CLEAR" && count >= 4) {
    uint8_t din = atoi(parts[1]);
    uint8_t cs = atoi(parts[2]);
    uint8_t clk = atoi(parts[3]);
    max7219_init(din, cs, clk);
    for (int r = 1; r <= 8; r++) {
      max7219_write(din, cs, clk, r, 0x00);
    }
    return "OK:MATRIX_CLEAR";
  }

  // 7. 系統急停: STOP
  if (cmd == "STOP") {
    for (int i = 0; i < MAX_SERVOS; i++) {
      if (servoSlots[i].active) {
        servoSlots[i].servo.detach();
        servoSlots[i].active = false;
      }
    }
    return "OK:STOPPED";
  }

  return "ERR:UNKNOWN_CMD";
}

// 內嵌式超輕量 Web 控制遙控頁面 (直接從 Arduino Uno 晶片回傳)
const char INDEX_HTML[] PROGMEM = 
"<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
"<title>Arduino Uno Wi-Fi 控制台</title>"
"<style>body{background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;text-align:center;padding:20px;}"
".btn{background:#89b4fa;color:#11111b;border:none;padding:12px 24px;border-radius:8px;font-size:16px;font-weight:bold;margin:8px;cursor:pointer;}"
".danger{background:#f38ba8;}"
".card{background:#313244;border-radius:12px;padding:16px;margin:12px auto;max-width:400px;box-shadow:0 4px 10px rgba(0,0,0,0.3);}"
"</style></head><body>"
"<h2>⚡ Arduino Wi-Fi 控制台</h2>"
"<p style='color:#a6e3a1;'>● Webduino Fly (ESP8266) 無線連線就緒</p>"
"<div class='card'><h3>💡 數位 LED (Pin 13)</h3>"
"<button class='btn' onclick='send(\"DWRITE,13,1\")'>開啟</button>"
"<button class='btn danger' onclick='send(\"DWRITE,13,0\")'>關閉</button>"
"</div>"
"<div class='card'><h3>🛑 安全急停</h3>"
"<button class='btn danger' style='width:80%;' onclick='send(\"STOP\")'>緊急全體停機</button>"
"</div>"
"<script>"
"function send(cmd){fetch('/cmd?c='+encodeURIComponent(cmd)).then(r=>r.json()).then(d=>console.log(d));}"
"</script></body></html>";

void setup() {
  for (int i = 0; i < MAX_SERVOS; i++) {
    servoSlots[i].active = false;
  }

  // 初始化 Wi-Fi 模組
  initWiFi();
}

void loop() {
  // 監聽 ESP8266 接收到的網路資料 (+IPD,linkId,len:...)
  if (Serial.available()) {
    if (Serial.find("+IPD,")) {
      int linkId = Serial.parseInt();
      int len = Serial.parseInt();
      
      // 等待資料標頭 ':'
      if (Serial.find(":")) {
        String req = "";
        unsigned long timeout = millis() + 600;
        while (req.length() < 120 && millis() < timeout) {
          if (Serial.available()) {
            char c = Serial.read();
            req += c;
            if (c == '\n') break;
          }
        }

        // 判斷請求路由
        if (req.indexOf(F("GET /cmd?c=")) != -1) {
          int start = req.indexOf(F("c=")) + 2;
          int end = req.indexOf(F(" "), start);
          if (end == -1) end = req.indexOf(F("&"), start);
          if (end == -1) end = req.length();
          String rawCmd = req.substring(start, end);
          
          // 簡易 URL 解碼
          rawCmd.replace(F("%2C"), F(","));
          rawCmd.replace(F("%20"), F(" "));
          
          String res = executeCommand(rawCmd);
          String json = "{\"ok\":true,\"ip\":\"" + localIP + "\",\"res\":\"" + res + "\"}";
          sendHTTPResponse(linkId, json, F("application/json"));
        } 
        else if (req.indexOf(F("GET /status")) != -1 || req.indexOf(F("GET /ping")) != -1) {
          String json = "{\"ok\":true,\"ip\":\"" + localIP + "\",\"board\":\"Arduino Uno + Webduino Fly\"}";
          sendHTTPResponse(linkId, json, F("application/json"));
        }
        else {
          // 回傳內嵌 Web 遙控頁面
          String html = String((__FlashStringHelper*)INDEX_HTML);
          sendHTTPResponse(linkId, html, F("text/html; charset=utf-8"));
        }
      }
    }
  }
}
