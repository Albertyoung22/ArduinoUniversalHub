# -*- coding: utf-8 -*-
"""
⚡ ESP-01 雙路 Wi-Fi 繼電器控制中樞 (Bestep 2-CH Relay Hub)
================================================================
專為 Bestep / LC Technology ESP8266 (ESP-01) 雙路 5V 繼電器模組打造的專屬控制程式。
支援：
- Mode 1 原廠 AP 模式直連 (預設 192.168.4.1:8080)
- Mode 2 區網路由器模式 (自訂 IP:Port)
- 雙繼電器獨立開關、狀態即時回饋
- 點動模式 (Pulse / 延時自斷，適用於鐵捲門、點火、重啟等設備)
- 全開 / 全關 / 交叉切換
- 自動心跳偵測、通訊 HEX 指令日誌記錄
- 支援 CLI 命令列直接控制 (例: python relay_controller.py --ch1 on)
"""

import os
import sys
import time
import socket
import threading
import argparse
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

# Windows 終端機 UTF-8 支援
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 繼電器專用 16 進位 HEX 指令碼 (LC-Tech / Bestep 標準通訊協議)
CMD_R1_ON  = bytes.fromhex("A0 01 01 A2")
CMD_R1_OFF = bytes.fromhex("A0 01 00 A1")
CMD_R2_ON  = bytes.fromhex("A0 02 01 A3")
CMD_R2_OFF = bytes.fromhex("A0 02 00 A2")


class RelayClient:
    """管理與 ESP-01 板載伺服器的 TCP 網路通訊"""

    def __init__(self, host="192.168.4.1", port=8080, timeout=3.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.sock = None
        self.is_connected = False
        self._lock = threading.Lock()

    def connect(self, host=None, port=None):
        if host:
            self.host = host
        if port:
            self.port = int(port)

        self.disconnect()

        with self._lock:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)

                # 智慧多網卡支援：若電腦有雙網卡 (有線+Wi-Fi)，自動綁定至與目標同網段的本機 IP
                try:
                    hostname = socket.gethostname()
                    local_ips = socket.gethostbyname_ex(hostname)[2]
                    target_prefix = ".".join(self.host.split(".")[:3])
                    matched_ip = next((ip for ip in local_ips if ip.startswith(target_prefix)), None)
                    if matched_ip:
                        self.sock.bind((matched_ip, 0))
                except Exception:
                    pass

                self.sock.connect((self.host, self.port))
                self.is_connected = True
                return True, f"成功連線至 {self.host}:{self.port}"
            except Exception as e:
                self.is_connected = False
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None
                return False, f"連線失敗: {str(e)}"

    def disconnect(self):
        with self._lock:
            self.is_connected = False
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

    def send_cmd(self, cmd_bytes):
        """發送 16 進位指令"""
        with self._lock:
            if not self.is_connected or not self.sock:
                raise ConnectionError("尚未連線至繼電器模組")
            try:
                self.sock.sendall(cmd_bytes)
                return True
            except Exception as e:
                self.is_connected = False
                raise ConnectionError(f"傳送指令失敗 ({e})")


class RelayControllerApp:
    """現代深色系 GUI 控制介面"""

    # 主題色調 (Modern Dark Theme)
    BG_MAIN = "#1E1E2E"
    BG_NAV = "#181825"
    BG_CARD = "#2A2B3D"
    BG_INPUT = "#11111B"
    TEXT_MAIN = "#CDD6F4"
    TEXT_MUTED = "#9399B2"
    ACCENT_CYAN = "#89DCEB"
    ACCENT_GREEN = "#A6E3A1"
    ACCENT_RED = "#F38BA8"
    ACCENT_YELLOW = "#F9E2AF"
    BORDER_COLOR = "#45475A"

    def __init__(self, root):
        self.root = root
        self.root.title("⚡ ESP-01 雙路 Wi-Fi 繼電器控制中樞")
        self.root.geometry("820x720")
        self.root.minsize(760, 640)
        self.root.configure(bg=self.BG_MAIN)

        self.client = RelayClient()
        self.r1_state = False
        self.r2_state = False

        self._setup_window_icon()
        self._build_ui()

    def _setup_window_icon(self):
        """設置視窗與 Windows 工作列專屬高畫質圖示"""
        if sys.platform.startswith("win"):
            try:
                import ctypes
                myappid = "bestep.esp01.relay.hub.1.0"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        icon_ico = os.path.join(BASE_DIR, "wifi_icon.ico")
        icon_png = os.path.join(BASE_DIR, "wifi_icon.png")

        if os.path.exists(icon_ico):
            try:
                self.root.iconbitmap(icon_ico)
            except Exception:
                pass

        if os.path.exists(icon_png):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_png).resize((64, 64), Image.Resampling.LANCZOS)
                self._app_icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._app_icon)
            except Exception:
                pass

    def _build_ui(self):
        # 1. 頂部標題列與模式提示
        header_frame = tk.Frame(self.root, bg=self.BG_NAV, padx=16, pady=12)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="⚡ Bestep ESP-01 雙路 Wi-Fi 繼電器中樞",
            font=("Segoe UI", 13, "bold"),
            bg=self.BG_NAV,
            fg=self.ACCENT_CYAN,
        )
        title_lbl.pack(side=tk.LEFT)

        sub_lbl = tk.Label(
            header_frame,
            text="預設 AP 模式熱點: 192.168.4.1 : 8080 (HEX Protocol)",
            font=("Segoe UI", 9),
            bg=self.BG_NAV,
            fg=self.TEXT_MUTED,
        )
        sub_lbl.pack(side=tk.RIGHT)

        # 2. 連線設定卡片
        conn_frame = tk.Frame(self.root, bg=self.BG_CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        conn_frame.pack(fill=tk.X, padx=16, pady=(12, 6))

        tk.Label(conn_frame, text="🌐 設備 IP:", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.TEXT_MAIN).pack(side=tk.LEFT, padx=(0, 4))
        self.ip_entry = tk.Entry(conn_frame, font=("Consolas", 10), bg=self.BG_INPUT, fg=self.TEXT_MAIN, insertbackground=self.TEXT_MAIN, relief=tk.FLAT, width=15)
        self.ip_entry.insert(0, "192.168.4.1")
        self.ip_entry.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(conn_frame, text="通訊埠:", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.TEXT_MAIN).pack(side=tk.LEFT, padx=(0, 4))
        self.port_entry = tk.Entry(conn_frame, font=("Consolas", 10), bg=self.BG_INPUT, fg=self.TEXT_MAIN, insertbackground=self.TEXT_MAIN, relief=tk.FLAT, width=7)
        self.port_entry.insert(0, "8080")
        self.port_entry.pack(side=tk.LEFT, padx=(0, 14))

        self.btn_conn = tk.Button(
            conn_frame,
            text="📶 連線繼電器",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_CYAN,
            fg="#11111B",
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.toggle_connection,
        )
        self.btn_conn.pack(side=tk.LEFT, padx=4)

        self.lbl_status = tk.Label(
            conn_frame,
            text="🔴 未連線 (請先連上 AI-THINKER 熱點)",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG_CARD,
            fg=self.ACCENT_RED,
        )
        self.lbl_status.pack(side=tk.RIGHT, padx=4)

        # 3. 雙路繼電器控制面板 (左右兩欄)
        cards_container = tk.Frame(self.root, bg=self.BG_MAIN)
        cards_container.pack(fill=tk.X, padx=16, pady=6)
        cards_container.columnconfigure(0, weight=1)
        cards_container.columnconfigure(1, weight=1)

        # ---- 第一路卡片 ----
        self.card_r1 = tk.Frame(cards_container, bg=self.BG_CARD, padx=16, pady=16, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        self.card_r1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        tk.Label(self.card_r1, text="⚡ 繼電器 1 (Relay 1)", font=("Segoe UI", 11, "bold"), bg=self.BG_CARD, fg=self.ACCENT_YELLOW).pack(anchor="w")
        tk.Label(self.card_r1, text="輸出端子: NO1 / COM1 / NC1", font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.TEXT_MUTED).pack(anchor="w", pady=(0, 10))

        self.r1_status_badge = tk.Label(
            self.card_r1,
            text="已關閉 [OFF]",
            font=("Segoe UI", 12, "bold"),
            bg="#363A4F",
            fg=self.TEXT_MUTED,
            pady=10,
        )
        self.r1_status_badge.pack(fill=tk.X, pady=(0, 12))

        btn_row_r1 = tk.Frame(self.card_r1, bg=self.BG_CARD)
        btn_row_r1.pack(fill=tk.X)

        self.btn_r1_on = tk.Button(btn_row_r1, text="🟢 開啟 (ON)", font=("Segoe UI", 9, "bold"), bg="#363A4F", fg=self.TEXT_MAIN, relief=tk.FLAT, pady=6, cursor="hand2", command=lambda: self.set_relay(1, True))
        self.btn_r1_on.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_r1_off = tk.Button(btn_row_r1, text="🔴 關閉 (OFF)", font=("Segoe UI", 9, "bold"), bg="#363A4F", fg=self.TEXT_MAIN, relief=tk.FLAT, pady=6, cursor="hand2", command=lambda: self.set_relay(1, False))
        self.btn_r1_off.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.btn_r1_pulse = tk.Button(self.card_r1, text="⏱️ 點動觸發 (吸合 1 秒後自動關閉)", font=("Segoe UI", 8), bg="#313244", fg=self.TEXT_MUTED, relief=tk.FLAT, pady=4, cursor="hand2", command=lambda: self.pulse_relay(1, 1.0))
        self.btn_r1_pulse.pack(fill=tk.X, pady=(8, 0))

        # ---- 第二路卡片 ----
        self.card_r2 = tk.Frame(cards_container, bg=self.BG_CARD, padx=16, pady=16, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        self.card_r2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        tk.Label(self.card_r2, text="⚡ 繼電器 2 (Relay 2)", font=("Segoe UI", 11, "bold"), bg=self.BG_CARD, fg=self.ACCENT_YELLOW).pack(anchor="w")
        tk.Label(self.card_r2, text="輸出端子: NO2 / COM2 / NC2", font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.TEXT_MUTED).pack(anchor="w", pady=(0, 10))

        self.r2_status_badge = tk.Label(
            self.card_r2,
            text="已關閉 [OFF]",
            font=("Segoe UI", 12, "bold"),
            bg="#363A4F",
            fg=self.TEXT_MUTED,
            pady=10,
        )
        self.r2_status_badge.pack(fill=tk.X, pady=(0, 12))

        btn_row_r2 = tk.Frame(self.card_r2, bg=self.BG_CARD)
        btn_row_r2.pack(fill=tk.X)

        self.btn_r2_on = tk.Button(btn_row_r2, text="🟢 開啟 (ON)", font=("Segoe UI", 9, "bold"), bg="#363A4F", fg=self.TEXT_MAIN, relief=tk.FLAT, pady=6, cursor="hand2", command=lambda: self.set_relay(2, True))
        self.btn_r2_on.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_r2_off = tk.Button(btn_row_r2, text="🔴 關閉 (OFF)", font=("Segoe UI", 9, "bold"), bg="#363A4F", fg=self.TEXT_MAIN, relief=tk.FLAT, pady=6, cursor="hand2", command=lambda: self.set_relay(2, False))
        self.btn_r2_off.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.btn_r2_pulse = tk.Button(self.card_r2, text="⏱️ 點動觸發 (吸合 1 秒後自動關閉)", font=("Segoe UI", 8), bg="#313244", fg=self.TEXT_MUTED, relief=tk.FLAT, pady=4, cursor="hand2", command=lambda: self.pulse_relay(2, 1.0))
        self.btn_r2_pulse.pack(fill=tk.X, pady=(8, 0))

        # 4. 全域快捷操作區
        batch_frame = tk.Frame(self.root, bg=self.BG_CARD, padx=16, pady=10, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        batch_frame.pack(fill=tk.X, padx=16, pady=6)

        tk.Label(batch_frame, text="🚀 全域快捷控制:", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.TEXT_MAIN).pack(side=tk.LEFT, padx=(0, 10))

        btn_all_on = tk.Button(batch_frame, text="⚡ 全部開啟 (ALL ON)", font=("Segoe UI", 8, "bold"), bg="#2E7D32", fg="#FFFFFF", relief=tk.FLAT, padx=10, pady=3, cursor="hand2", command=self.all_on)
        btn_all_on.pack(side=tk.LEFT, padx=4)

        btn_all_off = tk.Button(batch_frame, text="⏹️ 全部關閉 (ALL OFF)", font=("Segoe UI", 8, "bold"), bg="#C62828", fg="#FFFFFF", relief=tk.FLAT, padx=10, pady=3, cursor="hand2", command=self.all_off)
        btn_all_off.pack(side=tk.LEFT, padx=4)

        btn_invert = tk.Button(batch_frame, text="🔄 狀態反轉 (INVERT)", font=("Segoe UI", 8), bg="#45475A", fg=self.TEXT_MAIN, relief=tk.FLAT, padx=10, pady=3, cursor="hand2", command=self.invert_all)
        btn_invert.pack(side=tk.LEFT, padx=4)

        btn_test = tk.Button(batch_frame, text="🧪 輪流開關測試 (Self-Test)", font=("Segoe UI", 8), bg="#313244", fg=self.ACCENT_CYAN, relief=tk.FLAT, padx=10, pady=3, cursor="hand2", command=self.run_self_test)
        btn_test.pack(side=tk.RIGHT, padx=4)

        # 5. 通訊終端與日誌區
        log_frame = tk.Frame(self.root, bg=self.BG_CARD, padx=16, pady=10, highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(6, 16))

        log_header = tk.Frame(log_frame, bg=self.BG_CARD)
        log_header.pack(fill=tk.X, pady=(0, 6))

        tk.Label(log_header, text="📜 HEX 通訊指令傳輸日誌", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.TEXT_MUTED).pack(side=tk.LEFT)
        btn_clear_log = tk.Button(log_header, text="清除日誌", font=("Segoe UI", 7), bg="#313244", fg=self.TEXT_MUTED, relief=tk.FLAT, padx=6, pady=1, cursor="hand2", command=self.clear_log)
        btn_clear_log.pack(side=tk.RIGHT)

        self.log_text = ScrolledText(
            log_frame,
            font=("Consolas", 9),
            bg=self.BG_INPUT,
            fg="#A6ADC8",
            insertbackground=self.TEXT_MAIN,
            relief=tk.FLAT,
            height=8,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.log("ℹ️ 歡迎使用 ESP-01 雙路 Wi-Fi 繼電器控制中樞")
        self.log("💡 提示：請先將電腦或手機 Wi-Fi 連線至「AI-THINKER_xxxxxx」，然後點擊「連線繼電器」")

    def log(self, msg):
        """將訊息輸出至介面日誌"""
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def toggle_connection(self):
        if self.client.is_connected:
            self.client.disconnect()
            self.lbl_status.config(text="🔴 已斷線", fg=self.ACCENT_RED)
            self.btn_conn.config(text="📶 連線繼電器", bg=self.ACCENT_CYAN, fg="#11111B")
            self.log("⏹️ 已中斷與繼電器的連線")
        else:
            ip = self.ip_entry.get().strip()
            port = self.port_entry.get().strip()
            self.lbl_status.config(text="🟡 連線中...", fg=self.ACCENT_YELLOW)
            self.btn_conn.config(state=tk.DISABLED)

            def do_connect():
                ok, msg = self.client.connect(ip, port)
                self.root.after(0, lambda: self._on_connect_result(ok, msg))

            threading.Thread(target=do_connect, daemon=True).start()

    def _on_connect_result(self, ok, msg):
        self.btn_conn.config(state=tk.NORMAL)
        if ok:
            self.lbl_status.config(text="🟢 已連線 (Ready)", fg=self.ACCENT_GREEN)
            self.btn_conn.config(text="❌ 中斷連線", bg=self.ACCENT_RED, fg="#FFFFFF")
            self.log(f"✅ {msg}")
        else:
            self.lbl_status.config(text="🔴 連線失敗", fg=self.ACCENT_RED)
            self.btn_conn.config(text="📶 連線繼電器", bg=self.ACCENT_CYAN, fg="#11111B")
            self.log(f"❌ {msg}")
            messagebox.showwarning(
                "連線提示",
                f"無法連線到 {self.ip_entry.get()}:{self.port_entry.get()}\n\n"
                "請確認：\n"
                "1. 電腦是否已切換 Wi-Fi 並連上板子的「AI-THINKER_xxxx」熱點？\n"
                "2. 繼電器板子的 5V 電源是否正常接通？\n"
                "3. 板上紅色指示燈 D7 是否亮起 (Mode 1)？"
            )

    def set_relay(self, ch, state):
        """控制單一繼電器"""
        if not self.client.is_connected:
            messagebox.showinfo("連線提示", "請先點擊頂部「📶 連線繼電器」再進行操作！")
            return

        if ch == 1:
            cmd = CMD_R1_ON if state else CMD_R1_OFF
            hex_str = "A0 01 01 A2" if state else "A0 01 00 A1"
        else:
            cmd = CMD_R2_ON if state else CMD_R2_OFF
            hex_str = "A0 02 01 A3" if state else "A0 02 00 A2"

        def task():
            try:
                self.client.send_cmd(cmd)
                self.root.after(0, lambda c=ch, s=state, h=hex_str: self._update_relay_ui(c, s, h))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda msg=err_msg: self._on_send_error(msg))

        threading.Thread(target=task, daemon=True).start()

    def _update_relay_ui(self, ch, state, hex_str):
        if ch == 1:
            self.r1_state = state
            if state:
                self.r1_status_badge.config(text="⚡ 已開啟 [ON]", bg="#2E7D32", fg="#FFFFFF")
                self.btn_r1_on.config(bg=self.ACCENT_GREEN, fg="#11111B")
                self.btn_r1_off.config(bg="#363A4F", fg=self.TEXT_MAIN)
            else:
                self.r1_status_badge.config(text="已關閉 [OFF]", bg="#363A4F", fg=self.TEXT_MUTED)
                self.btn_r1_on.config(bg="#363A4F", fg=self.TEXT_MAIN)
                self.btn_r1_off.config(bg=self.ACCENT_RED, fg="#FFFFFF")
            self.log(f"📤 第 1 路繼電器 -> {'開啟 (ON)' if state else '關閉 (OFF)'} | HEX: [{hex_str}]")
        else:
            self.r2_state = state
            if state:
                self.r2_status_badge.config(text="⚡ 已開啟 [ON]", bg="#2E7D32", fg="#FFFFFF")
                self.btn_r2_on.config(bg=self.ACCENT_GREEN, fg="#11111B")
                self.btn_r2_off.config(bg="#363A4F", fg=self.TEXT_MAIN)
            else:
                self.r2_status_badge.config(text="已關閉 [OFF]", bg="#363A4F", fg=self.TEXT_MUTED)
                self.btn_r2_on.config(bg="#363A4F", fg=self.TEXT_MAIN)
                self.btn_r2_off.config(bg=self.ACCENT_RED, fg="#FFFFFF")
            self.log(f"📤 第 2 路繼電器 -> {'開啟 (ON)' if state else '關閉 (OFF)'} | HEX: [{hex_str}]")

    def _on_send_error(self, err_msg):
        self.lbl_status.config(text="🔴 連線中斷", fg=self.ACCENT_RED)
        self.btn_conn.config(text="📶 連線繼電器", bg=self.ACCENT_CYAN, fg="#11111B")
        self.log(f"⚠️ 發送失敗: {err_msg}")
        messagebox.showerror("傳送錯誤", f"發送控制指令失敗：\n{err_msg}\n請檢查是否已斷線。")

    def pulse_relay(self, ch, duration=1.0):
        """點動模式：吸合指定秒數後自動復歸關閉"""
        if not self.client.is_connected:
            messagebox.showinfo("連線提示", "請先點擊頂部「📶 連線繼電器」再進行操作！")
            return
        def task():
            self.set_relay(ch, True)
            time.sleep(duration)
            self.set_relay(ch, False)
        threading.Thread(target=task, daemon=True).start()

    def all_on(self):
        if not self.client.is_connected:
            messagebox.showinfo("連線提示", "請先點擊頂部「📶 連線繼電器」再進行操作！")
            return
        self.set_relay(1, True)
        self.root.after(100, lambda: self.set_relay(2, True))

    def all_off(self):
        if not self.client.is_connected:
            messagebox.showinfo("連線提示", "請先點擊頂部「📶 連線繼電器」再進行操作！")
            return
        self.set_relay(1, False)
        self.root.after(100, lambda: self.set_relay(2, False))

    def invert_all(self):
        if not self.client.is_connected:
            messagebox.showinfo("連線提示", "請先點擊頂部「📶 連線繼電器」再進行操作！")
            return
        self.set_relay(1, not self.r1_state)
        self.root.after(100, lambda: self.set_relay(2, not self.r2_state))

    def run_self_test(self):
        """自我檢測：依序開關 Relay 1 & Relay 2 聽取聲音"""
        if not self.client.is_connected:
            messagebox.showinfo("提示", "請先點擊「連線繼電器」再進行測試！")
            return

        def task():
            self.log("🧪 開始自動測試序列...")
            self.set_relay(1, True)
            time.sleep(1.0)
            self.set_relay(1, False)
            time.sleep(0.5)
            self.set_relay(2, True)
            time.sleep(1.0)
            self.set_relay(2, False)
            self.log("🎉 測試序列已完成！")

        threading.Thread(target=task, daemon=True).start()


def main_cli():
    """命令列 CLI 模式 (無 GUI)"""
    parser = argparse.ArgumentParser(description="Bestep ESP-01 2-CH Relay CLI")
    parser.add_argument("--ip", default="192.168.4.1", help="ESP-01 IP address")
    parser.add_argument("--port", type=int, default=8080, help="ESP-01 Port")
    parser.add_argument("--ch1", choices=["on", "off", "pulse"], help="Control Channel 1")
    parser.add_argument("--ch2", choices=["on", "off", "pulse"], help="Control Channel 2")
    args = parser.parse_args()

    client = RelayClient(args.ip, args.port)
    ok, msg = client.connect()
    if not ok:
        print(f"Error: {msg}")
        sys.exit(1)

    print(f"Connected: {msg}")

    def execute_action(ch, action):
        if action == "on":
            cmd = CMD_R1_ON if ch == 1 else CMD_R2_ON
            client.send_cmd(cmd)
            print(f"CH{ch} -> ON")
        elif action == "off":
            cmd = CMD_R1_OFF if ch == 1 else CMD_R2_OFF
            client.send_cmd(cmd)
            print(f"CH{ch} -> OFF")
        elif action == "pulse":
            cmd_on = CMD_R1_ON if ch == 1 else CMD_R2_ON
            cmd_off = CMD_R1_OFF if ch == 1 else CMD_R2_OFF
            client.send_cmd(cmd_on)
            print(f"CH{ch} -> ON (Pulse)")
            time.sleep(1)
            client.send_cmd(cmd_off)
            print(f"CH{ch} -> OFF")

    if args.ch1:
        execute_action(1, args.ch1)
    if args.ch2:
        execute_action(2, args.ch2)

    client.disconnect()
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and any(arg in sys.argv for arg in ["--ch1", "--ch2", "--help", "-h", "--ip", "--port"]):
        main_cli()
    else:
        root = tk.Tk()
        app = RelayControllerApp(root)
        root.mainloop()
