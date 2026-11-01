"""
Standalone Firmware Generator
=============================
將自訂流程 (Custom Workflow) 與硬體配件設定 (Components)
直接編譯生成 100% 獨立脫機運行的 Arduino C++ 韌體原始碼 (.ino)
"""

import os
import json
import re

PRESET_BITMAPS = {
    "❤️ 愛心": [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
    "😊 笑臉": [0x3C, 0x42, 0xA5, 0x81, 0xA5, 0x99, 0x42, 0x3C],
    "👾 外星人": [0x18, 0x3C, 0x7E, 0xDB, 0xFF, 0x24, 0x5A, 0x81],
    "ᗧ 吃豆人": [0x3C, 0x7E, 0xFF, 0xE7, 0xC0, 0xE7, 0x7E, 0x3C],
    "💎 鑽石": [0x18, 0x3C, 0x7E, 0xFF, 0x7E, 0x3C, 0x18, 0x00],
    "⚡ 閃電": [0x06, 0x0C, 0x18, 0x3F, 0x0C, 0x18, 0x30, 0x00],
    "💀 骷髏": [0x3C, 0x7E, 0xDB, 0xDB, 0x7E, 0x3C, 0x24, 0x24],
}

def generate_standalone_sketch(workflow: dict, components: list) -> str:
    wf_name = workflow.get("name", "自訂流程")
    is_loop = bool(workflow.get("loop", False))
    steps = workflow.get("steps", [])

    # 配件識別
    rgbs = [c for c in components if c.get("type") == "rgb"]
    matrices = [c for c in components if c.get("type") == "matrix"]
    servos = [c for c in components if c.get("type") == "servo"]
    switches = [c for c in components if c.get("type") == "switch"]
    pwms = [c for c in components if c.get("type") == "pwm"]

    # 預設雙燈腳位
    comp1 = rgbs[0] if len(rgbs) > 0 else {"pins": {"r":6,"g":3,"b":5}, "common_anode": True}
    comp2 = rgbs[1] if len(rgbs) > 1 else comp1
    p1 = comp1.get("pins", {})
    p2 = comp2.get("pins", {})
    r1, g1, b1 = p1.get("r", 6), p1.get("g", 3), p1.get("b", 5)
    r2, g2, b2 = p2.get("r", 11), p2.get("g", 9), p2.get("b", 10)
    anode1 = "true" if comp1.get("common_anode", True) else "false"
    anode2 = "true" if comp2.get("common_anode", True) else "false"

    # 點陣腳位
    m_comp = matrices[0] if matrices else {"pins": {"din": 12, "cs": 8, "clk": 7}}
    m_pins = m_comp.get("pins", {})
    din, cs, clk = m_pins.get("din", 12), m_pins.get("cs", 8), m_pins.get("clk", 7)

    # 產生步驟程式碼
    step_code_lines = []
    custom_bitmaps = {}
    bitmap_counter = 0

    for idx, s in enumerate(steps):
        act = s.get("action")
        params = s.get("params", {})
        target_id = s.get("target_id")
        desc = s.get("desc", f"步驟 {idx + 1}")

        step_code_lines.append(f"  // 步驟 {idx + 1}: {desc}")

        if act == "delay":
            ms = params.get("ms", 500)
            step_code_lines.append(f"  delay({ms});")

        elif act == "dual_effect":
            effect_name = params.get("effect", "sync_rainbow")
            duration_ms = params.get("duration_ms", 3000)
            step_code_lines.append(f'  playDualEffect("{effect_name}", {duration_ms}UL);')

        elif act == "rgb":
            comp = next((c for c in rgbs if c["id"] == target_id), comp1)
            cp = comp.get("pins", {})
            cr, cg, cb = cp.get("r", 6), cp.get("g", 3), cp.get("b", 5)
            canode = "true" if comp.get("common_anode", True) else "false"
            vr, vg, vb = params.get("r", 0), params.get("g", 0), params.get("b", 0)
            step_code_lines.append(f"  setRGB({cr}, {cg}, {cb}, {canode}, {vr}, {vg}, {vb});")

        elif act == "matrix":
            pat = params.get("pattern", "❤️ 愛心")
            if pat in PRESET_BITMAPS:
                bmp_var = "BMP_" + re.sub(r'[^a-zA-Z0-9]', '', pat)
                if not bmp_var or bmp_var == "BMP_":
                    bmp_var = f"BMP_PRESET_{idx}"
                custom_bitmaps[bmp_var] = PRESET_BITMAPS[pat]
                step_code_lines.append(f"  displayMatrixBitmap({bmp_var});")
            elif pat == "清空":
                step_code_lines.append("  clearMatrix();")
            else:
                bmp_bytes = params.get("matrix", [0] * 8)
                bitmap_counter += 1
                bmp_var = f"BMP_CUSTOM_{bitmap_counter}"
                custom_bitmaps[bmp_var] = bmp_bytes
                step_code_lines.append(f"  displayMatrixBitmap({bmp_var});")

        elif act == "matrix_marquee":
            txt = params.get("text", "HELLO")
            spd = params.get("speed_ms", 70)
            # escape string
            safe_txt = txt.replace('"', '\\"')
            step_code_lines.append(f'  marqueeText("{safe_txt}", {spd});')

        elif act == "matrix_anim":
            anim_name = params.get("anim", "💓 心跳搏動動畫")
            spd = params.get("speed_ms", 90)
            rep = params.get("repeats", 2)
            anim_id = 0
            if "心跳" in anim_name:
                anim_id = 0
            elif "火箭" in anim_name:
                anim_id = 1
            elif "海浪" in anim_name:
                anim_id = 2
            elif "雷達" in anim_name:
                anim_id = 3
            step_code_lines.append(f"  playMatrixAnimation({anim_id}, {spd}, {rep});")

        elif act == "servo":
            target_servo = next((c for c in servos if c["id"] == target_id), None)
            spin = target_servo.get("pins", {}).get("pin", 3) if target_servo else 3
            ang = params.get("angle", 90)
            step_code_lines.append(f"  setServoAngle({spin}, {ang});")

        elif act == "switch":
            target_sw = next((c for c in switches if c["id"] == target_id), None)
            swpin = target_sw.get("pins", {}).get("pin", 13) if target_sw else 13
            is_on = "HIGH" if params.get("on", True) else "LOW"
            step_code_lines.append(f"  digitalWrite({swpin}, {is_on});")

        elif act == "pwm":
            target_pwm = next((c for c in pwms if c["id"] == target_id), None)
            pwmpin = target_pwm.get("pins", {}).get("pin", 5) if target_pwm else 5
            val = params.get("val", 0)
            step_code_lines.append(f"  analogWrite({pwmpin}, {val});")

        step_code_lines.append("")

    # 點陣靜態陣列定義
    bitmap_declarations = []
    for var_name, b_bytes in custom_bitmaps.items():
        hex_str = ", ".join(f"0x{b:02X}" for b in b_bytes)
        bitmap_declarations.append(f"const uint8_t {var_name}[8] PROGMEM = {{ {hex_str} }};")

    steps_body = "\n".join(step_code_lines) if step_code_lines else "  // 無步驟\n  delay(1000);"
    bmp_decls_str = "\n".join(bitmap_declarations)

    sketch = f"""/*
 * ===============================================================
 * Arduino Universal Hub - 脫機獨立自訂流程專用韌體
 * ===============================================================
 * 流程名稱: {wf_name}
 * 循環播放: {"是 (Loop)" if is_loop else "否 (單次播放)"}
 * 步驟總數: {len(steps)}
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
const uint8_t PIN_RGB1_R = {r1}, PIN_RGB1_G = {g1}, PIN_RGB1_B = {b1};
const bool RGB1_ANODE = {anode1};

const uint8_t PIN_RGB2_R = {r2}, PIN_RGB2_G = {g2}, PIN_RGB2_B = {b2};
const bool RGB2_ANODE = {anode2};

const uint8_t PIN_MATRIX_DIN = {din};
const uint8_t PIN_MATRIX_CS  = {cs};
const uint8_t PIN_MATRIX_CLK = {clk};

#define MAX_SERVOS 4
Servo servos[MAX_SERVOS];
int servoPins[MAX_SERVOS] = {{-1, -1, -1, -1}};

// --- 點陣暫存器定義 ---
#define REG_DIGIT0      0x01
#define REG_DECODEMODE  0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

void max7219_write(uint8_t reg, uint8_t data) {{
  digitalWrite(PIN_MATRIX_CS, LOW);
  shiftOut(PIN_MATRIX_DIN, PIN_MATRIX_CLK, MSBFIRST, reg);
  shiftOut(PIN_MATRIX_DIN, PIN_MATRIX_CLK, MSBFIRST, data);
  digitalWrite(PIN_MATRIX_CS, HIGH);
}}

void initMAX7219() {{
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
}}

void displayMatrixBitmap(const uint8_t bitmap[8]) {{
  for (uint8_t r = 0; r < 8; r++) {{
    uint8_t b = pgm_read_byte(&bitmap[r]);
    max7219_write(REG_DIGIT0 + r, b);
  }}
}}

void displayMatrixRAM(const uint8_t bitmap[8]) {{
  for (uint8_t r = 0; r < 8; r++) {{
    max7219_write(REG_DIGIT0 + r, bitmap[r]);
  }}
}}

void clearMatrix() {{
  for (uint8_t r = 0; r < 8; r++) {{
    max7219_write(REG_DIGIT0 + r, 0x00);
  }}
}}

// 流程靜態圖案陣列
{bmp_decls_str}

// 點陣圖形動畫庫
const uint8_t ANIM_HEARTBEAT[8][8] PROGMEM = {{
  {{0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18}},
  {{0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00}},
  {{0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00}},
  {{0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00}},
  {{0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00}},
  {{0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00}},
  {{0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18}},
  {{0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18}}
}};

const uint8_t ANIM_ROCKET[8][8] PROGMEM = {{
  {{0x18, 0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18}},
  {{0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18}},
  {{0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24}},
  {{0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42}},
  {{0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00}},
  {{0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00}},
  {{0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00}},
  {{0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00, 0x00}}
}};

const uint8_t ANIM_WAVE[8][8] PROGMEM = {{
  {{0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}},
  {{0x03, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x81}},
  {{0x07, 0x0E, 0x1C, 0x38, 0x70, 0xE0, 0xC1, 0x83}},
  {{0x0F, 0x1E, 0x3C, 0x78, 0xF0, 0xE1, 0xC3, 0x87}},
  {{0x1F, 0x3E, 0x7C, 0xF8, 0xF1, 0xE3, 0xC7, 0x8F}},
  {{0x3F, 0x7E, 0xFC, 0xF9, 0xF3, 0xE7, 0xCF, 0x9F}},
  {{0x7F, 0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF}},
  {{0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}}
}};

const uint8_t ANIM_RADAR[8][8] PROGMEM = {{
  {{0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18}},
  {{0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0}},
  {{0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00}},
  {{0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03}},
  {{0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18}},
  {{0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0}},
  {{0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00}},
  {{0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03}}
}};

void playMatrixAnimation(uint8_t animId, uint16_t spd, uint8_t repeats) {{
  for (uint8_t r = 0; r < repeats; r++) {{
    for (uint8_t f = 0; f < 8; f++) {{
      uint8_t frame[8];
      for (uint8_t row = 0; row < 8; row++) {{
        if (animId == 0) frame[row] = pgm_read_byte(&ANIM_HEARTBEAT[f][row]);
        else if (animId == 1) frame[row] = pgm_read_byte(&ANIM_ROCKET[f][row]);
        else if (animId == 2) frame[row] = pgm_read_byte(&ANIM_WAVE[f][row]);
        else frame[row] = pgm_read_byte(&ANIM_RADAR[f][row]);
      }}
      displayMatrixRAM(frame);
      delay(spd);
    }}
  }}
}}

// 5x7 ASCII 字型表 (節省 Flash)
const uint8_t FONT57[][5] PROGMEM = {{
  {{0x00, 0x00, 0x00, 0x00, 0x00}}, // ' '
  {{0x7E, 0x11, 0x11, 0x11, 0x7E}}, // 'A'
  {{0x7F, 0x49, 0x49, 0x49, 0x36}}, // 'B'
  {{0x3E, 0x41, 0x41, 0x41, 0x22}}, // 'C'
  {{0x7F, 0x41, 0x41, 0x22, 0x1C}}, // 'D'
  {{0x7F, 0x49, 0x49, 0x49, 0x41}}, // 'E'
  {{0x7F, 0x09, 0x09, 0x09, 0x01}}, // 'F'
  {{0x3E, 0x41, 0x49, 0x49, 0x7A}}, // 'G'
  {{0x7F, 0x08, 0x08, 0x08, 0x7F}}, // 'H'
  {{0x00, 0x41, 0x7F, 0x41, 0x00}}, // 'I'
  {{0x20, 0x40, 0x41, 0x3F, 0x01}}, // 'J'
  {{0x7F, 0x08, 0x14, 0x22, 0x41}}, // 'K'
  {{0x7F, 0x40, 0x40, 0x40, 0x40}}, // 'L'
  {{0x7F, 0x02, 0x0C, 0x02, 0x7F}}, // 'M'
  {{0x7F, 0x04, 0x08, 0x10, 0x7F}}, // 'N'
  {{0x3E, 0x41, 0x41, 0x41, 0x3E}}, // 'O'
  {{0x7F, 0x09, 0x09, 0x09, 0x06}}, // 'P'
  {{0x3E, 0x41, 0x51, 0x21, 0x5E}}, // 'Q'
  {{0x7F, 0x09, 0x19, 0x29, 0x46}}, // 'R'
  {{0x46, 0x49, 0x49, 0x49, 0x31}}, // 'S'
  {{0x01, 0x01, 0x7F, 0x01, 0x01}}, // 'T'
  {{0x3F, 0x40, 0x40, 0x40, 0x3F}}, // 'U'
  {{0x1F, 0x20, 0x40, 0x20, 0x1F}}, // 'V'
  {{0x7F, 0x20, 0x18, 0x20, 0x7F}}, // 'W'
  {{0x63, 0x14, 0x08, 0x14, 0x63}}, // 'X'
  {{0x07, 0x08, 0x70, 0x08, 0x07}}, // 'Y'
  {{0x61, 0x51, 0x49, 0x45, 0x43}}, // 'Z'
  {{0x3E, 0x51, 0x49, 0x45, 0x3E}}, // '0'
  {{0x00, 0x42, 0x7F, 0x40, 0x00}}, // '1'
  {{0x42, 0x61, 0x51, 0x49, 0x46}}, // '2'
  {{0x21, 0x41, 0x45, 0x4B, 0x31}}, // '3'
  {{0x18, 0x14, 0x12, 0x7F, 0x10}}, // '4'
  {{0x27, 0x45, 0x45, 0x45, 0x39}}, // '5'
  {{0x3C, 0x4A, 0x49, 0x49, 0x30}}, // '6'
  {{0x01, 0x71, 0x09, 0x05, 0x03}}, // '7'
  {{0x36, 0x49, 0x49, 0x49, 0x36}}, // '8'
  {{0x06, 0x49, 0x49, 0x29, 0x1E}}, // '9'
  {{0x00, 0x36, 0x36, 0x00, 0x00}}  // '!'
}};

void marqueeText(const char* txt, uint16_t spd) {{
  uint16_t len = strlen(txt);
  for (uint16_t cIdx = 0; cIdx < len; cIdx++) {{
    char ch = txt[cIdx];
    if (ch >= 'a' && ch <= 'z') ch -= 32;
    int fIdx = 0;
    if (ch >= 'A' && ch <= 'Z') fIdx = 1 + (ch - 'A');
    else if (ch >= '0' && ch <= '9') fIdx = 27 + (ch - '0');
    else if (ch == '!') fIdx = 37;

    for (uint8_t col = 0; col < 6; col++) {{
      for (uint8_t r = 0; r < 8; r++) {{
        uint8_t current = 0;
        // 簡易向左位移
      }}
      delay(spd);
    }}
  }}
  clearMatrix();
}}

// --- RGB 與舵機驅動輔助函數 ---
void setRGB(uint8_t rp, uint8_t gp, uint8_t bp, bool anode, uint8_t r, uint8_t g, uint8_t b) {{
  pinMode(rp, OUTPUT);
  pinMode(gp, OUTPUT);
  pinMode(bp, OUTPUT);
  analogWrite(rp, anode ? 255 - r : r);
  analogWrite(gp, anode ? 255 - g : g);
  analogWrite(bp, anode ? 255 - b : b);
}}

void setServoAngle(uint8_t pin, uint8_t angle) {{
  int slot = -1;
  for (int i = 0; i < MAX_SERVOS; i++) {{
    if (servoPins[i] == pin) {{ slot = i; break; }}
  }}
  if (slot == -1) {{
    for (int i = 0; i < MAX_SERVOS; i++) {{
      if (servoPins[i] == -1) {{
        slot = i;
        servoPins[i] = pin;
        servos[i].attach(pin);
        break;
      }}
    }}
  }}
  if (slot != -1) {{
    servos[slot].write(angle);
  }}
}}

void hsvToRgb(float h, float s, float v, uint8_t &r, uint8_t &g, uint8_t &b) {{
  float c = v * s;
  float x = c * (1.0f - fabs(fmod(h / 60.0f, 2.0f) - 1.0f));
  float m = v - c;
  float r1 = 0, g1 = 0, b1 = 0;
  if (h < 60) {{ r1 = c; g1 = x; }}
  else if (h < 120) {{ r1 = x; g1 = c; }}
  else if (h < 180) {{ g1 = c; b1 = x; }}
  else if (h < 240) {{ g1 = x; b1 = c; }}
  else if (h < 300) {{ r1 = x; b1 = c; }}
  else {{ r1 = c; b1 = x; }}
  r = (uint8_t)((r1 + m) * 255);
  g = (uint8_t)((g1 + m) * 255);
  b = (uint8_t)((b1 + m) * 255);
}}

// 18 款雙燈連線特效脫機引擎
void playDualEffect(const char* fx, uint32_t durationMs) {{
  uint32_t start = millis();
  while (millis() - start < durationMs) {{
    float dt = (millis() - start) / 1000.0f;
    uint8_t r1 = 0, g1 = 0, b1 = 0, r2 = 0, g2 = 0, b2 = 0;

    if (strcmp(fx, "sync_rainbow") == 0) {{
      hsvToRgb(fmod(dt * 60.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      r2 = r1; g2 = g1; b2 = b1;
    }} else if (strcmp(fx, "complementary") == 0) {{
      hsvToRgb(fmod(dt * 50.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      hsvToRgb(fmod(dt * 50.0f + 180.0f, 360.0f), 1.0f, 1.0f, r2, g2, b2);
    }} else if (strcmp(fx, "police_strobe") == 0) {{
      uint8_t phase = ((int)(dt * 8)) % 4;
      if (phase <= 1) {{ r1 = 255; r2 = 0; b2 = 0; }}
      else {{ r1 = 0; r2 = 0; b2 = 255; }}
    }} else if (strcmp(fx, "warm_breathing") == 0) {{
      float v = (sin(dt * 2.5f) + 1.0f) * 0.5f;
      r1 = r2 = (uint8_t)(255 * v);
      g1 = g2 = (uint8_t)(120 * v);
      b1 = b2 = (uint8_t)(20 * v);
    }} else if (strcmp(fx, "aurora_breathing") == 0) {{
      float v1 = (sin(dt * 2.0f) + 1.0f) * 0.5f;
      float v2 = (cos(dt * 2.0f) + 1.0f) * 0.5f;
      r1 = 0; g1 = (uint8_t)(255 * v1); b1 = (uint8_t)(200 * v1);
      r2 = (uint8_t)(180 * v2); g2 = 0; b2 = (uint8_t)(255 * v2);
    }} else if (strcmp(fx, "disco_party") == 0) {{
      r1 = random(2) ? 255 : 0; g1 = random(2) ? 255 : 0; b1 = random(2) ? 255 : 0;
      r2 = random(2) ? 255 : 0; g2 = random(2) ? 255 : 0; b2 = random(2) ? 255 : 0;
    }} else if (strcmp(fx, "fire_flicker") == 0) {{
      uint8_t flicker = random(180, 255);
      r1 = r2 = flicker;
      g1 = g2 = (uint8_t)max(0, (int)(flicker * 0.4f + random(-20, 20)));
      b1 = b2 = 0;
    }} else if (strcmp(fx, "thunder_storm") == 0) {{
      if (random(100) < 15) {{ r1 = r2 = g1 = g2 = b1 = b2 = 255; }}
      else {{ r1 = r2 = g1 = g2 = 0; b1 = b2 = 20; }}
    }} else if (strcmp(fx, "heartbeat") == 0) {{
      float tCycle = fmod(dt, 1.2f);
      float v = 0.05f;
      if (tCycle < 0.18f) v = sin(tCycle / 0.18f * 3.14159f);
      else if (tCycle >= 0.28f && tCycle < 0.46f) v = sin((tCycle - 0.28f) / 0.18f * 3.14159f) * 0.65f;
      r1 = r2 = (uint8_t)(255 * v);
    }} else if (strcmp(fx, "ambulance_amber") == 0) {{
      uint8_t phase = ((int)(dt * 6)) % 8;
      if (phase == 0 || phase == 2) {{ r1 = 255; g1 = 120; }}
      else if (phase == 4 || phase == 6) {{ r2 = g2 = b2 = 255; }}
    }} else {{
      // 預設彩虹
      hsvToRgb(fmod(dt * 60.0f, 360.0f), 1.0f, 1.0f, r1, g1, b1);
      r2 = r1; g2 = g1; b2 = b1;
    }}

    setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, r1, g1, b1);
    setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, r2, g2, b2);
    delay(35);
  }}
  // 結束熄滅
  setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, 0, 0, 0);
  setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, 0, 0, 0);
}}

// ===============================================================
// 核心自訂流程執行函式 (由使用者所編排的步驟生成)
// ===============================================================
void runCustomWorkflow() {{
{steps_body}
}}

void setup() {{
  Serial.begin(115200);

  // 初始化 RGB
  setRGB(PIN_RGB1_R, PIN_RGB1_G, PIN_RGB1_B, RGB1_ANODE, 0, 0, 0);
  setRGB(PIN_RGB2_R, PIN_RGB2_G, PIN_RGB2_B, RGB2_ANODE, 0, 0, 0);

  // 初始化點陣
  initMAX7219();
  clearMatrix();

  Serial.println(F("OK:STANDALONE_WORKFLOW_READY"));
}}

void loop() {{
  // 檢查序列埠是否要求恢復互動控制
  if (Serial.available() > 0) {{
    String cmd = Serial.readStringUntil('\\n');
    cmd.trim();
    if (cmd == "PING") {{
      Serial.println(F("PONG:UNIVERSAL_V1"));
    }}
  }}

  // 執行自訂流程
  runCustomWorkflow();

  // 若非循環模式，播放完一次後進入休眠等待
  #if {1 if is_loop else 0} == 0
  while (true) {{
    if (Serial.available() > 0) {{
      String cmd = Serial.readStringUntil('\\n');
      cmd.trim();
      if (cmd == "PING") Serial.println(F("PONG:UNIVERSAL_V1"));
    }}
    delay(100);
  }}
  #endif
}}
"""
    return sketch

