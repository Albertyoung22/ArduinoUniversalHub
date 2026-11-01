/*
 * Webduino Fly / ESP8266 Wi-Fi 訊號即時掃描工具
 */

#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println(F("\n======================================"));
  Serial.println(F("🔍 正在透過 ESP8266 掃描周遭 Wi-Fi 基地台..."));
  Serial.println(F("======================================"));

  // 發送 AT 指令要求 ESP8266 列出附近所有 Wi-Fi
  Serial.println(F("AT+CWMODE=1"));
  delay(500);
  Serial.println(F("AT+CWLAP"));
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    Serial.write(c);
  }
}

