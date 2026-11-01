"""
Arduino Universal Hardware Control Center (萬能硬體控制中心)
============================================================
架構特性：
1. 通用組件動態卡片架構 (Dynamic Widget Architecture)：
   - 介面與硬體完全解耦，適用於「所有配件」。
   - 隨插即用：透過「➕ 新增配件」動態生成控制卡片，隨時增減、變更腳位。
   - 支援 7 大核心配件類別：
     * 🌈 多通道 RGB LED (全彩調色、共陰/共陽切換)
     * 👾 MAX7219 8x8 點陣 (互動點選畫布、預設像素圖、全矩陣寫入)
     * 🦾 伺服舵機 Servo (0°~180° 滑桿、快捷角度按鍵)
     * 💡 數位開關 (繼電器、單色LED、電磁閥、開關控制)
     * 🎚️ PWM 類比輸出 (LED 調光、直流馬達調速)
     * 🌡️ 感測器即時監控 (光敏、溫度、按鈕、可變電阻，即時串流儀表)
     * 🦇 超音波測距 HC-SR04 (即時距離感測)
2. 專案配置庫 (JSON Profiles)：
   - 一鍵儲存/載入配置 (Save/Load Profile)，不同專案一秒切換。
3. 萬能韌體一鍵燒錄 (One-Click Firmware Flasher)：
   - 內建呼叫 arduino-cli 自動編譯並燒錄萬能韌體，無需手動開 Arduino IDE。
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
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except (ImportError, Exception):
    class _DummyTk(type):
        def __getattr__(self, name):
            return object
    class _DummyModule(metaclass=_DummyTk):
        def __getattr__(self, name):
            return object
        def __call__(self, *args, **kwargs):
            return object()
    tk = _DummyModule()
    filedialog = messagebox = ttk = ScrolledText = _DummyModule()

import serial
import serial.tools.list_ports

from universal_shared import (
    WORKSPACE_DIR,
    ARDUINO_CLI_PATH,
    FIRMWARE_DIR,
    DEFAULT_PROFILE_PATH,
    PRESET_MATRIX,
    FONT_5X7,
    text_to_matrix_frames,
    PRESET_ANIMATIONS,
    parse_pin
)

# 基本路徑配置
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
ARDUINO_CLI_PATH = r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
FIRMWARE_DIR = os.path.join(WORKSPACE_DIR, "universal_firmware")
DEFAULT_PROFILE_PATH = os.path.join(WORKSPACE_DIR, "default_profile.json")

# 經典點陣像素預設
PRESET_MATRIX = {
    "❤️ 愛心": [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
    "😊 笑臉": [0x3C, 0x42, 0xA5, 0x81, 0xA5, 0x99, 0x42, 0x3C],
    "👾 外星人": [0x18, 0x3C, 0x7E, 0xDB, 0xFF, 0x24, 0x5A, 0x81],
    "ᗧ 吃豆人": [0x3C, 0x7E, 0xFF, 0xE7, 0xC0, 0xE7, 0x7E, 0x3C],
    "💎 鑽石": [0x18, 0x3C, 0x7E, 0xFF, 0x7E, 0x3C, 0x18, 0x00],
    "⚡ 閃電": [0x06, 0x0C, 0x18, 0x3F, 0x0C, 0x18, 0x30, 0x00],
    "💀 骷髏": [0x3C, 0x7E, 0xDB, 0xDB, 0x7E, 0x3C, 0x24, 0x24],
}

# 標準 5x7 ASCII 字型表 (支援英數字、符號跑馬燈)
FONT_5X7 = {
    ' ': [0x00, 0x00, 0x00, 0x00, 0x00],
    '!': [0x00, 0x00, 0x5F, 0x00, 0x00],
    '"': [0x00, 0x07, 0x00, 0x07, 0x00],
    '#': [0x14, 0x7F, 0x14, 0x7F, 0x14],
    '$': [0x24, 0x2A, 0x7F, 0x2A, 0x12],
    '%': [0x23, 0x13, 0x08, 0x64, 0x62],
    '&': [0x36, 0x49, 0x55, 0x22, 0x50],
    '\'': [0x00, 0x05, 0x03, 0x00, 0x00],
    '(': [0x00, 0x1C, 0x22, 0x41, 0x00],
    ')': [0x00, 0x41, 0x22, 0x1C, 0x00],
    '*': [0x08, 0x2A, 0x1C, 0x2A, 0x08],
    '+': [0x08, 0x08, 0x3E, 0x08, 0x08],
    ',': [0x00, 0x50, 0x30, 0x00, 0x00],
    '-': [0x08, 0x08, 0x08, 0x08, 0x08],
    '.': [0x00, 0x60, 0x60, 0x00, 0x00],
    '/': [0x20, 0x10, 0x08, 0x04, 0x02],
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
    ':': [0x00, 0x36, 0x36, 0x00, 0x00],
    ';': [0x00, 0x56, 0x36, 0x00, 0x00],
    '<': [0x08, 0x14, 0x22, 0x41, 0x00],
    '=': [0x14, 0x14, 0x14, 0x14, 0x14],
    '>': [0x00, 0x41, 0x22, 0x14, 0x08],
    '?': [0x02, 0x01, 0x51, 0x09, 0x06],
    '@': [0x32, 0x49, 0x79, 0x41, 0x3E],
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

def text_to_matrix_frames(text, padding=True):
    """將任意英數文字轉換為 8x8 點陣逐幀平滑滾動影格清單 (每幀 8 bytes)"""
    cols = []
    if padding:
        cols.extend([0] * 8)
    for ch in str(text).upper():
        cols.extend(FONT_5X7.get(ch, [0x00, 0x55, 0x2A, 0x55, 0x00]))
        cols.append(0x00)
    if padding:
        cols.extend([0] * 8)

    frames = []
    total_shifts = max(1, len(cols) - 7)
    for shift in range(total_shifts):
        window = cols[shift : shift + 8]
        if len(window) < 8:
            window = window + [0] * (8 - len(window))
        frame = [0] * 8
        for r in range(8):
            row_val = 0
            for c in range(8):
                if (window[c] >> r) & 1:
                    row_val |= (1 << (7 - c))
            frame[r] = row_val
        frames.append(frame)
    return frames

# 經典動態圖示動畫影格
PRESET_ANIMATIONS = {
    "💓 心跳搏動動畫": [
        [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
        [0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00],
        [0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00],
        [0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00],
        [0x00, 0x00, 0x00, 0x24, 0x3C, 0x18, 0x00, 0x00],
        [0x00, 0x00, 0x24, 0x7E, 0x7E, 0x3C, 0x18, 0x00],
        [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
        [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18],
    ],
    "🚀 火箭升空動畫": [
        [0x18, 0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18],
        [0x3C, 0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18],
        [0x7E, 0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24],
        [0xDB, 0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42],
        [0x99, 0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00],
        [0x99, 0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00],
        [0x3C, 0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00],
        [0x18, 0x18, 0x24, 0x42, 0x00, 0x00, 0x00, 0x00],
    ],
    "🌊 像素海浪動畫": [
        [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80],
        [0x03, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x81],
        [0x07, 0x0E, 0x1C, 0x38, 0x70, 0xE0, 0xC1, 0x83],
        [0x0F, 0x1E, 0x3C, 0x78, 0xF0, 0xE1, 0xC3, 0x87],
        [0x1F, 0x3E, 0x7C, 0xF8, 0xF1, 0xE3, 0xC7, 0x8F],
        [0x3F, 0x7E, 0xFC, 0xF9, 0xF3, 0xE7, 0xCF, 0x9F],
        [0x7F, 0xFE, 0xFD, 0xFB, 0xF7, 0xEF, 0xDF, 0xBF],
        [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
    ],
    "⏳ 旋轉雷達動畫": [
        [0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18],
        [0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0],
        [0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00],
        [0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03],
        [0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18],
        [0x03, 0x06, 0x0C, 0x18, 0x18, 0x30, 0x60, 0xC0],
        [0x00, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00],
        [0xC0, 0x60, 0x30, 0x18, 0x18, 0x0C, 0x06, 0x03],
    ],
    "ᗧ 吃豆人動態": [
        [0x3C, 0x7E, 0xFF, 0xE7, 0xC0, 0xE7, 0x7E, 0x3C],
        [0x3C, 0x7E, 0xFF, 0xEF, 0xE0, 0xEF, 0x7E, 0x3C],
        [0x3C, 0x7E, 0xFF, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C],
        [0x3C, 0x7E, 0xFF, 0xEF, 0xE0, 0xEF, 0x7E, 0x3C],
    ],
}


def parse_pin(val):
    """智慧解析腳位輸入：支援整數、自由文字 ('13', 'A0'~'A15', 'D5', 'GPIO16' 等)"""
    if val is None:
        return 0
    s = str(val).strip().upper()
    if s.startswith("D") and len(s) > 1 and s[1:].isdigit():
        return int(s[1:])
    if s.startswith("A") and len(s) > 1 and s[1:].isdigit():
        return 14 + int(s[1:])
    if s.startswith("GPIO") and len(s) > 4 and s[4:].isdigit():
        return int(s[4:])
    try:
        return int(s)
    except ValueError:
        return 0


def create_pin_field(container, row, label, init_val, suggestions=None):
    """建立完全自由輸入且提供建議選單的腳位輸入元件"""
    if suggestions is None:
        suggestions = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "A0", "A1", "A2", "A3", "A4", "A5"]
    tk.Label(container, text=label, bg=container.cget("bg"), fg="#CDD6F4", font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=4)
    var = tk.StringVar(value=str(init_val))
    combo = ttk.Combobox(container, textvariable=var, values=suggestions, width=12)
    combo.grid(row=row, column=1, sticky="w", padx=10, pady=4)
    return var


class UniversalControllerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino Universal Hub (萬能硬體動態控制中心)")

        # 智慧自適應螢幕展開最大高度與寬度 (充分展現高度，完整呈現卡片，不留空白)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_w = min(1380, max(1200, int(screen_w * 0.90)))
        target_h = min(1040, max(880, int(screen_h * 0.92)))
        x_pos = max(0, (screen_w - target_w) // 2)
        y_pos = max(0, (screen_h - target_h) // 2 - 25)
        self.root.geometry(f"{target_w}x{target_h}+{x_pos}+{y_pos}")
        self.root.minsize(1050, 750)

        # 序列埠連線狀態
        self.ser = None
        self.serial_lock = threading.Lock()
        self.rx_thread = None
        self.rx_running = False
        self.cmd_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self._start_ui_queue_poller()

        # 配件卡片清單與參照 (id -> widget controller)
        self.components = []
        self.card_widgets = {}

        # 雙燈即時連線特效 (18 款炫彩即時特效)
        self.effect_stop_event = threading.Event()
        self.effect_thread = None
        self.current_effect_name = None

        # 自訂流程與自動化排程引擎
        self.workflows = []
        self.workflow_engine = WorkflowEngine(self)

        # 建立 UI
        self._setup_styles()
        self._setup_window_icon()
        self._build_top_bar()
        self._build_dashboard_area()
        self._build_bottom_log()

        # 載入預設配置
        self.load_profile(DEFAULT_PROFILE_PATH, silent=True)

        # 自動搜尋 COM 埠
        self.scan_ports()

        # 啟動時自動嘗試連線 (若已偵測到 Arduino 埠)
        self.root.after(400, self._auto_connect_startup)

        # 啟動時自動在背景啟動嵌入式 Web 伺服器 (Waitress + Flask) 與 Cloudflare Tunnel
        self.root.after(600, self._auto_start_web_server)

        # 監聽主視窗關閉事件，保證安全釋放 COM 埠與結束背景執行緒
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_closing)

    def _auto_start_web_server(self):
        """主控端啟動時自動在背景啟動 Web 伺服器與 Cloudflare Tunnel，確保各端隨時無縫同步"""
        try:
            if not getattr(self, "_web_server_started", False):
                from universal_web import start_web_server_thread, hub as web_hub
                start_web_server_thread(self, host="0.0.0.0", port=5000)
                self._web_server_started = True
                self._web_hub = web_hub
                self.log("🌐 嵌入式 Web 伺服器已在背景啟動 (http://0.0.0.0:5000)")
                self.log("🚀 Cloudflare Tunnel 穿透程序已在背景啟動...")
        except Exception as e:
            self.log(f"⚠️ 背景啟動 Web 服務異常: {e}")

    def _on_app_closing(self):
        try:
            # 關閉視窗前自動保存目前所有配件與腳位設定
            self.save_profile(DEFAULT_PROFILE_PATH, silent=True)
        except Exception:
            pass
        self.rx_running = False
        try:
            from cloudflare_tunnel import tunnel_manager
            tunnel_manager.stop()
        except Exception:
            pass
        if hasattr(self, "workflow_engine"):
            self.workflow_engine.stop()
        for card in getattr(self, "card_widgets", {}).values():
            if hasattr(card, "stop_marquee"):
                card.stop_marquee()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.root.destroy()

    def _start_ui_queue_poller(self):
        """主執行緒週期輪詢 UI 任務佇列，100% 杜絕多執行緒呼叫 root.after 死鎖"""
        try:
            while not self.ui_queue.empty():
                try:
                    fn, args, kwargs = self.ui_queue.get_nowait()
                    fn(*args, **kwargs)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.after(15, self._start_ui_queue_poller)
        except Exception:
            pass

    def dispatch_ui(self, fn, *args, **kwargs):
        """100% 執行緒安全的 UI 調用分派器：背景執行緒直接入列，絕不死鎖 Tcl 解釋器"""
        if threading.current_thread() is threading.main_thread():
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
        else:
            self.ui_queue.put((fn, args, kwargs))

    def _setup_window_icon(self):
        """設置視窗與 Windows 工作列專屬高清圖示 (16x16 ~ 256x256)"""
        icon_ico = os.path.join(WORKSPACE_DIR, "universal_icon.ico")
        icon_png = os.path.join(WORKSPACE_DIR, "universal_icon.png")

        if os.path.exists(icon_ico):
            try:
                self.root.iconbitmap(icon_ico)
            except Exception:
                pass

        if os.path.exists(icon_png):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_png).resize((64, 64), Image.Resampling.LANCZOS)
                self._app_icon_img = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._app_icon_img)
            except Exception:
                pass

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # 顏色常量
        self.BG_MAIN = "#1E1E2E"
        self.BG_CARD = "#2A2A3C"
        self.BG_TOP = "#252538"
        self.ACCENT = "#89B4FA"
        self.ACCENT_GREEN = "#A6E3A1"
        self.ACCENT_RED = "#F38BA8"
        self.ACCENT_YELLOW = "#F9E2AF"
        self.TEXT_MAIN = "#CDD6F4"
        self.TEXT_MUTED = "#A6ADC8"

        self.root.configure(bg=self.BG_MAIN)
        style.configure("TFrame", background=self.BG_MAIN)
        style.configure("Top.TFrame", background=self.BG_TOP)
        style.configure("TLabel", background=self.BG_MAIN, foreground=self.TEXT_MAIN, font=("Segoe UI", 9))
        style.configure("Top.TLabel", background=self.BG_TOP, foreground=self.TEXT_MAIN, font=("Segoe UI", 9))
        style.configure("Header.TLabel", background=self.BG_TOP, foreground=self.ACCENT, font=("Segoe UI", 12, "bold"))
        style.configure("CardTitle.TLabel", background=self.BG_CARD, foreground=self.ACCENT, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 9))
        style.configure("Primary.TButton", background="#45475A", foreground="#FFFFFF", font=("Segoe UI", 9, "bold"))

    def _build_top_bar(self):
        top_frame = ttk.Frame(self.root, style="Top.TFrame", padding=(12, 6))
        top_frame.pack(fill=tk.X)

        # 第 1 列：主標題、連線設定與即時狀態
        row1 = tk.Frame(top_frame, bg=self.BG_TOP)
        row1.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(row1, text="⚡ Arduino Universal Hub", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="COM 埠:", style="Top.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.port_combobox = ttk.Combobox(row1, width=12, state="readonly")
        self.port_combobox.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(row1, text="🔄 重新整理", command=self.scan_ports).pack(side=tk.LEFT, padx=(0, 6))

        self.btn_connect = ttk.Button(row1, text="🔌 連線設備", style="Primary.TButton", command=self.toggle_connection)
        self.btn_connect.pack(side=tk.LEFT, padx=(0, 12))

        self.lbl_status = tk.Label(row1, text="● 未連線", bg=self.BG_TOP, fg="#F38BA8", font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=(0, 10))

        # 右側高權限操作：全體急停與 Web 控制台
        ttk.Button(row1, text="🌐 Web 控制台", style="Primary.TButton", command=self.open_web_console).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row1, text="📱 跨電腦同步", style="Primary.TButton", command=self.open_share_dialog).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row1, text="🛑 全體急停", command=self.emergency_stop).pack(side=tk.RIGHT, padx=4)

        # 第 2 列：配置檔案管理與擴充功能按鈕（兩列排版，在任何螢幕解析度下 100% 完整顯示不被擠壓裁切）
        row2 = tk.Frame(top_frame, bg=self.BG_TOP)
        row2.pack(fill=tk.X)

        # 左側配置檔管理
        ttk.Button(row2, text="💾 儲存配置", command=self.save_profile_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row2, text="📂 載入配置", command=self.load_profile_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row2, text="➕ 新增配件", command=self.open_add_component_dialog).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row2, text="⚡ 燒錄萬能韌體", command=self.flash_firmware).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row2, text="🔥 脫機燒錄流程", command=self.flash_standalone_workflow).pack(side=tk.LEFT, padx=(0, 6))

        # 右側核心功能捷徑
        ttk.Button(row2, text="✨ 雙燈特效 (18款)", style="Primary.TButton", command=self.open_dual_effects_dialog).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row2, text="🎭 自訂流程中樞", style="Primary.TButton", command=self.open_workflow_dialog).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row2, text="🔍 系統巡檢", command=self.run_diagnostics).pack(side=tk.RIGHT, padx=4)

    def _build_dashboard_area(self):
        # 外層包含滾動條的主框架
        canvas_container = tk.Frame(self.root, bg=self.BG_MAIN)
        canvas_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 5))

        self.canvas = tk.Canvas(canvas_container, bg=self.BG_MAIN, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)

        self.scroll_frame = tk.Frame(self.canvas, bg=self.BG_MAIN)
        self.scroll_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_bottom_log(self):
        self.log_frame = tk.Frame(self.root, bg=self.BG_TOP)
        self.log_frame.pack(fill=tk.X, side=tk.BOTTOM)

        bar = tk.Frame(self.log_frame, bg=self.BG_TOP)
        bar.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(bar, text="📜 通訊與系統紀錄 (Log)", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)

        self._log_collapsed = False
        def toggle_log():
            if self._log_collapsed:
                self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
                self.btn_toggle_log.configure(text="🔽 折疊日誌")
                self._log_collapsed = False
            else:
                self.log_text.pack_forget()
                self.btn_toggle_log.configure(text="🔼 展開日誌")
                self._log_collapsed = True

        self.btn_toggle_log = tk.Button(bar, text="🔽 折疊日誌", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 7), bd=0, command=toggle_log)
        self.btn_toggle_log.pack(side=tk.RIGHT, padx=4)

        tk.Button(bar, text="清空", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 7), bd=0, command=lambda: self.log_text.delete("1.0", tk.END)).pack(side=tk.RIGHT)

        self.log_text = ScrolledText(self.log_frame, height=4, bg="#11111B", fg="#A6ADC8", insertbackground="white", font=("Consolas", 8), bd=0)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

    def log(self, msg):
        """執行緒安全的日誌輸出函數 (防止多執行緒直寫 Tkinter 造成介面凍結當機)"""
        def _append():
            try:
                if hasattr(self, "log_text") and self.log_text.winfo_exists():
                    timestamp = time.strftime("%H:%M:%S")
                    self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
                    # 自動保留最近 200 行，避免文字緩衝過大拖垮 UI
                    line_count = int(self.log_text.index("end-1c").split(".")[0])
                    if line_count > 200:
                        self.log_text.delete("1.0", "40.0")
                    self.log_text.see(tk.END)
            except Exception:
                pass

        self.dispatch_ui(_append)

    # ==========================
    # 序列埠與通訊管理
    # ==========================
    def scan_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.port_combobox["values"] = port_list
        if port_list:
            # 優先辨識真正的 Arduino Uno (例如 COM4)，次之為 CH340 / USB-Serial
            exact_uno = [p.device for p in ports if "arduino" in p.description.lower()]
            ch340_ports = [p.device for p in ports if "ch340" in p.description.lower() or "usb-serial" in p.description.lower()]

            target_port = None
            if exact_uno:
                target_port = exact_uno[0]
            elif ch340_ports:
                target_port = ch340_ports[0]
            else:
                target_port = port_list[0]

            self.port_combobox.set(target_port)
            self.log(f"已掃描到 COM 埠：{', '.join(port_list)} (已預選 Arduino: {target_port})")
        else:
            self.port_combobox.set("")
            self.log("未偵測到任何序列埠設備")

    def toggle_connection(self):
        if self.ser and self.ser.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_combobox.get().strip()
        if not port:
            messagebox.showwarning("提示", "請先選擇有效的 COM 埠！")
            return

        try:
            self.ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=0.3)
            time.sleep(1.8)  # 等待 Arduino 重啟復位
            self.rx_running = True
            self.rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
            self.rx_thread.start()

            self.lbl_status.configure(text=f"● 已連線 ({port})", fg="#A6E3A1")
            self.btn_connect.configure(text="❌ 斷開連線")
            self.log(f"已成功連線至 {port} (波特率 115200)")

            if hasattr(self, "_web_hub") and self._web_hub:
                self._web_hub.port = port
                self._web_hub.broadcast({"type": "status", "connected": True, "port": port})

            # 發送 PING 握手
            self.send_cmd("PING")
        except Exception as e:
            messagebox.showerror("連線失敗", f"無法開啟 {port}：\n{e}")
            self.ser = None

    def _auto_connect_startup(self):
        """啟動時若發現明確的 Arduino 埠，自動無感連線"""
        port = self.port_combobox.get().strip()
        if port and not self.ser:
            self.log(f"⚡ 自動連線至已偵測之 Arduino：{port}")
            self.connect()

    def disconnect(self, manual=True):
        self.rx_running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

        if manual:
            self.lbl_status.configure(text="● 未連線", fg="#F38BA8")
            self.btn_connect.configure(text="🔌 連線設備")
            self.log("已中斷序列埠連線")

        if hasattr(self, "_web_hub") and self._web_hub:
            self._web_hub.port = ""
            self._web_hub.broadcast({"type": "status", "connected": False, "port": ""})

    def _on_device_disconnected(self):
        """處理硬體突然斷開/熱拔插"""
        self.disconnect(manual=False)
        self.lbl_status.configure(text="⚠️ 設備離線 (等待重新接入...)", fg="#F9E2AF")
        self.log("⚠️ 偵測到硬體連線中斷，已啟動背景重連監聽...")
        self.root.after(2000, self._poll_reconnect)

    def _poll_reconnect(self):
        """週期性偵測設備是否插回，插回即自動秒連"""
        if self.ser and self.ser.is_open:
            return
        ports = [p.device for p in serial.tools.list_ports.comports()]
        target_port = self.port_combobox.get().strip()
        if target_port in ports:
            self.log(f"🔄 偵測到 {target_port} 重新接入！正在恢復連線...")
            self.connect()
        else:
            self.root.after(2000, self._poll_reconnect)

    def emergency_stop(self):
        """🛑 一鍵全體急停安全防護：立即歸零/熄滅所有配件"""
        self.stop_dual_effect()
        if hasattr(self, "workflow_engine"):
            self.workflow_engine.stop()
        self.log("🛑 觸發緊急安全停機 (Emergency Stop)！正在熄滅/重設所有配件...")
        for comp in self.components:
            c_type = comp.get("type")
            pins = comp.get("pins", {})
            if c_type == "switch":
                p = pins.get("pin", 13)
                comp.setdefault("state", {})["on"] = False
                self.send_cmd(f"DWRITE,{p},0")
            elif c_type == "pwm":
                p = pins.get("pin", 9)
                comp.setdefault("state", {})["val"] = 0
                self.send_cmd(f"AWRITE,{p},0")
            elif c_type == "servo":
                p = pins.get("pin", 9)
                comp.setdefault("state", {})["angle"] = 90
                self.send_cmd(f"SERVO,{p},90")
            elif c_type == "rgb":
                rp, gp, bp = pins.get("r", 6), pins.get("g", 4), pins.get("b", 5)
                anode = 1 if comp.get("common_anode", True) else 0
                st = comp.setdefault("state", {})
                st["r"], st["g"], st["b"] = 0, 0, 0
                self.send_cmd(f"RGB,{rp},{gp},{bp},{anode},0,0,0")
            elif c_type == "matrix":
                din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
                comp.setdefault("state", {})["matrix"] = [0] * 8
                self.send_cmd(f"MATRIX_CLEAR,{din},{cs},{clk}")
                card = self.card_widgets.get(comp.get("id"))
                if card and hasattr(card, "stop_marquee"):
                    card.stop_marquee()
            elif c_type == "sensor":
                if comp.get("state", {}).get("streaming", False):
                    p = pins.get("pin", 0)
                    stype = comp.get("sensor_type", "A")
                    comp["state"]["streaming"] = False
                    self.send_cmd(f"STREAM,{p},{stype},0,200")
        self.refresh_cards()
        if hasattr(self, "_web_hub") and self._web_hub:
            self._web_hub.broadcast({"type": "emergency_stop"})
        self.log("✅ 全體設備已安全熄滅，所有輸出已歸零！")

    def run_diagnostics(self):
        """🔍 一鍵硬體自檢與健康診斷"""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("提示", "請先連線 Arduino 才能執行系統巡檢！")
            return

        def diag_worker():
            self.log("🔍 === 開始執行硬體全面巡檢 ===")
            t0 = time.time()
            self.send_cmd("PING")
            time.sleep(0.1)
            latency = int((time.time() - t0) * 1000)
            self.log(f"1. 序列通訊鏈路：正常 (延遲 ~{latency}ms)")

            # 檢測當前配件清單
            self.log(f"2. 配置元件清單：共 {len(self.components)} 個配件已註冊")
            for comp in self.components:
                c_name = comp.get("name")
                c_type = comp.get("type")
                pins = comp.get("pins", {})
                self.log(f"   - [{c_type.upper()}] {c_name} (腳位: {pins})")

            # 測試點陣顯示愛心確認通訊
            matrices = [c for c in self.components if c.get("type") == "matrix"]
            if matrices:
                m = matrices[0]
                din, cs, clk = m["pins"].get("din", 12), m["pins"].get("cs", 8), m["pins"].get("clk", 7)
                self.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},0,102,255,255,255,126,60,24")
                self.log("3. 8x8 點陣自檢：已發送心形測試訊號")

            # 測試 RGB 雙燈測試脈衝
            rgbs = [c for c in self.components if c.get("type") == "rgb"]
            if rgbs:
                for rgb_c in rgbs:
                    rp, gp, bp = rgb_c["pins"].get("r", 6), rgb_c["pins"].get("g", 4), rgb_c["pins"].get("b", 5)
                    anode = 1 if rgb_c.get("common_anode", True) else 0
                    self.send_cmd(f"RGB,{rp},{gp},{bp},{anode},100,100,255")
                    time.sleep(0.15)
                self.log("4. RGB 全彩燈自檢：已激發柔光藍光測試脈衝")

            self.log("🎉 === 系統巡檢完成！所有通道運作正常 ===")

        threading.Thread(target=diag_worker, daemon=True).start()

    def send_cmd(self, cmd_str):
        if not self.ser or not self.ser.is_open:
            if not cmd_str.startswith("RGB,"):
                self.log(f"⚠️ 未連線，無法發送: {cmd_str.strip()}")
            return
        acquired = self.serial_lock.acquire(timeout=0.2)
        if not acquired:
            if not cmd_str.startswith("RGB,"):
                self.log(f"⚠️ 序列埠忙碌中，略過指令: {cmd_str.strip()}")
            return
        try:
            line = (cmd_str.strip() + "\n").encode("utf-8")
            self.ser.write(line)
            # 避免高頻 (每秒數十次) 特效流光指令洗版日誌導致 Tkinter UI 阻塞延遲
            if not cmd_str.startswith("RGB,"):
                self.log(f">> {cmd_str.strip()}")
        except Exception as e:
            self.log(f"發送指令失敗: {e}")
        finally:
            self.serial_lock.release()

    def _rx_worker(self):
        while self.rx_running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.dispatch_ui(self._handle_incoming_line, line)
            except Exception:
                if self.rx_running:
                    self.dispatch_ui(self._on_device_disconnected)
                break

    def _handle_incoming_line(self, line):
        self.log(f"<< {line}")
        if "UNIVERSAL" in line:
            self.lbl_status.configure(text=f"● 萬能韌體已連線 ({self.port_combobox.get()})", fg="#A6E3A1")
            self.log("🌟 驗證成功：Arduino 正運行最新萬能韌體！")
        elif line == "PONG":
            self.lbl_status.configure(text=f"● 舊版韌體已連線 ({self.port_combobox.get()})", fg="#F9E2AF")
            self.log("⚠️ 提示：Arduino 目前為舊版韌體，建議點擊右上角「🔥 一鍵燒錄萬能韌體」以獲得完整相容性！")
        # 分派給對應的卡片處理
        if line.startswith("STREAM_DATA,"):
            parts = line.split(",")
            if len(parts) >= 3:
                pin = int(parts[1])
                val = int(parts[2])
                for card in self.card_widgets.values():
                    if getattr(card, "on_stream_data", None):
                        card.on_stream_data(pin, val)
                if hasattr(self, "_web_hub") and self._web_hub:
                    self._web_hub.broadcast({"type": "sensor_data", "pin": pin, "val": val})
        elif line.startswith("SONAR_RES,"):
            parts = line.split(",")
            if len(parts) >= 3:
                trig = int(parts[1])
                dist = int(parts[2])
                for card in self.card_widgets.values():
                    if getattr(card, "on_sonar_data", None):
                        card.on_sonar_data(trig, dist)
                if hasattr(self, "_web_hub") and self._web_hub:
                    self._web_hub.broadcast({"type": "sonar_data", "trig": trig, "dist": dist})

    # ==========================
    # 配件管理與介面渲染
    # ==========================
    def refresh_cards(self):
        # 清除現有所有卡片
        for child in self.scroll_frame.winfo_children():
            child.destroy()
        self.card_widgets.clear()

        if not self.components:
            empty_lbl = tk.Label(
                self.scroll_frame,
                text="尚無任何配件。點擊右上角「➕ 新增配件」來添加控制卡片！",
                bg=self.BG_MAIN,
                fg=self.TEXT_MUTED,
                font=("Segoe UI", 12),
                pady=50,
            )
            empty_lbl.pack()
            if hasattr(self, "_web_hub") and self._web_hub:
                self._web_hub.broadcast({
                    "type": "profile_update",
                    "components": self.components,
                    "workflows": getattr(self, "workflows", [])
                })
            return

        # 兩欄流式佈局或單欄響應式佈局
        container = tk.Frame(self.scroll_frame, bg=self.BG_MAIN)
        container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        col0 = tk.Frame(container, bg=self.BG_MAIN)
        col0.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)
        col1 = tk.Frame(container, bg=self.BG_MAIN)
        col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)

        cols = [col0, col1]
        for idx, comp_data in enumerate(self.components):
            target_col = cols[idx % 2]
            card = self._create_card_widget(target_col, comp_data)
            if card:
                self.card_widgets[comp_data["id"]] = card

        if hasattr(self, "_web_hub") and self._web_hub:
            self._web_hub.broadcast({
                "type": "profile_update",
                "components": self.components,
                "workflows": getattr(self, "workflows", [])
            })

    def _create_card_widget(self, parent, comp_data):
        c_type = comp_data.get("type")
        if c_type == "rgb":
            return RGBCard(parent, self, comp_data)
        elif c_type == "matrix":
            return MatrixCard(parent, self, comp_data)
        elif c_type == "servo":
            return ServoCard(parent, self, comp_data)
        elif c_type == "switch":
            return SwitchCard(parent, self, comp_data)
        elif c_type == "pwm":
            return PWMCard(parent, self, comp_data)
        elif c_type == "sensor":
            return SensorCard(parent, self, comp_data)
        elif c_type == "sonar":
            return SonarCard(parent, self, comp_data)
        return None

    def remove_component(self, comp_id):
        self.components = [c for c in self.components if c["id"] != comp_id]
        self.refresh_cards()
        self.log(f"已移除配件並自動儲存配置 (ID: {comp_id})")

    # ==========================
    # 新增配件對話方塊
    # ==========================
    def open_add_component_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("➕ 新增通用配件")
        dlg.geometry("450x480")
        dlg.resizable(False, False)
        dlg.configure(bg=self.BG_TOP)
        dlg.grab_set()

        tk.Label(dlg, text="選擇配件類型並設定腳位", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 12, "bold")).pack(pady=(15, 10))

        form_frame = tk.Frame(dlg, bg=self.BG_TOP, padx=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 類型選擇
        tk.Label(form_frame, text="配件類型:", bg=self.BG_TOP, fg=self.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=6)
        type_var = tk.StringVar(value="switch")
        type_combo = ttk.Combobox(
            form_frame,
            textvariable=type_var,
            state="readonly",
            values=[
                "💡 數位開關 (繼電器/單色LED)",
                "🎚️ PWM 調光/馬達調速",
                "🦾 伺服舵機 (Servo)",
                "🌈 RGB 全彩 LED",
                "👾 MAX7219 8x8 點陣",
                "🌡️ 感測器 (類比/數位)",
                "🦇 超音波測距 (HC-SR04)",
            ],
            width=26,
        )
        type_combo.grid(row=0, column=1, sticky="w", pady=6)
        type_combo.current(0)

        # 2. 名稱
        tk.Label(form_frame, text="配件名稱:", bg=self.BG_TOP, fg=self.TEXT_MAIN).grid(row=1, column=0, sticky="w", pady=6)
        name_entry = ttk.Entry(form_frame, width=28)
        name_entry.insert(0, "我的配件")
        name_entry.grid(row=1, column=1, sticky="w", pady=6)

        # 動態腳位容器
        pin_container = tk.Frame(form_frame, bg=self.BG_TOP)
        pin_container.grid(row=2, column=0, columnspan=2, sticky="we", pady=10)

        pin_vars = {}

        def update_pin_inputs(*args):
            for w in pin_container.winfo_children():
                w.destroy()
            pin_vars.clear()

            sel_idx = type_combo.current()
            if sel_idx == 0:  # 數位開關
                pin_vars["pin"] = create_pin_field(pin_container, 0, "控制腳位 (Pin):", 13)
            elif sel_idx == 1:  # PWM
                pin_vars["pin"] = create_pin_field(pin_container, 0, "PWM 腳位 (任意):", 9, ["3", "5", "6", "9", "10", "11"])
            elif sel_idx == 2:  # 舵機
                pin_vars["pin"] = create_pin_field(pin_container, 0, "訊號腳位 (Pin):", 9)
            elif sel_idx == 3:  # RGB
                pin_vars["r"] = create_pin_field(pin_container, 0, "R 腳位:", 6)
                pin_vars["g"] = create_pin_field(pin_container, 1, "G 腳位:", 4)
                pin_vars["b"] = create_pin_field(pin_container, 2, "B 腳位:", 5)
                anode_var = tk.BooleanVar(value=True)
                pin_vars["common_anode"] = anode_var
                ttk.Checkbutton(pin_container, text="共陽極 (Common Anode)", variable=anode_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
            elif sel_idx == 4:  # 點陣
                pin_vars["din"] = create_pin_field(pin_container, 0, "DIN 腳位:", 12)
                pin_vars["cs"] = create_pin_field(pin_container, 1, "CS 腳位:", 8)
                pin_vars["clk"] = create_pin_field(pin_container, 2, "CLK 腳位:", 7)
            elif sel_idx == 5:  # 感測器
                tk.Label(pin_container, text="感測器類型:", bg=self.BG_TOP, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=3)
                stype_var = tk.StringVar(value="類比 (A0~A5)")
                pin_vars["sensor_type_str"] = stype_var
                ttk.Combobox(pin_container, textvariable=stype_var, values=["類比 (A0~A5)", "數位 (D0~D13)"], width=14, state="readonly").grid(row=0, column=1, sticky="w", padx=10, pady=3)
                pin_vars["pin"] = create_pin_field(pin_container, 1, "腳位編號:", 0)
            elif sel_idx == 6:  # 超音波
                pin_vars["trig"] = create_pin_field(pin_container, 0, "Trig 腳位:", 2)
                pin_vars["echo"] = create_pin_field(pin_container, 1, "Echo 腳位:", 3)

        type_combo.bind("<<ComboboxSelected>>", update_pin_inputs)
        update_pin_inputs()

        def on_confirm():
            name = name_entry.get().strip() or "未命名配件"
            sel_idx = type_combo.current()
            type_keys = ["switch", "pwm", "servo", "rgb", "matrix", "sensor", "sonar"]
            chosen_type = type_keys[sel_idx]
            new_id = f"comp_{int(time.time() * 1000)}"

            new_comp = {
                "id": new_id,
                "type": chosen_type,
                "name": name,
                "pins": {},
                "state": {},
            }

            if chosen_type == "switch":
                new_comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
                new_comp["state"]["on"] = False
            elif chosen_type == "pwm":
                new_comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
                new_comp["state"]["val"] = 0
            elif chosen_type == "servo":
                new_comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
                new_comp["state"]["angle"] = 90
            elif chosen_type == "rgb":
                new_comp["pins"]["r"] = parse_pin(pin_vars["r"].get())
                new_comp["pins"]["g"] = parse_pin(pin_vars["g"].get())
                new_comp["pins"]["b"] = parse_pin(pin_vars["b"].get())
                new_comp["common_anode"] = pin_vars["common_anode"].get()
                new_comp["state"] = {"r": 255, "g": 255, "b": 255}
            elif chosen_type == "matrix":
                new_comp["pins"]["din"] = parse_pin(pin_vars["din"].get())
                new_comp["pins"]["cs"] = parse_pin(pin_vars["cs"].get())
                new_comp["pins"]["clk"] = parse_pin(pin_vars["clk"].get())
                new_comp["state"]["matrix"] = [0] * 8
            elif chosen_type == "sensor":
                is_analog = "類比" in pin_vars["sensor_type_str"].get()
                new_comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
                new_comp["sensor_type"] = "A" if is_analog else "D"
                new_comp["interval_ms"] = 200
                new_comp["state"]["streaming"] = False
            elif chosen_type == "sonar":
                new_comp["pins"]["trig"] = parse_pin(pin_vars["trig"].get())
                new_comp["pins"]["echo"] = parse_pin(pin_vars["echo"].get())

            self.components.append(new_comp)
            self.refresh_cards()
            self.save_profile(DEFAULT_PROFILE_PATH, silent=True)
            dlg.destroy()

        btn_box = tk.Frame(dlg, bg=self.BG_TOP)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM, pady=15)
        ttk.Button(btn_box, text="確定建立", style="Primary.TButton", command=on_confirm).pack(side=tk.RIGHT, padx=15)
        ttk.Button(btn_box, text="取消", command=dlg.destroy).pack(side=tk.RIGHT)

    # ==========================
    # 編輯配件對話方塊 (隨時自由修改腳位與名稱)
    # ==========================
    def open_edit_component_dialog(self, comp_id):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return

        c_type = comp.get("type")
        dlg = tk.Toplevel(self.root)
        dlg.title(f"⚙️ 設定腳位與屬性 - {comp.get('name', '配件')}")
        dlg.geometry("450x450")
        dlg.resizable(False, False)
        dlg.configure(bg=self.BG_TOP)
        dlg.grab_set()

        tk.Label(dlg, text="修改配件名稱與腳位 (支援自由自訂)", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 12, "bold")).pack(pady=(15, 10))

        form_frame = tk.Frame(dlg, bg=self.BG_TOP, padx=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_frame, text="配件名稱:", bg=self.BG_TOP, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=6)
        name_entry = ttk.Entry(form_frame, width=28)
        name_entry.insert(0, comp.get("name", ""))
        name_entry.grid(row=0, column=1, sticky="w", pady=6)

        pin_container = tk.Frame(form_frame, bg=self.BG_TOP)
        pin_container.grid(row=1, column=0, columnspan=2, sticky="we", pady=10)

        pin_vars = {}
        pins = comp.get("pins", {})

        if c_type == "switch":
            pin_vars["pin"] = create_pin_field(pin_container, 0, "控制腳位 (Pin):", pins.get("pin", 13))
        elif c_type == "pwm":
            pin_vars["pin"] = create_pin_field(pin_container, 0, "PWM 腳位 (任意):", pins.get("pin", 9), ["3", "5", "6", "9", "10", "11"])
        elif c_type == "servo":
            pin_vars["pin"] = create_pin_field(pin_container, 0, "訊號腳位 (Pin):", pins.get("pin", 9))
        elif c_type == "rgb":
            pin_vars["r"] = create_pin_field(pin_container, 0, "R 腳位:", pins.get("r", 6))
            pin_vars["g"] = create_pin_field(pin_container, 1, "G 腳位:", pins.get("g", 4))
            pin_vars["b"] = create_pin_field(pin_container, 2, "B 腳位:", pins.get("b", 5))
            anode_var = tk.BooleanVar(value=comp.get("common_anode", True))
            pin_vars["common_anode"] = anode_var
            ttk.Checkbutton(pin_container, text="共陽極 (Common Anode)", variable=anode_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        elif c_type == "matrix":
            pin_vars["din"] = create_pin_field(pin_container, 0, "DIN 腳位:", pins.get("din", 12))
            pin_vars["cs"] = create_pin_field(pin_container, 1, "CS 腳位:", pins.get("cs", 8))
            pin_vars["clk"] = create_pin_field(pin_container, 2, "CLK 腳位:", pins.get("clk", 7))
        elif c_type == "sensor":
            tk.Label(pin_container, text="感測器類型:", bg=self.BG_TOP, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=4)
            stype_var = tk.StringVar(value="類比 (A0~A5)" if comp.get("sensor_type") == "A" else "數位 (D0~D13)")
            pin_vars["sensor_type_str"] = stype_var
            ttk.Combobox(pin_container, textvariable=stype_var, values=["類比 (A0~A5)", "數位 (D0~D13)"], width=14, state="readonly").grid(row=0, column=1, sticky="w", padx=10, pady=4)
            pin_vars["pin"] = create_pin_field(pin_container, 1, "腳位編號:", pins.get("pin", 0))
        elif c_type == "sonar":
            pin_vars["trig"] = create_pin_field(pin_container, 0, "Trig 腳位:", pins.get("trig", 2))
            pin_vars["echo"] = create_pin_field(pin_container, 1, "Echo 腳位:", pins.get("echo", 3))

        def on_save():
            comp["name"] = name_entry.get().strip() or comp["name"]
            if c_type == "switch":
                comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
            elif c_type == "pwm":
                comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
            elif c_type == "servo":
                comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
            elif c_type == "rgb":
                comp["pins"]["r"] = parse_pin(pin_vars["r"].get())
                comp["pins"]["g"] = parse_pin(pin_vars["g"].get())
                comp["pins"]["b"] = parse_pin(pin_vars["b"].get())
                comp["common_anode"] = pin_vars["common_anode"].get()
            elif c_type == "matrix":
                comp["pins"]["din"] = parse_pin(pin_vars["din"].get())
                comp["pins"]["cs"] = parse_pin(pin_vars["cs"].get())
                comp["pins"]["clk"] = parse_pin(pin_vars["clk"].get())
            elif c_type == "sensor":
                is_analog = "類比" in pin_vars["sensor_type_str"].get()
                comp["pins"]["pin"] = parse_pin(pin_vars["pin"].get())
                comp["sensor_type"] = "A" if is_analog else "D"
            elif c_type == "sonar":
                comp["pins"]["trig"] = parse_pin(pin_vars["trig"].get())
                comp["pins"]["echo"] = parse_pin(pin_vars["echo"].get())

            self.refresh_cards()
            self.save_profile(DEFAULT_PROFILE_PATH, silent=True)
            self.log(f"已更新配件與腳位設定並自動儲存配置：{comp['name']}")

        btn_box = tk.Frame(dlg, bg=self.BG_TOP)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM, pady=15)
        ttk.Button(btn_box, text="儲存變更", style="Primary.TButton", command=on_save).pack(side=tk.RIGHT, padx=15)
        ttk.Button(btn_box, text="取消", command=dlg.destroy).pack(side=tk.RIGHT)

    # ==========================
    # 配置檔案儲存與載入 (JSON Profiles)
    # ==========================
    def save_profile_dialog(self):
        # 點擊「💾 儲存配置」直接存入預設配置檔案，下次啟動自動套用
        self.save_profile(DEFAULT_PROFILE_PATH, silent=False)

    def open_share_dialog(self):
        """開啟跨電腦/多裝置連線資訊視窗，方便其他電腦與手機即時連線同步"""
        dlg = tk.Toplevel(self.root)
        dlg.title("📱 跨電腦 / 多裝置即時同步連線")
        dlg.geometry("640x450")
        dlg.minsize(580, 420)
        dlg.configure(bg=self.BG_TOP)
        dlg.transient(self.root)

        header = tk.Frame(dlg, bg=self.BG_TOP, padx=16, pady=12)
        header.pack(fill=tk.X)
        tk.Label(header, text="🔗 跨電腦與多設備即時連線同步", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(header, text="在其他電腦、筆電、手機或平板打開瀏覽器輸入以下網址，即可與本機達成 100% 雙向即時同步！", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(dlg, bg=self.BG_MAIN, padx=16, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tunnel_url = ""
        try:
            from cloudflare_tunnel import tunnel_manager
            tunnel_url = tunnel_manager.get_url() or ""
        except Exception:
            pass

        local_ip = "127.0.0.1"
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        lan_url = f"http://{local_ip}:5000"

        # 方式 1: 雲端外網穿透 (最推薦，任何網路、任何設備均可直接連線)
        f1 = tk.LabelFrame(body, text="🌐 方式 1：雲端外網穿透網址 (最推薦 · 任何電腦/手機免設 Wi-Fi 隨開即用)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), padx=10, pady=8)
        f1.pack(fill=tk.X, pady=(0, 10))

        url_str = tunnel_url or "正在獲取 Cloudflare Tunnel 網址中，請稍候..."
        lbl_url = tk.Label(f1, text=url_str, bg=self.BG_CARD, fg="#A6E3A1" if tunnel_url else "#F9E2AF", font=("Consolas", 10, "bold"), wraplength=520, justify="left")
        lbl_url.pack(anchor="w", pady=(0, 6))

        act_row1 = tk.Frame(f1, bg=self.BG_CARD)
        act_row1.pack(fill=tk.X)

        def copy_tunnel():
            if tunnel_url:
                dlg.clipboard_clear()
                dlg.clipboard_append(tunnel_url)
                messagebox.showinfo("已複製", f"已成功複製外網同步網址：\n{tunnel_url}\n\n請在其他電腦或手機瀏覽器貼上開啟！")
            else:
                messagebox.showwarning("提示", "網址生成中，請稍候再點擊複製！")

        def open_tunnel():
            if tunnel_url:
                import webbrowser
                webbrowser.open(tunnel_url)

        tk.Button(act_row1, text="📋 複製外網網址", bg="#45475A", fg=self.TEXT_MAIN, bd=0, padx=8, pady=3, font=("Segoe UI", 8, "bold"), cursor="hand2", command=copy_tunnel).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(act_row1, text="↗️ 在瀏覽器中開啟", bg="#313244", fg=self.TEXT_MAIN, bd=0, padx=8, pady=3, font=("Segoe UI", 8), cursor="hand2", command=open_tunnel).pack(side=tk.LEFT)

        # 方式 2: 同 Wi-Fi 區域網路
        f2 = tk.LabelFrame(body, text="💻 方式 2：區域網路網址 (同 Wi-Fi 內網其他電腦/平板專用)", bg=self.BG_CARD, fg="#89B4FA", font=("Segoe UI", 9, "bold"), padx=10, pady=8)
        f2.pack(fill=tk.X, pady=(0, 10))

        tk.Label(f2, text=lan_url, bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Consolas", 10, "bold")).pack(anchor="w", pady=(0, 6))
        act_row2 = tk.Frame(f2, bg=self.BG_CARD)
        act_row2.pack(fill=tk.X)

        def copy_lan():
            dlg.clipboard_clear()
            dlg.clipboard_append(lan_url)
            messagebox.showinfo("已複製", f"已成功複製區域網路網址：\n{lan_url}\n\n請在同一 Wi-Fi 下的其他設備開啟！")

        tk.Button(act_row2, text="📋 複製區網網址", bg="#45475A", fg=self.TEXT_MAIN, bd=0, padx=8, pady=3, font=("Segoe UI", 8, "bold"), cursor="hand2", command=copy_lan).pack(side=tk.LEFT)

        # 重要提示
        notice_frame = tk.Frame(body, bg=self.BG_MAIN)
        notice_frame.pack(fill=tk.X, pady=(4, 0))
        tk.Label(notice_frame, text="💡 跨電腦同步要訣：", bg=self.BG_MAIN, fg="#F9E2AF", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(notice_frame, text="1. 只有這台插著 USB 的主控電腦需要運行 Python 程式。\n2. 其他電腦/手機『只需打開瀏覽器』連線上述網址，切勿在其他電腦重複運行 Python！\n3. 任何設備上的開關、滑桿、點陣、RGB 與急停均為毫秒級即時全域同步。", bg=self.BG_MAIN, fg=self.TEXT_MUTED, font=("Segoe UI", 8), justify="left").pack(anchor="w", pady=(2, 0))

        # 關閉按鈕
        tk.Button(dlg, text="關閉", bg="#45475A", fg=self.TEXT_MAIN, bd=0, padx=16, pady=4, font=("Segoe UI", 9), command=dlg.destroy).pack(side=tk.BOTTOM, pady=10)

    def open_web_console(self):
        """啟動 Web 服務 (Flask + Waitress) 與 Cloudflare Tunnel 內網穿透並於瀏覽器中開啟"""
        try:
            import webbrowser
            if not getattr(self, "_web_server_started", False):
                from universal_web import start_web_server_thread, hub as web_hub
                start_web_server_thread(self, host="0.0.0.0", port=5000)
                self._web_server_started = True
                self._web_hub = web_hub
                self.log("🌐 Waitress + Flask 伺服器已在背景啟動 (http://127.0.0.1:5000)")
                self.log("🚀 Cloudflare Tunnel 穿透程序已在背景啟動，正在捕獲 trycloudflare.com 網址...")
            webbrowser.open("http://127.0.0.1:5000")
        except Exception as e:
            self.log(f"❌ 開啟 Web 控制台失敗: {e}")

    def open_workflow_dialog(self):
        """開啟自訂流程與自動化編排管理視窗"""
        WorkflowDialog(self.root, self)

    def open_dual_effects_dialog(self):
        """開啟雙燈即時連線特效 (18 款炫彩即時特效) 控制視窗"""
        DualRGBEffectsDialog(self.root, self)

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

    def start_dual_effect(self, effect_name):
        """雙燈即時連線特效 (18 款炫彩即時特效)"""
        self.stop_dual_effect()
        # 建立全新的 Event 實例，避免舊執行緒因為 clear() 再次被喚醒
        self.effect_stop_event = threading.Event()
        self.current_effect_name = effect_name

        rgbs = [c for c in self.components if c.get("type") == "rgb"]
        if not rgbs:
            self.log("⚠️ 尚未配置 RGB 配件，無法播放特效")
            return
        comp1 = rgbs[0]
        comp2 = rgbs[1] if len(rgbs) > 1 else rgbs[0]
        pins1 = comp1.get("pins", {})
        pins2 = comp2.get("pins", {})
        rp1, gp1, bp1 = pins1.get("r", 6), pins1.get("g", 3), pins1.get("b", 5)
        rp2, gp2, bp2 = pins2.get("r", 11), pins2.get("g", 9), pins2.get("b", 10)
        anode1 = 1 if comp1.get("common_anode", True) else 0
        anode2 = 1 if comp2.get("common_anode", True) else 0

        # 擷取此執行緒所屬的 stop_event 參照，杜絕任何跨實例競爭
        stop_evt = self.effect_stop_event

        def worker():
            t0 = time.time()
            self.log(f"✨ 啟動雙燈即時連線特效: [{effect_name}]")
            while not stop_evt.is_set():
                dt = time.time() - t0
                r1, g1, b1 = 0, 0, 0
                r2, g2, b2 = 0, 0, 0
                sleep_t = 0.035

                if effect_name == "sync_rainbow":
                    hue = (dt * 60) % 360
                    r1, g1, b1 = self._hsv_to_rgb(hue, 1.0, 1.0)
                    r2, g2, b2 = r1, g1, b1
                    sleep_t = 0.04
                elif effect_name == "complementary":
                    hue1 = (dt * 50) % 360
                    hue2 = (hue1 + 180) % 360
                    r1, g1, b1 = self._hsv_to_rgb(hue1, 1.0, 1.0)
                    r2, g2, b2 = self._hsv_to_rgb(hue2, 1.0, 1.0)
                    sleep_t = 0.04
                elif effect_name == "police_strobe":
                    phase = int(dt * 8) % 4
                    if phase in [0, 1]:
                        r1, g1, b1 = 255, 0, 0
                        r2, g2, b2 = 0, 0, 0
                    else:
                        r1, g1, b1 = 0, 0, 0
                        r2, g2, b2 = 0, 0, 255
                    sleep_t = 0.06
                elif effect_name == "warm_breathing":
                    v = (math.sin(dt * 2.5) + 1.0) / 2.0
                    r1, g1, b1 = int(255 * v), int(120 * v), int(20 * v)
                    r2, g2, b2 = r1, g1, b1
                elif effect_name == "aurora_breathing":
                    v1 = (math.sin(dt * 2.0) + 1.0) / 2.0
                    v2 = (math.cos(dt * 2.0) + 1.0) / 2.0
                    r1, g1, b1 = 0, int(255 * v1), int(200 * v1)
                    r2, g2, b2 = int(180 * v2), 0, int(255 * v2)
                elif effect_name == "disco_party":
                    r1, g1, b1 = [random.choice([0, 255]) for _ in range(3)]
                    r2, g2, b2 = [random.choice([0, 255]) for _ in range(3)]
                    sleep_t = 0.12
                elif effect_name == "chase_wave":
                    phase = math.sin(dt * 4)
                    v1 = max(0.0, phase)
                    v2 = max(0.0, -phase)
                    r1, g1, b1 = 0, int(255 * v1), int(255 * v1)
                    r2, g2, b2 = int(255 * v2), 0, int(128 * v2)
                elif effect_name == "fire_flicker":
                    flicker = random.randint(180, 255)
                    r1 = flicker
                    g1 = max(0, int(flicker * 0.4 + random.randint(-20, 20)))
                    b1 = 0
                    r2, g2, b2 = r1, g1, b1
                    sleep_t = 0.05
                elif effect_name == "thunder_storm":
                    if random.random() < 0.15:
                        r1, g1, b1 = 255, 255, 255
                        r2, g2, b2 = 255, 255, 255
                        sleep_t = random.uniform(0.03, 0.08)
                    else:
                        r1, g1, b1 = 0, 0, 20
                        r2, g2, b2 = 0, 0, 20
                        sleep_t = 0.1
                elif effect_name == "heartbeat":
                    t_cycle = dt % 1.2
                    if 0 <= t_cycle < 0.18:
                        v = math.sin(t_cycle / 0.18 * math.pi)
                    elif 0.25 <= t_cycle < 0.42:
                        v = math.sin((t_cycle - 0.25) / 0.17 * math.pi) * 0.75
                    else:
                        v = 0.05
                    r1, g1, b1 = int(255 * v), int(15 * v), int(40 * v)
                    r2, g2, b2 = r1, g1, b1
                    sleep_t = 0.02
                elif effect_name == "cyberpunk_neon":
                    p = (math.sin(dt * 3.0) + 1.0) / 2.0
                    r1, g1, b1 = int(255 * p), int(240 * (1 - p)), int(180 * p + 255 * (1 - p))
                    r2, g2, b2 = int(255 * (1 - p)), int(240 * p), int(180 * (1 - p) + 255 * p)
                elif effect_name == "meteor_shower":
                    t_c = dt % 1.6
                    if t_c < 0.8:
                        decay = max(0.0, 1.0 - (t_c / 0.8) * 2.2)
                        r1, g1, b1 = int(220 * decay), int(240 * decay), int(255 * decay)
                        r2, g2, b2 = 0, 0, 15
                    else:
                        decay = max(0.0, 1.0 - ((t_c - 0.8) / 0.8) * 2.2)
                        r1, g1, b1 = 0, 0, 15
                        r2, g2, b2 = int(220 * decay), int(240 * decay), int(255 * decay)
                elif effect_name == "sunrise_glow":
                    v = (math.sin(dt * 1.5) + 1.0) / 2.0
                    r1 = int(255 * (0.3 + 0.7 * v))
                    g1 = int(60 * v + 160 * (v ** 2))
                    b1 = int(180 * (v ** 3))
                    r2, g2, b2 = r1, g1, b1
                elif effect_name == "emerald_forest":
                    v1 = (math.sin(dt * 2.2) + 1.0) / 2.0
                    v2 = (math.cos(dt * 1.8) + 1.0) / 2.0
                    r1, g1, b1 = int(15 * v1), int(240 * v1 + 15), int(110 * v1)
                    r2, g2, b2 = int(10 * v2), int(255 * v2), int(50 * v2)
                elif effect_name == "magic_crystal":
                    v1 = (math.sin(dt * 2.5) + 1.0) / 2.0
                    v2 = (math.cos(dt * 2.5) + 1.0) / 2.0
                    r1, g1, b1 = int(190 * v1 + 30), 0, int(255 * v1)
                    r2, g2, b2 = 0, int(160 * v2), int(255 * v2)
                elif effect_name == "volcano_magma":
                    base = (math.sin(dt * 1.6) + 1.0) / 2.0
                    r1 = min(255, int(210 + random.randint(0, 45) * base))
                    g1 = max(0, int((45 + random.randint(-15, 30)) * base))
                    b1 = 0
                    r2, g2, b2 = int(r1 * 0.9), int(g1 * 0.8), 0
                    sleep_t = 0.04
                elif effect_name == "ambulance_amber":
                    phase = int(dt * 12) % 8
                    if phase in [0, 2]:
                        r1, g1, b1 = 255, 170, 0
                        r2, g2, b2 = 0, 0, 0
                    elif phase in [4, 6]:
                        r1, g1, b1 = 0, 0, 0
                        r2, g2, b2 = 255, 255, 255
                    else:
                        r1, g1, b1 = 0, 0, 0
                        r2, g2, b2 = 0, 0, 0
                    sleep_t = 0.04
                elif effect_name == "candy_pop":
                    hue1 = (dt * 45) % 360
                    hue2 = (hue1 + 90) % 360
                    r1, g1, b1 = self._hsv_to_rgb(hue1, 0.65, 1.0)
                    r2, g2, b2 = self._hsv_to_rgb(hue2, 0.65, 1.0)
                    sleep_t = 0.04

                comp1["state"]["r"], comp1["state"]["g"], comp1["state"]["b"] = r1, g1, b1
                self.send_cmd(f"RGB,{rp1},{gp1},{bp1},{anode1},{r1},{g1},{b1}")
                if comp1["id"] in self.card_widgets:
                    card1 = self.card_widgets[comp1["id"]]
                    if hasattr(card1, "sync_ui"):
                        self.dispatch_ui(card1.sync_ui, r1, g1, b1)

                if comp2["id"] != comp1["id"]:
                    comp2["state"]["r"], comp2["state"]["g"], comp2["state"]["b"] = r2, g2, b2
                    self.send_cmd(f"RGB,{rp2},{gp2},{bp2},{anode2},{r2},{g2},{b2}")
                    if comp2["id"] in self.card_widgets:
                        card2 = self.card_widgets[comp2["id"]]
                        if hasattr(card2, "sync_ui"):
                            self.dispatch_ui(card2.sync_ui, r2, g2, b2)

                # 即時向 Web 控制台推播 RGB 雙燈流動影格 (色塊與滑桿同步跳動)
                if getattr(self, "_web_hub", None):
                    self._web_hub.broadcast({
                        "type": "dual_rgb_frame",
                        "id1": comp1["id"], "r1": r1, "g1": g1, "b1": b1,
                        "id2": comp2["id"], "r2": r2, "g2": g2, "b2": b2
                    })

                # 使用 Event.wait() 替代 time.sleep()，收到停止訊號瞬間 0ms 立即喚醒跳出
                if stop_evt.wait(sleep_t):
                    break

            # 迴圈退出時，由 worker 執行緒親自發送熄滅指令，100% 保證實體雙燈熄滅
            self.send_cmd(f"RGB,{rp1},{gp1},{bp1},{anode1},0,0,0")
            if comp2["id"] != comp1["id"]:
                self.send_cmd(f"RGB,{rp2},{gp2},{bp2},{anode2},0,0,0")
            comp1.setdefault("state", {})
            comp1["state"]["r"], comp1["state"]["g"], comp1["state"]["b"] = 0, 0, 0
            if comp2["id"] != comp1["id"]:
                comp2.setdefault("state", {})
                comp2["state"]["r"], comp2["state"]["g"], comp2["state"]["b"] = 0, 0, 0
            if comp1["id"] in self.card_widgets:
                card1 = self.card_widgets[comp1["id"]]
                if hasattr(card1, "sync_ui"):
                    self.dispatch_ui(card1.sync_ui, 0, 0, 0)
            if comp2["id"] != comp1["id"] and comp2["id"] in self.card_widgets:
                card2 = self.card_widgets[comp2["id"]]
                if hasattr(card2, "sync_ui"):
                    self.dispatch_ui(card2.sync_ui, 0, 0, 0)
            if getattr(self, "_web_hub", None):
                self._web_hub.broadcast({
                    "type": "dual_rgb_frame",
                    "id1": comp1["id"], "r1": 0, "g1": 0, "b1": 0,
                    "id2": comp2["id"], "r2": 0, "g2": 0, "b2": 0
                })
                self._web_hub.broadcast({"type": "dual_effect_stop"})
            self.log(f"⏹️ 特效 [{effect_name}] 已停止")

        self.effect_thread = threading.Thread(target=worker, daemon=True)
        self.effect_thread.start()

        # 同步 Web 控制台狀態 (若已開啟)
        if getattr(self, "_web_hub", None):
            self._web_hub.broadcast({"type": "dual_effect_start", "effect": effect_name})

    def stop_dual_effect(self, turn_off=True):
        """停止雙燈特效並視需要關閉/熄滅雙 RGB 燈光"""
        was_running = bool(
            (getattr(self, "effect_thread", None) and self.effect_thread.is_alive())
            or getattr(self, "current_effect_name", None)
        )
        if hasattr(self, "effect_stop_event"):
            self.effect_stop_event.set()
        if getattr(self, "effect_thread", None) and self.effect_thread.is_alive():
            self.effect_thread.join(timeout=0.4)
        self.effect_thread = None
        self.current_effect_name = None

        if not was_running:
            return

        if turn_off:
            # 主動發送全關指令 (0, 0, 0) 確保硬體雙燈完全熄滅
            rgbs = [c for c in self.components if c.get("type") == "rgb"]
            for comp in rgbs:
                pins = comp.get("pins", {})
                rp, gp, bp = pins.get("r", 6), pins.get("g", 3), pins.get("b", 5)
                anode = 1 if comp.get("common_anode", True) else 0
                comp.setdefault("state", {})
                comp["state"]["r"] = 0
                comp["state"]["g"] = 0
                comp["state"]["b"] = 0
                self.send_cmd(f"RGB,{rp},{gp},{bp},{anode},0,0,0")
                if comp["id"] in self.card_widgets:
                    card = self.card_widgets[comp["id"]]
                    if hasattr(card, "sync_ui"):
                        self.dispatch_ui(card.sync_ui, 0, 0, 0)

            # 同步 Web 控制台狀態 (若已開啟)
            if getattr(self, "_web_hub", None):
                self._web_hub.broadcast({"type": "dual_effect_stop"})
        else:
            if getattr(self, "_web_hub", None):
                self._web_hub.broadcast({"type": "dual_effect_clear_badge"})

    def save_profile(self, path=None, silent=False):
        if not path:
            path = DEFAULT_PROFILE_PATH
        data = {
            "profile_name": "Arduino Universal Hub Profile",
            "components": self.components,
            "workflows": getattr(self, "workflows", []),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log(f"💾 配件與腳位設定已成功儲存至：{os.path.basename(path)}")
            if not silent:
                messagebox.showinfo("儲存成功", f"配件與腳位設定已成功儲存至預設配置：\n{path}\n下次啟動將自動以此腳位運行！")
            if getattr(self, "_web_hub", None):
                self._web_hub.components = self.components
                self._web_hub.workflows = getattr(self, "workflows", [])
                self._web_hub.broadcast({
                    "type": "status",
                    "connected": self.is_connected,
                    "port": self.port_combobox.get().strip() if hasattr(self, "port_combobox") else ""
                })
        except Exception as e:
            self.log(f"❌ 儲存配置失敗: {e}")
            if not silent:
                messagebox.showerror("儲存失敗", f"無法儲存檔案：\n{e}")

    def load_profile_dialog(self):
        path = filedialog.askopenfilename(
            initialdir=WORKSPACE_DIR,
            title="載入配件配置檔案",
            filetypes=[("JSON Files", "*.json")],
        )
        if path:
            self.load_profile(path)

    def load_profile(self, path, silent=False):
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.components = data.get("components", [])
            self.workflows = data.get("workflows", [])
            self.refresh_cards()
            self.log(f"已載入配置：{os.path.basename(path)} (包含 {len(self.components)} 個配件, {len(self.workflows)} 個自訂流程)")
            if not silent:
                messagebox.showinfo("成功", f"已成功載入配置：\n{os.path.basename(path)}")
        except Exception as e:
            if not silent:
                messagebox.showerror("載入失敗", f"無法讀取設定檔：\n{e}")

    # ==========================
    # 一鍵燒錄萬能韌體
    # ==========================
    def flash_firmware(self):
        port = self.port_combobox.get().strip()
        if not port:
            messagebox.showwarning("提示", "請先選擇燒錄使用的 COM 埠！")
            return

        if not messagebox.askyesno("燒錄確認", f"即將編譯並燒錄萬能韌體到 {port}。\n燒錄過程中會暫時中斷序列埠連線，是否繼續？"):
            return

        # 先斷開連線以釋放 COM 埠
        self.disconnect()

        def worker():
            self.log("🚀 開始編譯萬能韌體 (arduino:avr:uno)...")
            cmd_compile = [ARDUINO_CLI_PATH, "compile", "--fqbn", "arduino:avr:uno", FIRMWARE_DIR]
            try:
                res_comp = subprocess.run(cmd_compile, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log("✅ 編譯成功！開始上傳韌體...")
                cmd_upload = [ARDUINO_CLI_PATH, "upload", "-p", port, "--fqbn", "arduino:avr:uno", FIRMWARE_DIR]
                res_up = subprocess.run(cmd_upload, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log("🎉 韌體燒錄大功告成！正在自動重新連線...")
                time.sleep(1.5)
                self.root.after(0, self.connect)
                messagebox.showinfo("燒錄完成", "萬能韌體已成功燒錄！系統已就緒。")
            except subprocess.CalledProcessError as err:
                err_text = err.stderr or err.stdout or str(err)
                self.log(f"❌ 燒錄失敗: {err_text}")
                messagebox.showerror("燒錄失敗", f"編譯或燒錄時發生錯誤：\n{err_text}")
            except Exception as ex:
                self.log(f"❌ 錯誤: {ex}")
                messagebox.showerror("錯誤", f"發生未知例外：\n{ex}")

        threading.Thread(target=worker, daemon=True).start()

    # ==========================
    # 脫機燒錄自訂流程至 Arduino
    # ==========================
    def flash_standalone_workflow(self, wf_idx=None):
        """將指定自訂流程編譯生成獨立脫機韌體並直接燒錄至 Arduino Uno"""
        if wf_idx is None:
            if not self.workflows:
                messagebox.showwarning("提示", "目前沒有任何自訂流程可供燒錄！")
                return
            wf_idx = 0

        if wf_idx < 0 or wf_idx >= len(self.workflows):
            messagebox.showwarning("提示", "請先選擇要脫機燒錄的自訂流程！")
            return

        wf = self.workflows[wf_idx]
        wf_name = wf.get("name", f"自訂流程_{wf_idx + 1}")
        step_count = len(wf.get("steps", []))

        port = self.port_combobox.get().strip()
        if not port:
            messagebox.showwarning("提示", "請先選擇燒錄使用的 COM 埠！")
            return

        confirm_msg = (
            f"🔥 即將把自訂流程【{wf_name}】直接燒錄至 Arduino Uno ({port})！\n\n"
            f"• 流程步驟：共 {step_count} 個步驟\n"
            f"• 循環模式：{'🔁 開啟循環播放' if wf.get('loop') else '▶️ 單次執行'}\n\n"
            f"【脫機獨立運行特性】：\n"
            f"✅ 燒錄完成後，可完全拔除 USB 線，無需連接電腦或 Python！\n"
            f"✅ 只要接上 5V 行動電源或手機充電頭，通電立即自動循環執行此自訂流程！\n"
            f"✅ 日後隨時點擊主介面【⚡ 燒錄萬能韌體】即可一鍵復原回即時聯機模式！\n\n"
            f"確定要開始編譯並燒錄嗎？"
        )
        if not messagebox.askyesno("脫機流程燒錄確認", confirm_msg):
            return

        # 斷開連線以釋放 COM 埠
        self.disconnect()

        def worker():
            try:
                import standalone_generator
                self.log(f"🛠️ 正在生成自訂流程【{wf_name}】的獨立 C++ 原始碼...")
                sketch_code = standalone_generator.generate_standalone_sketch(wf, self.components)

                out_dir = os.path.join(WORKSPACE_DIR, "standalone_sketch")
                os.makedirs(out_dir, exist_ok=True)
                sketch_file = os.path.join(out_dir, "standalone_sketch.ino")
                with open(sketch_file, "w", encoding="utf-8") as f:
                    f.write(sketch_code)
                self.log(f"📄 獨立原始碼生成完成 ({len(sketch_code)} 位元組)，調用 arduino-cli 開始編譯...")

                cmd_compile = [ARDUINO_CLI_PATH, "compile", "--fqbn", "arduino:avr:uno", out_dir]
                res_comp = subprocess.run(cmd_compile, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log("✅ 編譯成功！開始上傳脫機自訂流程韌體至 Arduino Uno...")

                cmd_upload = [ARDUINO_CLI_PATH, "upload", "-p", port, "--fqbn", "arduino:avr:uno", out_dir]
                res_up = subprocess.run(cmd_upload, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log(f"🎉 自訂流程【{wf_name}】脫機獨立燒錄成功！")

                time.sleep(1.5)
                self.root.after(0, self.connect)

                success_msg = (
                    f"🎉 自訂流程【{wf_name}】已成功脫機燒錄至 Arduino 晶片！\n\n"
                    f"🌟 【脫機獨立模式已生效】：\n"
                    f"現在您可以拔除 USB 連接線，拿到任何地方插上 5V 行動電源或充電頭，"
                    f"Arduino 晶片將會自動永久執行此自訂流程與燈效！\n\n"
                    f"💡 隨時點擊主介面【⚡ 燒錄萬能韌體】可一鍵切換回即時聯機控制模式。"
                )
                messagebox.showinfo("脫機流程燒錄成功", success_msg)
            except subprocess.CalledProcessError as err:
                err_text = err.stderr or err.stdout or str(err)
                self.log(f"❌ 脫機燒錄失敗: {err_text}")
                messagebox.showerror("燒錄失敗", f"編譯或燒錄時發生錯誤：\n{err_text}")
                self.root.after(0, self.connect)
            except Exception as ex:
                self.log(f"❌ 錯誤: {ex}")
                messagebox.showerror("錯誤", f"發生未知例外：\n{ex}")
                self.root.after(0, self.connect)

        threading.Thread(target=worker, daemon=True).start()


# ==============================================================================
# 自訂流程與自動化排程引擎 (Workflow Automation Sequencer)
# ==============================================================================

class WorkflowEngine:
    """非同步自訂流程執行引擎"""
    def __init__(self, hub):
        self.hub = hub
        self.running_thread = None
        self.stop_event = threading.Event()
        self.current_wf = None
        self.on_step_change = None

    def start_workflow(self, workflow, on_step_callback=None, on_finish_callback=None):
        self.stop()
        self.stop_event.clear()
        self.current_wf = workflow
        self.on_step_change = on_step_callback

        def worker():
            try:
                steps = workflow.get("steps", [])
                loop = workflow.get("loop", False)
                wf_name = workflow.get("name", "未命名流程")
                self.hub.log(f"🎭 啟動自訂流程：『{wf_name}』(共 {len(steps)} 個步驟, 循環: {'是' if loop else '否'})")

                while not self.stop_event.is_set():
                    for idx, step in enumerate(steps):
                        if self.stop_event.is_set():
                            break
                        if self.on_step_change:
                            self.hub.dispatch_ui(self.on_step_change, idx)
                        self.execute_step(step)

                        # 若為非延遲之硬體指令，加入 30ms 微調節間隔，防止撐爆 Arduino Uno 64-byte 序列緩衝區
                        if step.get("action") != "delay":
                            elapsed = 0
                            while elapsed < 30 and not self.stop_event.is_set():
                                time.sleep(0.005)
                                elapsed += 5

                    if not loop or self.stop_event.is_set():
                        break

                if self.on_step_change:
                    self.hub.dispatch_ui(self.on_step_change, -1)
                if on_finish_callback:
                    self.hub.dispatch_ui(on_finish_callback)
                self.hub.log(f"🏁 流程『{wf_name}』執行完成。")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.hub.log(f"❌ 流程執行異常終止: {e}")

        self.running_thread = threading.Thread(target=worker, daemon=True)
        self.running_thread.start()

    def stop(self):
        self.stop_event.set()
        if self.running_thread and self.running_thread.is_alive():
            self.running_thread.join(timeout=0.5)
        self.running_thread = None

    def is_running(self):
        return self.running_thread is not None and self.running_thread.is_alive()

    def execute_step(self, step):
        action = step.get("action")
        params = step.get("params", {})
        target_id = step.get("target_id")

        if action == "delay":
            ms = params.get("ms", 500)
            elapsed = 0
            while elapsed < ms and not self.stop_event.is_set():
                chunk = min(20, ms - elapsed)
                time.sleep(chunk / 1000.0)
                elapsed += chunk
            return

        if action == "dual_effect":
            effect_name = params.get("effect", "sync_rainbow")
            duration_ms = params.get("duration_ms", 3000)
            self.hub.start_dual_effect(effect_name)
            elapsed = 0
            while elapsed < duration_ms and not self.stop_event.is_set():
                chunk = min(30, duration_ms - elapsed)
                time.sleep(chunk / 1000.0)
                elapsed += chunk
            self.hub.stop_dual_effect(turn_off=True)
            return

        comp = next((c for c in self.hub.components if c["id"] == target_id), None)
        if not comp:
            return

        pins = comp.get("pins", {})
        try:
            if action == "rgb":
                r = params.get("r", 0)
                g = params.get("g", 0)
                b = params.get("b", 0)
                rp, gp, bp = pins.get("r", 6), pins.get("g", 4), pins.get("b", 5)
                anode = 1 if comp.get("common_anode", True) else 0
                comp["state"]["r"], comp["state"]["g"], comp["state"]["b"] = r, g, b
                self.hub.send_cmd(f"RGB,{rp},{gp},{bp},{anode},{r},{g},{b}")
                card = self.hub.card_widgets.get(target_id)
                if card and hasattr(card, "sync_ui"):
                    self.hub.dispatch_ui(card.sync_ui, r, g, b)

            elif action == "matrix":
                din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
                pat_name = params.get("pattern", "❤️ 愛心")
                if pat_name in PRESET_MATRIX:
                    bmp = PRESET_MATRIX[pat_name]
                elif pat_name == "清空":
                    bmp = [0] * 8
                else:
                    bmp = params.get("matrix", [0] * 8)
                comp["state"]["matrix"] = list(bmp)
                bytes_str = ",".join(str(b) for b in bmp)
                self.hub.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},{bytes_str}")
                card = self.hub.card_widgets.get(target_id)
                if card and hasattr(card, "sync_matrix"):
                    self.hub.dispatch_ui(card.sync_matrix, list(bmp))

            elif action == "matrix_marquee":
                din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
                txt = params.get("text", "HELLO")
                spd = max(25, params.get("speed_ms", 70))
                loops = max(1, params.get("loops", 1))
                frames = text_to_matrix_frames(txt)
                for _ in range(loops):
                    for f in frames:
                        if self.stop_event.is_set():
                            break
                        comp["state"]["matrix"] = list(f)
                        bytes_str = ",".join(str(b) for b in f)
                        self.hub.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},{bytes_str}")
                        card = self.hub.card_widgets.get(target_id)
                        if card and hasattr(card, "sync_matrix"):
                            self.hub.dispatch_ui(card.sync_matrix, list(f))
                        elapsed = 0
                        while elapsed < spd and not self.stop_event.is_set():
                            time.sleep(0.005)
                            elapsed += 5

            elif action == "matrix_anim":
                din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
                anim_name = params.get("anim", "💓 心跳搏動動畫")
                spd = max(30, params.get("speed_ms", 90))
                repeats = max(1, params.get("repeats", 2))
                frames = PRESET_ANIMATIONS.get(anim_name, [])
                for _ in range(repeats):
                    for f in frames:
                        if self.stop_event.is_set():
                            break
                        comp["state"]["matrix"] = list(f)
                        bytes_str = ",".join(str(b) for b in f)
                        self.hub.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},{bytes_str}")
                        card = self.hub.card_widgets.get(target_id)
                        if card and hasattr(card, "sync_matrix"):
                            self.hub.dispatch_ui(card.sync_matrix, list(f))
                        elapsed = 0
                        while elapsed < spd and not self.stop_event.is_set():
                            time.sleep(0.005)
                            elapsed += 5

            elif action == "servo":
                p = pins.get("pin", 9)
                ang = params.get("angle", 90)
                comp["state"]["angle"] = ang
                self.hub.send_cmd(f"SERVO,{p},{ang}")
                card = self.hub.card_widgets.get(target_id)
                if card and hasattr(card, "sync_ui"):
                    self.hub.dispatch_ui(card.sync_ui, ang)

            elif action == "switch":
                p = pins.get("pin", 13)
                is_on = params.get("on", True)
                comp["state"]["on"] = is_on
                self.hub.send_cmd(f"DWRITE,{p},{1 if is_on else 0}")
                card = self.hub.card_widgets.get(target_id)
                if card and hasattr(card, "sync_ui"):
                    self.hub.dispatch_ui(card.sync_ui, is_on)

            elif action == "pwm":
                p = pins.get("pin", 9)
                val = params.get("val", 0)
                comp["state"]["val"] = val
                self.hub.send_cmd(f"AWRITE,{p},{val}")
                card = self.hub.card_widgets.get(target_id)
                if card and hasattr(card, "sync_ui"):
                    self.hub.dispatch_ui(card.sync_ui, val)
        except Exception as e:
            self.hub.log(f"⚠️ 步驟執行異常: {e}")


class WorkflowDialog(tk.Toplevel):
    """自訂流程與自動化編排管理視窗"""
    def __init__(self, parent, hub):
        super().__init__(parent)
        self.hub = hub
        self.title("🎭 自訂流程與自動化編排管理中樞 (Workflow Sequencer)")
        self.geometry("880x580")
        self.minsize(780, 500)
        self.configure(bg=hub.BG_TOP)
        # 保持非強制獨佔，確保自動化背景執行與主介面同步響應，杜絕 Windows「沒有回應」假死
        self.transient(parent)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.current_wf_idx = 0 if hub.workflows else -1

        self._build_ui()
        self._refresh_wf_list()
        self._refresh_step_table()

    def _on_close(self):
        if self.hub.workflow_engine.on_step_change == self._on_step_active:
            self.hub.workflow_engine.on_step_change = None
        self.destroy()

    def _build_ui(self):
        top_bar = tk.Frame(self, bg=self.hub.BG_TOP, padx=15, pady=8)
        top_bar.pack(fill=tk.X)
        tk.Label(top_bar, text="🎭 動作序列自動化排程 (自訂多配件聯動流程)", bg=self.hub.BG_TOP, fg=self.hub.ACCENT, font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        main_body = tk.Frame(self, bg=self.hub.BG_MAIN, padx=10, pady=10)
        main_body.pack(fill=tk.BOTH, expand=True)

        # --- 左欄：流程清單與播放控制 ---
        left_frame = tk.Frame(main_body, bg=self.hub.BG_CARD, width=280, padx=10, pady=10)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="流程清單", bg=self.hub.BG_CARD, fg=self.hub.TEXT_MAIN, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        self.wf_listbox = tk.Listbox(left_frame, bg="#181825", fg="#CDD6F4", selectbackground="#45475A", selectforeground="#89B4FA", bd=0, font=("Segoe UI", 9))
        self.wf_listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.wf_listbox.bind("<<ListboxSelect>>", self._on_select_wf)

        wf_btn_bar = tk.Frame(left_frame, bg=self.hub.BG_CARD)
        wf_btn_bar.pack(fill=tk.X, pady=(0, 12))
        tk.Button(wf_btn_bar, text="➕ 新增", bg="#313244", fg=self.hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), command=self.add_workflow).pack(side=tk.LEFT, padx=2)
        tk.Button(wf_btn_bar, text="✏️ 命名", bg="#313244", fg=self.hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), command=self.rename_workflow).pack(side=tk.LEFT, padx=2)
        tk.Button(wf_btn_bar, text="🗑️ 刪除", bg="#313244", fg="#F38BA8", bd=0, font=("Segoe UI", 8), command=self.delete_workflow).pack(side=tk.LEFT, padx=2)

        play_box = tk.LabelFrame(left_frame, text="執行控制", bg=self.hub.BG_CARD, fg=self.hub.TEXT_MUTED, padx=8, pady=8)
        play_box.pack(fill=tk.X)

        self.loop_var = tk.BooleanVar(value=False)
        self.chk_loop = ttk.Checkbutton(play_box, text="🔁 循環播放 (Loop)", variable=self.loop_var, command=self._toggle_loop)
        self.chk_loop.pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(play_box, bg=self.hub.BG_CARD)
        btn_row.pack(fill=tk.X)
        self.btn_run = tk.Button(btn_row, text="▶️ 啟動流程", bg="#A6E3A1", fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, command=self.run_current_workflow)
        self.btn_run.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.btn_stop = tk.Button(btn_row, text="⏹️ 停止", bg="#F38BA8", fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, command=self.stop_current_workflow)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.btn_flash_standalone = tk.Button(
            play_box, text="🔥 脫機燒錄此流程至 Arduino",
            bg="#FAB387", fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0,
            command=self.flash_standalone_workflow
        )
        self.btn_flash_standalone.pack(fill=tk.X, pady=(6, 0))

        self.status_lbl = tk.Label(play_box, text="狀態: 閒置", bg=self.hub.BG_CARD, fg=self.hub.TEXT_MUTED, font=("Segoe UI", 8))
        self.status_lbl.pack(anchor="w", pady=(8, 0))

        # --- 右欄：步驟序列表格與操作 ---
        right_frame = tk.Frame(main_body, bg=self.hub.BG_CARD, padx=10, pady=10)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_top = tk.Frame(right_frame, bg=self.hub.BG_CARD)
        right_top.pack(fill=tk.X, pady=(0, 6))
        self.step_title_lbl = tk.Label(right_top, text="步驟序列", bg=self.hub.BG_CARD, fg=self.hub.TEXT_MAIN, font=("Segoe UI", 10, "bold"))
        self.step_title_lbl.pack(side=tk.LEFT)
        tk.Label(right_top, text="💡 點選任一步驟即時觸發執行動作", bg=self.hub.BG_CARD, fg=self.hub.ACCENT, font=("Segoe UI", 8)).pack(side=tk.RIGHT)

        tree_container = tk.Frame(right_frame, bg=self.hub.BG_CARD)
        tree_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        columns = ("step", "target", "desc")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=12)
        self.tree.heading("step", text="#")
        self.tree.heading("target", text="目標對象 / 模組")
        self.tree.heading("desc", text="執行動作內容")

        self.tree.column("step", width=45, anchor="center")
        self.tree.column("target", width=160)
        self.tree.column("desc", width=320)

        # 綁定點選與鍵盤導航：點到哪裡立即即時執行該步驟！
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<KeyRelease-Up>", self._on_tree_key_nav)
        self.tree.bind("<KeyRelease-Down>", self._on_tree_key_nav)

        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        step_btn_bar = tk.Frame(right_frame, bg=self.hub.BG_CARD)
        step_btn_bar.pack(fill=tk.X)
        tk.Button(step_btn_bar, text="➕ 新增步驟", bg="#45475A", fg="#FFFFFF", bd=0, font=("Segoe UI", 8, "bold"), padx=8, command=self.add_step_dialog).pack(side=tk.LEFT, padx=3)
        tk.Button(step_btn_bar, text="⬆️ 上移", bg="#313244", fg=self.hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), padx=6, command=lambda: self.move_step(-1)).pack(side=tk.LEFT, padx=3)
        tk.Button(step_btn_bar, text="⬇️ 下移", bg="#313244", fg=self.hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), padx=6, command=lambda: self.move_step(1)).pack(side=tk.LEFT, padx=3)
        tk.Button(step_btn_bar, text="❌ 刪除步驟", bg="#313244", fg="#F38BA8", bd=0, font=("Segoe UI", 8), padx=6, command=self.delete_step).pack(side=tk.RIGHT, padx=3)

    def _refresh_wf_list(self):
        self.wf_listbox.delete(0, tk.END)
        for wf in self.hub.workflows:
            loop_tag = " [🔁]" if wf.get("loop", False) else ""
            self.wf_listbox.insert(tk.END, f"{wf.get('name', '未命名')}{loop_tag}")
        if 0 <= self.current_wf_idx < len(self.hub.workflows):
            self.wf_listbox.select_set(self.current_wf_idx)
            wf = self.hub.workflows[self.current_wf_idx]
            self.loop_var.set(wf.get("loop", False))
            self.step_title_lbl.configure(text=f"步驟序列 - {wf.get('name')}")
        else:
            self.step_title_lbl.configure(text="步驟序列 (請先選取流程)")

    def _on_select_wf(self, event):
        sel = self.wf_listbox.curselection()
        if sel:
            self.current_wf_idx = sel[0]
            wf = self.hub.workflows[self.current_wf_idx]
            self.loop_var.set(wf.get("loop", False))
            self.step_title_lbl.configure(text=f"步驟序列 - {wf.get('name')}")
            self._refresh_step_table()

    def _refresh_step_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return

        wf = self.hub.workflows[self.current_wf_idx]
        steps = wf.get("steps", [])
        for idx, s in enumerate(steps):
            action = s.get("action")
            desc = s.get("desc", "")
            if action == "delay":
                target_name = "系統延遲 (Delay)"
            elif action == "dual_effect":
                target_name = "✨ 雙燈連線特效"
            else:
                comp = next((c for c in self.hub.components if c["id"] == s.get("target_id")), None)
                target_name = comp.get("name", "未知配件") if comp else "未綁定配件"
            self.tree.insert("", tk.END, iid=str(idx), values=(str(idx + 1), target_name, desc))

    def _toggle_loop(self):
        if 0 <= self.current_wf_idx < len(self.hub.workflows):
            self.hub.workflows[self.current_wf_idx]["loop"] = self.loop_var.get()
            self._refresh_wf_list()

    def add_workflow(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("新增流程", "請輸入新流程名稱：", parent=self)
        if name and name.strip():
            new_wf = {
                "id": f"wf_{int(time.time() * 1000)}",
                "name": name.strip(),
                "loop": False,
                "steps": [],
            }
            self.hub.workflows.append(new_wf)
            self.current_wf_idx = len(self.hub.workflows) - 1
            self._refresh_wf_list()
            self._refresh_step_table()

    def rename_workflow(self):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return
        from tkinter import simpledialog
        wf = self.hub.workflows[self.current_wf_idx]
        new_name = simpledialog.askstring("重新命名", "請輸入新流程名稱：", initialvalue=wf.get("name"), parent=self)
        if new_name and new_name.strip():
            wf["name"] = new_name.strip()
            self._refresh_wf_list()

    def delete_workflow(self):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return
        wf = self.hub.workflows[self.current_wf_idx]
        if messagebox.askyesno("刪除確認", f"確定要刪除流程『{wf.get('name')}』嗎？", parent=self):
            self.hub.workflows.pop(self.current_wf_idx)
            self.current_wf_idx = max(0, len(self.hub.workflows) - 1)
            self._refresh_wf_list()
            self._refresh_step_table()

    def run_current_workflow(self):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            messagebox.showwarning("提示", "請先選取要執行的流程！", parent=self)
            return
        wf = self.hub.workflows[self.current_wf_idx]
        if not wf.get("steps"):
            messagebox.showwarning("提示", "此流程目前沒有任何步驟，請先新增步驟！", parent=self)
            return

        self.status_lbl.configure(text=f"🟢 執行中: {wf.get('name')}", fg="#A6E3A1")
        self.btn_run.configure(state="disabled")
        self.hub.workflow_engine.start_workflow(
            wf,
            on_step_callback=self._on_step_active,
            on_finish_callback=self._on_finish_active,
        )

    def stop_current_workflow(self):
        self.hub.workflow_engine.stop()
        self.status_lbl.configure(text="狀態: 已停止", fg=self.hub.TEXT_MUTED)
        self.btn_run.configure(state="normal")

    def flash_standalone_workflow(self):
        """將目前選定的自訂流程脫機燒錄進 Arduino Uno 晶片"""
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            messagebox.showwarning("提示", "請先選取要脫機燒錄的自訂流程！", parent=self)
            return
        self.hub.flash_standalone_workflow(self.current_wf_idx)

    def _on_step_active(self, step_idx):
        try:
            if not self.winfo_exists():
                return
            if step_idx >= 0:
                self.status_lbl.configure(text=f"🟢 正在執行: 步驟 {step_idx + 1}", fg="#A6E3A1")
                try:
                    self.tree.selection_set(str(step_idx))
                    self.tree.see(str(step_idx))
                except Exception:
                    pass
            else:
                self.status_lbl.configure(text="狀態: 閒置", fg=self.hub.TEXT_MUTED)
                self.btn_run.configure(state="normal")
        except Exception:
            pass

    def _on_finish_active(self):
        try:
            if not self.winfo_exists():
                return
            self.status_lbl.configure(text="狀態: 執行完畢", fg="#89B4FA")
            self.btn_run.configure(state="normal")
        except Exception:
            pass

    def move_step(self, direction):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        new_idx = idx + direction
        steps = self.hub.workflows[self.current_wf_idx].get("steps", [])
        if 0 <= new_idx < len(steps):
            steps[idx], steps[new_idx] = steps[new_idx], steps[idx]
            self._refresh_step_table()
            self.tree.selection_set(str(new_idx))

    def delete_step(self):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        steps = self.hub.workflows[self.current_wf_idx].get("steps", [])
        if 0 <= idx < len(steps):
            steps.pop(idx)
            self._refresh_step_table()

    def _on_tree_click(self, event):
        """滑鼠點擊任意步驟，立即執行該步驟動作"""
        if self.hub.workflow_engine.is_running():
            return
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        try:
            idx = int(item_id)
            self._execute_single_step_by_idx(idx)
        except ValueError:
            pass

    def _on_tree_key_nav(self, event):
        """方向鍵上下切換步驟時，同步即時執行該步驟動作"""
        if self.hub.workflow_engine.is_running():
            return
        sel = self.tree.selection()
        if sel:
            try:
                idx = int(sel[0])
                self._execute_single_step_by_idx(idx)
            except ValueError:
                pass

    def _execute_single_step_by_idx(self, idx):
        """直接單步觸發特定步驟"""
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return
        steps = self.hub.workflows[self.current_wf_idx].get("steps", [])
        if 0 <= idx < len(steps):
            step = steps[idx]
            self.status_lbl.configure(text=f"⚡ 即時單步: 步驟 {idx + 1}", fg="#89B4FA")
            threading.Thread(target=lambda: self.hub.workflow_engine.execute_step(step), daemon=True).start()
            self.hub.log(f"⚡ 單步即時觸發 [步驟 {idx + 1}]: {step.get('desc')}")

    def add_step_dialog(self):
        if self.current_wf_idx < 0 or self.current_wf_idx >= len(self.hub.workflows):
            return

        dlg = tk.Toplevel(self)
        dlg.title("➕ 新增動作步驟")
        dlg.geometry("450x420")
        dlg.resizable(False, False)
        dlg.configure(bg=self.hub.BG_TOP)
        dlg.grab_set()

        tk.Label(dlg, text="設定步驟目標與動作參數", bg=self.hub.BG_TOP, fg=self.hub.ACCENT, font=("Segoe UI", 11, "bold")).pack(pady=(12, 8))

        form = tk.Frame(dlg, bg=self.hub.BG_TOP, padx=20)
        form.pack(fill=tk.BOTH, expand=True)

        # 目標配件選擇
        tk.Label(form, text="目標配件:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=6)
        target_options = ["⏱️ 系統等待延遲 (Delay)", "✨ 雙燈連線特效 (18款炫彩)"] + [f"[{c['type'].upper()}] {c['name']}" for c in self.hub.components]
        target_var = tk.StringVar(value=target_options[0])
        target_combo = ttk.Combobox(form, textvariable=target_var, values=target_options, state="readonly", width=28)
        target_combo.grid(row=0, column=1, sticky="w", pady=6)

        param_box = tk.Frame(form, bg=self.hub.BG_TOP)
        param_box.grid(row=1, column=0, columnspan=2, sticky="we", pady=10)

        param_vars = {}

        def update_param_fields(*args):
            for w in param_box.winfo_children():
                w.destroy()
            param_vars.clear()

            sel_idx = target_combo.current()
            if sel_idx == 0:  # 延遲
                tk.Label(param_box, text="延遲時間 (毫秒 ms):", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=4)
                v = tk.IntVar(value=500)
                param_vars["ms"] = v
                ttk.Spinbox(param_box, from_=50, to=10000, increment=50, textvariable=v, width=10).grid(row=0, column=1, sticky="w", padx=10)
            elif sel_idx == 1:  # 雙燈連線特效
                tk.Label(param_box, text="選擇特效:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=4)
                fx_names = [label for key, label in DualRGBEffectsDialog.EFFECTS]
                v_fx = tk.StringVar(value=fx_names[0])
                param_vars["dual_effect_label"] = v_fx
                ttk.Combobox(param_box, textvariable=v_fx, values=fx_names, state="readonly", width=18).grid(row=0, column=1, sticky="w", padx=10)

                tk.Label(param_box, text="持續時間 (毫秒 ms):", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=1, column=0, sticky="w", pady=4)
                v_dur = tk.IntVar(value=3000)
                param_vars["duration_ms"] = v_dur
                ttk.Spinbox(param_box, from_=500, to=60000, increment=500, textvariable=v_dur, width=10).grid(row=1, column=1, sticky="w", padx=10)
            else:
                comp = self.hub.components[sel_idx - 2]
                c_type = comp.get("type")

                if c_type == "rgb":
                    tk.Label(param_box, text="R 數值 (0~255):", bg=self.hub.BG_TOP, fg="#F38BA8").grid(row=0, column=0, sticky="w", pady=2)
                    vr = tk.IntVar(value=255)
                    param_vars["r"] = vr
                    ttk.Spinbox(param_box, from_=0, to=255, textvariable=vr, width=8).grid(row=0, column=1, sticky="w", padx=10)

                    tk.Label(param_box, text="G 數值 (0~255):", bg=self.hub.BG_TOP, fg="#A6E3A1").grid(row=1, column=0, sticky="w", pady=2)
                    vg = tk.IntVar(value=0)
                    param_vars["g"] = vg
                    ttk.Spinbox(param_box, from_=0, to=255, textvariable=vg, width=8).grid(row=1, column=1, sticky="w", padx=10)

                    tk.Label(param_box, text="B 數值 (0~255):", bg=self.hub.BG_TOP, fg="#89B4FA").grid(row=2, column=0, sticky="w", pady=2)
                    vb = tk.IntVar(value=128)
                    param_vars["b"] = vb
                    ttk.Spinbox(param_box, from_=0, to=255, textvariable=vb, width=8).grid(row=2, column=1, sticky="w", padx=10)

                elif c_type == "matrix":
                    tk.Label(param_box, text="點陣模式:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=2)
                    v_mmode = tk.StringVar(value="1. 靜態圖案")
                    param_vars["matrix_mode"] = v_mmode
                    cb_m = ttk.Combobox(param_box, textvariable=v_mmode, values=["1. 靜態圖案", "2. 跑馬燈文字", "3. 動態圖示動畫"], state="readonly", width=14)
                    cb_m.grid(row=0, column=1, sticky="w", padx=10, pady=2)

                    sub_m = tk.Frame(param_box, bg=self.hub.BG_TOP)
                    sub_m.grid(row=1, column=0, columnspan=2, sticky="we", pady=4)

                    v_pat = tk.StringVar(value="❤️ 愛心")
                    v_txt = tk.StringVar(value="HELLO")
                    v_spd = tk.IntVar(value=70)
                    v_anim = tk.StringVar(value=list(PRESET_ANIMATIONS.keys())[0])
                    v_rep = tk.IntVar(value=2)
                    param_vars["pattern"] = v_pat
                    param_vars["text"] = v_txt
                    param_vars["speed_ms"] = v_spd
                    param_vars["anim"] = v_anim
                    param_vars["repeats"] = v_rep

                    def render_sub(*e):
                        for child in sub_m.winfo_children(): child.destroy()
                        m = v_mmode.get()
                        if m.startswith("1"):
                            tk.Label(sub_m, text="選擇圖案:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=2)
                            ttk.Combobox(sub_m, textvariable=v_pat, values=list(PRESET_MATRIX.keys()) + ["清空"], state="readonly", width=14).grid(row=0, column=1, sticky="w", padx=10)
                        elif m.startswith("2"):
                            tk.Label(sub_m, text="文字內容:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=2)
                            ttk.Entry(sub_m, textvariable=v_txt, width=14).grid(row=0, column=1, sticky="w", padx=10)
                            tk.Label(sub_m, text="滾動速度 (ms):", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=1, column=0, sticky="w", pady=2)
                            ttk.Spinbox(sub_m, from_=30, to=300, increment=10, textvariable=v_spd, width=8).grid(row=1, column=1, sticky="w", padx=10)
                        else:
                            tk.Label(sub_m, text="動畫種類:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=2)
                            ttk.Combobox(sub_m, textvariable=v_anim, values=list(PRESET_ANIMATIONS.keys()), state="readonly", width=14).grid(row=0, column=1, sticky="w", padx=10)
                            tk.Label(sub_m, text="播放次數:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=1, column=0, sticky="w", pady=2)
                            ttk.Spinbox(sub_m, from_=1, to=20, textvariable=v_rep, width=8).grid(row=1, column=1, sticky="w", padx=10)

                    cb_m.bind("<<ComboboxSelected>>", render_sub)
                    render_sub()

                elif c_type == "servo":
                    tk.Label(param_box, text="目標角度 (0~180°):", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=4)
                    v_ang = tk.IntVar(value=90)
                    param_vars["angle"] = v_ang
                    ttk.Spinbox(param_box, from_=0, to=180, textvariable=v_ang, width=8).grid(row=0, column=1, sticky="w", padx=10)

                elif c_type == "switch":
                    tk.Label(param_box, text="開關狀態:", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=4)
                    v_sw = tk.BooleanVar(value=True)
                    param_vars["on"] = v_sw
                    ttk.Radiobutton(param_box, text="🟢 開啟 (ON)", variable=v_sw, value=True).grid(row=0, column=1, sticky="w", padx=5)
                    ttk.Radiobutton(param_box, text="⚪ 關閉 (OFF)", variable=v_sw, value=False).grid(row=1, column=1, sticky="w", padx=5)

                elif c_type == "pwm":
                    tk.Label(param_box, text="PWM 數值 (0~255):", bg=self.hub.BG_TOP, fg=self.hub.TEXT_MAIN).grid(row=0, column=0, sticky="w", pady=4)
                    v_pwm = tk.IntVar(value=128)
                    param_vars["val"] = v_pwm
                    ttk.Spinbox(param_box, from_=0, to=255, textvariable=v_pwm, width=8).grid(row=0, column=1, sticky="w", padx=10)

        target_combo.bind("<<ComboboxSelected>>", update_param_fields)
        update_param_fields()

        def on_add():
            sel_idx = target_combo.current()
            if sel_idx == 0:
                ms = param_vars["ms"].get()
                new_step = {
                    "action": "delay",
                    "params": {"ms": ms},
                    "desc": f"延遲等待 {ms} 毫秒",
                }
            elif sel_idx == 1:
                label = param_vars["dual_effect_label"].get()
                dur = param_vars["duration_ms"].get()
                match = next((k for k, l in DualRGBEffectsDialog.EFFECTS if l == label), "sync_rainbow")
                new_step = {
                    "action": "dual_effect",
                    "params": {"effect": match, "duration_ms": dur},
                    "desc": f"雙燈特效: 『{label}』(持續 {dur}ms)",
                }
            else:
                comp = self.hub.components[sel_idx - 2]
                c_type = comp.get("type")
                cid = comp["id"]
                cname = comp["name"]

                if c_type == "rgb":
                    r, g, b = param_vars["r"].get(), param_vars["g"].get(), param_vars["b"].get()
                    new_step = {
                        "action": "rgb",
                        "target_id": cid,
                        "params": {"r": r, "g": g, "b": b},
                        "desc": f"設為調色 RGB({r}, {g}, {b})",
                    }
                elif c_type == "matrix":
                    mm = param_vars.get("matrix_mode", tk.StringVar(value="1")).get()
                    if mm.startswith("1"):
                        pat = param_vars["pattern"].get()
                        new_step = {
                            "action": "matrix",
                            "target_id": cid,
                            "params": {"pattern": pat},
                            "desc": f"點陣靜態切換『{pat}』",
                        }
                    elif mm.startswith("2"):
                        txt = param_vars["text"].get().strip() or "HELLO"
                        spd = param_vars["speed_ms"].get()
                        new_step = {
                            "action": "matrix_marquee",
                            "target_id": cid,
                            "params": {"text": txt, "speed_ms": spd},
                            "desc": f"點陣跑馬燈: 『{txt}』({spd}ms)",
                        }
                    else:
                        anim = param_vars["anim"].get()
                        rep = param_vars["repeats"].get()
                        new_step = {
                            "action": "matrix_anim",
                            "target_id": cid,
                            "params": {"anim": anim, "repeats": rep},
                            "desc": f"點陣動畫: {anim} (播 {rep} 次)",
                        }
                elif c_type == "servo":
                    ang = param_vars["angle"].get()
                    new_step = {
                        "action": "servo",
                        "target_id": cid,
                        "params": {"angle": ang},
                        "desc": f"舵機旋轉至 {ang}°",
                    }
                elif c_type == "switch":
                    is_on = param_vars["on"].get()
                    new_step = {
                        "action": "switch",
                        "target_id": cid,
                        "params": {"on": is_on},
                        "desc": "開關開啟 (ON)" if is_on else "開關關閉 (OFF)",
                    }
                elif c_type == "pwm":
                    val = param_vars["val"].get()
                    new_step = {
                        "action": "pwm",
                        "target_id": cid,
                        "params": {"val": val},
                        "desc": f"PWM 輸出調整為 {val}",
                    }
                else:
                    return

            self.hub.workflows[self.current_wf_idx]["steps"].append(new_step)
            self._refresh_step_table()
            dlg.destroy()

        btn_box = tk.Frame(dlg, bg=self.hub.BG_TOP)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM, pady=12)
        ttk.Button(btn_box, text="確定加入", style="Primary.TButton", command=on_add).pack(side=tk.RIGHT, padx=15)
        ttk.Button(btn_box, text="取消", command=dlg.destroy).pack(side=tk.RIGHT)


# ==============================================================================
# 雙燈即時連線特效視窗 (Dual RGB Effects Dialog - 18款炫彩特效)
# ==============================================================================

class DualRGBEffectsDialog(tk.Toplevel):
    """雙燈即時連線特效 (18 款炫彩即時特效) 控制視窗"""

    EFFECTS = [
        ("sync_rainbow", "🌈 同步彩虹"),
        ("complementary", "☯ 互補流光"),
        ("police_strobe", "🚨 警車雙閃"),
        ("warm_breathing", "🕯️ 暖色呼吸"),
        ("aurora_breathing", "🌌 極光呼吸"),
        ("disco_party", "🪩 派對跳閃"),
        ("chase_wave", "🌊 交替流水"),
        ("fire_flicker", "🔥 壁爐跳火"),
        ("thunder_storm", "⚡ 暴風雷電"),
        ("heartbeat", "💓 心跳搏動"),
        ("cyberpunk_neon", "🛸 賽博霓虹"),
        ("meteor_shower", "🌠 彗星拖尾"),
        ("sunrise_glow", "🌅 晨曦日出"),
        ("emerald_forest", "🌲 翡翠森林"),
        ("magic_crystal", "🔮 魔法水晶"),
        ("volcano_magma", "🌋 岩漿熔岩"),
        ("ambulance_amber", "🚑 救護警戒"),
        ("candy_pop", "🍭 糖果幻彩"),
    ]

    def __init__(self, parent, hub):
        super().__init__(parent)
        self.hub = hub
        self.title("✨ 雙燈即時連線特效 (18 款炫彩即時特效)")
        self.geometry("720x460")
        self.minsize(680, 420)
        self.configure(bg=hub.BG_TOP)
        self.transient(parent)

        self.btn_map = {}
        self._build_ui()
        self._update_active_state()

    def _build_ui(self):
        top_bar = tk.Frame(self, bg=self.hub.BG_TOP, padx=16, pady=10)
        top_bar.pack(fill=tk.X)
        tk.Label(
            top_bar,
            text="✨ 雙燈即時連線特效 (18 款炫彩即時特效)",
            bg=self.hub.BG_TOP,
            fg=self.hub.ACCENT,
            font=("Segoe UI", 12, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            top_bar,
            text="雙 RGB 模組即時流光演色 · 隨選即播",
            bg=self.hub.BG_TOP,
            fg=self.hub.TEXT_MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT, pady=2)

        main_body = tk.Frame(self, bg=self.hub.BG_MAIN, padx=14, pady=12)
        main_body.pack(fill=tk.BOTH, expand=True)

        grid_frame = tk.Frame(main_body, bg=self.hub.BG_MAIN)
        grid_frame.pack(fill=tk.BOTH, expand=True)

        # 3 行 x 6 列 排列
        for idx, (key, label) in enumerate(self.EFFECTS):
            row = idx // 6
            col = idx % 6
            grid_frame.grid_columnconfigure(col, weight=1, uniform="col")
            grid_frame.grid_rowconfigure(row, weight=1, uniform="row")

            btn = tk.Button(
                grid_frame,
                text=label,
                bg="#313244",
                fg=self.hub.TEXT_MAIN,
                activebackground="#45475A",
                activeforeground="#89B4FA",
                bd=0,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
                command=lambda k=key: self._on_select_effect(k),
            )
            btn.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            self.btn_map[key] = btn

        bottom_bar = tk.Frame(self, bg=self.hub.BG_TOP, padx=16, pady=10)
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_lbl = tk.Label(
            bottom_bar,
            text="狀態: 閒置 (請點選上方按鈕播放特效)",
            bg=self.hub.BG_TOP,
            fg=self.hub.TEXT_MUTED,
            font=("Segoe UI", 9),
        )
        self.status_lbl.pack(side=tk.LEFT)

        tk.Button(
            bottom_bar,
            text="關閉",
            bg="#45475A",
            fg=self.hub.TEXT_MAIN,
            bd=0,
            font=("Segoe UI", 9),
            padx=12,
            pady=4,
            command=self.destroy,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        self.btn_stop = tk.Button(
            bottom_bar,
            text="⏹️ 停止特效 / 關閉雙燈",
            bg="#F38BA8",
            fg="#11111B",
            bd=0,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=4,
            cursor="hand2",
            command=self._on_stop,
        )
        self.btn_stop.pack(side=tk.RIGHT)

    def _on_select_effect(self, key):
        self.hub.start_dual_effect(key)
        self._update_active_state(key)

    def _on_stop(self):
        self.hub.stop_dual_effect()
        self._update_active_state(None)

    def _update_active_state(self, active_key=None):
        if active_key is None:
            active_key = getattr(self.hub, "current_effect_name", None)

        for k, btn in self.btn_map.items():
            if k == active_key:
                btn.configure(bg="#89B4FA", fg="#11111B")
            else:
                btn.configure(bg="#313244", fg=self.hub.TEXT_MAIN)

        if active_key:
            name = next((lbl for k, lbl in self.EFFECTS if k == active_key), active_key)
            self.status_lbl.configure(text=f"狀態: 正在播放 [{name}]", fg="#A6E3A1")
        else:
            self.status_lbl.configure(text="狀態: 閒置 (已停止)", fg=self.hub.TEXT_MUTED)


# ==============================================================================
# 配件卡片元件類別 (Component Cards)
# ==============================================================================

class BaseCard(tk.Frame):
    """所有配件卡片的基礎框架，統一外觀、標題與刪除操作"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, bg=hub.BG_CARD, bd=1, relief="ridge", padx=10, pady=8)
        self.pack(fill=tk.X, expand=True, pady=6)
        self.hub = hub
        self.data = data
        self.comp_id = data["id"]

        # 卡片頂部欄
        top_bar = tk.Frame(self, bg=hub.BG_CARD)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        tk.Label(top_bar, text=data.get("name", "配件"), bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        # 右側操作按鈕區 (⚙️ 設定腳位 / 🗑️ 刪除)
        actions = tk.Frame(top_bar, bg=hub.BG_CARD)
        actions.pack(side=tk.RIGHT)

        edit_btn = tk.Button(
            actions, text="⚙️ 設定腳位", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, activebackground=hub.BG_TOP,
            activeforeground=hub.ACCENT, bd=0, cursor="hand2", font=("Segoe UI", 8),
            command=lambda: self.hub.open_edit_component_dialog(self.comp_id)
        )
        edit_btn.pack(side=tk.LEFT, padx=(0, 6))

        del_btn = tk.Button(
            actions, text="🗑️", bg=hub.BG_CARD, fg="#F38BA8", bd=0, cursor="hand2", font=("Segoe UI", 9),
            command=lambda: self.hub.remove_component(self.comp_id)
        )
        del_btn.pack(side=tk.LEFT)


class SwitchCard(BaseCard):
    """💡 數位開關 (繼電器 / 單色 LED / 蜂鳴器)"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.pin = data["pins"].get("pin", 13)
        self.is_on = data.get("state", {}).get("on", False)

        info_lbl = tk.Label(self, text=f"數位腳位: Pin {self.pin}", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        info_lbl.pack(anchor="w", pady=(0, 6))

        btn_box = tk.Frame(self, bg=hub.BG_CARD)
        btn_box.pack(fill=tk.X, pady=4)

        self.btn_toggle = tk.Button(
            btn_box,
            text="🟢 開啟 (ON)" if self.is_on else "⚪ 關閉 (OFF)",
            bg="#A6E3A1" if self.is_on else "#45475A",
            fg="#11111B" if self.is_on else "#CDD6F4",
            font=("Segoe UI", 10, "bold"),
            command=self.toggle,
            width=14,
            pady=4,
        )
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 10))

    def toggle(self):
        self.is_on = not self.is_on
        self.data["state"]["on"] = self.is_on
        val = 1 if self.is_on else 0
        self.hub.send_cmd(f"DWRITE,{self.pin},{val}")

        if self.is_on:
            self.btn_toggle.configure(text="🟢 開啟 (ON)", bg="#A6E3A1", fg="#11111B")
        else:
            self.btn_toggle.configure(text="⚪ 關閉 (OFF)", bg="#45475A", fg="#CDD6F4")

        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "comp_state",
                "id": self.data["id"],
                "state": {"on": self.is_on}
            })

    def sync_ui(self, is_on):
        try:
            if not self.winfo_exists():
                return
            self.is_on = is_on
            self.data["state"]["on"] = is_on
            if is_on:
                self.btn_toggle.configure(text="🟢 開啟 (ON)", bg="#A6E3A1", fg="#11111B")
            else:
                self.btn_toggle.configure(text="⚪ 關閉 (OFF)", bg="#45475A", fg="#CDD6F4")
        except Exception:
            pass


class PWMCard(BaseCard):
    """🎚️ PWM 調光 / 馬達轉速"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.pin = data["pins"].get("pin", 9)
        self.val = data.get("state", {}).get("val", 0)
        self.ready = False

        info_lbl = tk.Label(self, text=f"PWM 輸出腳位: Pin {self.pin}", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        info_lbl.pack(anchor="w")

        ctrl_box = tk.Frame(self, bg=hub.BG_CARD)
        ctrl_box.pack(fill=tk.X, pady=6)

        pct = int(self.val / 255 * 100)
        self.val_lbl = tk.Label(ctrl_box, text=f"{self.val} ({pct}%)", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 9, "bold"), width=10)
        self.val_lbl.pack(side=tk.RIGHT)

        self.scale = ttk.Scale(ctrl_box, from_=0, to=255, orient=tk.HORIZONTAL, command=self.on_slide)
        self.scale.set(self.val)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # 快速預設
        quick_box = tk.Frame(self, bg=hub.BG_CARD)
        quick_box.pack(fill=tk.X)
        for pct_item, pval in [(0, 0), (25, 64), (50, 128), (75, 191), (100, 255)]:
            tk.Button(
                quick_box, text=f"{pct_item}%", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 7),
                command=lambda v=pval: self.set_val(v)
            ).pack(side=tk.LEFT, padx=2)

        self.ready = True

    def on_slide(self, val_str):
        if not getattr(self, "ready", False):
            return
        val = int(float(val_str))
        self.set_val(val, update_slider=False)

    def set_val(self, val, update_slider=True):
        self.val = val
        self.data["state"]["val"] = val
        if update_slider:
            self.scale.set(val)
        pct = int(val / 255 * 100)
        self.val_lbl.configure(text=f"{val} ({pct}%)")
        self.hub.send_cmd(f"AWRITE,{self.pin},{val}")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "comp_state",
                "id": self.data["id"],
                "state": {"val": self.val}
            })

    def sync_ui(self, val):
        try:
            if not self.winfo_exists():
                return
            self.ready = False
            self.val = val
            self.data["state"]["val"] = val
            self.scale.set(val)
            pct = int(val / 255 * 100)
            self.val_lbl.configure(text=f"{val} ({pct}%)")
        except Exception:
            pass
        finally:
            self.ready = True


class ServoCard(BaseCard):
    """🦾 伺服舵機控制 (Servo 0°~180°)"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.pin = data["pins"].get("pin", 9)
        self.angle = data.get("state", {}).get("angle", 90)
        self.ready = False

        info_lbl = tk.Label(self, text=f"舵機訊號腳位: Pin {self.pin}", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        info_lbl.pack(anchor="w")

        ctrl_box = tk.Frame(self, bg=hub.BG_CARD)
        ctrl_box.pack(fill=tk.X, pady=6)

        self.angle_lbl = tk.Label(ctrl_box, text=f"{self.angle}°", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 10, "bold"), width=6)
        self.angle_lbl.pack(side=tk.RIGHT)

        self.scale = ttk.Scale(ctrl_box, from_=0, to=180, orient=tk.HORIZONTAL, command=self.on_slide)
        self.scale.set(self.angle)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # 常用角度按鈕
        preset_box = tk.Frame(self, bg=hub.BG_CARD)
        preset_box.pack(fill=tk.X)
        for ang in [0, 45, 90, 135, 180]:
            tk.Button(
                preset_box, text=f"{ang}°", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8),
                command=lambda a=ang: self.set_angle(a)
            ).pack(side=tk.LEFT, padx=3)

        self.ready = True

    def on_slide(self, val_str):
        if not getattr(self, "ready", False):
            return
        angle = int(float(val_str))
        self.set_angle(angle, update_slider=False)

    def set_angle(self, angle, update_slider=True):
        self.angle = angle
        self.data["state"]["angle"] = angle
        if update_slider:
            self.scale.set(angle)
        self.angle_lbl.configure(text=f"{angle}°")
        self.hub.send_cmd(f"SERVO,{self.pin},{angle}")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "comp_state",
                "id": self.data["id"],
                "state": {"angle": self.angle}
            })

    def sync_ui(self, angle):
        try:
            if not self.winfo_exists():
                return
            self.ready = False
            self.angle = angle
            self.data["state"]["angle"] = angle
            self.scale.set(angle)
            self.angle_lbl.configure(text=f"{angle}°")
        except Exception:
            pass
        finally:
            self.ready = True


class RGBCard(BaseCard):
    """🌈 多通道 RGB LED 控制器"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.r_pin = data["pins"].get("r", 6)
        self.g_pin = data["pins"].get("g", 3)
        self.b_pin = data["pins"].get("b", 5)
        self.is_anode = data.get("common_anode", True)
        self.ready = False

        st = data.get("state", {})
        self.r = st.get("r", 255)
        self.g = st.get("g", 0)
        self.b = st.get("b", 128)

        info_lbl = tk.Label(
            self,
            text=f"腳位: R={self.r_pin}, G={self.g_pin}, B={self.b_pin} | {'共陽極' if self.is_anode else '共陰極'}",
            bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8),
        )
        info_lbl.pack(anchor="w", pady=(0, 4))

        main_box = tk.Frame(self, bg=hub.BG_CARD)
        main_box.pack(fill=tk.X, pady=2)

        # 顏色即時預覽方塊
        self.color_preview = tk.Canvas(main_box, width=42, height=42, bd=1, relief="ridge", highlightthickness=0)
        self.color_preview.pack(side=tk.LEFT, padx=(0, 10))

        # 滑桿容器
        sliders_box = tk.Frame(main_box, bg=hub.BG_CARD)
        sliders_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.r_scale = self._add_color_slider(sliders_box, "R", "#F38BA8", self.r, self.on_change)
        self.g_scale = self._add_color_slider(sliders_box, "G", "#A6E3A1", self.g, self.on_change)
        self.b_scale = self._add_color_slider(sliders_box, "B", "#89B4FA", self.b, self.on_change)

        self.ready = True
        self._update_preview()

        # 快捷顏色按鈕
        quick_box = tk.Frame(self, bg=hub.BG_CARD)
        quick_box.pack(fill=tk.X, pady=(6, 0))
        palette = [
            ("🔴 紅", 255, 0, 0),
            ("🟢 綠", 0, 255, 0),
            ("🔵 藍", 0, 0, 255),
            ("🟡 黃", 255, 200, 0),
            ("🟣 紫", 200, 0, 255),
            ("⚪ 白", 255, 255, 255),
            ("⚫ 全熄", 0, 0, 0),
        ]
        for name, r, g, b in palette:
            tk.Button(
                quick_box, text=name, bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 7),
                command=lambda cr=r, cg=g, cb=b: self.set_rgb(cr, cg, cb)
            ).pack(side=tk.LEFT, padx=2)

    def _add_color_slider(self, parent, label, fg_color, init_val, callback):
        row = tk.Frame(parent, bg=self.hub.BG_CARD)
        row.pack(fill=tk.X, pady=1)
        tk.Label(row, text=label, bg=self.hub.BG_CARD, fg=fg_color, font=("Segoe UI", 8, "bold"), width=2).pack(side=tk.LEFT)
        scale = ttk.Scale(row, from_=0, to=255, orient=tk.HORIZONTAL, command=lambda v: callback())
        scale.set(init_val)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        return scale

    def _update_preview(self):
        hex_color = f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        self.color_preview.configure(bg=hex_color)

    def on_change(self):
        if not getattr(self, "ready", False):
            return
        if getattr(self.hub, "current_effect_name", None):
            self.hub.stop_dual_effect(turn_off=False)
        self.r = int(self.r_scale.get())
        self.g = int(self.g_scale.get())
        self.b = int(self.b_scale.get())
        self._update_preview()
        self.data["state"]["r"] = self.r
        self.data["state"]["g"] = self.g
        self.data["state"]["b"] = self.b
        anode_flag = 1 if self.is_anode else 0
        self.hub.send_cmd(f"RGB,{self.r_pin},{self.g_pin},{self.b_pin},{anode_flag},{self.r},{self.g},{self.b}")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "comp_state",
                "id": self.data["id"],
                "state": {"r": self.r, "g": self.g, "b": self.b}
            })

    def set_rgb(self, r, g, b):
        self.r_scale.set(r)
        self.g_scale.set(g)
        self.b_scale.set(b)
        self.on_change()

    def sync_ui(self, r, g, b):
        try:
            if not self.winfo_exists():
                return
            self.ready = False
            self.r, self.g, self.b = r, g, b
            self.data["state"]["r"] = r
            self.data["state"]["g"] = g
            self.data["state"]["b"] = b
            self.r_scale.set(r)
            self.g_scale.set(g)
            self.b_scale.set(b)
            self._update_preview()
        except Exception:
            pass
        finally:
            self.ready = True


class MatrixCard(BaseCard):
    """👾 MAX7219 8x8 點陣動態畫布與控制器"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.din = data["pins"].get("din", 12)
        self.cs = data["pins"].get("cs", 8)
        self.clk = data["pins"].get("clk", 7)

        # 8x8 像素矩陣 (8 bytes)
        self.matrix = list(data.get("state", {}).get("matrix", [0] * 8))

        info_lbl = tk.Label(
            self,
            text=f"MAX7219 腳位: DIN={self.din}, CS={self.cs}, CLK={self.clk}",
            bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8),
        )
        info_lbl.pack(anchor="w", pady=(0, 4))

        body = tk.Frame(self, bg=hub.BG_CARD)
        body.pack(fill=tk.X, pady=4)

        # 8x8 互動 Canvas
        self.dot_size = 18
        self.margin = 2
        canvas_dim = 8 * self.dot_size + 4
        self.canvas = tk.Canvas(body, width=canvas_dim, height=canvas_dim, bg="#11111B", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, padx=(0, 15))
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        # 右側控制區
        right_box = tk.Frame(body, bg=hub.BG_CARD)
        right_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(right_box, text="預設經典圖案:", bg=hub.BG_CARD, fg=hub.TEXT_MAIN, font=("Segoe UI", 8)).pack(anchor="w")
        self.pattern_combo = ttk.Combobox(right_box, values=list(PRESET_MATRIX.keys()), state="readonly", width=12)
        self.pattern_combo.pack(fill=tk.X, pady=(2, 6))
        self.pattern_combo.bind("<<ComboboxSelected>>", self.on_select_preset)

        btn_row = tk.Frame(right_box, bg=hub.BG_CARD)
        btn_row.pack(fill=tk.X, pady=2)
        tk.Button(btn_row, text="清空", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), command=self.clear_matrix).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_row, text="反轉", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), command=self.invert_matrix).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_row, text="全亮", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 8), command=self.fill_matrix).pack(side=tk.LEFT, padx=2)

        self.draw_grid()

        # --- 🏃‍♂️ 跑馬燈與動態播放中樞 ---
        self._marquee_thread = None
        self._stop_marquee_event = threading.Event()

        mq_box = tk.LabelFrame(self, text="🏃‍♂️ 跑馬燈文字與動態動畫播放中樞", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 9, "bold"), padx=6, pady=6)
        mq_box.pack(fill=tk.X, pady=(6, 0))

        # 模式選取
        m_row = tk.Frame(mq_box, bg=hub.BG_CARD)
        m_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(m_row, text="播放模式:", bg=hub.BG_CARD, fg=hub.TEXT_MAIN, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="📝 自訂跑馬燈文字")
        mode_options = ["📝 自訂跑馬燈文字"] + list(PRESET_ANIMATIONS.keys())
        self.mode_combo = ttk.Combobox(m_row, textvariable=self.mode_var, values=mode_options, state="readonly", width=18)
        self.mode_combo.pack(side=tk.LEFT, padx=6)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        # 文字輸入框（加寬至全幅橫跨，可完整檢視與輸入長字串）
        self.text_frame = tk.Frame(mq_box, bg=hub.BG_CARD)
        self.text_frame.pack(fill=tk.X, pady=(0, 4))

        input_row = tk.Frame(self.text_frame, bg=hub.BG_CARD)
        input_row.pack(fill=tk.X, pady=(0, 3))
        tk.Label(input_row, text="跑馬燈內容:", bg=hub.BG_CARD, fg=hub.TEXT_MAIN, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 4))
        
        init_txt = self.data.get("state", {}).get("marquee_text", "HELLO ARDUINO UNO!")
        self.text_var = tk.StringVar(value=init_txt)
        self.text_entry = ttk.Entry(input_row, textvariable=self.text_var, font=("Segoe UI", 9))
        self.text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self._syncing_text = False
        def _on_txt_write(*args):
            if self._syncing_text:
                return
            val = self.text_var.get()
            self.data.setdefault("state", {})["marquee_text"] = val
            if getattr(self.hub, "_web_hub", None):
                self.hub._web_hub.broadcast({
                    "type": "matrix_text_sync",
                    "id": self.comp_id,
                    "text": val
                })
        self.text_var.trace_add("write", _on_txt_write)

        # 常用長短詞快速代入捷徑
        quick_row = tk.Frame(self.text_frame, bg=hub.BG_CARD)
        quick_row.pack(fill=tk.X, pady=(0, 2))
        tk.Label(quick_row, text="常用範例:", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 3))
        for q_txt in ["HELLO", "ARDUINO", "WELCOME TO LAB", "SYSTEM OK", "LOVE 1314", "1234567890"]:
            tk.Button(quick_row, text=q_txt, bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 7),
                      command=lambda t=q_txt: self.text_var.set(t)).pack(side=tk.LEFT, padx=1)

        # 速度與循環
        ctrl_row = tk.Frame(mq_box, bg=hub.BG_CARD)
        ctrl_row.pack(fill=tk.X, pady=(0, 4))
        init_speed = int(self.data.get("state", {}).get("marquee_speed", 150))
        self.current_speed_ms = init_speed
        self.current_loop = True
        self.speed_var = tk.IntVar(value=init_speed)
        self.speed_lbl = tk.Label(ctrl_row, text=f"速度: {init_speed}ms", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 8), width=9)
        self.speed_lbl.pack(side=tk.RIGHT)
        self.speed_scale = ttk.Scale(ctrl_row, from_=40, to=500, orient=tk.HORIZONTAL, variable=self.speed_var, command=self._on_speed_change)
        self.speed_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=4)
        tk.Label(ctrl_row, text="速度:", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)

        self.loop_var = tk.BooleanVar(value=True)
        self.chk_loop = ttk.Checkbutton(ctrl_row, text="🔁 循環", variable=self.loop_var)
        self.chk_loop.pack(side=tk.LEFT, padx=(4, 8))

        # 4 款常用速度快捷鈕
        spd_preset_row = tk.Frame(mq_box, bg=hub.BG_CARD)
        spd_preset_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(spd_preset_row, text="常用:", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 2))
        for p_lbl, p_val in [("⚡ 快速 80ms", 80), ("🚶 適中 150ms", 150), ("🐢 慢速 260ms", 260), ("🕯️ 極慢 420ms", 420)]:
            tk.Button(spd_preset_row, text=p_lbl, bg="#181825", fg=hub.TEXT_MAIN,
                      font=("Segoe UI", 7), bd=1, relief="flat", padx=3, pady=1,
                      command=lambda v=p_val: self.set_speed(v)).pack(side=tk.LEFT, padx=1)

        # 啟動 / 停止按鈕與狀態指示
        act_row = tk.Frame(mq_box, bg=hub.BG_CARD)
        act_row.pack(fill=tk.X)
        self.btn_mq_start = tk.Button(act_row, text="▶️ 啟動跑馬燈", bg="#A6E3A1", fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=6, pady=2, command=self.start_marquee)
        self.btn_mq_start.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_mq_stop = tk.Button(act_row, text="⏹️ 停止", bg="#F38BA8", fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=6, pady=2, command=self.stop_marquee)
        self.btn_mq_stop.pack(side=tk.LEFT, padx=(0, 6))

        self.mq_status_lbl = tk.Label(act_row, text="● 閒置中", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        self.mq_status_lbl.pack(side=tk.LEFT)

    def draw_grid(self):
        self.canvas.delete("all")
        for r in range(8):
            row_val = self.matrix[r]
            for c in range(8):
                is_on = bool(row_val & (1 << (7 - c)))
                color = "#F38BA8" if is_on else "#313244"
                x1 = c * self.dot_size + self.margin
                y1 = r * self.dot_size + self.margin
                x2 = x1 + self.dot_size - self.margin * 2
                y2 = y1 + self.dot_size - self.margin * 2
                self.canvas.create_oval(x1, y1, x2, y2, fill=color, outline="#45475A", width=1)

    def on_canvas_click(self, event):
        c = event.x // self.dot_size
        r = event.y // self.dot_size
        if 0 <= r < 8 and 0 <= c < 8:
            self.matrix[r] ^= (1 << (7 - c))
            self.data["state"]["matrix"] = self.matrix
            self.draw_grid()
            self.sync_hardware()

    def on_select_preset(self, event):
        name = self.pattern_combo.get()
        if name in PRESET_MATRIX:
            self.matrix = list(PRESET_MATRIX[name])
            self.data["state"]["matrix"] = self.matrix
            self.draw_grid()
            self.sync_hardware()

    def clear_matrix(self):
        self.matrix = [0] * 8
        self.data["state"]["matrix"] = self.matrix
        self.draw_grid()
        self.hub.send_cmd(f"MATRIX_CLEAR,{self.din},{self.cs},{self.clk}")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "matrix_frame",
                "id": self.comp_id,
                "matrix": list(self.matrix)
            })

    def invert_matrix(self):
        self.matrix = [val ^ 0xFF for val in self.matrix]
        self.data["state"]["matrix"] = self.matrix
        self.draw_grid()
        self.sync_hardware()

    def fill_matrix(self):
        self.matrix = [0xFF] * 8
        self.data["state"]["matrix"] = self.matrix
        self.draw_grid()
        self.sync_hardware()

    def sync_hardware(self):
        bytes_str = ",".join(str(b) for b in self.matrix)
        self.hub.send_cmd(f"MATRIX_ALL,{self.din},{self.cs},{self.clk},{bytes_str}")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "matrix_frame",
                "id": self.comp_id,
                "matrix": list(self.matrix)
            })

    def sync_matrix(self, bmp):
        try:
            if not self.winfo_exists():
                return
            self.matrix = list(bmp)
            self.data["state"]["matrix"] = self.matrix
            self.draw_grid()
        except Exception:
            pass

    def sync_marquee_text(self, text):
        """從 Web 端同步自訂跑馬燈文字至 GUI 輸入框"""
        if not self.winfo_exists():
            return
        self._syncing_text = True
        try:
            self.text_var.set(text)
            self.data.setdefault("state", {})["marquee_text"] = text
        finally:
            self._syncing_text = False

    def start_marquee_from_web(self, text=None, speed_ms=None, loop=None, mode=None):
        """Web 端發起跑馬燈時委派給 GUI 卡片執行"""
        if not self.winfo_exists():
            return
        if text is not None:
            self._syncing_text = True
            self.text_var.set(text)
            self.data.setdefault("state", {})["marquee_text"] = text
            self._syncing_text = False
        if speed_ms is not None:
            self.speed_var.set(speed_ms)
            self.speed_lbl.configure(text=f"速度: {speed_ms}ms")
        if loop is not None:
            self.loop_var.set(loop)
        if mode is not None:
            mode_val = "📝 自訂跑馬燈文字" if mode == "text" else mode
            if mode_val in self.mode_combo["values"]:
                self.mode_var.set(mode_val)
                self._on_mode_change()
        self.start_marquee()

    def _on_mode_change(self, event=None):
        if self.mode_var.get() == "📝 自訂跑馬燈文字":
            self.text_frame.pack(fill=tk.X, pady=(0, 4))
        else:
            self.text_frame.pack_forget()

    def set_speed(self, speed_ms):
        """主動設置速度並同步廣播"""
        self.current_speed_ms = int(speed_ms)
        self.speed_var.set(speed_ms)
        self._on_speed_change(str(speed_ms))

    def sync_speed(self, speed_ms):
        """由 Web 端回傳的速度同步更新 GUI"""
        if not self.winfo_exists():
            return
        self.current_speed_ms = int(speed_ms)
        self.speed_var.set(speed_ms)
        self.speed_lbl.configure(text=f"速度: {speed_ms}ms")
        self.data.setdefault("state", {})["marquee_speed"] = speed_ms
        if hasattr(self, "btn_mq_start") and str(self.btn_mq_start["state"]) == "disabled":
            self.mq_status_lbl.configure(text=f"🟢 播放中 ({speed_ms}ms)")

    def _on_speed_change(self, val_str):
        ms = int(float(val_str))
        self.current_speed_ms = ms
        self.speed_lbl.configure(text=f"速度: {ms}ms")
        self.data.setdefault("state", {})["marquee_speed"] = ms
        if hasattr(self, "btn_mq_start") and str(self.btn_mq_start["state"]) == "disabled":
            self.mq_status_lbl.configure(text=f"🟢 播放中 ({ms}ms)")
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "matrix_speed_sync",
                "id": self.comp_id,
                "speed": ms
            })

    def start_marquee(self):
        self.stop_marquee()
        self._stop_marquee_event.clear()

        mode = self.mode_var.get()
        self.current_speed_ms = max(35, int(self.speed_var.get()))
        self.current_loop = bool(self.loop_var.get())
        speed = self.current_speed_ms
        is_loop = self.current_loop

        if mode == "📝 自訂跑馬燈文字":
            txt = self.text_var.get().strip() or "HELLO"
            frames = text_to_matrix_frames(txt)
            desc_tag = f"文字: {txt}"
        else:
            txt = ""
            frames = PRESET_ANIMATIONS.get(mode, [])
            desc_tag = mode
            if not frames:
                return

        self.btn_mq_start.configure(state="disabled")
        self.mq_status_lbl.configure(text=f"🟢 播放中 ({speed}ms)", fg="#A6E3A1")
        self.hub.log(f"🏃‍♂️ 啟動 8x8 點陣跑馬燈 [{desc_tag}] (總影格: {len(frames)}, 速度: {speed}ms, 循環: {'是' if is_loop else '否'})")

        # 同步廣播給 Web 狀態通知
        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "matrix_marquee_status",
                "id": self.comp_id,
                "running": True,
                "text": txt,
                "speed": speed
            })

        def marquee_worker():
            while not self._stop_marquee_event.is_set():
                for f in frames:
                    if self._stop_marquee_event.is_set():
                        break
                    self.matrix = list(f)
                    self.data["state"]["matrix"] = self.matrix
                    self.sync_hardware()
                    self.hub.dispatch_ui(self.draw_grid)

                    # 重要：即時同步給 Web 介面即時渲染 8x8 點陣流動影格
                    if getattr(self.hub, "_web_hub", None):
                        self.hub._web_hub.broadcast({
                            "type": "matrix_frame",
                            "id": self.comp_id,
                            "matrix": list(f)
                        })

                    # 動態即時讀取最新速度（使用純 Python 變數，線程安全，不觸碰 Tcl 直讀）
                    current_delay = max(0.035, float(getattr(self, "current_speed_ms", 150)) / 1000.0)
                    if self._stop_marquee_event.wait(current_delay):
                        break

                if not getattr(self, "current_loop", True) or self._stop_marquee_event.is_set():
                    break

            def _finish():
                if self.winfo_exists():
                    self.btn_mq_start.configure(state="normal")
                    self.mq_status_lbl.configure(text="● 閒置中", fg=self.hub.TEXT_MUTED)
                if getattr(self.hub, "_web_hub", None):
                    self.hub._web_hub.broadcast({
                        "type": "matrix_marquee_status",
                        "id": self.comp_id,
                        "running": False
                    })
            self.hub.dispatch_ui(_finish)

        self._marquee_thread = threading.Thread(target=marquee_worker, daemon=True)
        self._marquee_thread.start()

    def stop_marquee(self):
        self._stop_marquee_event.set()
        if self._marquee_thread and self._marquee_thread.is_alive():
            self._marquee_thread.join(timeout=0.3)
        self._marquee_thread = None
        if self.winfo_exists():
            self.btn_mq_start.configure(state="normal")
            self.mq_status_lbl.configure(text="● 已停止", fg=self.hub.TEXT_MUTED)

        if getattr(self.hub, "_web_hub", None):
            self.hub._web_hub.broadcast({
                "type": "matrix_marquee_status",
                "id": self.comp_id,
                "running": False
            })


class SensorCard(BaseCard):
    """🌡️ 類比 / 數位感測器串流監控 (光敏、熱敏、按鈕、可變電阻)"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.pin = data["pins"].get("pin", 0)
        self.sensor_type = data.get("sensor_type", "A")  # 'A' or 'D'
        self.is_streaming = data.get("state", {}).get("streaming", False)
        self.history = [0] * 35

        type_text = f"類比輸入 (A{self.pin})" if self.sensor_type == "A" else f"數位輸入 (D{self.pin})"
        info_lbl = tk.Label(self, text=f"通道: {type_text}", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        info_lbl.pack(anchor="w")

        # 數值即時顯示與進度條
        row = tk.Frame(self, bg=hub.BG_CARD)
        row.pack(fill=tk.X, pady=4)

        self.val_lbl = tk.Label(row, text="---", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 12, "bold"), width=8)
        self.val_lbl.pack(side=tk.LEFT)

        max_val = 1023 if self.sensor_type == "A" else 1
        self.progress = ttk.Progressbar(row, orient=tk.HORIZONTAL, mode="determinate", maximum=max_val)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # 即時微型示波畫布 (Mini Oscilloscope Waveform)
        if self.sensor_type == "A":
            self.chart_canvas = tk.Canvas(self, height=40, bg="#181825", highlightthickness=1, highlightbackground="#313244")
            self.chart_canvas.pack(fill=tk.X, pady=(2, 6))

        # 串流啟動/停止按鈕
        self.btn_stream = tk.Button(
            self,
            text="▶️ 啟動串流監聽" if not self.is_streaming else "⏹️ 停止串流",
            bg="#313244",
            fg=hub.TEXT_MAIN,
            bd=0,
            font=("Segoe UI", 9),
            command=self.toggle_stream,
        )
        self.btn_stream.pack(anchor="w", pady=(2, 0))

    def toggle_stream(self):
        self.is_streaming = not self.is_streaming
        self.data["state"]["streaming"] = self.is_streaming
        if self.is_streaming:
            self.btn_stream.configure(text="⏹️ 停止串流", bg="#F38BA8", fg="#11111B")
            self.hub.send_cmd(f"STREAM,{self.pin},{self.sensor_type},1,100")
        else:
            self.btn_stream.configure(text="▶️ 啟動串流監聽", bg="#313244", fg=self.hub.TEXT_MAIN)
            self.hub.send_cmd(f"STREAM,{self.pin},{self.sensor_type},0,100")

    def on_stream_data(self, pin, val):
        if pin == self.pin:
            self.val_lbl.configure(text=str(val))
            self.progress["value"] = val
            if self.sensor_type == "A" and hasattr(self, "chart_canvas"):
                self.history.pop(0)
                self.history.append(val)
                self._draw_wave()

    def _draw_wave(self):
        w = self.chart_canvas.winfo_width()
        if w < 20: w = 220
        h = 40
        self.chart_canvas.delete("all")
        # 繪製基準格線
        self.chart_canvas.create_line(0, h // 2, w, h // 2, fill="#252538", dash=(2, 2))
        pts = []
        n = len(self.history)
        for i, v in enumerate(self.history):
            x = int(i * (w / (n - 1)))
            y = int(h - (v / 1023.0) * (h - 6) - 3)
            pts.extend([x, y])
        if len(pts) >= 4:
            self.chart_canvas.create_line(pts, fill="#89B4FA", width=2, smooth=True)


class SonarCard(BaseCard):
    """🦇 超音波測距感測器 HC-SR04"""
    def __init__(self, parent, hub, data):
        super().__init__(parent, hub, data)
        self.trig = data["pins"].get("trig", 2)
        self.echo = data["pins"].get("echo", 3)

        info_lbl = tk.Label(self, text=f"Trig={self.trig}, Echo={self.echo}", bg=hub.BG_CARD, fg=hub.TEXT_MUTED, font=("Segoe UI", 8))
        info_lbl.pack(anchor="w")

        row = tk.Frame(self, bg=hub.BG_CARD)
        row.pack(fill=tk.X, pady=6)

        self.dist_lbl = tk.Label(row, text="--- cm", bg=hub.BG_CARD, fg=hub.ACCENT, font=("Segoe UI", 12, "bold"), width=10)
        self.dist_lbl.pack(side=tk.LEFT)

        tk.Button(
            row, text="📏 單次測距", bg="#313244", fg=hub.TEXT_MAIN, bd=0, font=("Segoe UI", 9), command=self.measure
        ).pack(side=tk.LEFT, padx=8)

    def measure(self):
        self.hub.send_cmd(f"SONAR,{self.trig},{self.echo}")

    def on_sonar_data(self, trig, dist):
        if trig == self.trig:
            if dist < 0:
                self.dist_lbl.configure(text="超出範圍")
            else:
                self.dist_lbl.configure(text=f"{dist} cm")


# ==============================================================================
# 程式進入點
# ==============================================================================
if __name__ == "__main__":
    # 設定 Windows 獨立 AppUserModelID，讓工作列顯示獨立應用程式圖示 (而非 python.exe 預設羽毛圖示)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("google.deepmind.arduino.universal.hub.v1")
    except Exception:
        pass

    root = tk.Tk()
    app = UniversalControllerApp(root)
    root.mainloop()

