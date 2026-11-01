/*
 * Auto-Generated Unified Master Firmware by Google OR-Tools CP-SAT
 * ===============================================================
 * Hardware Pinout:
 *   Module 1: R=6, G=3, B=5 (Common Anode: true)
 *   Module 2: R=11, G=9, B=10 (Common Anode: true)
 *   MAX7219 8x8 Dot Matrix: DIN=12, CS=8, CLK=7
 *
 * Supports BOTH:
 *   1. 100% Standalone Offline Mode (Dual RGB + 8x8 Dot Matrix synchronized show)
 *   2. Real-Time USB Serial Mode (PING, RGB, MATRIX, CLEAR_MATRIX commands)
 */

#include <Arduino.h>

// RGB 腳位定義
const uint8_t M1_R = 6;
const uint8_t M1_G = 3;
const uint8_t M1_B = 5;

const uint8_t M2_R = 11;
const uint8_t M2_G = 9;
const uint8_t M2_B = 10;

const bool COMMON_ANODE = true;

// MAX7219 8x8 點陣腳位定義
const uint8_t PIN_DIN = 12;
const uint8_t PIN_CS  = 8;
const uint8_t PIN_CLK = 7;

#define REG_DIGIT0      0x01
#define REG_DECODEMODE  0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

void writeMatrixReg(uint8_t reg, uint8_t data) {
  digitalWrite(PIN_CS, LOW);
  shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, reg);
  shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, data);
  digitalWrite(PIN_CS, HIGH);
}

void initMAX7219() {
  pinMode(PIN_DIN, OUTPUT);
  pinMode(PIN_CS,  OUTPUT);
  pinMode(PIN_CLK, OUTPUT);

  digitalWrite(PIN_CS, HIGH);
  digitalWrite(PIN_CLK, LOW);
  digitalWrite(PIN_DIN, LOW);

  writeMatrixReg(REG_DISPLAYTEST, 0x00);
  writeMatrixReg(REG_SCANLIMIT,   0x07);
  writeMatrixReg(REG_DECODEMODE,  0x00);
  writeMatrixReg(REG_INTENSITY,   0x05); // 適中亮度
  writeMatrixReg(REG_SHUTDOWN,    0x01);
}

void displayMatrixBitmap(const uint8_t bitmap[8]) {
  for (uint8_t r = 0; r < 8; r++) {
    writeMatrixReg(REG_DIGIT0 + r, bitmap[r]);
  }
}

void clearMatrix() {
  for (uint8_t r = 0; r < 8; r++) {
    writeMatrixReg(REG_DIGIT0 + r, 0x00);
  }
}

// 脫機點陣動畫圖標
const uint8_t ICON_CUSTOM[8] = { 0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18 };

const uint8_t ICON_HEART[8] = {
  0b00000000, 0b01100110, 0b11111111, 0b11111111,
  0b11111111, 0b01111110, 0b00111100, 0b00011000
};
const uint8_t ICON_HEART_SM[8] = {
  0b00000000, 0b00000000, 0b00100100, 0b01111110,
  0b01111110, 0b00111100, 0b00011000, 0b00000000
};
const uint8_t ICON_POLICE[8] = {
  0b00011000, 0b00111100, 0b01111110, 0b11111111,
  0b11111111, 0b01111110, 0b00111100, 0b00011000
};
const uint8_t ICON_SMILE[8] = {
  0b00111100, 0b01000010, 0b10100101, 0b10000001,
  0b10100101, 0b10011001, 0b01000010, 0b00111100
};
const uint8_t ICON_WINK[8] = {
  0b00111100, 0b01000010, 0b10100001, 0b10000110,
  0b10100001, 0b10011001, 0b01000010, 0b00111100
};
const uint8_t ICON_INVADER_A[8] = {
  0b00011000, 0b00111100, 0b01111110, 0b11011011,
  0b11111111, 0b00100100, 0b01011010, 0b10100101
};
const uint8_t ICON_INVADER_B[8] = {
  0b00011000, 0b00111100, 0b01111110, 0b11011011,
  0b11111111, 0b01011010, 0b10000001, 0b01000010
};
const uint8_t ICON_DIAMOND[8] = {
  0b00011000, 0b00111100, 0b01111110, 0b11111111,
  0b01111110, 0b00111100, 0b00011000, 0b00000000
};

// 排程結構
struct EffectStep {
  uint8_t effectType;
  uint32_t durationMs;
};

const EffectStep SCHEDULE[] = {
  { 0, 2000UL },
  { 1, 2000UL },
  { 2, 9000UL },
  { 3, 2000UL },
  { 4, 2000UL },
  { 5, 11000UL },
  { 6, 2000UL }
};
const uint8_t SCHEDULE_COUNT = sizeof(SCHEDULE) / sizeof(SCHEDULE[0]);

void setRGB(uint8_t rPin, uint8_t gPin, uint8_t bPin, uint8_t r, uint8_t g, uint8_t b) {
  if (COMMON_ANODE) {
    analogWrite(rPin, 255 - r);
    analogWrite(gPin, 255 - g);
    analogWrite(bPin, 255 - b);
  } else {
    analogWrite(rPin, r);
    analogWrite(gPin, g);
    analogWrite(bPin, b);
  }
}

void setM1(uint8_t r, uint8_t g, uint8_t b) {
  setRGB(M1_R, M1_G, M1_B, r, g, b);
}

void setM2(uint8_t r, uint8_t g, uint8_t b) {
  setRGB(M2_R, M2_G, M2_B, r, g, b);
}

void hsvToRgb(float h, float s, float v, uint8_t &r, uint8_t &g, uint8_t &b) {
  float c = v * s;
  float x = c * (1.0f - fabs(fmod(h / 60.0f, 2.0f) - 1.0f));
  float m = v - c;
  float r1 = 0, g1 = 0, b1 = 0;
  if (h >= 0 && h < 60) { r1 = c; g1 = x; b1 = 0; }
  else if (h >= 60 && h < 120) { r1 = x; g1 = c; b1 = 0; }
  else if (h >= 120 && h < 180) { r1 = 0; g1 = c; b1 = x; }
  else if (h >= 180 && h < 240) { r1 = 0; g1 = x; b1 = c; }
  else if (h >= 240 && h < 300) { r1 = x; g1 = 0; b1 = c; }
  else { r1 = c; g1 = 0; b1 = x; }
  r = (uint8_t)((r1 + m) * 255);
  g = (uint8_t)((g1 + m) * 255);
  b = (uint8_t)((b1 + m) * 255);
}

bool isInteractiveMode = false;
uint32_t lastSerialCmdTime = 0;
uint8_t currentStepIdx = 0;
uint32_t stepStartTime = 0;
uint32_t lastAnimTick = 0;
float animHue = 0.0f;

char cmdBuffer[128];
uint8_t cmdIdx = 0;

void processSerialCommand(char* cmd) {
  while (*cmd == ' ' || *cmd == '\r' || *cmd == '\t') cmd++;
  if (strlen(cmd) == 0) return;

  if (strcmp(cmd, "PING") == 0) {
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    Serial.println("PONG");
    return;
  }

  if (strcmp(cmd, "OFFLINE") == 0) {
    isInteractiveMode = false;
    stepStartTime = millis();
    Serial.println("OK:OFFLINE");
    return;
  }

  if (strncmp(cmd, "RGB", 3) == 0) {
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    int rp, gp, bp, r, g, b;
    if (sscanf(cmd + 3, "%d %d %d %d %d %d", &rp, &gp, &bp, &r, &g, &b) == 6) {
      analogWrite(rp, r);
      analogWrite(gp, g);
      analogWrite(bp, b);
      Serial.println("OK");
    } else {
      Serial.println("ERR:PARSE");
    }
    return;
  }

  if (strncmp(cmd, "MATRIX", 6) == 0) {
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    int b[8];
    if (sscanf(cmd + 6, "%d %d %d %d %d %d %d %d",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &b[6], &b[7]) == 8) {
      uint8_t bmp[8];
      for (int i = 0; i < 8; i++) bmp[i] = (uint8_t)b[i];
      displayMatrixBitmap(bmp);
      Serial.println("OK:MATRIX");
    } else {
      Serial.println("ERR:MATRIX");
    }
    return;
  }

  if (strcmp(cmd, "CLEAR_MATRIX") == 0) {
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    clearMatrix();
    Serial.println("OK:CLEAR");
    return;
  }

  Serial.println("ERR:UNKNOWN");
}

void setup() {
  Serial.begin(115200);

  pinMode(M1_R, OUTPUT);
  pinMode(M1_G, OUTPUT);
  pinMode(M1_B, OUTPUT);
  pinMode(M2_R, OUTPUT);
  pinMode(M2_G, OUTPUT);
  pinMode(M2_B, OUTPUT);

  setM1(0, 0, 0);
  setM2(0, 0, 0);

  initMAX7219();
  displayMatrixBitmap(ICON_CUSTOM);

  stepStartTime = millis();
  lastAnimTick = millis();
}

void loop() {
  uint32_t now = millis();

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIdx > 0) {
        cmdBuffer[cmdIdx] = '\0';
        processSerialCommand(cmdBuffer);
        cmdIdx = 0;
      }
    } else if (cmdIdx < sizeof(cmdBuffer) - 1) {
      cmdBuffer[cmdIdx++] = c;
    }
  }

  if (isInteractiveMode) {
    if (now - lastSerialCmdTime > 15000) {
      isInteractiveMode = false;
      stepStartTime = now;
    }
    return;
  }

  if (now - stepStartTime >= SCHEDULE[currentStepIdx].durationMs) {
    currentStepIdx = (currentStepIdx + 1) % SCHEDULE_COUNT;
    stepStartTime = now;
  }

  if (now - lastAnimTick >= 25) {
    lastAnimTick = now;
    uint8_t effect = SCHEDULE[currentStepIdx].effectType;

    switch (effect) {
      case 0: { // 0. 雙燈同步彩虹流光 + 外星人踏步
        uint8_t r, g, b;
        hsvToRgb(animHue, 1.0f, 1.0f, r, g, b);
        setM1(r, g, b);
        setM2(r, g, b);
        animHue = fmod(animHue + 2.5f, 360.0f);

        uint32_t step = (now / 300) % 2;
        displayMatrixBitmap(step ? ICON_INVADER_A : ICON_INVADER_B);
        break;
      }
      case 1: { // 1. 雙燈互補流光 + 旋轉鑽石
        uint8_t r1, g1, b1, r2, g2, b2;
        float hue2 = fmod(animHue + 180.0f, 360.0f);
        hsvToRgb(animHue, 1.0f, 1.0f, r1, g1, b1);
        hsvToRgb(hue2, 1.0f, 1.0f, r2, g2, b2);
        setM1(r1, g1, b1);
        setM2(r2, g2, b2);
        animHue = fmod(animHue + 2.5f, 360.0f);

        displayMatrixBitmap(ICON_DIAMOND);
        break;
      }
      case 2: { // 2. 警車雙閃爆閃 (70ms) + 警徽雙閃
        uint32_t cycle = (now / 70) % 12;
        if (cycle == 0 || cycle == 2 || cycle == 4) {
          setM1(255, 0, 0);
          setM2(0, 0, 0);
          displayMatrixBitmap(ICON_POLICE);
        } else if (cycle == 6 || cycle == 8 || cycle == 10) {
          setM1(0, 0, 0);
          setM2(0, 0, 255);
          displayMatrixBitmap(ICON_POLICE);
        } else {
          setM1(0, 0, 0);
          setM2(0, 0, 0);
          clearMatrix();
        }
        break;
      }
      case 3: { // 3. 暖色療癒呼吸燈 + 跳動愛心 ❤️
        float breath = (sin(now * 0.0025f) + 1.0f) * 0.5f;
        setM1((uint8_t)(255 * breath), (uint8_t)(90 * breath), (uint8_t)(10 * breath));
        setM2((uint8_t)(255 * breath), (uint8_t)(140 * breath), (uint8_t)(20 * breath));

        uint32_t hStep = (now / 350) % 2;
        displayMatrixBitmap(hStep ? ICON_HEART : ICON_HEART_SM);
        break;
      }
      case 4: { // 4. 極光冷艷呼吸燈 + 微笑眨眼
        float b1 = (sin(now * 0.003f) + 1.0f) * 0.5f;
        float b2 = (cos(now * 0.003f) + 1.0f) * 0.5f;
        setM1(0, (uint8_t)(240 * b1), (uint8_t)(180 * b1));
        setM2((uint8_t)(160 * b2), 0, (uint8_t)(255 * b2));

        uint32_t wStep = (now / 700) % 4;
        displayMatrixBitmap(wStep == 0 ? ICON_WINK : ICON_SMILE);
        break;
      }
      case 5: { // 5. 派對夜店快速跳閃 + 擴散霓虹波紋
        uint32_t beat = (now / 150) % 6;
        const uint8_t colors[6][3] = {
          {255, 0, 100}, {0, 255, 200}, {255, 220, 0},
          {120, 0, 255}, {0, 255, 50},  {255, 50, 0}
        };
        setM1(colors[beat][0], colors[beat][1], colors[beat][2]);
        uint8_t opp = (beat + 3) % 6;
        setM2(colors[opp][0], colors[opp][1], colors[opp][2]);

        uint8_t bar = (now / 100) % 4;
        uint8_t box[8] = {0};
        for (int y = 3 - bar; y <= 4 + bar; y++) {
          for (int x = 3 - bar; x <= 4 + bar; x++) {
            if (x == 3 - bar || x == 4 + bar || y == 3 - bar || y == 4 + bar) {
              box[y] |= (1 << (7 - x));
            }
          }
        }
        displayMatrixBitmap(box);
        break;
      }
      case 6: { // 6. 雙燈交替流水波紋 + 水波律動
        float p1 = (sin(now * 0.005f) + 1.0f) * 0.5f;
        float p2 = (cos(now * 0.005f) + 1.0f) * 0.5f;
        setM1((uint8_t)(255 * p1), (uint8_t)(255 * (1.0f - p1)), 128);
        setM2((uint8_t)(255 * (1.0f - p2)), 128, (uint8_t)(255 * p2));

        uint8_t shift = (now / 120) % 8;
        uint8_t wave[8];
        for (int r = 0; r < 8; r++) {
          wave[r] = (0x33 << ((r + shift) % 4)) | (0x33 >> (8 - ((r + shift) % 4)));
        }
        displayMatrixBitmap(wave);
        break;
      }
    }
  }
}
