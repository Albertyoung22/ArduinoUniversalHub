/*
 * Arduino Universal Hardware Engine (萬能硬體控制韌體)
 * ====================================================
 * 支援透過序列埠 (Serial RPC) 動態控制所有常見 Arduino 配件：
 * - 數位輸出 (LED、繼電器、蜂鳴器)
 * - PWM 類比輸出 (調光、馬達轉速)
 * - 舵機驅動 (Servo 0~180 度)
 * - 複合 RGB LED (共陽/共陰可切換)
 * - MAX7219 8x8 點陣顯示器
 * - 數位/類比感測器自動採樣串流 (光敏、按鈕、電位計、溫度)
 * - 超音波測距 (HC-SR04)
 */

#include <Arduino.h>
#include <Servo.h>

#define MAX_SERVOS 6
struct ServoSlot {
  uint8_t pin;
  Servo servo;
  bool active;
};
ServoSlot servoSlots[MAX_SERVOS];

#define MAX_STREAM_PINS 8
struct StreamSlot {
  uint8_t pin;
  char type; // 'A' or 'D'
  uint16_t intervalMs;
  unsigned long lastSend;
  bool active;
};
StreamSlot streamSlots[MAX_STREAM_PINS];

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

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50); // 縮短序列埠讀取超時至 50ms，杜絕 readStringUntil 阻塞主迴圈
  while (!Serial && millis() < 1500) {}

  for (int i = 0; i < MAX_SERVOS; i++) {
    servoSlots[i].active = false;
  }
  for (int i = 0; i < MAX_STREAM_PINS; i++) {
    streamSlots[i].active = false;
  }

  Serial.println(F("OK:UNIVERSAL_READY"));
}

void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  // 1. PING 心跳包
  if (line == "PING") {
    Serial.println(F("PONG:UNIVERSAL_V1"));
    return;
  }

  // 分割逗點或空格參數 (通用相容空格與逗點協定)
  char buf[128];
  line.toCharArray(buf, sizeof(buf));
  for (int i = 0; buf[i]; i++) {
    if (buf[i] == ' ') buf[i] = ',';
  }
  char* parts[16];
  int count = 0;
  char* tok = strtok(buf, ",");
  while (tok != NULL && count < 16) {
    parts[count++] = tok;
    tok = strtok(NULL, ",");
  }

  if (count == 0) return;
  String cmd = String(parts[0]);
  cmd.toUpperCase();

  // 2. 數位寫入: DWRITE,pin,val (0 或 1)
  if (cmd == "DWRITE" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    uint8_t val = atoi(parts[2]) > 0 ? HIGH : LOW;
    pinMode(pin, OUTPUT);
    digitalWrite(pin, val);
    Serial.print(F("OK:DWRITE,"));
    Serial.print(pin);
    Serial.print(F(","));
    Serial.println(val);
    return;
  }

  // 3. PWM / 類比寫入: AWRITE,pin,val (0~255)
  if (cmd == "AWRITE" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    int val = constrain(atoi(parts[2]), 0, 255);
    pinMode(pin, OUTPUT);
    analogWrite(pin, val);
    Serial.print(F("OK:AWRITE,"));
    Serial.print(pin);
    Serial.print(F(","));
    Serial.println(val);
    return;
  }

  // 4. 舵機控制: SERVO,pin,angle (0~180)
  if (cmd == "SERVO" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    int angle = constrain(atoi(parts[2]), 0, 180);

    // 尋找或註冊舵機槽
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
      Serial.print(F("OK:SERVO,"));
      Serial.print(pin);
      Serial.print(F(","));
      Serial.println(angle);
    } else {
      Serial.println(F("ERR:MAX_SERVOS_REACHED"));
    }
    return;
  }

  // 5. RGB LED: RGB,rPin,gPin,bPin,commonAnode(0|1),r,g,b 或 RGB,rPin,gPin,bPin,r,g,b
  if (cmd == "RGB" && count >= 7) {
    uint8_t rPin = atoi(parts[1]);
    uint8_t gPin = atoi(parts[2]);
    uint8_t bPin = atoi(parts[3]);
    bool isAnode = false;
    uint8_t r = 0, g = 0, b = 0;
    if (count >= 8) {
      isAnode = (atoi(parts[4]) == 1);
      r = constrain(atoi(parts[5]), 0, 255);
      g = constrain(atoi(parts[6]), 0, 255);
      b = constrain(atoi(parts[7]), 0, 255);
    } else {
      r = constrain(atoi(parts[4]), 0, 255);
      g = constrain(atoi(parts[5]), 0, 255);
      b = constrain(atoi(parts[6]), 0, 255);
    }

    pinMode(rPin, OUTPUT);
    pinMode(gPin, OUTPUT);
    pinMode(bPin, OUTPUT);

    analogWrite(rPin, isAnode ? 255 - r : r);
    analogWrite(gPin, isAnode ? 255 - g : g);
    analogWrite(bPin, isAnode ? 255 - b : b);

    Serial.print(F("OK:RGB,"));
    Serial.print(rPin);
    Serial.print(F(","));
    Serial.print(r);
    Serial.print(F(","));
    Serial.print(g);
    Serial.print(F(","));
    Serial.println(b);
    return;
  }

  // 5b. 點陣相容 (MATRIX <b0>...<b7> 或 CLEAR_MATRIX)
  if ((cmd == "MATRIX" || cmd == "CLEAR_MATRIX") && count >= 1) {
    uint8_t din = 12, cs = 8, clk = 7;
    max7219_init(din, cs, clk);
    if (cmd == "CLEAR_MATRIX") {
      for (int r = 1; r <= 8; r++) max7219_write(din, cs, clk, r, 0x00);
      Serial.println(F("OK:CLEAR"));
      return;
    } else if (count >= 9) {
      for (int r = 0; r < 8; r++) {
        uint8_t val = (uint8_t)strtoul(parts[1 + r], NULL, 0);
        max7219_write(din, cs, clk, r + 1, val);
      }
      Serial.println(F("OK:MATRIX"));
      return;
    }
  }

  // 6. MAX7219 全矩陣繪製: MATRIX_ALL,din,cs,clk,b0,b1,b2,b3,b4,b5,b6,b7
  if (cmd == "MATRIX_ALL" && count >= 12) {
    uint8_t din = atoi(parts[1]);
    uint8_t cs = atoi(parts[2]);
    uint8_t clk = atoi(parts[3]);

    max7219_init(din, cs, clk);
    for (int r = 0; r < 8; r++) {
      uint8_t val = (uint8_t)strtoul(parts[4 + r], NULL, 0);
      max7219_write(din, cs, clk, r + 1, val);
    }
    Serial.println(F("OK:MATRIX_ALL"));
    return;
  }

  // 7. MAX7219 單行寫入: MATRIX_ROW,din,cs,clk,row(0~7),val
  if (cmd == "MATRIX_ROW" && count >= 6) {
    uint8_t din = atoi(parts[1]);
    uint8_t cs = atoi(parts[2]);
    uint8_t clk = atoi(parts[3]);
    uint8_t row = constrain(atoi(parts[4]), 0, 7);
    uint8_t val = (uint8_t)strtoul(parts[5], NULL, 0);

    max7219_write(din, cs, clk, row + 1, val);
    Serial.println(F("OK:MATRIX_ROW"));
    return;
  }

  // 8. MAX7219 清除: MATRIX_CLEAR,din,cs,clk
  if (cmd == "MATRIX_CLEAR" && count >= 4) {
    uint8_t din = atoi(parts[1]);
    uint8_t cs = atoi(parts[2]);
    uint8_t clk = atoi(parts[3]);
    max7219_init(din, cs, clk);
    for (int r = 1; r <= 8; r++) {
      max7219_write(din, cs, clk, r, 0x00);
    }
    Serial.println(F("OK:MATRIX_CLEAR"));
    return;
  }

  // 9. 感測器定時串流: STREAM,pin,type(A|D),enable(0|1),intervalMs
  if (cmd == "STREAM" && count >= 5) {
    uint8_t pin = atoi(parts[1]);
    char type = parts[2][0]; // 'A' or 'D'
    bool enable = atoi(parts[3]) > 0;
    uint16_t interval = (uint16_t)max(50, atoi(parts[4]));

    int slot = -1;
    for (int i = 0; i < MAX_STREAM_PINS; i++) {
      if (streamSlots[i].active && streamSlots[i].pin == pin && streamSlots[i].type == type) {
        slot = i;
        break;
      }
    }
    if (!enable) {
      if (slot != -1) streamSlots[slot].active = false;
      Serial.print(F("OK:STREAM_OFF,"));
      Serial.println(pin);
      return;
    }

    if (slot == -1) {
      for (int i = 0; i < MAX_STREAM_PINS; i++) {
        if (!streamSlots[i].active) {
          slot = i;
          break;
        }
      }
    }

    if (slot != -1) {
      streamSlots[slot].pin = pin;
      streamSlots[slot].type = type;
      streamSlots[slot].intervalMs = interval;
      streamSlots[slot].lastSend = 0;
      streamSlots[slot].active = true;
      if (type == 'D') pinMode(pin, INPUT_PULLUP);
      Serial.print(F("OK:STREAM_ON,"));
      Serial.println(pin);
    } else {
      Serial.println(F("ERR:MAX_STREAMS_REACHED"));
    }
    return;
  }

  // 10. 單次讀取: READ,pin,type(A|D)
  if (cmd == "READ" && count >= 3) {
    uint8_t pin = atoi(parts[1]);
    char type = parts[2][0];
    int val = 0;
    if (type == 'A' || type == 'a') {
      val = analogRead(pin);
    } else {
      pinMode(pin, INPUT_PULLUP);
      val = digitalRead(pin);
    }
    Serial.print(F("READ_DATA,"));
    Serial.print(pin);
    Serial.print(F(","));
    Serial.println(val);
    return;
  }

  // 11. 超音波測距: SONAR,trigPin,echoPin
  if (cmd == "SONAR" && count >= 3) {
    uint8_t trig = atoi(parts[1]);
    uint8_t echo = atoi(parts[2]);
    pinMode(trig, OUTPUT);
    pinMode(echo, INPUT);

    digitalWrite(trig, LOW);
    delayMicroseconds(2);
    digitalWrite(trig, HIGH);
    delayMicroseconds(10);
    digitalWrite(trig, LOW);

    long duration = pulseIn(echo, HIGH, 30000); // 30ms 超時 (約 5 公尺)
    int distance = (duration == 0) ? -1 : (int)(duration * 0.034 / 2);

    Serial.print(F("SONAR_RES,"));
    Serial.print(trig);
    Serial.print(F(","));
    Serial.println(distance);
    return;
  }

  // 12. 蜂鳴器發聲: TONE,pin,freq,duration
  if (cmd == "TONE" && count >= 4) {
    uint8_t pin = atoi(parts[1]);
    unsigned int freq = atoi(parts[2]);
    unsigned long dur = atoi(parts[3]);
    tone(pin, freq, dur);
    Serial.println(F("OK:TONE"));
    return;
  }

  Serial.println(F("ERR:UNKNOWN_CMD"));
}

void loop() {
  // 處理序列埠指令
  while (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }

  // 處理自動串流感測器讀取
  unsigned long now = millis();
  for (int i = 0; i < MAX_STREAM_PINS; i++) {
    if (streamSlots[i].active && (now - streamSlots[i].lastSend >= streamSlots[i].intervalMs)) {
      streamSlots[i].lastSend = now;
      int val = 0;
      if (streamSlots[i].type == 'A') {
        val = analogRead(streamSlots[i].pin);
      } else {
        val = digitalRead(streamSlots[i].pin);
      }
      Serial.print(F("STREAM_DATA,"));
      Serial.print(streamSlots[i].pin);
      Serial.print(F(","));
      Serial.println(val);
    }
  }
}

