"""
Arduino Uno Master Control Center (Dual RGB LEDs + MAX7219 8x8 Dot Matrix)
==========================================================================
功能特性：
- 雙分頁標籤導航 (ttk.Notebook)：
  * 分頁 1【🌈 雙 RGB 全彩燈】：9 大即時連線特效、零延遲雙燈滑桿調色、OR-Tools 脫機智慧排程燒錄
  * 分頁 2【👾 8×8 點陣互動中心】：64 點可點擊即時同步畫布、8 款經典像素圖案、ASCII 跑馬燈橫向滾動
- 雙模式無縫切換 (Unified Dual-Mode Firmware)：
  * 即時連線控制 (USB 0 延遲同步反饋)
  * 脫機獨立秀 (拔除電腦接行動電源，雙燈與點陣同步播放震撼燈光秀)
- 自動辨識 Arduino Uno COM 埠、自動連線與腳位永久儲存
"""

import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import serial
import serial.tools.list_ports

# 固定工作目錄
WORKSPACE_DIR = r"D:\PythonTest\AduinoTest"
ARDUINO_CLI_PATH = r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
PYTHON312_PATH = r"C:\Users\ALBERT\AppData\Local\Programs\Python\Python312\python.exe"

# 8x8 點陣預設像素圖案
PRESET_PATTERNS = {
    "❤️ 愛心": [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
    "😊 笑臉": [0x3C, 0x42, 0xA5, 0x81, 0xA5, 0x99, 0x42, 0x3C],
    "👾 外星人": [0x18, 0x3C, 0x7E, 0xDB, 0xFF, 0x24, 0x5A, 0x81],
    "ᗧ 吃豆人": [0x3C, 0x7E, 0xFF, 0xE7, 0xC0, 0xE7, 0x7E, 0x3C],
    "🎵 音符": [0x0C, 0x0E, 0x0B, 0x09, 0x09, 0x19, 0x79, 0x70],
    "⚡ 閃電": [0x06, 0x0C, 0x18, 0x3F, 0x0C, 0x18, 0x30, 0x00],
    "💎 鑽石": [0x18, 0x3C, 0x7E, 0xFF, 0x7E, 0x3C, 0x18, 0x00],
    "💀 骷髏": [0x3C, 0x7E, 0xDB, 0xDB, 0x7E, 0x3C, 0x24, 0x24],
}

# 5x7 ASCII 簡易字模表 (用於 8x8 跑馬燈)
ASCII_FONT = {
    ' ': [0x00, 0x00, 0x00, 0x00, 0x00],
    '!': [0x00, 0x00, 0x5F, 0x00, 0x00],
    '?': [0x02, 0x01, 0x51, 0x09, 0x06],
    '-': [0x08, 0x08, 0x08, 0x08, 0x08],
    '+': [0x08, 0x08, 0x3E, 0x08, 0x08],
    '=': [0x14, 0x14, 0x14, 0x14, 0x14],
    '0': [0x3E, 0x51, 0x49, 0x45, 0x3E],
    '1': [0x00, 0x42, 0x7F, 0x40, 0x00],
    '2': [0x42, 0x61, 0x51, 0x49, 0x46],
    '3': [0x21, 0x41, 0x45, 0x4B, 0x31],
    '4': [0x18, 0x14, 0x12, 0x7F, 0x10],
    '5': [0x27, 0x45, 0x45, 0x45, 0x39],
    '6': [0x3C, 0x4A, 0x49, 0x49, 0x30],
    '7': [0x01, 0x71, 0x09, 0x05, 0x03],
    '8': [0x36, 0x49, 0x49, 0x49, 0x36],
    '9': [0x06, 0x49, 0x49, 0x29, 0x1E],
    'A': [0x7E, 0x11, 0x11, 0x11, 0x7E],
    'B': [0x7F, 0x49, 0x49, 0x49, 0x36],
    'C': [0x3E, 0x41, 0x41, 0x41, 0x22],
    'D': [0x7F, 0x41, 0x41, 0x22, 0x1C],
    'E': [0x7F, 0x49, 0x49, 0x49, 0x41],
    'F': [0x7F, 0x09, 0x09, 0x09, 0x01],
    'G': [0x3E, 0x41, 0x49, 0x49, 0x7A],
    'H': [0x7F, 0x08, 0x08, 0x08, 0x7F],
    'I': [0x00, 0x41, 0x7F, 0x41, 0x00],
    'J': [0x20, 0x40, 0x41, 0x3F, 0x01],
    'K': [0x7F, 0x08, 0x14, 0x22, 0x41],
    'L': [0x7F, 0x40, 0x40, 0x40, 0x40],
    'M': [0x7F, 0x02, 0x0C, 0x02, 0x7F],
    'N': [0x7F, 0x04, 0x08, 0x10, 0x7F],
    'O': [0x3E, 0x41, 0x41, 0x41, 0x3E],
    'P': [0x7F, 0x09, 0x09, 0x09, 0x06],
    'Q': [0x3E, 0x41, 0x51, 0x21, 0x5E],
    'R': [0x7F, 0x09, 0x19, 0x29, 0x46],
    'S': [0x46, 0x49, 0x49, 0x49, 0x31],
    'T': [0x01, 0x01, 0x7F, 0x01, 0x01],
    'U': [0x3F, 0x40, 0x40, 0x40, 0x3F],
    'V': [0x1F, 0x20, 0x40, 0x20, 0x1F],
    'W': [0x7F, 0x20, 0x18, 0x20, 0x7F],
    'X': [0x63, 0x14, 0x08, 0x14, 0x63],
    'Y': [0x07, 0x08, 0x70, 0x08, 0x07],
    'Z': [0x61, 0x51, 0x49, 0x45, 0x43],
}

# 脫機燒錄特效清單
EFFECT_DEFS = [
    (0, "🌈 經典彩虹漸變 (Rainbow)"),
    (1, "☯ 互補流光穿梭 (Complementary)"),
    (2, "🚨 警車雙色爆閃 (Police Strobe)"),
    (3, "🕯️ 溫暖燭光呼吸 (Warm Breathing)"),
    (4, "🌌 賽博極光律動 (Cyber Aurora)"),
    (5, "🪩 派對夜店狂歡 (Disco Party)"),
    (6, "🌊 雙色波浪交替 (Chase Wave)"),
]


def get_config_path():
    fixed_path = os.path.join(WORKSPACE_DIR, "config.json")
    if os.path.exists(WORKSPACE_DIR):
        return fixed_path
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "config.json")


def find_arduino_device():
    """自動掃描可用 Serial 埠，辨識 Arduino Uno 或相容板"""
    candidates = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        score = 0
        if "arduino" in desc or "arduino" in mfg or p.vid == 0x2341:
            score += 100
        elif p.vid == 0x1A86 or "ch340" in desc or "ch341" in desc:
            score += 50
        elif p.vid in [0x10C4, 0x0403]:
            score += 40
        elif "usb-serial" in desc or "usb serial" in desc:
            score += 30
        if score > 0:
            candidates.append((score, p.device, p.description))

    candidates.sort(key=lambda x: x[0], reverse=True)
    if candidates:
        return candidates[0][1], candidates[0][2]
    return None, None


def parse_user_description(text):
    """自然語言意圖辨識"""
    if not text or not text.strip():
        return [0, 1, 2, 3, 4, 5, 6]
    text = text.lower().strip()
    selected_ids = set()
    if any(k in text for k in ["派對", "夜店", "狂歡", "嗨", "disco", "熱鬧", "節奏"]):
        selected_ids.update([0, 2, 5])
    elif any(k in text for k in ["睡", "放鬆", "療癒", "安靜", "助眠", "夜燈", "溫柔", "燭光"]):
        selected_ids.update([3, 4, 6])
    elif any(k in text for k in ["警車", "警察", "巡邏", "緊急", "警報"]):
        selected_ids.update([2, 1])
    elif any(k in text for k in ["科幻", "賽博", "未來", "科技", "極光", "太空"]):
        selected_ids.update([4, 1, 6, 0])
    elif any(k in text for k in ["自然", "海洋", "流水", "水波", "森林"]):
        selected_ids.update([6, 3, 4, 0])

    tags_map = {
        1: ["互補", "對比", "流光", "雙色"],
        2: ["警車", "爆閃", "閃爍", "警察", "巡邏"],
        3: ["暖色", "呼吸", "放鬆", "睡", "夕陽", "燭光", "夜燈"],
        4: ["極光", "冷色", "藍色", "紫色", "神秘", "冰冷"],
        5: ["派對", "夜店", "狂歡", "跳舞", "disco", "節奏"],
        6: ["流水", "水波", "波浪", "波紋", "追逐"]
    }
    for eff_id, tags in tags_map.items():
        if any(t in text for t in tags):
            selected_ids.add(eff_id)

    if not selected_ids:
        selected_ids = {0, 1, 2, 3, 6}
    return sorted(list(selected_ids))


class ArduinoGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino Uno 控制中心 (雙全彩 RGB + MAX7219 8×8 點陣)")
        self.root.geometry("880x920")
        self.root.resizable(False, False)

        # 狀態
        self.is_connected = False
        self.worker_thread = None
        self.cmd_queue = queue.Queue()
        self.stop_worker = False

        self.ser = None
        self.current_effect_name = None
        self.effect_thread = None
        self.stop_effect = threading.Event()

        # 8x8 點陣狀態 (8 列，每列 8 位元 0/1)
        self.matrix_grid = [[0 for _ in range(8)] for _ in range(8)]
        self.pixel_buttons = []
        self.marquee_running = False
        self.marquee_thread = None
        self.stop_marquee = threading.Event()

        # 載入設定
        self.config = self.load_config()

        self.matrix_din_pin = tk.StringVar(value=str(self.config.get("matrix_din_pin", "12")))
        self.matrix_cs_pin = tk.StringVar(value=str(self.config.get("matrix_cs_pin", "8")))
        self.matrix_clk_pin = tk.StringVar(value=str(self.config.get("matrix_clk_pin", "7")))

        self.common_anode = tk.BooleanVar(value=self.config.get("common_anode", True))
        self.effect_vars = {}
        for eff_id, _ in EFFECT_DEFS:
            self.effect_vars[eff_id] = tk.BooleanVar(value=True)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 自動偵測連線
        self.root.after(300, lambda: self.auto_detect_and_fill(auto_connect=True))

    def load_config(self):
        cfg_path = get_config_path()
        defaults = {
            "m1_r_pin": "6",
            "m1_g_pin": "3",
            "m1_b_pin": "5",
            "m2_r_pin": "11",
            "m2_g_pin": "9",
            "m2_b_pin": "10",
            "matrix_din_pin": "12",
            "matrix_cs_pin": "8",
            "matrix_clk_pin": "7",
            "matrix_custom_bitmap": [0, 102, 255, 255, 255, 126, 60, 24],
            "common_anode": True,
            "last_com_port": "COM4"
        }
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    defaults.update(data)
            except Exception:
                pass
        return defaults

    def save_config(self, show_log=True):
        cfg_path = get_config_path()
        try:
            m1_r = self.m1_r_pin.get()
            m1_g = self.m1_g_pin.get()
            m1_b = self.m1_b_pin.get()
            m2_r = self.m2_r_pin.get()
            m2_g = self.m2_g_pin.get()
            m2_b = self.m2_b_pin.get()
            din = self.matrix_din_pin.get()
            cs = self.matrix_cs_pin.get()
            clk = self.matrix_clk_pin.get()
            ca = self.common_anode.get()
            com = self.port_combobox.get()
        except AttributeError:
            return

        data = {
            "m1_r_pin": m1_r,
            "m1_g_pin": m1_g,
            "m1_b_pin": m1_b,
            "m2_r_pin": m2_r,
            "m2_g_pin": m2_g,
            "m2_b_pin": m2_b,
            "matrix_din_pin": din,
            "matrix_cs_pin": cs,
            "matrix_clk_pin": clk,
            "matrix_custom_bitmap": self.config.get("matrix_custom_bitmap", [0, 102, 255, 255, 255, 126, 60, 24]),
            "common_anode": ca,
            "last_com_port": com
        }
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if show_log:
                self.log(f"💾 腳位設定已永久儲存至 config.json (RGB: M1={m1_r},{m1_g},{m1_b} M2={m2_r},{m2_g},{m2_b} | 點陣: DIN={din}, CS={cs}, CLK={clk})")
        except Exception as e:
            if show_log:
                self.log(f"❌ 儲存 config.json 失敗: {e}")

    def _build_ui(self):
        # 頂部連接列
        top_frame = ttk.LabelFrame(self.root, text=" 🔌 USB 序列通訊與硬體設定 ", padding=6)
        top_frame.pack(fill="x", padx=10, pady=4)

        ttk.Label(top_frame, text="COM 埠:").pack(side="left", padx=2)
        self.port_combobox = ttk.Combobox(top_frame, width=12)
        self.port_combobox.pack(side="left", padx=3)

        ttk.Button(top_frame, text="🔄 重新整理", command=lambda: self.auto_detect_and_fill(False)).pack(side="left", padx=2)
        self.btn_connect = ttk.Button(top_frame, text="⚡ 連線", command=self.toggle_connection)
        self.btn_connect.pack(side="left", padx=4)

        ttk.Checkbutton(top_frame, text="共陽極 (Common Anode)", variable=self.common_anode,
                        command=lambda: self.save_config(False)).pack(side="left", padx=10)

        ttk.Button(top_frame, text="💾 儲存腳位", command=lambda: self.save_config(True)).pack(side="right", padx=3)

        self.lbl_status = ttk.Label(top_frame, text="⚪ 未連線", font=("Arial", 9, "bold"), foreground="gray")
        self.lbl_status.pack(side="right", padx=8)

        # Notebook 主分頁
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=4)

        # Tab 1: RGB 燈控制
        tab_rgb = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_rgb, text=" 🌈 雙 RGB 全彩燈控制 ")
        self._build_rgb_tab(tab_rgb)

        # Tab 2: MAX7219 點陣控制
        tab_matrix = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab_matrix, text=" 👾 MAX7219 8×8 點陣互動中心 ")
        self._build_matrix_tab(tab_matrix)

        # 底部 Log
        log_frame = ttk.LabelFrame(self.root, text=" 系統執行日誌與 Arduino 回饋 ", padding=4)
        log_frame.pack(fill="x", padx=10, pady=4)

        self.log_text = ScrolledText(log_frame, height=5, state="disabled", font=("Consolas", 8))
        self.log_text.pack(fill="both", expand=True)

    def _build_rgb_tab(self, parent):
        # 1. 即時連線特效 (9 大特效)
        fx_frame = ttk.LabelFrame(parent, text=" 雙燈即時連線特效 (9 款炫彩即時特效) ", padding=4)
        fx_frame.pack(fill="x", pady=2)

        fx_row1 = ttk.Frame(fx_frame)
        fx_row1.pack(fill="x", pady=2)
        ttk.Button(fx_row1, text="🌈 同步彩虹", command=lambda: self.start_effect("sync_rainbow")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row1, text="☯ 互補流光", command=lambda: self.start_effect("complementary")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row1, text="🚨 警車雙閃", command=lambda: self.start_effect("police_strobe")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row1, text="🕯️ 暖色呼吸", command=lambda: self.start_effect("warm_breathing")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row1, text="🌌 極光呼吸", command=lambda: self.start_effect("aurora_breathing")).pack(side="left", expand=True, fill="x", padx=2)

        fx_row2 = ttk.Frame(fx_frame)
        fx_row2.pack(fill="x", pady=2)
        ttk.Button(fx_row2, text="🪩 派對跳閃", command=lambda: self.start_effect("disco_party")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row2, text="🌊 交替流水", command=lambda: self.start_effect("chase_wave")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row2, text="🔥 壁爐跳火", command=lambda: self.start_effect("fire_flicker")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row2, text="⚡ 暴風雷電", command=lambda: self.start_effect("thunder_storm")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(fx_row2, text="💡 全部關閉", command=self.all_off).pack(side="left", expand=True, fill="x", padx=2)

        # 2. 雙燈手動調色卡片
        cards_frame = ttk.Frame(parent)
        cards_frame.pack(fill="x", pady=4)

        card1 = ttk.LabelFrame(cards_frame, text=" ⚙ RGB 模組 1 (左側燈) ", padding=4)
        card1.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.m1_r_val = tk.IntVar(value=0)
        self.m1_g_val = tk.IntVar(value=0)
        self.m1_b_val = tk.IntVar(value=0)
        self.m1_r_pin = tk.StringVar(value=self.config.get("m1_r_pin", "6"))
        self.m1_g_pin = tk.StringVar(value=self.config.get("m1_g_pin", "4"))
        self.m1_b_pin = tk.StringVar(value=self.config.get("m1_b_pin", "5"))
        self._build_module_ui(card1, 1, self.m1_r_val, self.m1_g_val, self.m1_b_val,
                              self.m1_r_pin, self.m1_g_pin, self.m1_b_pin)

        card2 = ttk.LabelFrame(cards_frame, text=" ⚙ RGB 模組 2 (右側燈) ", padding=4)
        card2.pack(side="right", fill="both", expand=True, padx=(4, 0))
        self.m2_r_val = tk.IntVar(value=0)
        self.m2_g_val = tk.IntVar(value=0)
        self.m2_b_val = tk.IntVar(value=0)
        self.m2_r_pin = tk.StringVar(value=self.config.get("m2_r_pin", "11"))
        self.m2_g_pin = tk.StringVar(value=self.config.get("m2_g_pin", "10"))
        self.m2_b_pin = tk.StringVar(value=self.config.get("m2_b_pin", "9"))
        self._build_module_ui(card2, 2, self.m2_r_val, self.m2_g_val, self.m2_b_val,
                              self.m2_r_pin, self.m2_g_pin, self.m2_b_pin)

        # 3. 脫機智慧燒錄區塊 (OR-Tools)
        burn_frame = ttk.LabelFrame(parent, text=" 🚀 脫機獨立大秀：Google OR-Tools CP-SAT 智慧排程燒錄 ", padding=4)
        burn_frame.pack(fill="x", pady=3)

        desc_row = ttk.Frame(burn_frame)
        desc_row.pack(fill="x", pady=2)
        self.desc_entry = ttk.Entry(desc_row)
        self.desc_entry.insert(0, "例如: 派對夜店狂歡 / 睡前放鬆暖光 / 警車巡邏爆閃 / 科技未來極光")
        self.desc_entry.pack(side="left", fill="x", expand=True, padx=2)
        self.desc_entry.bind("<FocusIn>", self._clear_desc_placeholder)
        ttk.Button(desc_row, text="✨ AI 解析風格", command=self.parse_and_select_effects).pack(side="left", padx=2)

        chk_frame = ttk.Frame(burn_frame)
        chk_frame.pack(fill="x", pady=2)
        for idx, (eff_id, eff_name) in enumerate(EFFECT_DEFS):
            r = idx // 4
            c = idx % 4
            cb = ttk.Checkbutton(chk_frame, text=eff_name, variable=self.effect_vars[eff_id])
            cb.grid(row=r, column=c, sticky="w", padx=3, pady=1)

        b_row = ttk.Frame(burn_frame)
        b_row.pack(fill="x", pady=2)
        ttk.Button(b_row, text="全選", command=lambda: self._set_all_checks(True)).pack(side="left", padx=2)
        ttk.Button(b_row, text="全部取消", command=lambda: self._set_all_checks(False)).pack(side="left", padx=2)
        ttk.Label(b_row, text="循環總時長:").pack(side="left", padx=(10, 2))
        self.cycle_sec_var = tk.StringVar(value="30")
        ttk.Combobox(b_row, textvariable=self.cycle_sec_var, values=["15", "20", "30", "45", "60", "90"], width=4, state="readonly").pack(side="left", padx=1)
        ttk.Label(b_row, text="秒").pack(side="left", padx=1)

        self.btn_burn = ttk.Button(b_row, text="🔥 OR-Tools 排程並燒錄至晶片 (免電腦脫機運行)", command=self.burn_standalone)
        self.btn_burn.pack(side="right", fill="x", expand=True, padx=(10, 2))

    def _build_module_ui(self, parent, mod_id, r_var, g_var, b_var, r_pin, g_pin, b_pin):
        pin_frame = ttk.Frame(parent)
        pin_frame.pack(fill="x", pady=2)
        pwm_pins = ["3", "5", "6", "9", "10", "11"]
        for name, pin_var in [("R:", r_pin), ("G:", g_pin), ("B:", b_pin)]:
            ttk.Label(pin_frame, text=name).pack(side="left", padx=1)
            cb = ttk.Combobox(pin_frame, textvariable=pin_var, values=pwm_pins, width=3, state="readonly")
            cb.pack(side="left", padx=1)
            cb.bind("<<ComboboxSelected>>", lambda e: self.save_config(False))

        # 顏色預覽框
        color_box = tk.Label(parent, text="PREVIEW", bg="#000000", fg="white", font=("Arial", 8, "bold"), height=1)
        color_box.pack(fill="x", pady=2)

        def update_color(*args):
            r, g, b = r_var.get(), g_var.get(), b_var.get()
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            color_box.config(bg=hex_color, fg="black" if (r * 0.299 + g * 0.587 + b * 0.114) > 140 else "white")
            self.send_module_color(mod_id, r, g, b)

        for col_name, var in [("紅 (R)", r_var), ("綠 (G)", g_var), ("藍 (B)", b_var)]:
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=col_name, width=6).pack(side="left")
            s = ttk.Scale(row, from_=0, to=255, variable=var, orient="horizontal", command=lambda v: update_color())
            s.pack(side="left", fill="x", expand=True, padx=2)
            lbl = ttk.Label(row, text="0", width=3)
            lbl.pack(side="right")
            var.trace_add("write", lambda *a, l=lbl, v=var: l.config(text=str(v.get())))

        # 常用顏色快選
        pal_frame = ttk.Frame(parent)
        pal_frame.pack(fill="x", pady=2)
        presets = [
            ("紅", 255, 0, 0), ("綠", 0, 255, 0), ("藍", 0, 0, 255),
            ("黃", 255, 255, 0), ("青", 0, 255, 255), ("紫", 255, 0, 255),
            ("白", 255, 255, 255), ("滅", 0, 0, 0)
        ]
        for name, r, g, b in presets:
            ttk.Button(pal_frame, text=name, width=2,
                       command=lambda _r=r, _g=g, _b=b: self._set_slider_color(r_var, g_var, b_var, _r, _g, _b, update_color)
                       ).pack(side="left", expand=True, fill="x", padx=1)

    def _build_matrix_tab(self, parent):
        # 0. 點陣硬體腳位設定列
        pin_bar = ttk.LabelFrame(parent, text=" 📌 MAX7219 點陣硬體腳位設定 (SPI) ", padding=4)
        pin_bar.pack(fill="x", pady=2)
        digital_pins = [str(i) for i in range(2, 14)]
        ttk.Label(pin_bar, text="DIN (資料):").pack(side="left", padx=2)
        ttk.Combobox(pin_bar, textvariable=self.matrix_din_pin, values=digital_pins, width=3, state="readonly").pack(side="left", padx=2)
        ttk.Label(pin_bar, text="CS (片選):").pack(side="left", padx=2)
        ttk.Combobox(pin_bar, textvariable=self.matrix_cs_pin, values=digital_pins, width=3, state="readonly").pack(side="left", padx=2)
        ttk.Label(pin_bar, text="CLK (時脈):").pack(side="left", padx=2)
        ttk.Combobox(pin_bar, textvariable=self.matrix_clk_pin, values=digital_pins, width=3, state="readonly").pack(side="left", padx=2)
        ttk.Button(pin_bar, text="💾 儲存點陣腳位", command=lambda: self.save_config(True)).pack(side="left", padx=10)

        top_split = ttk.Frame(parent)
        top_split.pack(fill="both", expand=True, pady=4)

        # 左側: 8x8 點陣畫布
        canvas_box = ttk.LabelFrame(top_split, text=" 🖱️ 8×8 互動繪圖畫布 (點擊即時同步顯示) ", padding=6)
        canvas_box.pack(side="left", fill="both", expand=True, padx=(0, 6))

        grid_frame = ttk.Frame(canvas_box)
        grid_frame.pack(pady=4)

        self.pixel_buttons = []
        for r in range(8):
            row_btns = []
            for c in range(8):
                btn = tk.Button(
                    grid_frame,
                    width=3,
                    height=1,
                    bg="#222222",
                    activebackground="#ff3333",
                    relief="raised",
                    bd=1,
                    command=lambda _r=r, _c=c: self.toggle_matrix_pixel(_r, _c)
                )
                btn.grid(row=r, column=c, padx=1, pady=1)
                row_btns.append(btn)
            self.pixel_buttons.append(row_btns)

        # 畫布工具列
        c_tool_row = ttk.Frame(canvas_box)
        c_tool_row.pack(fill="x", pady=4)
        ttk.Button(c_tool_row, text="🧹 清空", command=self.matrix_clear_all).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(c_tool_row, text="🌟 全亮", command=self.matrix_fill_all).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(c_tool_row, text="🔄 反轉", command=self.matrix_invert_all).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(c_tool_row, text="💾 設為脫機圖標", command=self.set_current_canvas_as_offline_icon).pack(side="left", expand=True, fill="x", padx=1)

        # 右側: 預設圖案與跑馬燈
        right_box = ttk.Frame(top_split)
        right_box.pack(side="right", fill="both", expand=True, padx=(6, 0))

        # 1. 預設圖形
        presets_box = ttk.LabelFrame(right_box, text=" 🎨 經典像素圖案快捷庫 ", padding=6)
        presets_box.pack(fill="x", pady=2)

        p_row1 = ttk.Frame(presets_box)
        p_row1.pack(fill="x", pady=2)
        p_row2 = ttk.Frame(presets_box)
        p_row2.pack(fill="x", pady=2)

        p_items = list(PRESET_PATTERNS.items())
        for name, bmp in p_items[:4]:
            ttk.Button(p_row1, text=name, command=lambda _b=bmp: self.apply_matrix_bitmap(_b)).pack(side="left", expand=True, fill="x", padx=2)
        for name, bmp in p_items[4:]:
            ttk.Button(p_row2, text=name, command=lambda _b=bmp: self.apply_matrix_bitmap(_b)).pack(side="left", expand=True, fill="x", padx=2)

        # 2. 跑馬燈
        marquee_box = ttk.LabelFrame(right_box, text=" 📜 ASCII 文字平滑跑馬燈 ", padding=6)
        marquee_box.pack(fill="both", expand=True, pady=4)

        m_row1 = ttk.Frame(marquee_box)
        m_row1.pack(fill="x", pady=4)
        ttk.Label(m_row1, text="文字內容:").pack(side="left", padx=2)
        self.entry_marquee = ttk.Entry(m_row1)
        self.entry_marquee.insert(0, "HELLO ARDUINO!")
        self.entry_marquee.pack(side="left", fill="x", expand=True, padx=4)

        m_row2 = ttk.Frame(marquee_box)
        m_row2.pack(fill="x", pady=4)
        ttk.Label(m_row2, text="滾動速度:").pack(side="left", padx=2)
        self.marquee_speed = tk.DoubleVar(value=0.1)
        ttk.Scale(m_row2, from_=0.03, to=0.3, variable=self.marquee_speed, orient="horizontal").pack(side="left", fill="x", expand=True, padx=4)

        m_row3 = ttk.Frame(marquee_box)
        m_row3.pack(fill="x", pady=4)
        self.btn_start_marquee = ttk.Button(m_row3, text="▶ 開始滾動跑馬燈", command=self.start_marquee_text)
        self.btn_start_marquee.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_stop_marquee = ttk.Button(m_row3, text="⏹ 停止跑馬燈", command=self.stop_marquee_text)
        self.btn_stop_marquee.pack(side="right", expand=True, fill="x", padx=2)

    def _clear_desc_placeholder(self, event):
        if "例如" in self.desc_entry.get():
            self.desc_entry.delete(0, tk.END)

    def _set_all_checks(self, val):
        for var in self.effect_vars.values():
            var.set(val)

    def _set_slider_color(self, r_var, g_var, b_var, r, g, b, callback):
        r_var.set(r)
        g_var.set(g)
        b_var.set(b)
        callback()

    def parse_and_select_effects(self):
        text = self.desc_entry.get().strip()
        selected = parse_user_description(text)
        self._set_all_checks(False)
        for sid in selected:
            if sid in self.effect_vars:
                self.effect_vars[sid].set(True)
        self.log(f"✨ AI 解析完成：已自動挑選 {len(selected)} 項風格特效 (ID: {selected})")

    # 8x8 點陣操作
    def toggle_matrix_pixel(self, r, c):
        self.matrix_grid[r][c] = 1 if self.matrix_grid[r][c] == 0 else 0
        self._update_pixel_button(r, c)
        self.send_current_matrix()

    def _update_pixel_button(self, r, c):
        val = self.matrix_grid[r][c]
        btn = self.pixel_buttons[r][c]
        if val == 1:
            btn.config(bg="#ff2222", relief="sunken")
        else:
            btn.config(bg="#222222", relief="raised")

    def matrix_clear_all(self):
        self.stop_marquee_text()
        for r in range(8):
            for c in range(8):
                self.matrix_grid[r][c] = 0
                self._update_pixel_button(r, c)
        self.send_command("CLEAR_MATRIX")

    def matrix_fill_all(self):
        self.stop_marquee_text()
        for r in range(8):
            for c in range(8):
                self.matrix_grid[r][c] = 1
                self._update_pixel_button(r, c)
        self.send_current_matrix()

    def matrix_invert_all(self):
        self.stop_marquee_text()
        for r in range(8):
            for c in range(8):
                self.matrix_grid[r][c] = 1 - self.matrix_grid[r][c]
                self._update_pixel_button(r, c)
        self.send_current_matrix()

    def apply_matrix_bitmap(self, bitmap_8):
        self.stop_marquee_text()
        for r in range(8):
            val = bitmap_8[r]
            for c in range(8):
                bit = 1 if (val & (1 << (7 - c))) != 0 else 0
                self.matrix_grid[r][c] = bit
                self._update_pixel_button(r, c)
        self.send_current_matrix()

    def send_current_matrix(self):
        bytes_8 = []
        for r in range(8):
            row_byte = 0
            for c in range(8):
                if self.matrix_grid[r][c] == 1:
                    row_byte |= (1 << (7 - c))
            bytes_8.append(row_byte)
        cmd = f"MATRIX {' '.join(str(b) for b in bytes_8)}"
        self.send_command(cmd)

    def set_current_canvas_as_offline_icon(self):
        bytes_8 = []
        for r in range(8):
            row_byte = 0
            for c in range(8):
                if self.matrix_grid[r][c] == 1:
                    row_byte |= (1 << (7 - c))
            bytes_8.append(row_byte)
        self.config["matrix_custom_bitmap"] = bytes_8
        self.save_config(show_log=False)
        self.log(f"📌 已將當前畫布設為脫機自訂圖標: {bytes_8} (執行脫機燒錄時將永久固化至晶片！)")
        messagebox.showinfo("成功", f"已將當前畫布設為脫機開機圖標！\n\n點陣數值: {bytes_8}\n當您在第 1 分頁點擊【OR-Tools 智慧排程燒錄】時，此自訂圖標將作為開機簽名圖案一同固化至 Arduino 晶片中！")

    def start_marquee_text(self):
        text = self.entry_marquee.get().strip().upper()
        if not text:
            return
        self.stop_marquee_text()
        self.stop_marquee.clear()
        self.marquee_running = True
        self.marquee_thread = threading.Thread(target=self._marquee_loop, args=(text,), daemon=True)
        self.marquee_thread.start()
        self.log(f"📜 開始跑馬燈滾動: '{text}'")

    def stop_marquee_text(self):
        if self.marquee_running:
            self.stop_marquee.set()
            self.marquee_running = False

    def _marquee_loop(self, text):
        full_columns = [0x00] * 8
        for char in text:
            font_cols = ASCII_FONT.get(char, [0x00, 0x00, 0x00, 0x00, 0x00])
            full_columns.extend(font_cols)
            full_columns.append(0x00)
        full_columns.extend([0x00] * 8)

        total_cols = len(full_columns)
        idx = 0
        while not self.stop_marquee.is_set():
            window_cols = full_columns[idx:idx + 8]
            row_bytes = [0] * 8
            for r in range(8):
                b = 0
                for c in range(8):
                    if (window_cols[c] & (1 << r)) != 0:
                        b |= (1 << (7 - c))
                row_bytes[r] = b

            cmd = f"MATRIX {' '.join(str(x) for x in row_bytes)}"
            self.send_command(cmd)

            # 更新 UI 預覽
            for r in range(8):
                for c in range(8):
                    bit = 1 if (row_bytes[r] & (1 << (7 - c))) != 0 else 0
                    self.matrix_grid[r][c] = bit
            self.root.after(0, self._sync_canvas_ui)

            idx = (idx + 1) % (total_cols - 7)
            time.sleep(self.marquee_speed.get())

    def _sync_canvas_ui(self):
        for r in range(8):
            for c in range(8):
                self._update_pixel_button(r, c)

    # 序列通訊與 RGB 控制
    def auto_detect_and_fill(self, auto_connect=True):
        dev, desc = find_arduino_device()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combobox["values"] = ports
        if dev and dev in ports:
            self.port_combobox.set(dev)
            self.log(f"🔍 智慧偵測到 Arduino: {dev} ({desc})")
            if auto_connect and not self.is_connected:
                self.connect(dev)
        elif self.config.get("last_com_port") in ports:
            last = self.config.get("last_com_port")
            self.port_combobox.set(last)
            if auto_connect and not self.is_connected:
                self.connect(last)

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect()
        else:
            port = self.port_combobox.get()
            if port:
                self.connect(port)
            else:
                messagebox.showwarning("警告", "請選擇有效的 COM 埠！")

    def connect(self, port):
        self.stop_current_effect()
        self.stop_marquee_text()
        try:
            self.ser = serial.Serial(port, 115200, timeout=1.0)
            time.sleep(1.8)
            self.ser.reset_input_buffer()
            self.ser.write(b"PING\n")
            time.sleep(0.2)
            resp = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if "PONG" in resp:
                self.is_connected = True
                self.lbl_status.config(text=f"🟢 已連線 ({port})", foreground="#00aa00")
                self.btn_connect.config(text="🔌 斷開連線")
                self.log(f"✅ 成功與 Arduino Uno ({port}) 建立即時連線 (PING -> PONG)！")
                self.stop_worker = False
                self.worker_thread = threading.Thread(target=self._serial_worker, daemon=True)
                self.worker_thread.start()
                self.save_config(False)
            else:
                self.ser.close()
                self.lbl_status.config(text="❌ 連線無回應", foreground="red")
                self.log(f"⚠️ {port} 無法回應 PING (回應: '{resp}')")
        except Exception as e:
            self.lbl_status.config(text="❌ 連線失敗", foreground="red")
            self.log(f"❌ 無法連接 {port}: {e}")

    def disconnect(self):
        self.stop_current_effect()
        self.stop_marquee_text()
        self.stop_worker = True
        self.is_connected = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.lbl_status.config(text="⚪ 未連線", foreground="gray")
        self.btn_connect.config(text="⚡ 連線")
        self.log("🔌 已斷開序列埠連線")

    def _serial_worker(self):
        while not self.stop_worker and self.is_connected:
            try:
                cmd = self.cmd_queue.get(timeout=0.1)
                if self.ser and self.ser.is_open:
                    self.ser.write((cmd + "\n").encode("utf-8"))
            except queue.Empty:
                pass
            except Exception as e:
                self.log(f"⚠️ 傳送指令異常: {e}")
                break

    def send_command(self, cmd):
        if self.is_connected:
            self.cmd_queue.put(cmd)

    def send_module_color(self, mod_id, r, g, b):
        self.stop_current_effect()
        if mod_id == 1:
            rp = int(self.m1_r_pin.get())
            gp = int(self.m1_g_pin.get())
            bp = int(self.m1_b_pin.get())
        else:
            rp = int(self.m2_r_pin.get())
            gp = int(self.m2_g_pin.get())
            bp = int(self.m2_b_pin.get())

        if self.common_anode.get():
            r = 255 - r
            g = 255 - g
            b = 255 - b

        cmd = f"RGB {rp} {gp} {bp} {r} {g} {b}"
        self.send_command(cmd)

    def all_off(self):
        self.stop_current_effect()
        self.stop_marquee_text()
        self.m1_r_val.set(0)
        self.m1_g_val.set(0)
        self.m1_b_val.set(0)
        self.m2_r_val.set(0)
        self.m2_g_val.set(0)
        self.m2_b_val.set(0)
        self.send_module_color(1, 0, 0, 0)
        self.send_module_color(2, 0, 0, 0)
        self.matrix_clear_all()
        self.log("💡 全部燈光與點陣關閉")

    # 即時連線特效引擎
    def start_effect(self, effect_name):
        self.stop_current_effect()
        self.stop_effect.clear()
        self.current_effect_name = effect_name
        self.effect_thread = threading.Thread(target=self._run_effect_loop, args=(effect_name,), daemon=True)
        self.effect_thread.start()
        self.log(f"✨ 啟動即時特效: {effect_name}")

    def stop_current_effect(self):
        if self.current_effect_name is not None:
            self.stop_effect.set()
            self.current_effect_name = None

    def _run_effect_loop(self, effect_name):
        step = 0
        t0 = time.time()
        while not self.stop_effect.is_set() and self.is_connected:
            dt = time.time() - t0
            step += 1

            if effect_name == "sync_rainbow":
                hue = (dt * 60) % 360
                r, g, b = self._hsv_to_rgb(hue, 1.0, 1.0)
                self._send_both_rgb(r, g, b, r, g, b)
                time.sleep(0.04)

            elif effect_name == "complementary":
                hue1 = (dt * 50) % 360
                hue2 = (hue1 + 180) % 360
                r1, g1, b1 = self._hsv_to_rgb(hue1, 1.0, 1.0)
                r2, g2, b2 = self._hsv_to_rgb(hue2, 1.0, 1.0)
                self._send_both_rgb(r1, g1, b1, r2, g2, b2)
                time.sleep(0.04)

            elif effect_name == "police_strobe":
                phase = int(dt * 8) % 4
                if phase in [0, 1]:
                    self._send_both_rgb(255, 0, 0, 0, 0, 0)
                else:
                    self._send_both_rgb(0, 0, 0, 0, 0, 255)
                time.sleep(0.06)

            elif effect_name == "warm_breathing":
                v = (math.sin(dt * 2.5) + 1.0) / 2.0
                r = int(255 * v)
                g = int(120 * v)
                b = int(20 * v)
                self._send_both_rgb(r, g, b, r, g, b)
                time.sleep(0.03)

            elif effect_name == "aurora_breathing":
                v1 = (math.sin(dt * 2.0) + 1.0) / 2.0
                v2 = (math.cos(dt * 2.0) + 1.0) / 2.0
                self._send_both_rgb(0, int(255 * v1), int(200 * v1), int(180 * v2), 0, int(255 * v2))
                time.sleep(0.03)

            elif effect_name == "disco_party":
                r1, g1, b1 = [random.choice([0, 255]) for _ in range(3)]
                r2, g2, b2 = [random.choice([0, 255]) for _ in range(3)]
                self._send_both_rgb(r1, g1, b1, r2, g2, b2)
                time.sleep(0.12)

            elif effect_name == "chase_wave":
                phase = math.sin(dt * 4)
                v1 = max(0.0, phase)
                v2 = max(0.0, -phase)
                self._send_both_rgb(0, int(255 * v1), int(255 * v1), int(255 * v2), 0, int(128 * v2))
                time.sleep(0.03)

            elif effect_name == "fire_flicker":
                flicker = random.randint(180, 255)
                r = flicker
                g = max(0, int(flicker * 0.4 + random.randint(-20, 20)))
                b = 0
                self._send_both_rgb(r, g, b, r, g, b)
                time.sleep(0.05)

            elif effect_name == "thunder_storm":
                if random.random() < 0.15:
                    self._send_both_rgb(255, 255, 255, 255, 255, 255)
                    time.sleep(random.uniform(0.03, 0.08))
                    self._send_both_rgb(0, 0, 0, 0, 0, 0)
                else:
                    self._send_both_rgb(0, 0, 20, 0, 0, 20)
                    time.sleep(0.1)

    def _send_both_rgb(self, r1, g1, b1, r2, g2, b2):
        rp1, gp1, bp1 = int(self.m1_r_pin.get()), int(self.m1_g_pin.get()), int(self.m1_b_pin.get())
        rp2, gp2, bp2 = int(self.m2_r_pin.get()), int(self.m2_g_pin.get()), int(self.m2_b_pin.get())

        if self.common_anode.get():
            r1, g1, b1 = 255 - r1, 255 - g1, 255 - b1
            r2, g2, b2 = 255 - r2, 255 - g2, 255 - b2

        self.send_command(f"RGB {rp1} {gp1} {bp1} {r1} {g1} {b1}")
        self.send_command(f"RGB {rp2} {gp2} {bp2} {r2} {g2} {b2}")

    def _hsv_to_rgb(self, h, s, v):
        c = v * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = v - c
        if h < 60:
            r1, g1, b1 = c, x, 0
        elif h < 120:
            r1, g1, b1 = x, c, 0
        elif h < 180:
            r1, g1, b1 = 0, c, x
        elif h < 240:
            r1, g1, b1 = 0, x, c
        elif h < 300:
            r1, g1, b1 = x, 0, c
        else:
            r1, g1, b1 = c, 0, x
        return int((r1 + m) * 255), int((g1 + m) * 255), int((b1 + m) * 255)

    # 脫機燒錄功能
    def burn_standalone(self):
        port = self.port_combobox.get()
        if not port:
            messagebox.showwarning("警告", "請選擇 COM 埠！")
            return

        selected_ids = [eid for eid, var in self.effect_vars.items() if var.get()]
        if not selected_ids:
            messagebox.showwarning("警告", "請至少勾選一項特效！")
            return

        # 燒錄前先儲存最新設定 (含 RGB 與 點陣腳位、自訂圖案)
        self.save_config(show_log=False)

        # 燒錄前必須先斷開 serial 連線
        was_connected = self.is_connected
        self.disconnect()

        self.btn_burn.config(state="disabled", text="⏳ 正在呼叫 Google OR-Tools 智慧排程並編譯燒錄...")
        self.log("🚀 啟動 Google OR-Tools CP-SAT 智慧排程最佳化引擎 (雙 RGB + 8x8 點陣同步燒錄)...")

        def _do_burn():
            try:
                cycle_sec = int(self.cycle_sec_var.get())
                desc = self.desc_entry.get().strip()
                if "例如" in desc:
                    desc = ""

                cmd = [
                    PYTHON312_PATH,
                    os.path.join(WORKSPACE_DIR, "standalone_flash_optimizer.py"),
                    "--port", port,
                    "--cycle-time", str(cycle_sec),
                    "--effects", ",".join(str(i) for i in selected_ids)
                ]
                if desc:
                    cmd.extend(["--description", desc])

                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                out = p.stdout + "\n" + p.stderr
                for line in out.splitlines():
                    if line.strip():
                        self.log(f"[OR-Tools] {line}")

                if p.returncode == 0:
                    self.log("🎉 脫機韌體燒錄成功！雙全彩 RGB 與 8x8 點陣已載入獨立大秀！")
                    messagebox.showinfo("成功", "脫機韌體燒錄成功！現在即使拔除電腦 USB，只要接上行動電源，雙燈與點陣即可自動循環播放！")
                else:
                    self.log(f"❌ 燒錄失敗 (錯誤碼 {p.returncode})")
                    messagebox.showerror("失敗", f"燒錄失敗，請檢視執行日誌！")
            except Exception as e:
                self.log(f"❌ 燒錄過程發生異常: {e}")
            finally:
                self.root.after(0, lambda: self.btn_burn.config(state="normal", text="🔥 OR-Tools 排程並燒錄至晶片 (免電腦脫機運行)"))
                if was_connected:
                    self.root.after(1000, lambda: self.connect(port))

        threading.Thread(target=_do_burn, daemon=True).start()

    def log(self, msg):
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    def on_close(self):
        self.save_config(False)
        self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ArduinoGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
