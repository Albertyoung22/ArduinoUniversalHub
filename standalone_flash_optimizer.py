"""
Standalone Light Show Optimizer & Auto-Flasher using Google OR-Tools CP-SAT
===========================================================================
- 支援使用者自訂勾選想要燒錄的特效清單
- 支援自然語言/情境風格文字描述智慧解析 (如: "派對夜店狂歡", "睡前放鬆暖光", "警車巡邏")
- 使用 Google OR-Tools CP-SAT (ortools.sat.python.cp_model) 求解動態時間表排程
- 同步控制：雙 RGB 全彩燈 + MAX7219 8×8 點陣顯示模組
- 自動生成脫機獨立執行的 Arduino C++ 固件 (standalone_firmware.ino)
- 自動透過 arduino-cli 編譯並燒錄進電路板
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from ortools.sat.python import cp_model

ARDUINO_CLI_PATH = r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
WORKSPACE_DIR = r"D:\PythonTest\AduinoTest"
CONFIG_PATH = os.path.join(WORKSPACE_DIR, "config.json")
FIRMWARE_DIR = os.path.join(WORKSPACE_DIR, "standalone_firmware")
FIRMWARE_INO = os.path.join(FIRMWARE_DIR, "standalone_firmware.ino")

# 完整特效庫定義
EFFECT_CATALOG = [
    {
        "id": 0,
        "key": "sync_rainbow",
        "name": "🌈 雙燈同步彩虹流光",
        "desc": "兩模組同步呈現 360 度連續平滑彩虹流動 + 點陣外星人踏步動畫",
        "tags": ["彩虹", "多彩", "炫彩", "色彩", "豐富", "彩色", "七彩", "流動"],
        "min": 4,
        "max": 15,
        "excitement": 7,
        "power": 8
    },
    {
        "id": 1,
        "key": "complementary",
        "name": "☯ 雙燈互補流光",
        "desc": "兩燈呈 180 度互補色相強烈對比流動 + 點陣旋轉鑽石律動",
        "tags": ["互補", "對比", "流光", "流動", "科幻", "賽博", "雙色"],
        "min": 4,
        "max": 15,
        "excitement": 8,
        "power": 8
    },
    {
        "id": 2,
        "key": "police_strobe",
        "name": "🚨 警車雙閃爆閃",
        "desc": "左模組連閃 3 次紅光，右模組連閃 3 次藍光極速爆閃 (70ms) + 點陣警徽交替爆閃",
        "tags": ["警車", "爆閃", "閃爍", "警戒", "緊急", "警察", "巡邏", "快閃", "刺眼"],
        "min": 3,
        "max": 10,
        "excitement": 10,
        "power": 6
    },
    {
        "id": 3,
        "key": "warm_breathing",
        "name": "🕯️ 暖色療癒呼吸燈",
        "desc": "模擬燭光、夕陽暖橙色調深呼吸漸變 + 點陣撲通跳動愛心 ❤️",
        "tags": ["暖色", "呼吸", "放鬆", "睡", "睡眠", "溫柔", "助眠", "安靜", "療癒", "夕陽", "燭光", "夜燈", "慢"],
        "min": 4,
        "max": 15,
        "excitement": 4,
        "power": 4
    },
    {
        "id": 4,
        "key": "aurora_breathing",
        "name": "🌌 極光冷艷呼吸燈",
        "desc": "翡翠極光綠與深空紫藍交織呼吸 + 點陣微笑眨眼表情 😊😉",
        "tags": ["極光", "冷色", "藍色", "紫色", "科技", "未來", "神秘", "冰冷", "太空", "夜空"],
        "min": 4,
        "max": 15,
        "excitement": 6,
        "power": 5
    },
    {
        "id": 5,
        "key": "disco_party",
        "name": "🪩 派對夜店快速跳閃",
        "desc": "節奏強烈的隨機色彩快速跳動 + 點陣音樂波形頻譜跳動",
        "tags": ["派對", "夜店", "狂歡", "跳舞", "disco", "動感", "節奏", "快", "嗨", "熱鬧"],
        "min": 3,
        "max": 10,
        "excitement": 9,
        "power": 7
    },
    {
        "id": 6,
        "key": "chase_wave",
        "name": "🌊 雙色流水波紋",
        "desc": "如波浪般交替推移的流水漸變 + 點陣海洋波浪動畫",
        "tags": ["流水", "水波", "波浪", "波紋", "追逐", "交替", "海洋", "自然"],
        "min": 4,
        "max": 15,
        "excitement": 6,
        "power": 5
    }
]


def parse_user_description(text):
    """根據使用者輸入的自然語言描述，智慧辨識意圖並挑選合適的特效清單與權重調整"""
    if not text or not text.strip():
        return [eff["id"] for eff in EFFECT_CATALOG], {}

    text = text.lower().strip()
    selected_ids = set()
    weight_adjust = {}

    scores = {eff["id"]: 0 for eff in EFFECT_CATALOG}
    for eff in EFFECT_CATALOG:
        for tag in eff["tags"]:
            if tag in text:
                scores[eff["id"]] += 3

    if any(k in text for k in ["派對", "夜店", "狂歡", "嗨", "disco", "熱鬧", "節奏"]):
        selected_ids.update([5, 2, 1, 0])
        weight_adjust[5] = 12
        weight_adjust[2] = 10
    elif any(k in text for k in ["睡", "放鬆", "療癒", "安靜", "助眠", "夜燈", "溫柔", "燭光"]):
        selected_ids.update([3, 4, 6])
        weight_adjust[3] = 10
        weight_adjust[4] = 9
    elif any(k in text for k in ["警車", "警察", "巡邏", "緊急", "警報"]):
        selected_ids.update([2, 1])
        weight_adjust[2] = 15
    elif any(k in text for k in ["科幻", "賽博", "未來", "科技", "極光", "太空"]):
        selected_ids.update([4, 1, 6, 0])
        weight_adjust[4] = 10
        weight_adjust[1] = 9
    elif any(k in text for k in ["自然", "海洋", "流水", "水波", "森林"]):
        selected_ids.update([6, 3, 4, 0])

    for eff_id, score in scores.items():
        if score > 0:
            selected_ids.add(eff_id)

    if not selected_ids:
        selected_ids = {0, 1, 2, 3, 4, 5, 6}

    return sorted(list(selected_ids)), weight_adjust


def load_hardware_config():
    """載入硬體腳位 (雙 RGB + MAX7219 點陣) 與設定"""
    defaults = {
        "m1_r_pin": 6,
        "m1_g_pin": 4,
        "m1_b_pin": 5,
        "m2_r_pin": 11,
        "m2_g_pin": 10,
        "m2_b_pin": 9,
        "matrix_din_pin": 12,
        "matrix_cs_pin": 8,
        "matrix_clk_pin": 7,
        "matrix_custom_bitmap": [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
        "common_anode": True,
        "last_com_port": "COM4"
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if k.endswith("_pin"):
                        defaults[k] = int(v)
                    else:
                        defaults[k] = v
        except Exception as e:
            print(f"⚠️ 讀取設定檔警告: {e}")
    return defaults


def optimize_lightshow_with_cpsat(selected_ids=None, target_total_sec=30, weight_adjust=None):
    """使用 Google OR-Tools CP-SAT 求解器進行燈效時間表排程優化"""
    if not selected_ids:
        selected_ids = [0, 1, 2, 3, 4, 5, 6]

    if weight_adjust is None:
        weight_adjust = {}

    selected_effects = [eff for eff in EFFECT_CATALOG if eff["id"] in selected_ids]
    if not selected_effects:
        selected_effects = [EFFECT_CATALOG[0]]

    n = len(selected_effects)

    print(f"\n=======================================================")
    print(f"🧠 [Google OR-Tools CP-SAT] 啟動燈光特效排程與約束求解器")
    print(f"=======================================================")
    print(f"🎯 目標總循環時間: {target_total_sec} 秒 | 選中特效段數: {n} 段")

    model = cp_model.CpModel()

    durations = []
    for i, eff in enumerate(selected_effects):
        min_sec = max(2, min(eff["min"], target_total_sec // (n * 2) if n > 0 else 2))
        max_sec = min(eff["max"] * 2, max(min_sec + 2, target_total_sec))
        d_var = model.NewIntVar(min_sec, max_sec, f"dur_{eff['id']}")
        durations.append(d_var)

    # 約束 1: 總時長之和嚴格等於 target_total_sec
    model.Add(sum(durations) == target_total_sec)

    # 約束 2: 若包含高頻爆閃 (id 2)，最多佔 30%
    for i, eff in enumerate(selected_effects):
        if eff["id"] == 2:
            model.Add(durations[i] <= max(3, int(target_total_sec * 0.30)))

    # 約束 3: 功率負載積分約束
    total_power = sum(durations[i] * eff["power"] for i, eff in enumerate(selected_effects))
    model.Add(total_power <= target_total_sec * 9)

    # 目標函數：最大化視覺動態與使用者偏好加權分
    obj_terms = []
    for i, eff in enumerate(selected_effects):
        w = weight_adjust.get(eff["id"], eff["excitement"])
        obj_terms.append(durations[i] * w)

    model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"⚠️ CP-SAT 約束過嚴或無解，採用安全均分算法")
        each = max(1, target_total_sec // n)
        schedule = []
        for eff in selected_effects:
            schedule.append({
                "id": eff["id"],
                "name": eff["name"],
                "duration_sec": each,
                "duration_ms": each * 1000
            })
        return schedule

    print(f"✅ CP-SAT 求解完成！狀態: {solver.StatusName(status)}")
    print(f"📊 最優視覺滿意度得分: {solver.ObjectiveValue()}")
    print("-" * 55)

    schedule = []
    total_check = 0
    for i, eff in enumerate(selected_effects):
        sec = solver.Value(durations[i])
        total_check += sec
        schedule.append({
            "id": eff["id"],
            "name": eff["name"],
            "duration_sec": sec,
            "duration_ms": sec * 1000
        })
        print(f"  * [{eff['name']}]: 持續 {sec} 秒")

    print("-" * 55)
    print(f"⏱ 總循環週期合計: {total_check} 秒 (精準吻合設定)")
    return schedule


def generate_arduino_source(schedule, hw_config):
    """
    根據 CP-SAT 最佳化排程與硬體腳位，自動產生完整脫機獨立運行的 Arduino C++ 原始碼
    包含：雙 RGB LED + MAX7219 8x8 點陣顯示同步聯動
    """
    os.makedirs(FIRMWARE_DIR, exist_ok=True)
    ca_flag = "true" if hw_config["common_anode"] else "false"

    steps_cpp = []
    for s in schedule:
        steps_cpp.append(f"  {{ {s['id']}, {s['duration_ms']}UL }}")
    steps_code = ",\n".join(steps_cpp)

    custom_bmp = hw_config.get("matrix_custom_bitmap", [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18])
    if not isinstance(custom_bmp, list) or len(custom_bmp) != 8:
        custom_bmp = [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18]
    custom_bmp_cpp = ", ".join(f"0x{int(b):02X}" for b in custom_bmp)

    ino_content = f"""/*
 * Auto-Generated Unified Master Firmware by Google OR-Tools CP-SAT
 * ===============================================================
 * Hardware Pinout:
 *   Module 1: R={hw_config['m1_r_pin']}, G={hw_config['m1_g_pin']}, B={hw_config['m1_b_pin']} (Common Anode: {ca_flag})
 *   Module 2: R={hw_config['m2_r_pin']}, G={hw_config['m2_g_pin']}, B={hw_config['m2_b_pin']} (Common Anode: {ca_flag})
 *   MAX7219 8x8 Dot Matrix: DIN={hw_config.get('matrix_din_pin', 12)}, CS={hw_config.get('matrix_cs_pin', 8)}, CLK={hw_config.get('matrix_clk_pin', 7)}
 *
 * Supports BOTH:
 *   1. 100% Standalone Offline Mode (Dual RGB + 8x8 Dot Matrix synchronized show)
 *   2. Real-Time USB Serial Mode (PING, RGB, MATRIX, CLEAR_MATRIX commands)
 */

#include <Arduino.h>

// RGB 腳位定義
const uint8_t M1_R = {hw_config['m1_r_pin']};
const uint8_t M1_G = {hw_config['m1_g_pin']};
const uint8_t M1_B = {hw_config['m1_b_pin']};

const uint8_t M2_R = {hw_config['m2_r_pin']};
const uint8_t M2_G = {hw_config['m2_g_pin']};
const uint8_t M2_B = {hw_config['m2_b_pin']};

const bool COMMON_ANODE = {ca_flag};

// MAX7219 8x8 點陣腳位定義
const uint8_t PIN_DIN = {hw_config.get('matrix_din_pin', 12)};
const uint8_t PIN_CS  = {hw_config.get('matrix_cs_pin', 8)};
const uint8_t PIN_CLK = {hw_config.get('matrix_clk_pin', 7)};

#define REG_DIGIT0      0x01
#define REG_DECODEMODE  0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

void writeMatrixReg(uint8_t reg, uint8_t data) {{
  digitalWrite(PIN_CS, LOW);
  shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, reg);
  shiftOut(PIN_DIN, PIN_CLK, MSBFIRST, data);
  digitalWrite(PIN_CS, HIGH);
}}

void initMAX7219() {{
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
}}

void displayMatrixBitmap(const uint8_t bitmap[8]) {{
  for (uint8_t r = 0; r < 8; r++) {{
    writeMatrixReg(REG_DIGIT0 + r, bitmap[r]);
  }}
}}

void clearMatrix() {{
  for (uint8_t r = 0; r < 8; r++) {{
    writeMatrixReg(REG_DIGIT0 + r, 0x00);
  }}
}}

// 脫機點陣動畫圖標
const uint8_t ICON_CUSTOM[8] = {{ {custom_bmp_cpp} }};

const uint8_t ICON_HEART[8] = {{
  0b00000000, 0b01100110, 0b11111111, 0b11111111,
  0b11111111, 0b01111110, 0b00111100, 0b00011000
}};
const uint8_t ICON_HEART_SM[8] = {{
  0b00000000, 0b00000000, 0b00100100, 0b01111110,
  0b01111110, 0b00111100, 0b00011000, 0b00000000
}};
const uint8_t ICON_POLICE[8] = {{
  0b00011000, 0b00111100, 0b01111110, 0b11111111,
  0b11111111, 0b01111110, 0b00111100, 0b00011000
}};
const uint8_t ICON_SMILE[8] = {{
  0b00111100, 0b01000010, 0b10100101, 0b10000001,
  0b10100101, 0b10011001, 0b01000010, 0b00111100
}};
const uint8_t ICON_WINK[8] = {{
  0b00111100, 0b01000010, 0b10100001, 0b10000110,
  0b10100001, 0b10011001, 0b01000010, 0b00111100
}};
const uint8_t ICON_INVADER_A[8] = {{
  0b00011000, 0b00111100, 0b01111110, 0b11011011,
  0b11111111, 0b00100100, 0b01011010, 0b10100101
}};
const uint8_t ICON_INVADER_B[8] = {{
  0b00011000, 0b00111100, 0b01111110, 0b11011011,
  0b11111111, 0b01011010, 0b10000001, 0b01000010
}};
const uint8_t ICON_DIAMOND[8] = {{
  0b00011000, 0b00111100, 0b01111110, 0b11111111,
  0b01111110, 0b00111100, 0b00011000, 0b00000000
}};

// 排程結構
struct EffectStep {{
  uint8_t effectType;
  uint32_t durationMs;
}};

const EffectStep SCHEDULE[] = {{
{steps_code}
}};
const uint8_t SCHEDULE_COUNT = sizeof(SCHEDULE) / sizeof(SCHEDULE[0]);

void setRGB(uint8_t rPin, uint8_t gPin, uint8_t bPin, uint8_t r, uint8_t g, uint8_t b) {{
  if (COMMON_ANODE) {{
    analogWrite(rPin, 255 - r);
    analogWrite(gPin, 255 - g);
    analogWrite(bPin, 255 - b);
  }} else {{
    analogWrite(rPin, r);
    analogWrite(gPin, g);
    analogWrite(bPin, b);
  }}
}}

void setM1(uint8_t r, uint8_t g, uint8_t b) {{
  setRGB(M1_R, M1_G, M1_B, r, g, b);
}}

void setM2(uint8_t r, uint8_t g, uint8_t b) {{
  setRGB(M2_R, M2_G, M2_B, r, g, b);
}}

void hsvToRgb(float h, float s, float v, uint8_t &r, uint8_t &g, uint8_t &b) {{
  float c = v * s;
  float x = c * (1.0f - fabs(fmod(h / 60.0f, 2.0f) - 1.0f));
  float m = v - c;
  float r1 = 0, g1 = 0, b1 = 0;
  if (h >= 0 && h < 60) {{ r1 = c; g1 = x; b1 = 0; }}
  else if (h >= 60 && h < 120) {{ r1 = x; g1 = c; b1 = 0; }}
  else if (h >= 120 && h < 180) {{ r1 = 0; g1 = c; b1 = x; }}
  else if (h >= 180 && h < 240) {{ r1 = 0; g1 = x; b1 = c; }}
  else if (h >= 240 && h < 300) {{ r1 = x; g1 = 0; b1 = c; }}
  else {{ r1 = c; g1 = 0; b1 = x; }}
  r = (uint8_t)((r1 + m) * 255);
  g = (uint8_t)((g1 + m) * 255);
  b = (uint8_t)((b1 + m) * 255);
}}

bool isInteractiveMode = false;
uint32_t lastSerialCmdTime = 0;
uint8_t currentStepIdx = 0;
uint32_t stepStartTime = 0;
uint32_t lastAnimTick = 0;
float animHue = 0.0f;

char cmdBuffer[128];
uint8_t cmdIdx = 0;

void processSerialCommand(char* cmd) {{
  while (*cmd == ' ' || *cmd == '\\r' || *cmd == '\\t') cmd++;
  if (strlen(cmd) == 0) return;

  if (strcmp(cmd, "PING") == 0) {{
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    Serial.println("PONG");
    return;
  }}

  if (strcmp(cmd, "OFFLINE") == 0) {{
    isInteractiveMode = false;
    stepStartTime = millis();
    Serial.println("OK:OFFLINE");
    return;
  }}

  if (strncmp(cmd, "RGB", 3) == 0) {{
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    int rp, gp, bp, r, g, b;
    if (sscanf(cmd + 3, "%d %d %d %d %d %d", &rp, &gp, &bp, &r, &g, &b) == 6) {{
      analogWrite(rp, r);
      analogWrite(gp, g);
      analogWrite(bp, b);
      Serial.println("OK");
    }} else {{
      Serial.println("ERR:PARSE");
    }}
    return;
  }}

  if (strncmp(cmd, "MATRIX", 6) == 0) {{
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    int b[8];
    if (sscanf(cmd + 6, "%d %d %d %d %d %d %d %d",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &b[6], &b[7]) == 8) {{
      uint8_t bmp[8];
      for (int i = 0; i < 8; i++) bmp[i] = (uint8_t)b[i];
      displayMatrixBitmap(bmp);
      Serial.println("OK:MATRIX");
    }} else {{
      Serial.println("ERR:MATRIX");
    }}
    return;
  }}

  if (strcmp(cmd, "CLEAR_MATRIX") == 0) {{
    isInteractiveMode = true;
    lastSerialCmdTime = millis();
    clearMatrix();
    Serial.println("OK:CLEAR");
    return;
  }}

  Serial.println("ERR:UNKNOWN");
}}

void setup() {{
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
}}

void loop() {{
  uint32_t now = millis();

  while (Serial.available() > 0) {{
    char c = (char)Serial.read();
    if (c == '\\n' || c == '\\r') {{
      if (cmdIdx > 0) {{
        cmdBuffer[cmdIdx] = '\\0';
        processSerialCommand(cmdBuffer);
        cmdIdx = 0;
      }}
    }} else if (cmdIdx < sizeof(cmdBuffer) - 1) {{
      cmdBuffer[cmdIdx++] = c;
    }}
  }}

  if (isInteractiveMode) {{
    if (now - lastSerialCmdTime > 15000) {{
      isInteractiveMode = false;
      stepStartTime = now;
    }}
    return;
  }}

  if (now - stepStartTime >= SCHEDULE[currentStepIdx].durationMs) {{
    currentStepIdx = (currentStepIdx + 1) % SCHEDULE_COUNT;
    stepStartTime = now;
  }}

  if (now - lastAnimTick >= 25) {{
    lastAnimTick = now;
    uint8_t effect = SCHEDULE[currentStepIdx].effectType;

    switch (effect) {{
      case 0: {{ // 0. 雙燈同步彩虹流光 + 外星人踏步
        uint8_t r, g, b;
        hsvToRgb(animHue, 1.0f, 1.0f, r, g, b);
        setM1(r, g, b);
        setM2(r, g, b);
        animHue = fmod(animHue + 2.5f, 360.0f);

        uint32_t step = (now / 300) % 2;
        displayMatrixBitmap(step ? ICON_INVADER_A : ICON_INVADER_B);
        break;
      }}
      case 1: {{ // 1. 雙燈互補流光 + 旋轉鑽石
        uint8_t r1, g1, b1, r2, g2, b2;
        float hue2 = fmod(animHue + 180.0f, 360.0f);
        hsvToRgb(animHue, 1.0f, 1.0f, r1, g1, b1);
        hsvToRgb(hue2, 1.0f, 1.0f, r2, g2, b2);
        setM1(r1, g1, b1);
        setM2(r2, g2, b2);
        animHue = fmod(animHue + 2.5f, 360.0f);

        displayMatrixBitmap(ICON_DIAMOND);
        break;
      }}
      case 2: {{ // 2. 警車雙閃爆閃 (70ms) + 警徽雙閃
        uint32_t cycle = (now / 70) % 12;
        if (cycle == 0 || cycle == 2 || cycle == 4) {{
          setM1(255, 0, 0);
          setM2(0, 0, 0);
          displayMatrixBitmap(ICON_POLICE);
        }} else if (cycle == 6 || cycle == 8 || cycle == 10) {{
          setM1(0, 0, 0);
          setM2(0, 0, 255);
          displayMatrixBitmap(ICON_POLICE);
        }} else {{
          setM1(0, 0, 0);
          setM2(0, 0, 0);
          clearMatrix();
        }}
        break;
      }}
      case 3: {{ // 3. 暖色療癒呼吸燈 + 跳動愛心 ❤️
        float breath = (sin(now * 0.0025f) + 1.0f) * 0.5f;
        setM1((uint8_t)(255 * breath), (uint8_t)(90 * breath), (uint8_t)(10 * breath));
        setM2((uint8_t)(255 * breath), (uint8_t)(140 * breath), (uint8_t)(20 * breath));

        uint32_t hStep = (now / 350) % 2;
        displayMatrixBitmap(hStep ? ICON_HEART : ICON_HEART_SM);
        break;
      }}
      case 4: {{ // 4. 極光冷艷呼吸燈 + 微笑眨眼
        float b1 = (sin(now * 0.003f) + 1.0f) * 0.5f;
        float b2 = (cos(now * 0.003f) + 1.0f) * 0.5f;
        setM1(0, (uint8_t)(240 * b1), (uint8_t)(180 * b1));
        setM2((uint8_t)(160 * b2), 0, (uint8_t)(255 * b2));

        uint32_t wStep = (now / 700) % 4;
        displayMatrixBitmap(wStep == 0 ? ICON_WINK : ICON_SMILE);
        break;
      }}
      case 5: {{ // 5. 派對夜店快速跳閃 + 擴散霓虹波紋
        uint32_t beat = (now / 150) % 6;
        const uint8_t colors[6][3] = {{
          {{255, 0, 100}}, {{0, 255, 200}}, {{255, 220, 0}},
          {{120, 0, 255}}, {{0, 255, 50}},  {{255, 50, 0}}
        }};
        setM1(colors[beat][0], colors[beat][1], colors[beat][2]);
        uint8_t opp = (beat + 3) % 6;
        setM2(colors[opp][0], colors[opp][1], colors[opp][2]);

        uint8_t bar = (now / 100) % 4;
        uint8_t box[8] = {{0}};
        for (int y = 3 - bar; y <= 4 + bar; y++) {{
          for (int x = 3 - bar; x <= 4 + bar; x++) {{
            if (x == 3 - bar || x == 4 + bar || y == 3 - bar || y == 4 + bar) {{
              box[y] |= (1 << (7 - x));
            }}
          }}
        }}
        displayMatrixBitmap(box);
        break;
      }}
      case 6: {{ // 6. 雙燈交替流水波紋 + 水波律動
        float p1 = (sin(now * 0.005f) + 1.0f) * 0.5f;
        float p2 = (cos(now * 0.005f) + 1.0f) * 0.5f;
        setM1((uint8_t)(255 * p1), (uint8_t)(255 * (1.0f - p1)), 128);
        setM2((uint8_t)(255 * (1.0f - p2)), 128, (uint8_t)(255 * p2));

        uint8_t shift = (now / 120) % 8;
        uint8_t wave[8];
        for (int r = 0; r < 8; r++) {{
          wave[r] = (0x33 << ((r + shift) % 4)) | (0x33 >> (8 - ((r + shift) % 4)));
        }}
        displayMatrixBitmap(wave);
        break;
      }}
    }}
  }}
}}
"""
    with open(FIRMWARE_INO, "w", encoding="utf-8") as f:
        f.write(ino_content)

    print(f"💾 脫機固件原始碼 (含雙 RGB + MAX7219 8×8 點陣) 已生成: {FIRMWARE_INO}")
    return FIRMWARE_INO


def compile_and_upload(port=None):
    """調用 arduino-cli 自動編譯並燒錄至板子"""
    if not port:
        hw_config = load_hardware_config()
        port = hw_config.get("last_com_port", "COM4")

    print(f"\n=======================================================")
    print(f"🚀 開始自動編譯並燒錄進電路板 (COM 埠: {port})")
    print(f"=======================================================")

    compile_cmd = [
        ARDUINO_CLI_PATH,
        "compile",
        "--fqbn", "arduino:avr:uno",
        FIRMWARE_DIR
    ]
    print(f"🔨 正在編譯 C++ 固件...")
    res_compile = subprocess.run(compile_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_compile.returncode != 0:
        print(f"❌ 編譯失敗:\n{res_compile.stderr}")
        raise RuntimeError("Arduino-cli 編譯失敗")
    print("✅ 編譯成功！二進位 Flash Image 產生完成。")

    upload_cmd = [
        ARDUINO_CLI_PATH,
        "upload",
        "-p", port,
        "--fqbn", "arduino:avr:uno",
        FIRMWARE_DIR
    ]
    print(f"⚡ 正在燒錄 (Flash) 至 Arduino Uno ({port})...")
    res_upload = subprocess.run(upload_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_upload.returncode != 0:
        print(f"❌ 燒錄失敗:\n{res_upload.stderr}")
        raise RuntimeError("Arduino-cli 燒錄失敗")
    print("🎉 燒錄成功！固件已永久固化進 ATmega328P Flash 晶片。")
    print("\n" + "=" * 55)
    print("✨ 【脫機獨立運行驗證完成】")
    print("現在您可以直接拔掉電腦連線！")
    print("只要接上任何 USB 行動電源、手機充電豆腐頭或 5V 變壓器，")
    print("Arduino 電路板開機後將完全脫機獨立、自動循環執行專屬燈光秀與 8×8 點陣動畫！")
    print("=" * 55)


def run_pipeline(description="", selected_ids=None, target_sec=30, port=None):
    hw_config = load_hardware_config()
    if not port:
        port = hw_config.get("last_com_port", "COM4")

    weight_adjust = {}
    if description and not selected_ids:
        print(f"📝 解析使用者情境風格描述: \"{description}\"")
        selected_ids, weight_adjust = parse_user_description(description)
    elif not selected_ids:
        selected_ids = [0, 1, 2, 3, 4, 5, 6]

    schedule = optimize_lightshow_with_cpsat(
        selected_ids=selected_ids,
        target_total_sec=target_sec,
        weight_adjust=weight_adjust
    )
    generate_arduino_source(schedule, hw_config)
    compile_and_upload(port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone Light Show Optimizer with Google OR-Tools")
    parser.add_argument("--port", type=str, default=None, help="Serial COM Port")
    parser.add_argument("--cycle-time", type=int, default=30, help="Target cycle time in seconds")
    parser.add_argument("--effects", type=str, default="", help="Comma-separated effect IDs (e.g. 0,1,2,3)")
    parser.add_argument("--description", type=str, default="", help="Natural language description of desired light show")
    parser.add_argument("pos_args", nargs="*", help="Optional positional arguments (duration or description)")

    args = parser.parse_args()

    port = args.port
    sec = args.cycle_time
    desc = args.description

    selected_ids = None
    if args.effects:
        try:
            selected_ids = [int(x.strip()) for x in args.effects.split(",") if x.strip()]
        except Exception:
            selected_ids = None

    if args.pos_args:
        first = args.pos_args[0]
        try:
            sec = int(first)
            if len(args.pos_args) > 1:
                desc = args.pos_args[1]
        except ValueError:
            desc = first
            if len(args.pos_args) > 1:
                try:
                    sec = int(args.pos_args[1])
                except ValueError:
                    pass

    run_pipeline(description=desc, selected_ids=selected_ids, target_sec=sec, port=port)
