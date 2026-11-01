# -*- coding: utf-8 -*-
"""
⚡ Arduino Universal Hub - 全無線 Wi-Fi 控制中樞 (Desktop GUI)
================================================================
專為 Arduino Uno + Webduino Fly (ESP8266 擴充板) 或 Wi-Fi 模組打造的獨立無線控制應用

特色亮點：
1. 完全擺脫 USB 傳輸線，透過 Wi-Fi (IP/HTTP REST) 毫秒級無線雙向控制
2. 內建區域網路 (LAN) 快速掃描器，一鍵自動搜尋區網內的 Arduino Wi-Fi 設備
3. 整合雙 RGB LED 18 款炫彩即時特效 (Wi-Fi 串流)
4. 整合 MAX7219 8x8 點陣 (互動繪圖、文字跑馬燈、動態動畫)
5. 整合伺服舵機 (Servo)、PWM 調光調速、數位開關、全域急停
6. 內建「一鍵燒錄 Wi-Fi 韌體」輔助工具 (直接燒錄 wifi_firmware.ino)
"""

import os
import sys
import time
import json
import socket
import urllib.request
import urllib.parse
import threading
import queue
import subprocess

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox, ttk, colorchooser
from tkinter.scrolledtext import ScrolledText

from universal_shared import (
    WORKSPACE_DIR,
    ARDUINO_CLI_PATH,
    PRESET_MATRIX,
    FONT_5X7,
    text_to_matrix_frames,
    PRESET_ANIMATIONS
)

WIFI_FIRMWARE_DIR = os.path.join(WORKSPACE_DIR, "wifi_firmware")
WIFI_FIRMWARE_INO = os.path.join(WIFI_FIRMWARE_DIR, "wifi_firmware.ino")


class WiFiArduinoClient:
    """Wi-Fi HTTP 通訊客戶端核心"""
    def __init__(self, ip: str = "192.168.1.100", port: int = 80):
        self.ip = ip.strip()
        self.port = port
        self.is_connected = False
        self.latency_ms = 0
        self.cmd_queue = queue.Queue(maxsize=100)
        self.worker_thread = None
        self.running = False
        self.on_log = None

    def log(self, msg: str):
        if self.on_log:
            self.on_log(msg)
        else:
            print(f"[WiFiClient] {msg}")

    def ping(self) -> bool:
        try:
            start = time.time()
            url = f"http://{self.ip}:{self.port}/status"
            req = urllib.request.Request(url, headers={"User-Agent": "WiFiArduinoHub/1.0"})
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status == 200:
                    self.latency_ms = int((time.time() - start) * 1000)
                    self.is_connected = True
                    return True
        except Exception:
            pass
        self.is_connected = False
        return False

    def send_cmd_sync(self, cmd: str, timeout: float = 0.8) -> dict:
        """同步發送指令至 Arduino Wi-Fi 伺服器"""
        try:
            encoded_cmd = urllib.parse.quote(cmd)
            url = f"http://{self.ip}:{self.port}/cmd?c={encoded_cmd}"
            req = urllib.request.Request(url, headers={"User-Agent": "WiFiArduinoHub/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = resp.read().decode("utf-8")
                    return json.loads(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "timeout"}

    def send_cmd(self, cmd: str):
        """異步發送指令（放入佇列，不阻塞 UI）"""
        try:
            # 若佇列已滿，丟棄舊的頻繁連續指令 (如 PWM/RGB 滑桿) 以免積壓
            if self.cmd_queue.full():
                try:
                    self.cmd_queue.get_nowait()
                except queue.Empty:
                    pass
            self.cmd_queue.put(cmd)
        except Exception:
            pass

    def start_worker(self):
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def stop_worker(self):
        self.running = False

    def _worker_loop(self):
        while self.running:
            try:
                cmd = self.cmd_queue.get(timeout=0.1)
                self.send_cmd_sync(cmd)
                self.cmd_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass


class WiFiControllerApp:
    # 現代深色系主題配色
    BG_MAIN = "#1E1E2E"
    BG_TOP = "#181825"
    BG_CARD = "#313244"
    TEXT_MAIN = "#CDD6F4"
    TEXT_MUTED = "#A6ADC8"
    ACCENT = "#89B4FA"
    ACCENT_GREEN = "#A6E3A1"
    ACCENT_RED = "#F38BA8"
    ACCENT_YELLOW = "#F9E2AF"
    BORDER_COLOR = "#45475A"

    def __init__(self, root):
        self.root = root
        self.root.title("⚡ Arduino Universal Hub - 全無線 Wi-Fi 控制中樞")
        self.root.geometry("1060x860")
        self.root.minsize(980, 750)
        self.root.configure(bg=self.BG_MAIN)

        self.client = WiFiArduinoClient()
        self.client.on_log = self.log

        # 雙燈即時特效執行緒控制
        self.effect_thread = None
        self.effect_stop_event = threading.Event()
        self.current_effect_name = None

        # MAX7219 點陣畫布狀態 (8 bytes)
        self.matrix_state = [0] * 8
        self.matrix_btns = []

        self._build_ui()
        self.client.start_worker()

        # 背景定時延遲更新
        self._start_ping_timer()

    def _build_ui(self):
        # 1. 頂部導航與 Wi-Fi 連線控制欄
        top_frame = tk.Frame(self.root, bg=self.BG_TOP, padx=14, pady=10, relief=tk.FLAT)
        top_frame.pack(fill=tk.X)

        title_lbl = tk.Label(top_frame, text="⚡ Arduino Wi-Fi 控制中樞", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 12, "bold"))
        title_lbl.pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(top_frame, text="🌐 設備 IP:", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(top_frame, bg="#11111B", fg=self.TEXT_MAIN, insertbackground=self.TEXT_MAIN, relief=tk.FLAT, font=("Consolas", 10), width=15)
        self.ip_entry.insert(0, "192.168.1.100")
        self.ip_entry.pack(side=tk.LEFT, padx=6)

        self.btn_connect = tk.Button(top_frame, text="📶 連線 Wi-Fi", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2", command=self.toggle_connection)
        self.btn_connect.pack(side=tk.LEFT, padx=4)

        btn_scan = tk.Button(top_frame, text="🔍 自動搜尋區網", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=0, padx=8, pady=3, cursor="hand2", command=self.scan_lan_devices)
        btn_scan.pack(side=tk.LEFT, padx=4)

        btn_flash = tk.Button(top_frame, text="🛠️ 一鍵燒錄 Wi-Fi 韌體", bg="#F5C2E7", fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2", command=self.open_flash_dialog)
        btn_flash.pack(side=tk.LEFT, padx=4)

        self.lbl_status = tk.Label(top_frame, text="● 未連線", bg=self.BG_TOP, fg=self.ACCENT_RED, font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=12)

        btn_stop = tk.Button(top_frame, text="🛑 全體急停", bg=self.ACCENT_RED, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=12, pady=3, cursor="hand2", command=self.emergency_stop)
        btn_stop.pack(side=tk.RIGHT, padx=4)

        # 2. 主卡片儀表板滾動區域
        main_canvas = tk.Canvas(self.root, bg=self.BG_MAIN, highlightthickness=0)
        v_scroll = tk.Scrollbar(self.root, orient=tk.VERTICAL, command=main_canvas.yview)
        main_canvas.configure(yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.cards_frame = tk.Frame(main_canvas, bg=self.BG_MAIN, padx=16, pady=14)
        main_canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))

        # 渲染配件控制卡片
        self._build_switch_servo_card()
        self._build_rgb_card()
        self._build_matrix_card()
        self._build_log_console()

    def _build_switch_servo_card(self):
        row = tk.Frame(self.cards_frame, bg=self.BG_MAIN)
        row.pack(fill=tk.X, pady=(0, 12))

        # 開關卡片
        f_sw = tk.LabelFrame(row, text="💡 數位開關 (Pin 13 LED / 繼電器)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f_sw.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        self.sw_state = False
        self.btn_sw = tk.Button(f_sw, text="⚪ 目前：關閉 (點擊開啟)", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 10, "bold"), bd=0, pady=8, cursor="hand2", command=self.toggle_switch)
        self.btn_sw.pack(fill=tk.X, pady=4)

        # PWM 滑桿卡片
        f_pwm = tk.LabelFrame(row, text="⚡ PWM 功率/馬達 (Pin 9)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f_pwm.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        self.pwm_val = tk.IntVar(value=0)
        self.pwm_lbl = tk.Label(f_pwm, text="0 (0%)", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Consolas", 10))
        self.pwm_lbl.pack(anchor="e")
        scale_pwm = tk.Scale(f_pwm, from_=0, to=255, orient=tk.HORIZONTAL, variable=self.pwm_val, bg=self.BG_CARD, fg=self.TEXT_MAIN, highlightthickness=0, bd=0, command=self._on_pwm_change)
        scale_pwm.pack(fill=tk.X)

        # 伺服舵機卡片
        f_srv = tk.LabelFrame(row, text="🎯 伺服舵機 (Pin 10 / 0°~180°)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f_srv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.srv_val = tk.IntVar(value=90)
        self.srv_lbl = tk.Label(f_srv, text="90° (中間歸位)", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Consolas", 10))
        self.srv_lbl.pack(anchor="e")
        scale_srv = tk.Scale(f_srv, from_=0, to=180, orient=tk.HORIZONTAL, variable=self.srv_val, bg=self.BG_CARD, fg=self.TEXT_MAIN, highlightthickness=0, bd=0, command=self._on_servo_change)
        scale_srv.pack(fill=tk.X)

    def _build_rgb_card(self):
        f = tk.LabelFrame(self.cards_frame, text="🌈 雙 RGB LED 模組與 18 款炫彩即時特效", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f.pack(fill=tk.X, pady=(0, 12))

        top_r = tk.Frame(f, bg=self.BG_CARD)
        top_r.pack(fill=tk.X, pady=(0, 8))

        # 色塊預覽
        self.rgb_preview = tk.Canvas(top_r, width=50, height=50, bg="#000000", highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        self.rgb_preview.pack(side=tk.LEFT, padx=(0, 12))

        btn_color = tk.Button(top_r, text="🎨 選擇色彩", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 9), bd=0, padx=10, pady=4, cursor="hand2", command=self.pick_color)
        btn_color.pack(side=tk.LEFT, padx=4)

        self.anode_var = tk.BooleanVar(value=True)
        chk_anode = tk.Checkbutton(top_r, text="共陽 (Common Anode)", variable=self.anode_var, bg=self.BG_CARD, fg=self.TEXT_MUTED, selectcolor="#11111B", activebackground=self.BG_CARD, font=("Segoe UI", 8))
        chk_anode.pack(side=tk.LEFT, padx=10)

        btn_stop_fx = tk.Button(top_r, text="⏹️ 停止特效", bg=self.ACCENT_RED, fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2", command=self.stop_dual_effect)
        btn_stop_fx.pack(side=tk.RIGHT)

        # 18 款炫彩特效按鈕網格
        fx_grid = tk.Frame(f, bg=self.BG_CARD)
        fx_grid.pack(fill=tk.X)

        effects = [
            ("sync_rainbow", "🌈 同步彩虹"),
            ("alt_breathing", "🫁 交替呼吸"),
            ("police_strobe", "🚨 警車爆閃"),
            ("fire_flame", "🔥 熾烈焰火"),
            ("cyberpunk", "🏙️ 賽博朋克"),
            ("ocean_wave", "🌊 碧海浪濤"),
            ("matrix_code", "💻 數位雨痕"),
            ("aurora_borealis", "🌌 極光漫舞"),
            ("sunset_glow", "🌅 日落餘暉"),
            ("color_wipe", "🔄 跑馬追逐"),
            ("starry_night", "✨ 繁星閃爍"),
            ("energy_pulse", "⚡ 能量脈衝"),
            ("candy_pop", "🍬 糖果撞色"),
            ("glitch_spark", "⚡ 霓虹故障"),
            ("heartbeat_duo", "💓 雙生心跳"),
            ("fairy_glow", "🧚 仙子微光"),
            ("traffic_signal", "🚦 交通信號"),
            ("meteor_shower", "🌠 彗星流雨"),
        ]

        for i, (fid, name) in enumerate(effects):
            r = i // 6
            c = i % 6
            btn = tk.Button(fx_grid, text=name, bg="#181825", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=1, relief=tk.SOLID, padx=6, pady=4, cursor="hand2", command=lambda fx=fid: self.start_dual_effect(fx))
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            fx_grid.grid_columnconfigure(c, weight=1)

    def _build_matrix_card(self):
        f = tk.LabelFrame(self.cards_frame, text="🔲 MAX7219 8x8 點陣顯示器 (繪圖、跑馬燈、動態動畫)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f.pack(fill=tk.X, pady=(0, 12))

        body = tk.Frame(f, bg=self.BG_CARD)
        body.pack(fill=tk.X)

        # 8x8 互動像素點繪製面板
        grid_frame = tk.Frame(body, bg="#11111B", padx=6, pady=6, bd=1, relief=tk.SOLID)
        grid_frame.pack(side=tk.LEFT, padx=(0, 16))

        self.matrix_btns = []
        for r in range(8):
            row_btns = []
            for c in range(8):
                b = tk.Canvas(grid_frame, width=14, height=14, bg="#313244", highlightthickness=0, cursor="hand2")
                b.grid(row=r, column=c, padx=2, pady=2)
                b.bind("<Button-1>", lambda e, row=r, col=c: self._toggle_matrix_dot(row, col))
                row_btns.append(b)
            self.matrix_btns.append(row_btns)

        # 右側控制區
        ctrl_frame = tk.Frame(body, bg=self.BG_CARD)
        ctrl_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 經典預設圖形
        pre_row = tk.Frame(ctrl_frame, bg=self.BG_CARD)
        pre_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(pre_row, text="經典圖形:", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 4))
        for name, bmp in list(PRESET_MATRIX.items())[:5]:
            tk.Button(pre_row, text=name.split()[0], bg="#181825", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=0, padx=6, pady=2, cursor="hand2", command=lambda b=bmp: self._apply_matrix_preset(b)).pack(side=tk.LEFT, padx=2)

        btn_clear = tk.Button(pre_row, text="🧹 清空", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=0, padx=8, pady=2, cursor="hand2", command=self.clear_matrix)
        btn_clear.pack(side=tk.LEFT, padx=6)

        # 跑馬燈
        mq_row = tk.Frame(ctrl_frame, bg=self.BG_CARD)
        mq_row.pack(fill=tk.X, pady=(4, 6))
        tk.Label(mq_row, text="跑馬燈文字:", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.mq_entry = tk.Entry(mq_row, bg="#11111B", fg=self.TEXT_MAIN, relief=tk.FLAT, font=("Consolas", 9), width=12)
        self.mq_entry.insert(0, "HELLO")
        self.mq_entry.pack(side=tk.LEFT, padx=6)
        btn_mq = tk.Button(mq_row, text="▶️ 無線發送文字", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=2, cursor="hand2", command=self.play_marquee)
        btn_mq.pack(side=tk.LEFT, padx=2)

        # 動態動畫
        anim_row = tk.Frame(ctrl_frame, bg=self.BG_CARD)
        anim_row.pack(fill=tk.X)
        tk.Label(anim_row, text="動態動畫:", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 4))
        for anim_name in ["💓 心跳搏動動畫", "🚀 火箭升空動畫", "🌊 像素海浪動畫", "ᗧ 吃豆人動態"]:
            short_name = anim_name.split()[0]
            tk.Button(anim_row, text=short_name, bg="#181825", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=0, padx=6, pady=2, cursor="hand2", command=lambda a=anim_name: self.play_animation(a)).pack(side=tk.LEFT, padx=2)

    def _build_log_console(self):
        f = tk.LabelFrame(self.cards_frame, text="📋 Wi-Fi 通訊日誌", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8), bd=1, relief=tk.SOLID, padx=8, pady=6)
        f.pack(fill=tk.BOTH, expand=True)

        self.log_text = ScrolledText(f, height=6, bg="#11111B", fg="#A6ADC8", font=("Consolas", 8), bd=0, insertbackground="#A6ADC8")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, msg: str):
        t = time.strftime("%H:%M:%S")
        line = f"[{t}] {msg}\n"
        def _append():
            if hasattr(self, "log_text"):
                self.log_text.insert(tk.END, line)
                self.log_text.see(tk.END)
        self.root.after(0, _append)

    # ==========================
    # 連線與通訊邏輯
    # ==========================
    def toggle_connection(self):
        if self.client.is_connected:
            self.client.is_connected = False
            self.lbl_status.configure(text="● 未連線", fg=self.ACCENT_RED)
            self.btn_connect.configure(text="📶 連線 Wi-Fi", bg=self.ACCENT)
            self.log("已中斷 Wi-Fi 連線")
        else:
            ip = self.ip_entry.get().strip()
            if not ip:
                messagebox.showwarning("提示", "請輸入有效的設備 IP 地址！")
                return
            self.client.ip = ip
            self.lbl_status.configure(text="● 連線中...", fg=self.ACCENT_YELLOW)
            self.log(f"正在嘗試連線至 Arduino Wi-Fi ({ip})...")

            def worker():
                ok = self.client.ping()
                if ok:
                    self.root.after(0, lambda: self._on_connected(ip))
                else:
                    self.root.after(0, self._on_connect_fail)

            threading.Thread(target=worker, daemon=True).start()

    def _on_connected(self, ip: str):
        self.lbl_status.configure(text=f"● Wi-Fi 已連線 ({ip}, {self.client.latency_ms}ms)", fg=self.ACCENT_GREEN)
        self.btn_connect.configure(text="❌ 中斷連線", bg="#45475A")
        self.log(f"🎉 成功連線至 Arduino Wi-Fi！(延遲: {self.client.latency_ms}ms)")

    def _on_connect_fail(self):
        self.lbl_status.configure(text="● 連線失敗", fg=self.ACCENT_RED)
        self.log("❌ 連線超時，請確認：\n1. Arduino 與此電腦是否連在同一個 Wi-Fi 下？\n2. 設備 IP 地址是否正確？\n3. Webduino Fly 板上紅燈是否熄滅（已連網）？")
        messagebox.showerror("連線超時", "無法連線至指定的 Arduino Wi-Fi 設備！\n\n請確認設備 IP 正確，且已開啟電源與連線路由器。")

    def _start_ping_timer(self):
        def _poll():
            if self.client.is_connected:
                def worker():
                    if self.client.ping():
                        self.root.after(0, lambda: self.lbl_status.configure(text=f"● Wi-Fi 已連線 ({self.client.ip}, {self.client.latency_ms}ms)", fg=self.ACCENT_GREEN))
                threading.Thread(target=worker, daemon=True).start()
            self.root.after(4000, _poll)
        self.root.after(4000, _poll)

    def scan_lan_devices(self):
        """自動多執行緒掃描區域網路內開放 Port 80 的 Arduino Wi-Fi 設備"""
        self.log("🔍 正在快速掃描區域網路內的 Arduino Wi-Fi 設備...")
        
        def worker():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                my_ip = s.getsockname()[0]
            except Exception:
                my_ip = "192.168.1.1"
            finally:
                s.close()

            subnet = ".".join(my_ip.split(".")[:3])
            found_ips = []

            def probe(ip):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.35)
                    res = sock.connect_ex((ip, 80))
                    sock.close()
                    if res == 0:
                        # 驗證是否為 Arduino
                        try:
                            url = f"http://{ip}/status"
                            with urllib.request.urlopen(url, timeout=0.6) as r:
                                data = r.read().decode("utf-8")
                                if "Arduino" in data or "Universal" in data:
                                    found_ips.append(ip)
                        except Exception:
                            pass
                except Exception:
                    pass

            threads = []
            for i in range(1, 255):
                target_ip = f"{subnet}.{i}"
                t = threading.Thread(target=probe, args=(target_ip,))
                t.start()
                threads.append(t)

            for t in threads:
                t.join(timeout=1.5)

            def done():
                if found_ips:
                    chosen = found_ips[0]
                    self.ip_entry.delete(0, tk.END)
                    self.ip_entry.insert(0, chosen)
                    self.log(f"🎯 成功掃描到 Arduino 設備: {', '.join(found_ips)} (已填入 {chosen})")
                    self.toggle_connection()
                else:
                    self.log("⚠️ 掃描完成，未在區網內發現回應的 Arduino 設備，請手動確認 IP。")
                    messagebox.showinfo("掃描結果", "未自動偵測到 Arduino Wi-Fi 設備。\n請手動輸入 IP 或確認板子是否已連上 Wi-Fi。")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ==========================
    # 配件控制動作
    # ==========================
    def toggle_switch(self):
        self.sw_state = not self.sw_state
        val = 1 if self.sw_state else 0
        if self.sw_state:
            self.btn_sw.configure(text="🟢 目前：開啟 (點擊關閉)", bg=self.ACCENT_GREEN, fg="#11111B")
        else:
            self.btn_sw.configure(text="⚪ 目前：關閉 (點擊開啟)", bg="#45475A", fg=self.TEXT_MAIN)
        self.client.send_cmd(f"DWRITE,13,{val}")
        self.log(f"💡 [Wi-Fi] 數位開關 (Pin 13): {'開啟' if self.sw_state else '關閉'}")

    def _on_pwm_change(self, val):
        v = int(val)
        pct = int(v / 255.0 * 100)
        self.pwm_lbl.configure(text=f"{v} ({pct}%)")
        self.client.send_cmd(f"PWM,9,{v}")

    def _on_servo_change(self, val):
        ang = int(val)
        self.srv_lbl.configure(text=f"{ang}°")
        self.client.send_cmd(f"SERVO,10,{ang}")

    def pick_color(self):
        self.stop_dual_effect()
        clr = colorchooser.askcolor(title="選取 RGB 色彩")
        if clr and clr[0]:
            r, g, b = int(clr[0][0]), int(clr[0][1]), int(clr[0][2])
            hex_c = f"#{r:02x}{g:02x}{b:02x}"
            self.rgb_preview.configure(bg=hex_c)
            anode = 1 if self.anode_var.get() else 0
            self.client.send_cmd(f"RGB,6,5,3,{anode},{r},{g},{b}")
            self.log(f"🎨 [Wi-Fi] 設定 RGB 色彩: R={r}, G={g}, B={b}")

    def start_dual_effect(self, effect_name: str):
        self.stop_dual_effect()
        self.effect_stop_event.clear()
        self.current_effect_name = effect_name
        self.log(f"✨ [Wi-Fi] 啟動雙燈炫彩特效: {effect_name}")

        def fx_worker():
            step = 0
            anode = 1 if self.anode_var.get() else 0
            while not self.effect_stop_event.is_set():
                if effect_name == "police_strobe":
                    if step % 2 == 0:
                        r1, g1, b1 = 255, 0, 0
                        r2, g2, b2 = 0, 0, 255
                    else:
                        r1, g1, b1 = 0, 0, 255
                        r2, g2, b2 = 255, 0, 0
                    delay_s = 0.08
                elif effect_name == "sync_rainbow":
                    import math
                    rad = (step * 8) * math.pi / 180.0
                    r1 = int((math.sin(rad) + 1.0) * 127.5)
                    g1 = int((math.sin(rad + 2.094) + 1.0) * 127.5)
                    b1 = int((math.sin(rad + 4.188) + 1.0) * 127.5)
                    delay_s = 0.05
                else:
                    # 通用呼吸
                    import math
                    v = int((math.sin(step * 0.1) + 1.0) * 127.5)
                    r1, g1, b1 = v, int(v * 0.6), 255 - v
                    delay_s = 0.06

                self.client.send_cmd(f"RGB,6,5,3,{anode},{r1},{g1},{b1}")
                step += 1
                time.sleep(delay_s)

        self.effect_thread = threading.Thread(target=fx_worker, daemon=True)
        self.effect_thread.start()

    def stop_dual_effect(self):
        if self.effect_thread and self.effect_thread.is_alive():
            self.effect_stop_event.set()
            self.effect_thread.join(timeout=0.3)
            self.effect_thread = None
            anode = 1 if self.anode_var.get() else 0
            self.client.send_cmd(f"RGB,6,5,3,{anode},0,0,0")
            self.log("⏹️ [Wi-Fi] 特效已停止")

    # ==========================
    # MAX7219 點陣控制
    # ==========================
    def _toggle_matrix_dot(self, row: int, col: int):
        self.matrix_state[row] ^= (1 << (7 - col))
        is_on = bool(self.matrix_state[row] & (1 << (7 - col)))
        color = self.ACCENT_RED if is_on else "#313244"
        self.matrix_btns[row][col].configure(bg=color)
        self._sync_matrix_to_hardware()

    def _sync_matrix_to_hardware(self):
        bytes_str = ",".join(str(b) for b in self.matrix_state)
        # 預設點陣 Pin: DIN=12, CS=8, CLK=7
        self.client.send_cmd(f"MATRIX_ALL,12,8,7,{bytes_str}")

    def _apply_matrix_preset(self, bmp):
        self.matrix_state = list(bmp)
        for r in range(8):
            for c in range(8):
                is_on = bool(self.matrix_state[r] & (1 << (7 - c)))
                self.matrix_btns[r][c].configure(bg=self.ACCENT_RED if is_on else "#313244")
        self._sync_matrix_to_hardware()

    def clear_matrix(self):
        self.matrix_state = [0] * 8
        for r in range(8):
            for c in range(8):
                self.matrix_btns[r][c].configure(bg="#313244")
        self.client.send_cmd("MATRIX_CLEAR,12,8,7")
        self.log("🧹 [Wi-Fi] 已清空 8x8 點陣")

    def play_marquee(self):
        txt = self.mq_entry.get().strip() or "HELLO"
        frames = text_to_matrix_frames(txt)
        self.log(f"📜 [Wi-Fi] 正在無線發送跑馬燈文字: 『{txt}』({len(frames)} 幀)")

        def worker():
            for f in frames:
                bytes_str = ",".join(str(b) for b in f)
                self.client.send_cmd(f"MATRIX_ALL,12,8,7,{bytes_str}")
                time.sleep(0.08)
        threading.Thread(target=worker, daemon=True).start()

    def play_animation(self, anim_name):
        frames = PRESET_ANIMATIONS.get(anim_name, [])
        self.log(f"🎬 [Wi-Fi] 播放點陣動畫: {anim_name}")

        def worker():
            for _ in range(3):
                for f in frames:
                    bytes_str = ",".join(str(b) for b in f)
                    self.client.send_cmd(f"MATRIX_ALL,12,8,7,{bytes_str}")
                    time.sleep(0.09)
        threading.Thread(target=worker, daemon=True).start()

    def emergency_stop(self):
        self.stop_dual_effect()
        self.client.send_cmd("STOP")
        self.sw_state = False
        self.btn_sw.configure(text="⚪ 目前：關閉 (點擊開啟)", bg="#45475A", fg=self.TEXT_MAIN)
        self.clear_matrix()
        self.log("🛑 [Wi-Fi] 全體急停指令已發送！所有輸出已歸零！")

    # ==========================
    # 一鍵燒錄 Wi-Fi 韌體對話框
    # ==========================
    def open_flash_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("🛠️ 一鍵燒錄 Wi-Fi 韌體至 Arduino Uno")
        dlg.geometry("540x380")
        dlg.configure(bg=self.BG_TOP)
        dlg.transient(self.root)

        tk.Label(dlg, text="🛠️ 一鍵燒錄 Wi-Fi 韌體至 Arduino Uno", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        tk.Label(dlg, text="在拔除 USB 線改用純 Wi-Fi 控制前，請先將 Wi-Fi 韌體燒錄至 Uno 晶片中：", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 10))

        body = tk.Frame(dlg, bg=self.BG_CARD, padx=14, pady=12, bd=1, relief=tk.SOLID)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        # COM 埠選擇
        row0 = tk.Frame(body, bg=self.BG_CARD)
        row0.pack(fill=tk.X, pady=4)
        tk.Label(row0, text="COM 序列埠:", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        import serial.tools.list_ports
        port_var = tk.StringVar(value=sel_port)
        combo = ttk.Combobox(row0, textvariable=port_var, values=ports, width=12)
        combo.pack(side=tk.LEFT, padx=10)

        # Wi-Fi SSID (支援下拉選單與手動輸入)
        row1 = tk.Frame(body, bg=self.BG_CARD)
        row1.pack(fill=tk.X, pady=4)
        tk.Label(row1, text="Wi-Fi 名稱 (SSID):", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ssid_var = tk.StringVar(value="")
        ssid_combo = ttk.Combobox(row1, textvariable=ssid_var, width=18)
        ssid_combo.pack(side=tk.LEFT, padx=6)

        btn_scan_ap = tk.Button(row1, text="🔄 透過 USB 掃描 Wi-Fi AP", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2")
        btn_scan_ap.pack(side=tk.LEFT, padx=4)

        # Wi-Fi 密碼
        row2 = tk.Frame(body, bg=self.BG_CARD)
        row2.pack(fill=tk.X, pady=4)
        tk.Label(row2, text="Wi-Fi 密碼 (Password):", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        pass_entry = tk.Entry(row2, bg="#11111B", fg=self.TEXT_MAIN, relief=tk.FLAT, font=("Segoe UI", 9), width=20, show="*")
        pass_entry.insert(0, "")
        pass_entry.pack(side=tk.LEFT, padx=10)

        lbl_flash_status = tk.Label(body, text="💡 提示：點擊上方「🔄 掃描 Wi-Fi」即可從硬體讀取周遭無線 AP 清單！", bg=self.BG_CARD, fg=self.ACCENT_YELLOW, font=("Segoe UI", 8), justify="left")
        lbl_flash_status.pack(anchor="w", pady=(8, 0))

        def scan_aps_via_usb():
            port = port_var.get()
            if not port:
                messagebox.showwarning("提示", "請先選擇 COM 序列埠！")
                return
            lbl_flash_status.configure(text=f"🔍 正在透過 {port} 指令掃描周遭 Wi-Fi AP，請稍候 3~5 秒...", fg=self.ACCENT)
            btn_scan_ap.configure(state="disabled", text="掃描中...")

            def scan_worker():
                found_ssids = []
                import serial, re
                for baud in [115200, 57600, 9600]:
                    try:
                        s = serial.Serial(port, baud, timeout=1.0)
                        time.sleep(1.2)
                        s.reset_input_buffer()
                        # 發送 SCAN_WIFI 與 AT+CWLAP 嘗試雙重協議
                        s.write(b"SCAN_WIFI\r\n")
                        s.write(b"AT+CWMODE=1\r\n")
                        s.write(b"AT+CWLAP\r\n")
                        start_t = time.time()
                        while time.time() - start_t < 4.5:
                            line = s.readline().decode("utf-8", errors="replace").strip()
                            if "WIFI_AP:" in line:
                                ssid = line.split("WIFI_AP:")[1].strip()
                                if ssid and ssid not in found_ssids:
                                    found_ssids.append(ssid)
                            elif "+CWLAP:" in line:
                                m = re.search(r'\+CWLAP:\s*\(\d+,\s*"([^"]+)"', line)
                                if m:
                                    ssid = m.group(1).strip()
                                    if ssid and ssid not in found_ssids:
                                        found_ssids.append(ssid)
                        s.close()
                        if found_ssids:
                            break
                    except Exception:
                        pass

                def update_ui():
                    btn_scan_ap.configure(state="normal", text="🔄 透過 USB 掃描 Wi-Fi AP")
                    if found_ssids:
                        ssid_combo["values"] = found_ssids
                        ssid_combo.set(found_ssids[0])
                        lbl_flash_status.configure(text=f"🎉 成功掃描到 {len(found_ssids)} 個 Wi-Fi AP！請在下拉選單中選取您的 Wi-Fi。", fg=self.ACCENT_GREEN)
                    else:
                        lbl_flash_status.configure(text="⚠️ 未能從硬體回傳掃描清單，您可直接在上方輸入 Wi-Fi 名稱。", fg=self.ACCENT_YELLOW)
                        messagebox.showinfo("掃描結果", "未能自動獲取周遭 AP 清單。\n\n提示：您可直接在 Wi-Fi 名稱下拉框中手動輸入家裡的 Wi-Fi 名稱！")

                self.root.after(0, update_ui)

            threading.Thread(target=scan_worker, daemon=True).start()

        btn_scan_ap.configure(command=scan_aps_via_usb)

        def start_flash():
            port = port_var.get()
            ssid = ssid_var.get().strip()
            pwd = pass_entry.get().strip()
            if not port:
                messagebox.showwarning("提示", "請選擇有效的 COM 埠！")
                return

            lbl_flash_status.configure(text=f"⚙️ 正在寫入 Wi-Fi 設定並自動編譯燒錄至 {port}...", fg=self.ACCENT)

            def flash_worker():
                try:
                    # 替換 wifi_firmware.ino 中的 Wi-Fi 設定
                    with open(WIFI_FIRMWARE_INO, "r", encoding="utf-8") as f:
                        code = f.read()

                    import re
                    code = re.sub(r'const char DEFAULT_SSID\[\] = ".*?";', f'const char DEFAULT_SSID[] = "{ssid}";', code)
                    code = re.sub(r'const char DEFAULT_PASS\[\] = ".*?";', f'const char DEFAULT_PASS[] = "{pwd}";', code)

                    with open(WIFI_FIRMWARE_INO, "w", encoding="utf-8") as f:
                        f.write(code)

                    # 呼叫 Arduino CLI 編譯並燒錄
                    cmd = [
                        ARDUINO_CLI_PATH,
                        "compile",
                        "--fqbn", "arduino:avr:uno",
                        "--upload",
                        "-p", port,
                        WIFI_FIRMWARE_INO
                    ]
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                    if p.returncode == 0:
                        self.root.after(0, lambda: [
                            lbl_flash_status.configure(text="🎉 燒錄成功！板子正在連線 Wi-Fi，稍後即可拔除 USB 線！", fg=self.ACCENT_GREEN),
                            messagebox.showinfo("燒錄成功", f"Wi-Fi 韌體已成功燒錄至 {port}！\n\nArduino Uno 現在會自動連線到您的 Wi-Fi。\n請留意 Webduino Fly 板上的紅燈熄滅代表連線成功，接著即可點擊「🔍 自動搜尋區網」進行無線操控！")
                        ])
                    else:
                        err = p.stderr or p.stdout
                        self.root.after(0, lambda: [
                            lbl_flash_status.configure(text="❌ 燒錄失敗，請檢查序列埠是否有佔用", fg=self.ACCENT_RED),
                            messagebox.showerror("燒錄失敗", f"Arduino-CLI 燒錄錯誤：\n{err[-300:]}")
                        ])
                except Exception as ex:
                    self.root.after(0, lambda: [
                        lbl_flash_status.configure(text=f"❌ 錯誤: {ex}", fg=self.ACCENT_RED),
                        messagebox.showerror("例外錯誤", str(ex))
                    ])

            threading.Thread(target=flash_worker, daemon=True).start()

        btn_run_flash = tk.Button(dlg, text="⚡ 開始編譯並燒錄 Wi-Fi 韌體", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=16, pady=6, cursor="hand2", command=start_flash)
        btn_run_flash.pack(side=tk.BOTTOM, pady=10)


def main():
    root = tk.Tk()
    app = WiFiControllerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

