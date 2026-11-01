/*
 * MAX7219 8x8 LED Dot Matrix Test Animation
 * =========================================
 * Wiring:
 *   DIN  -> Arduino Pin 12
 *   CS   -> Arduino Pin 8
 *   CLK  -> Arduino Pin 7
 *   VCC  -> +5V
 *   GND  -> GND
 */

#include <Arduino.h>

const uint8_t PIN_DIN = 12;
const uint8_t PIN_CS  = 8;
const uint8_t PIN_CLK = 7;

// MAX7219 Register addresses
#define REG_NOOP        0x00
#define REG_DIGIT0      0x01
#define REG_DIGIT1      0x02
#define REG_DIGIT2      0x03
#define REG_DIGIT3      0x04
#define REG_DIGIT4      0x05
#define REG_DIGIT5      0x06
#define REG_DIGIT6      0x07
#define REG_DIGIT7      0x08
#define REG_DECODEMODE  0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

void writeRegister(uint8_t reg, uint8_t data) {
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

  // 初始化序列
  writeRegister(REG_DISPLAYTEST, 0x00); // 關閉測試模式
  writeRegister(REG_SCANLIMIT,   0x07); // 掃描 8 行全開 (0~7)
  writeRegister(REG_DECODEMODE,  0x00); // 不解碼 (原始 8x8 點陣模式)
  writeRegister(REG_INTENSITY,   0x05); // 亮度 (0x00 最暗 ~ 0x0F 最亮，預設適中 0x05)
  writeRegister(REG_SHUTDOWN,    0x01); // 啟動晶片正常工作
}

void displayBitmap(const uint8_t bitmap[8]) {
  for (uint8_t row = 0; row < 8; row++) {
    writeRegister(REG_DIGIT0 + row, bitmap[row]);
  }
}

void clearDisplay() {
  for (uint8_t row = 0; row < 8; row++) {
    writeRegister(REG_DIGIT0 + row, 0x00);
  }
}

// 8x8 像素圖案資料表 (二進位圖形)
// 1. 跳動大愛心
const uint8_t HEART_BIG[8] = {
  0b00000000,
  0b01100110,
  0b11111111,
  0b11111111,
  0b11111111,
  0b01111110,
  0b00111100,
  0b00011000
};

// 2. 跳動小愛心
const uint8_t HEART_SMALL[8] = {
  0b00000000,
  0b00000000,
  0b00100100,
  0b01111110,
  0b01111110,
  0b00111100,
  0b00011000,
  0b00000000
};

// 3. 笑臉 (張眼)
const uint8_t SMILE_OPEN[8] = {
  0b00111100,
  0b01000010,
  0b10100101,
  0b10000001,
  0b10100101,
  0b10011001,
  0b01000010,
  0b00111100
};

// 4. 笑臉 (單眼眨眼 Wink)
const uint8_t SMILE_WINK[8] = {
  0b00111100,
  0b01000010,
  0b10100001,
  0b10000111,
  0b10100001,
  0b10011001,
  0b01000010,
  0b00111100
};

// 5. 外星人侵略者 (Alien Invader 姿態 A)
const uint8_t INVADER_A[8] = {
  0b00011000,
  0b00111100,
  0b01111110,
  0b11011011,
  0b11111111,
  0b00100100,
  0b01011010,
  0b10100101
};

// 6. 外星人侵略者 (Alien Invader 姿態 B)
const uint8_t INVADER_B[8] = {
  0b00011000,
  0b00111100,
  0b01111110,
  0b11011011,
  0b11111111,
  0b01011010,
  0b10000001,
  0b01000010
};

// 7. 數字 3, 2, 1
const uint8_t NUM_3[8] = {
  0b00111100,
  0b01000010,
  0b00000010,
  0b00011100,
  0b00000010,
  0b00000010,
  0b01000010,
  0b00111100
};

const uint8_t NUM_2[8] = {
  0b00111100,
  0b01000010,
  0b00000010,
  0b00000100,
  0b00001000,
  0b00010000,
  0b01111110,
  0b00000000
};

const uint8_t NUM_1[8] = {
  0b00011000,
  0b00111000,
  0b00011000,
  0b00011000,
  0b00011000,
  0b00011000,
  0b00111100,
  0b00000000
};

// 8. 讚 (Thumbs Up)
const uint8_t THUMBS_UP[8] = {
  0b00000100,
  0b00001110,
  0b00001110,
  0b01111110,
  0b11111110,
  0b11111110,
  0b01111110,
  0b00000000
};

void setup() {
  Serial.begin(115200);
  initMAX7219();
  clearDisplay();
  Serial.println("MAX7219 8x8 Matrix Initialized OK!");
}

void loop() {
  // 1. 動態跳動愛心 (連跳 4 次)
  for (int i = 0; i < 4; i++) {
    displayBitmap(HEART_BIG);
    delay(280);
    displayBitmap(HEART_SMALL);
    delay(280);
  }
  delay(300);

  // 2. 笑臉眨眼動畫
  displayBitmap(SMILE_OPEN);
  delay(1200);
  displayBitmap(SMILE_WINK);
  delay(300);
  displayBitmap(SMILE_OPEN);
  delay(1200);

  // 3. 倒數 3 -> 2 -> 1
  displayBitmap(NUM_3);
  delay(700);
  displayBitmap(NUM_2);
  delay(700);
  displayBitmap(NUM_1);
  delay(700);
  displayBitmap(THUMBS_UP);
  delay(1000);

  // 4. 外星人踏步動畫
  for (int i = 0; i < 6; i++) {
    displayBitmap(INVADER_A);
    delay(220);
    displayBitmap(INVADER_B);
    delay(220);
  }
  delay(400);

  // 5. 擴散波紋方塊
  for (int r = 0; r < 4; r++) {
    uint8_t box[8] = {0};
    for (int y = 3 - r; y <= 4 + r; y++) {
      for (int x = 3 - r; x <= 4 + r; x++) {
        if (x == 3 - r || x == 4 + r || y == 3 - r || y == 4 + r) {
          box[y] |= (1 << (7 - x));
        }
      }
    }
    displayBitmap(box);
    delay(120);
  }
  delay(400);
}

