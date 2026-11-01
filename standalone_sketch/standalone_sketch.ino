/*
 * ===============================================================
 * Arduino Universal Hub - 脫機獨立自訂流程專用韌體
 * ===============================================================
 * 流程名稱: 🎉 迎賓聯動燈光秀
 * 循環播放: 否 (單次播放)
 * 步驟總數: 12
 *
 * 【脫機獨立特性】：
 * - 燒錄完成後，完全不需要連接電腦或執行 Python！
 * - 插上 5V 行動電源或手機充電頭即可自動從頭到尾獨立執行！
 * - 若插上電腦序列埠 (115200 Baud)，發送 PING 依然支援即時互動通訊！
 * ===============================================================
 */

#include <Arduino.h>
#include <Servo.h>
#include <avr/pgmspace.h>

// --- 硬體腳位配置 ---
const uint8_t PIN_RGB1_R = 6, PIN_RGB1_G = 3, PIN_RGB1_B = 5;
const bool RGB1_ANODE = true;

const uint8_t PIN_RGB2_R = 11, PIN_RGB2_G = 9, PIN_RGB2_B = 10;
const bool RGB2_ANODE = true;

const uint8_t PIN_MATRIX_DIN = 12;
const uint8_t PIN_MATRIX_CS  = 8;
const uint8_t PIN_MATRIX_CLK = 7;

#define MAX_SERVOS 4
Servo servos[MAX_SERVOS];
int servoPins[MAX_SERVOS] = {-1, -1, -1, -1};

// --- 點陣暫存器定義 ---
#define REG_DIGIT0      0x01
#define REG_DECODEMODE  0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

void max7219_write(uint8_t reg, uint8_t data) {
  digitalWrite(PIN_MATRIX_CS, LOW);
  shiftOut(PIN_MATRIX_DIN, PIN_MATRIX_CLK, MSBFIRST, reg);
  shiftOut(PIN_MATRIX_DIN, PIN_MATRIX_CLK, MSBFIRST, data);
  digitalWrite(PIN_MATRIX_CS, HIGH);
}

void initMAX7219() {
  pinMode(PIN_MATRIX_DIN, OUTPUT);
  pinMode(PIN_MATRIX_CS,  OUTPUT);
  pinMode(PIN_MATRIX_CLK, OUTPUT);
  digitalWrite(PIN_MATRIX_CS, HIGH);
  digitalWrite(PIN_MATRIX_CLK, LOW);
  digitalWrite(PIN_MATRIX_DIN, LOW);

  max7219_write(REG_DISPLAYTEST, 0x00);
  max7219_write(REG_SCANLIMIT,   0x07);
  max7219_write(REG_DECODEMODE,  0x00);
  max7219_write(REG_INTENSITY,   0x05);
  max7219_write(REG_SHUTDOWN,    0x01);
}

void displayMatrixBitmap(const uint8_t bitmap[8]) {
  for (uint8_t r = 0; r < 8; r++) {
    uint8_t b = pgm_read_byte(&bitmap[r]);
    max7219_write(REG_DIGIT0 + r, b);
  }
}

void displayMatrixRAM(const uint8_t bitmap[8]) {
  for (uint8_t r = 0; r < 8; r++) {
    max7219_write(REG_DIGIT0 + r, bitmap[r]);
  }
}

void clearMatrix() {
  for (uint8_t r = 0; r < 8; r++) {
    max7219_write(REG_DIGIT0 + r, 0x00);
  }
}

// 流程靜態圖案陣列
const uint8_t BMP_PRESET_1[8] PROGMEM = { 0x3C, 0x42, 0xA5, 0x81, 0xA5, 0x99, 0x42, 0x3C };
const uint8_t BMP_PRESET_4[8] PROGMEM = { 0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18 };
const uint8_t BMP_PRESET_8[8] PROGMEM = { 0x18, 0x3C, 0x7E, 0xFF, 0x7E, 0x3C, 0x18, 0x00 };

// 點陣圖形動畫庫
const uint8_t ANIM_HEARTBEAT[8][8] PROGMEM = {
  {0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18},
  {0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00},
  {0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00},
  {0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00},
  {0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00},
  {0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00},
  {0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18},
  {0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18}
};

const uint8_t ANIM_ROCKET[8][8] PROGMEM = {
  {0x18, 0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18},
  {0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18},
  {0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24},
  {0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42},
  {0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00},
  {0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00},
  {0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00},
  {0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00, 0x00}
};

const uint8_t ANIM_WAVE[8][8] PROGMEM = {
  {0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80},
  {0x03, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x81},
  {0x07, 0x0E, 0x1C, 0x38, 0x70, 0xE0, 0xC1, 0x83},
  {0x0F, 0x1E, 0x3C, 0x78, 0xF0, 0xE1, 0xC3, 0x87},
  {0x1F, 0x3E, 0x7C, 0xF8, 0xF1, 0xE3, 0xC7, 0x8F},
  {0x3F, 0x7E, 0xFC, 0xF9, 0xF3, 0xE7, 0xCF, 0x9F},
  {0x7F, 0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF},
  {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}
};

const uint8_t ANIM_RADAR[8][8] PROGMEM = {
  {0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18},
  {0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0},
  {0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00},
  {0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03},
  {0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18},
  {0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0},
  {0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00},
  {0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03}
};

void playMatrixAnimation(uint8_t animId, uint16_t spd, uint8_t repeats) {
  for (uint8_t r = 0; r < repeats; r++) {
    for (uint8_t f = 0; f < 8; f++) {
      uint8_t frame[8];
      for (uint8_t row = 0; row < 8; row++) {
        if (animId == 0) frame[row] = pgm_read_byte(&ANIM_HEARTBEAT[f][row]);
        else if (animId == 1) frame[row] = pgm_read_byte(&ANIM_ROCKET[f][row]);
        else if (animId == 2) frame[row] = pgm_read_byte(&ANIM_WAVE[f][row]);
        else frame[row] = pgm_read_byte(&ANIM_RADAR[f][row]);
      }
      displayMatrixRAM(frame);
      delay(spd);
    }
  }
}

// 5x7 ASCII 字型表 (節省 Flash)
const uint8_t FONT57[][5] PROGMEM = {
  {0x00, 0x00, 0x00, 0x00, 0x00}, // ' '
  {0x7E, 0x11, 0x11, 0x11, 0x7E}, // 'A'
  {0x7F, 0x49, 0x49, 0x49, 0x36}, // 'B'
  {0x3E, 0x41, 0x41, 0x41, 0x22}, // 'C'
  {0x7F, 0x41, 0x41, 0x22, 0x1C}, // 'D'
  {0x7F, 0x49, 0x49, 0x49, 0x41}, // 'E'
  {0x7F, 0x09, 0x09, 0x09, 0x01}, // 'F'
  {0x3E, 0x41, 0x49, 0x49, 0x7A}, // 'G'
  {0x7F, 0x08, 0x08, 0x08, 0x7F}, // 'H'
  {0x00, 0x41, 0x7F, 0x41, 0x00}, // 'I'
  {0x20, 0x40, 0x41, 0x3F, 0x01}, // 'J'
  {0x7F, 0x08, 0x14, 0x22, 0x41}, // 'K'
  {0x7F, 0x40, 0x40, 0x40, 0x40}, // 'L'
  {0x7F, 0x02, 0x0C, 0x02, 0x7F}, // 'M'
  {0x7F, 0x04, 0x08, 0x10, 0x7F}, // 'N'
  {0x3E, 0x41, 0x41, 0x41, 0x3E}, // 'O'
  {0x7F, 0x09, 0x09, 0x09, 0x06}, // 'P'
  {0x3E, 0x41, 0x51, 0x21, 0x5E}, // 'Q'
  {0x7F, 0x09, 0x19, 0x29, 0x46}, // 'R'
  {0x46, 0x49, 0x49, 0x49, 0x31}, // 'S'
  {0x01, 0x01, 0x7F, 0x01, 0x01}, // 'T'
  {0x3F, 0x40, 0x40, 0x40, 0x3F}, // 'U'
  {0x1F, 0x20, 0x40, 0x20, 0x1F}, // 'V'
  {0x7F, 0x20, 0x18, 0x20, 0x7F}, // 'W'
  {0x63, 0x14, 0x08, 0x14, 0x63}, // 'X'
  {0x07, 0x08, 0x70, 0x08, 0x07}, // 'Y'
  {0x61, 0x51, 0x49, 0x45, 0x43}, // 'Z'
  {0x3E, 0x51, 0x49, 0x45, 0x3E}, // '0'
  {0x00, 0x42, 0x7F, 0x40, 0x00}, // '1'
  {0x42, 0x61, 0x51, 0x49, 0x46}, // '2'
  {0x21, 0x41, 0x45, 0x4B, 0x31}, // '3'
  {0x18, 0x14, 0x12, 0x7F, 0x10}, // '4'
  {0x27, 0x45, 0x45, 0x45, 0x39}, // '5'
  {0x3C, 0x4A, 0x49, 0x49, 0x30}, // '6'
  {0x01, 0x71, 0x09, 0x05, 0x03}, // '7'
  {0x36, 0x49, 0x49, 0x49, 0x36}, // '8'
  {0x06, 0x49, 0x49, 0x29, 0x1E}, // '9'
  {0x00, 0x36, 0x36, 0x00, 0x00}  // '!'
};

void marqueeText(const char* txt, uint16_t spd) {
  uint16_t len = strlen(txt);
  for (uint16_t cIdx = 0; cIdx < len; cIdx++) {
    char ch = txt[cIdx];
    if (ch >= 'a' && ch <= 'z') ch -= 32;
    int fIdx = 0;
    if (ch >= 'A' && ch <= 'Z') fIdx = 1 + (ch - 'A');
    else if (ch >= '0' && ch <= '9') fIdx = 27 + (ch - '0');
    else if (ch == '!') fIdx = 37;

    for (uint8_t col = 0; col < 6; col++) {
      for (uint8_t r = 0; r < 8; r++) {
        uint8_t current = 0;
        // 簡易向左位移
      }
      delay(spd);
    }
  }
  clearMatrix();
}

// --- RGB 與舵機驅動輔助函數 ---
void setRGB(uint8_t rp, uint8_t gp, uint8_t bp, bool anode, uint8_t r, uint8_t g, uint8_t b) {
  pinMode(rp, OUTPUT);
  pinMode(gp, OUTPUT);
  pinMode(bp, OUTPUT);
  analogWrite(rp, anode ? 255 - r : r);
  analogWrite(gp, anode ? 255 - g : g);
  analogWrite(bp, anode ? 255 - b : b);
}

void setServoAngle(uint8_t pin, uint8_t angle) {
  int slot = -1;
  for (int i = 0; i < MAX_SERVOS; i++) {
    if (servoPins[i] == pin) { slot = i; break; }
  }
  if (slot == -1) {
    for (int i = 0; i < MAX_SERVOS; i++) {
      if (servoPins[i] == -1) {
        slot = i;
        servoPins[i] = pin;
        servos[i].attach(pin);
        break;
      }
    }
  }
  if (slot != -1) {
    servos[slot].write(angle);
  }
}

void hsvToRgb(float h, float s, float v, uint8_t &r, uint8_t &g, uint8_t &b) {
  float c = v * s;
  float x = c * (1.0f - fabs(fmod(h / 60.0f, 2.0f) - 1.0f));
  float m = v - c;
  float r1 = 0, g1 = 0, b1 = 0;
  if (h < 60) { r1 = c; g1 = x; }
  else if (h < 120) { r1 = x; g1 = c; }
  else if (h < 180) { g1 = c; b1 = x; }
  else if (h < 240) { g1 = x; b1 = c; }
  else if (h < 300) { r1 = x; b1 = c; }
  else { r1 = c; b1 = x; }
  r = (uint8_t)((r1 + m) * 255);
  g = (uint8_t)((g1 + m) * 255);
  b = (uint8_t)((b1 + m) * 255);
}

// 18 款雙燈連線特效脫機引擎
void playDualEffect(const char* fx, uint32_t durationMs) {
  uint32_t start = millis();
  while (millis() - start < durationMs) {
    float dt = (millis() - start) / 1000.0f;
    uint8_t r1 = 0, g1 = 0, b1 = 0, r2 = 0, g2 = 0, b2 = 0;

    if (strcmp(fx, "sync_rainbow") == 0) {
      hsvToRgb(fmod(dt * 60.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      r2 = r1; g2 = g1; b2 = b1;
    } else if (strcmp(fx, "complementary") == 0) {
      hsvToRgb(fmod(dt * 50.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      hsvToRgb(fmod(dt * 50.0f + 180.0f, 360.0f), 1.0f, 1.0f, r2, g2, b2);
    } else if (strcmp(fx, "police_strobe") == 0) {
      uint8_t phase = ((int)(dt * 8)) % 4;
      if (phase <= 1) { r1 = 255; r2 = 0; b2 = 0; }
      else { r1 = 0; r2 = 0; b2 = 255; }
    } else if (strcmp(fx, "warm_breathing") == 0) {
      float v = (sin(dt * 2.5f) + 1.0f) * 0.5f;
      r1 = r2 = (uint8_t)(255 * v);
      g1 = g2 = (uint8_t)(120 * v);
      b1 = b2 = (uint8_t)(20 * v);
    } else if (strcmp(fx, "aurora_breathing") == 0) {
      float v1 = (sin(dt * 2.0f) + 1.0f) * 0.5f;
      float v2 = (cos(dt * 2.0f) + 1.0f) * 0.5f;
      r1 = 0; g1 = (uint8_t)(255 * v1); b1 = (uint8_t)(200 * v1);
      r2 = (uint8_t)(180 * v2); g2 = 0; b2 = (uint8_t)(255 * v2);
    } else if (strcmp(fx, "disco_party") == 0) {
      r1 = random(2) ? 255 : 0; g1 = random(2) ? 255 : 0; b1 = random(2) ? 255 : 0;
      r2 = random(2) ? 255 : 0; g2 = random(2) ? 255 : 0; b2 = random(2) ? 255 : 0;
    } else if (strcmp(fx, "fire_flicker") == 0) {
      uint8_t flicker = random(180, 255);
      r1 = r2 = flicker;
      g1 = g2 = (uint8_t)max(0, (int)(flicker * 0.4f + random(-20, 20)));
      b1 = b2 = 0;
    } else if (strcmp(fx, "thunder_storm") == 0) {
      if (random(100) < 15) { r1 = r2 = g1 = g2 = b1 = b2 = 255; }
      else { r1 = r2 = g1 = g2 = 0; b1 = b2 = 20; }
    } else if (strcmp(fx, "heartbeat") == 0) {
      float tCycle = fmod(dt, 1.2f);
      float v = 0.05f;
      if (tCycle < 0.18f) v = sin(tCycle / 0.18f * 3.14159f);
      else if (tCycle >= 0.28f && tCycle < 0.46f) v = sin((tCycle - 0.28f) / 0.18f * 3.14159f) * 0.65f;
      r1 = r2 = (uint8_t)(255 * v);
    } else if (strcmp(fx, "ambulance_amber") == 0) {
      uint8_t phase = ((int)(dt * 6)) % 8;
      if (phase == 0 || phase == 2) { r1 = 255; g1 = 120; }
      else if (phase == 4 || phase == 6) { r2 = g2 = b2 = 255; }
    } else {
      // 預設彩虹
      hsvToRgb(fmod(dt * 60.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      r2 = r1; g2 = g1; b2 = b1;
    }

    setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, r1, g1, b1);
    setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, r2, g2, b2);
    delay(35);
  }
  // 結束熄滅
  setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, 0, 0, 0);
  setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, 0, 0, 0);
}

// ===============================================================
// 核心自訂流程執行函式 (由使用者所編排的步驟生成)
// ===============================================================
void runCustomWorkflow() {
  // 步驟 1: RGB 1 炫彩紫紅
  setRGB(6, 3, 5, true, 255, 0, 120);

  // 步驟 2: 點陣顯示笑臉
  displayMatrixBitmap(BMP_PRESET_1);

  // 步驟 3: 等待 600ms
  delay(600);

  // 步驟 4: RGB 2 冰川亮藍
  setRGB(11, 9, 10, true, 0, 220, 255);

  // 步驟 5: 點陣切換愛心
  displayMatrixBitmap(BMP_PRESET_4);

  // 步驟 6: 等待 600ms
  delay(600);

  // 步驟 7: RGB 1 暖金黃光
  setRGB(6, 3, 5, true, 255, 200, 0);

  // 步驟 8: RGB 2 電光洋紅
  setRGB(11, 9, 10, true, 255, 0, 255);

  // 步驟 9: 點陣切換鑽石
  displayMatrixBitmap(BMP_PRESET_8);

  // 步驟 10: 等待 800ms
  delay(800);

  // 步驟 11: 熄滅 RGB 1
  setRGB(6, 3, 5, true, 0, 0, 0);

  // 步驟 12: 熄滅 RGB 2
  setRGB(11, 9, 10, true, 0, 0, 0);

}

void setup() {
  Serial.begin(115200);

  // 初始化 RGB
  setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, 0, 0, 0);
  setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, 0, 0, 0);

  // 初始化點陣
  initMAX7219();
  clearMatrix();

  Serial.println(F("OK:STANDALONE_WORKFLOW_READY"));
}

void loop() {
  // 檢查序列埠是否要求恢復互動控制
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "PING") {
      Serial.println(F("PONG:UNIVERSAL_V1"));
    }
  }

  // 執行自訂流程
  runCustomWorkflow();

  // 若非循環模式，播放完一次後進入休眠等待
  #if 0 == 0
  while (true) {
    if (Serial.available() > 0) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "PING") Serial.println(F("PONG:UNIVERSAL_V1"));
    }
    delay(100);
  }
  #endif
}
