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
    """Wi-Fi 通訊客戶端核心 (Webduino 二進位 WebSocket 高速直通引擎)"""
    def __init__(self, ip: str = "192.168.1.134", port: int = 80):
        self.ip = ip.strip()
        self.port = port
        self.is_connected = False
        self.latency_ms = 0
        self.cmd_queue = queue.Queue(maxsize=100)
        self.worker_thread = None
        self.rx_thread = None
        self.running = False
        self.on_log = None
        self.ws_sock = None
        self.is_websocket = False
        self._lock = threading.Lock()

    def log(self, msg: str):
        if self.on_log:
            self.on_log(msg)
        else:
            print(f"[WiFiClient] {msg}")

    def connect(self) -> bool:
        """主動連線至 Webduino Fly WebSocket 伺服器"""
        with self._lock:
            if self.ws_sock:
                try:
                    self.ws_sock.close()
                except Exception:
                    pass
                self.ws_sock = None

            start = time.time()
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((self.ip, self.port))
                handshake = (
                    f"GET / HTTP/1.1\r\n"
                    f"Host: {self.ip}\r\n"
                    f"Upgrade: websocket\r\n"
                    f"Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    f"Sec-WebSocket-Version: 13\r\n\r\n"
                )
                sock.sendall(handshake.encode())
                resp = sock.recv(512)
                if b"101 Switching" in resp or b"WebSockets" in resp or b"Webduino" in resp:
                    sock.settimeout(None)  # 設為長連線暢通模式
                    self.ws_sock = sock
                    self.is_websocket = True
                    self.is_connected = True
                    self.latency_ms = max(1, int((time.time() - start) * 1000))
                    
                    # 立即回應 Handshake 夾帶的 PING (Webduino-Server 特性)
                    if b"\x89" in resp:
                        try:
                            pong = bytearray([0x8A, 0x80, 0, 0, 0, 0])
                            sock.sendall(pong)
                        except Exception:
                            pass

                    # 啟動非阻塞背景排空與心跳接收執行緒
                    self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
                    self.rx_thread.start()
                    return True
                sock.close()
            except Exception as e:
                self.log(f"連線失敗: {e}")
            self.is_connected = False
            return False

    def _rx_loop(self):
        """背景接收執行緒：持續清空接收緩衝區，杜絕 TCP 阻塞黏包並自動回應 PONG 心跳"""
        sock = self.ws_sock
        while self.running and sock and self.is_connected:
            try:
                data = sock.recv(512)
                if not data:
                    break
                # 若收到 Webduino Fly 的 WebSocket PING (\x89)，自動回應 PONG (\x8A)
                if b"\x89" in data:
                    with self._lock:
                        if self.ws_sock:
                            self.ws_sock.sendall(bytearray([0x8A, 0x80, 0, 0, 0, 0]))
            except Exception:
                break
        if self.ws_sock == sock:
            self.is_connected = False

    def ping(self) -> bool:
        if not self.is_connected or not self.ws_sock:
            return self.connect()

        # 透過現有連線發送輕量探測
        start = time.time()
        try:
            payload = b"PING\n"
            frame = bytearray([0x82, 0x80 | len(payload), 0, 0, 0, 0]) + payload
            with self._lock:
                if self.ws_sock:
                    self.ws_sock.sendall(frame)
            self.latency_ms = max(1, int((time.time() - start) * 1000))
            return True
        except Exception:
            self.is_connected = False
            return False

    def send_cmd_sync(self, cmd: str) -> dict:
        """即時發送指令至 Arduino Uno 晶片 (二進位高速轉發)"""
        if not self.is_connected or not self.ws_sock:
            if not self.connect():
                return {"ok": False, "error": "not_connected"}

        try:
            payload = (cmd.strip() + "\n").encode("utf-8")
            length = len(payload)
            if length < 126:
                header = bytearray([0x82, 0x80 | length, 0, 0, 0, 0])
            else:
                header = bytearray([0x82, 0x80 | 126, (length >> 8) & 0xFF, length & 0xFF, 0, 0, 0, 0])
            frame = header + payload
            with self._lock:
                if self.ws_sock:
                    self.ws_sock.sendall(frame)
                    return {"ok": True, "res": "sent"}
        except Exception as e:
            self.is_connected = False
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "send_failed"}

    def send_cmd(self, cmd: str):
        try:
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
        with self._lock:
            if self.ws_sock:
                try:
                    self.ws_sock.close()
                except Exception:
                    pass
                self.ws_sock = None

    def _worker_loop(self):
        while self.running:
            try:
                cmd = self.cmd_queue.get(timeout=0.08)
                self.send_cmd_sync(cmd)
                self.cmd_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

PIN_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wifi_pins_config.json')

def load_pin_config() -> dict:
    defaults = {
        'switch_pin': 13,
        'pwm_pin': 3,
        'servo_pin': 4,
        'rgb_r_pin': 9,
        'rgb_g_pin': 10,
        'rgb_b_pin': 11,
        'anode': True,
        'matrix_din': 12,
        'matrix_cs': 8,
        'matrix_clk': 7
    }
    if os.path.exists(PIN_CONFIG_FILE):
        try:
            with open(PIN_CONFIG_FILE, 'r', encoding='utf-8') as f:
                defaults.update(json.load(f))
        except Exception:
            pass
    return defaults

def save_pin_config(cfg: dict):
    try:
        with open(PIN_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ==========================
# 內嵌式超輕量 Web 遙控伺服器 (供 Cloudflare Tunnel 外網穿透直連)
# ==========================
import http.server
import urllib.parse

WEB_REMOTE_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>⚡ Arduino Wi-Fi 外網遠端遙控</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #1E1E2E; color: #CDD6F4; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 16px; text-align: center; }
    .header { margin-bottom: 16px; }
    .header h1 { font-size: 1.35rem; color: #89B4FA; margin-bottom: 4px; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; background: #313244; color: #A6E3A1; }
    .card { background: #313244; border-radius: 12px; padding: 14px; margin-bottom: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); border: 1px solid #45475A; }
    .card-title { font-size: 0.95rem; font-weight: bold; color: #89B4FA; margin-bottom: 10px; text-align: left; }
    .btn { display: inline-flex; align-items: center; justify-content: center; border: none; border-radius: 8px; font-size: 0.92rem; font-weight: bold; padding: 12px 16px; cursor: pointer; transition: transform 0.1s, opacity 0.2s; user-select: none; }
    .btn:active { transform: scale(0.96); }
    .btn-primary { background: #89B4FA; color: #11111B; }
    .btn-success { background: #A6E3A1; color: #11111B; }
    .btn-danger { background: #F38BA8; color: #11111B; }
    .btn-dark { background: #181825; color: #CDD6F4; border: 1px solid #45475A; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .palette-btn { height: 40px; border-radius: 6px; font-weight: bold; font-size: 0.82rem; border: none; cursor: pointer; }
    .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #181825; color: #89B4FA; border: 1px solid #89B4FA; padding: 8px 16px; border-radius: 20px; font-size: 0.85rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>
  <div class="header">
    <h1>⚡ Arduino Wi-Fi 遠端遙控</h1>
    <span class="badge" id="stBadge">● 連線就緒 (Cloudflare Tunnel)</span>
  </div>

  <div class="card">
    <div class="card-title">💡 數位開關 (Pin 13)</div>
    <div class="grid-2">
      <button class="btn btn-success" onclick="sendCmd('DWRITE,13,1')">開燈 (ON)</button>
      <button class="btn btn-danger" onclick="sendCmd('DWRITE,13,0')">關燈 (OFF)</button>
    </div>
  </div>

  <div class="card">
    <div class="card-title">🎨 RGB 燈光即時調色 (Pin 9, 10, 11)</div>
    <div class="grid-4" style="margin-bottom: 10px;">
      <button class="palette-btn" style="background:#F38BA8; color:#111;" onclick="setRgb(255,0,0)">🔴 紅</button>
      <button class="palette-btn" style="background:#A6E3A1; color:#111;" onclick="setRgb(0,255,0)">🟢 綠</button>
      <button class="palette-btn" style="background:#89B4FA; color:#111;" onclick="setRgb(0,0,255)">🔵 藍</button>
      <button class="palette-btn" style="background:#F9E2AF; color:#111;" onclick="setRgb(255,255,0)">🟡 黃</button>
      <button class="palette-btn" style="background:#CBA6F7; color:#111;" onclick="setRgb(255,0,255)">🟣 紫</button>
      <button class="palette-btn" style="background:#94E2D5; color:#111;" onclick="setRgb(0,255,255)">🩵 青</button>
      <button class="palette-btn" style="background:#FFFFFF; color:#111;" onclick="setRgb(255,255,255)">⚪ 白光</button>
      <button class="palette-btn" style="background:#181825; color:#A6ADC8; border:1px solid #45475A;" onclick="setRgb(0,0,0)">⚫ 關閉</button>
    </div>
    <div style="display:flex; align-items:center; gap:10px; justify-content:center;">
      <span style="font-size:0.85rem; color:#A6ADC8;">自訂選色:</span>
      <input type="color" id="picker" value="#ff0000" onchange="onColorPick(this.value)" style="width:50px; height:34px; border:none; border-radius:6px; cursor:pointer;">
    </div>
  </div>

  <div class="card">
    <div class="card-title">✨ 炫彩即時特效</div>
    <div class="grid-2" style="margin-bottom: 8px;">
      <button class="btn btn-dark" onclick="sendCmd('FX,sync_rainbow')">🌈 同步彩虹</button>
      <button class="btn btn-dark" onclick="sendCmd('FX,police_strobe')">🚨 警車爆閃</button>
    </div>
    <div class="grid-2">
      <button class="btn btn-dark" onclick="sendCmd('FX,alt_breathing')">🫁 呼吸漸變</button>
      <button class="btn btn-danger" onclick="sendCmd('FX,stop')">⏹️ 停止特效</button>
    </div>
  </div>

  <button class="btn btn-danger" style="width:100%; padding:14px; font-size:1.05rem;" onclick="sendCmd('STOP')">🛑 全體急停 (STOP)</button>

  <div class="toast" id="toastMsg">指令已送出</div>

  <script>
    function showToast(msg) {
      const t = document.getElementById('toastMsg');
      t.innerText = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 1200);
    }
    function sendCmd(cmd) {
      fetch('/api/cmd?c=' + encodeURIComponent(cmd))
        .then(r => r.json())
        .then(d => { showToast('⚡ 已送出: ' + cmd); })
        .catch(e => { showToast('❌ 發送失敗'); });
    }
    function setRgb(r, g, b) {
      sendCmd('RGB,9,10,11,1,' + r + ',' + g + ',' + b);
    }
    function onColorPick(hex) {
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      setRgb(r, g, b);
    }
  </script>
</body>
</html>
"""

class WiFiWebRemoteHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 壓制終端存取洗版

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(WEB_REMOTE_HTML.encode("utf-8"))
        elif parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            app = getattr(self.server, "app", None)
            st = {
                "connected": app.client.is_connected if app else False,
                "ip": app.client.ip if app else "",
                "latency": app.client.latency_ms if app else 0
            }
            self.wfile.write(json.dumps(st).encode("utf-8"))
        elif parsed.path == "/api/cmd":
            query = urllib.parse.parse_qs(parsed.query)
            cmd = query.get("c", [""])[0]
            app = getattr(self.server, "app", None)
            if app and cmd:
                if cmd.startswith("FX,"):
                    fx = cmd.split(",")[1]
                    if fx == "stop":
                        app.stop_dual_effect()
                    else:
                        app.start_dual_effect(fx)
                elif cmd == "STOP":
                    app.emergency_stop()
                else:
                    app.client.send_cmd(cmd)
                app.log(f"📱 [外網遙控] 收到指令: {cmd}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        else:
            self.send_response(404)
            self.end_headers()

class EmbeddedWebServer:
    def __init__(self, app, port=5000):
        self.app = app
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self, port=5000):
        if self.httpd:
            return True
        self.port = port
        try:
            self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), WiFiWebRemoteHandler)
            self.httpd.app = self.app
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
            self.app.log(f"🌐 內嵌式 Web 遙控伺服器已在 Port {self.port} 啟動！")
            return True
        except Exception as e:
            self.app.log(f"❌ 啟動 Web 伺服器失敗: {e}")
            return False

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
            self.thread = None
            self.app.log("⏹️ 內嵌式 Web 遙控伺服器已停止")

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
        self.web_server = EmbeddedWebServer(self, port=5000)
        self.client.on_log = self.log

        # 雙燈即時特效執行緒控制
        self.effect_thread = None
        self.effect_stop_event = threading.Event()
        self.current_effect_name = None

        # MAX7219 點陣畫布狀態 (8 bytes)
        self.matrix_state = [0] * 8
        self.matrix_btns = []

        # 手動自訂腳位配置 (支援記憶存檔)
        self.pin_cfg = load_pin_config()
        self.sw_pin_var = tk.IntVar(value=self.pin_cfg.get("switch_pin", 13))
        self.pwm_pin_var = tk.IntVar(value=self.pin_cfg.get("pwm_pin", 9))
        self.srv_pin_var = tk.IntVar(value=self.pin_cfg.get("servo_pin", 10))
        self.rgb_r_pin_var = tk.IntVar(value=self.pin_cfg.get("rgb_r_pin", 6))
        self.rgb_g_pin_var = tk.IntVar(value=self.pin_cfg.get("rgb_g_pin", 3))
        self.rgb_b_pin_var = tk.IntVar(value=self.pin_cfg.get("rgb_b_pin", 5))
        self.matrix_din_var = tk.IntVar(value=self.pin_cfg.get("matrix_din", 12))
        self.matrix_cs_var = tk.IntVar(value=self.pin_cfg.get("matrix_cs", 8))
        self.matrix_clk_var = tk.IntVar(value=self.pin_cfg.get("matrix_clk", 7))

        self._build_ui()
        self.client.start_worker()

        # 啟動時自動嘗試無線連線 (200ms 後無感接入)
        self.root.after(200, self.toggle_connection)

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
        self.ip_entry.insert(0, "192.168.1.134")
        self.ip_entry.pack(side=tk.LEFT, padx=6)

        self.btn_connect = tk.Button(top_frame, text="📶 連線 Wi-Fi", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=3, cursor="hand2", command=self.toggle_connection)
        self.btn_connect.pack(side=tk.LEFT, padx=4)

        btn_scan = tk.Button(top_frame, text="🔍 自動搜尋區網", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 8), bd=0, padx=8, pady=3, cursor="hand2", command=self.scan_lan_devices)
        btn_scan.pack(side=tk.LEFT, padx=4)

        btn_flash = tk.Button(top_frame, text="🛠️ 一鍵燒錄 Wi-Fi 韌體", bg="#F5C2E7", fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2", command=self.open_flash_dialog)
        btn_flash.pack(side=tk.LEFT, padx=4)

        btn_tunnel = tk.Button(top_frame, text="🌐 外網穿透", bg="#89B4FA", fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2", command=self.open_tunnel_dialog)
        btn_tunnel.pack(side=tk.LEFT, padx=4)
        self.btn_tunnel = btn_tunnel

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

    def _save_pins(self, *args):
        self.pin_cfg["switch_pin"] = self.sw_pin_var.get()
        self.pin_cfg["pwm_pin"] = self.pwm_pin_var.get()
        self.pin_cfg["servo_pin"] = self.srv_pin_var.get()
        self.pin_cfg["rgb_r_pin"] = self.rgb_r_pin_var.get()
        self.pin_cfg["rgb_g_pin"] = self.rgb_g_pin_var.get()
        self.pin_cfg["rgb_b_pin"] = self.rgb_b_pin_var.get()
        self.pin_cfg["anode"] = self.anode_var.get()
        self.pin_cfg["matrix_din"] = self.matrix_din_var.get()
        self.pin_cfg["matrix_cs"] = self.matrix_cs_var.get()
        self.pin_cfg["matrix_clk"] = self.matrix_clk_var.get()
        save_pin_config(self.pin_cfg)
        self.log(f"⚙️ 腳位設定已自動保存！")

    def _build_switch_servo_card(self):
        row = tk.Frame(self.cards_frame, bg=self.BG_MAIN)
        row.pack(fill=tk.X, pady=(0, 12))

        # 1. 數位開關卡片 (附腳位自訂)
        f_sw = tk.LabelFrame(row, text="💡 數位開關 (LED / 繼電器)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=8)
        f_sw.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        top_sw = tk.Frame(f_sw, bg=self.BG_CARD)
        top_sw.pack(fill=tk.X, pady=(0, 6))
        tk.Label(top_sw, text="📌 腳位: Pin", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        cb_sw = ttk.Combobox(top_sw, textvariable=self.sw_pin_var, values=list(range(2, 14)), width=4, state="readonly")
        cb_sw.pack(side=tk.LEFT, padx=4)
        cb_sw.bind("<<ComboboxSelected>>", self._save_pins)

        self.sw_state = False
        self.btn_sw = tk.Button(f_sw, text="⚪ 目前：關閉 (點擊開啟)", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 10, "bold"), bd=0, pady=8, cursor="hand2", command=self.toggle_switch)
        self.btn_sw.pack(fill=tk.X, pady=4)

        # 2. PWM 滑桿卡片 (附腳位自訂)
        f_pwm = tk.LabelFrame(row, text="⚡ PWM 功率/馬達", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=8)
        f_pwm.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        top_pwm = tk.Frame(f_pwm, bg=self.BG_CARD)
        top_pwm.pack(fill=tk.X, pady=(0, 4))
        tk.Label(top_pwm, text="📌 腳位: Pin", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        cb_pwm = ttk.Combobox(top_pwm, textvariable=self.pwm_pin_var, values=[3, 5, 6, 9, 10, 11], width=4, state="readonly")
        cb_pwm.pack(side=tk.LEFT, padx=4)
        cb_pwm.bind("<<ComboboxSelected>>", self._save_pins)

        self.pwm_val = tk.IntVar(value=0)
        self.pwm_lbl = tk.Label(top_pwm, text="0 (0%)", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Consolas", 10))
        self.pwm_lbl.pack(side=tk.RIGHT)
        scale_pwm = tk.Scale(f_pwm, from_=0, to=255, orient=tk.HORIZONTAL, variable=self.pwm_val, bg=self.BG_CARD, fg=self.TEXT_MAIN, highlightthickness=0, bd=0, command=self._on_pwm_change)
        scale_pwm.pack(fill=tk.X)

        # 3. 伺服舵機卡片 (附腳位自訂)
        f_srv = tk.LabelFrame(row, text="🎯 伺服舵機 (0°~180°)", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=8)
        f_srv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_srv = tk.Frame(f_srv, bg=self.BG_CARD)
        top_srv.pack(fill=tk.X, pady=(0, 4))
        tk.Label(top_srv, text="📌 腳位: Pin", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        cb_srv = ttk.Combobox(top_srv, textvariable=self.srv_pin_var, values=list(range(2, 14)), width=4, state="readonly")
        cb_srv.pack(side=tk.LEFT, padx=4)
        cb_srv.bind("<<ComboboxSelected>>", self._save_pins)

        self.srv_val = tk.IntVar(value=90)
        self.srv_lbl = tk.Label(top_srv, text="90° (中間歸位)", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Consolas", 10))
        self.srv_lbl.pack(side=tk.RIGHT)
        scale_srv = tk.Scale(f_srv, from_=0, to=180, orient=tk.HORIZONTAL, variable=self.srv_val, bg=self.BG_CARD, fg=self.TEXT_MAIN, highlightthickness=0, bd=0, command=self._on_servo_change)
        scale_srv.pack(fill=tk.X)

    def _build_rgb_card(self):
        f = tk.LabelFrame(self.cards_frame, text="🌈 雙 RGB LED 模組與 18 款炫彩即時特效", bg=self.BG_CARD, fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=14, pady=10)
        f.pack(fill=tk.X, pady=(0, 12))

        top_r = tk.Frame(f, bg=self.BG_CARD)
        top_r.pack(fill=tk.X, pady=(0, 8))

        # 色塊預覽
        self.rgb_preview = tk.Canvas(top_r, width=44, height=44, bg="#000000", highlightthickness=1, highlightbackground=self.BORDER_COLOR)
        self.rgb_preview.pack(side=tk.LEFT, padx=(0, 10))

        btn_color = tk.Button(top_r, text="🎨 選擇色彩", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 9), bd=0, padx=10, pady=4, cursor="hand2", command=self.pick_color)
        btn_color.pack(side=tk.LEFT, padx=4)

        self.anode_var = tk.BooleanVar(value=True)
        chk_anode = tk.Checkbutton(top_r, text="共陽 (V接5V)", variable=self.anode_var, command=self._save_pins, bg=self.BG_CARD, fg=self.ACCENT_YELLOW, selectcolor="#11111B", activebackground=self.BG_CARD, font=("Segoe UI", 8, "bold"))
        chk_anode.pack(side=tk.LEFT, padx=6)

        # RGB 腳位自訂
        pin_box = tk.Frame(top_r, bg="#252538", padx=6, pady=3, bd=1, relief=tk.SOLID)
        pin_box.pack(side=tk.LEFT, padx=8)
        tk.Label(pin_box, text="📌 腳位 R:", bg="#252538", fg=self.ACCENT_RED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        cb_r = ttk.Combobox(pin_box, textvariable=self.rgb_r_pin_var, values=[3, 5, 6, 9, 10, 11], width=3, state="readonly")
        cb_r.pack(side=tk.LEFT, padx=2)
        cb_r.bind("<<ComboboxSelected>>", self._save_pins)

        tk.Label(pin_box, text="G:", bg="#252538", fg=self.ACCENT_GREEN, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(4, 0))
        cb_g = ttk.Combobox(pin_box, textvariable=self.rgb_g_pin_var, values=[3, 5, 6, 9, 10, 11], width=3, state="readonly")
        cb_g.pack(side=tk.LEFT, padx=2)
        cb_g.bind("<<ComboboxSelected>>", self._save_pins)

        tk.Label(pin_box, text="B:", bg="#252538", fg=self.ACCENT, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(4, 0))
        cb_b = ttk.Combobox(pin_box, textvariable=self.rgb_b_pin_var, values=[3, 5, 6, 9, 10, 11], width=3, state="readonly")
        cb_b.pack(side=tk.LEFT, padx=2)
        cb_b.bind("<<ComboboxSelected>>", self._save_pins)

        btn_stop_fx = tk.Button(top_r, text="⏹️ 停止特效", bg=self.ACCENT_RED, fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2", command=self.stop_dual_effect)
        btn_stop_fx.pack(side=tk.RIGHT)

        # 即時快捷單鍵調色盤
        quick_frame = tk.Frame(f, bg=self.BG_CARD)
        quick_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(quick_frame, text="⚡ 即時單鍵變色:", bg=self.BG_CARD, fg=self.TEXT_MUTED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        palette = [
            ("🔴 紅", 255, 0, 0, "#F38BA8"),
            ("🟢 綠", 0, 255, 0, "#A6E3A1"),
            ("🔵 藍", 0, 0, 255, "#89B4FA"),
            ("🟡 黃", 255, 255, 0, "#F9E2AF"),
            ("🟣 紫", 255, 0, 255, "#CBA6F7"),
            ("⚪ 白光", 255, 255, 255, "#CDD6F4"),
            ("⚫ 全滅", 0, 0, 0, "#A6ADC8")
        ]
        for lbl, r, g, b, fg_c in palette:
            btn = tk.Button(quick_frame, text=lbl, bg="#181825", fg=fg_c, font=("Segoe UI", 8, "bold"), bd=1, relief=tk.SOLID, padx=6, pady=2, cursor="hand2", command=lambda r=r, g=g, b=b: self.set_rgb_color(r, g, b))
            btn.pack(side=tk.LEFT, padx=3)

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

        # 點陣腳位自訂
        m_pin_row = tk.Frame(ctrl_frame, bg="#252538", padx=6, pady=4, bd=1, relief=tk.SOLID)
        m_pin_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(m_pin_row, text="📌 點陣腳位 DIN: Pin", bg="#252538", fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        cb_din = ttk.Combobox(m_pin_row, textvariable=self.matrix_din_var, values=list(range(2, 14)), width=3, state="readonly")
        cb_din.pack(side=tk.LEFT, padx=2)
        cb_din.bind("<<ComboboxSelected>>", self._save_pins)

        tk.Label(m_pin_row, text="CS: Pin", bg="#252538", fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 0))
        cb_cs = ttk.Combobox(m_pin_row, textvariable=self.matrix_cs_var, values=list(range(2, 14)), width=3, state="readonly")
        cb_cs.pack(side=tk.LEFT, padx=2)
        cb_cs.bind("<<ComboboxSelected>>", self._save_pins)

        tk.Label(m_pin_row, text="CLK: Pin", bg="#252538", fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 0))
        cb_clk = ttk.Combobox(m_pin_row, textvariable=self.matrix_clk_var, values=list(range(2, 14)), width=3, state="readonly")
        cb_clk.pack(side=tk.LEFT, padx=2)
        cb_clk.bind("<<ComboboxSelected>>", self._save_pins)

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
        print(f"[WiFiLog] {msg}", flush=True)
        def _append():
            try:
                if hasattr(self, "log_text"):
                    self.log_text.insert(tk.END, line)
                    self.log_text.see(tk.END)
            except Exception:
                pass
        try:
            self.root.after(0, _append)
        except Exception:
            pass

    # ==========================
    # 連線與通訊邏輯
    # ==========================
    def toggle_connection(self):
        if self.client.is_connected:
            self.client.is_connected = False
            if self.client.ws_sock:
                try:
                    self.client.ws_sock.close()
                except Exception:
                    pass
                self.client.ws_sock = None
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
        # 連線就緒後主動發送初始 RGB 指令，確保硬體燈號即時受控
        anode = 1 if self.anode_var.get() else 0
        self.client.send_cmd(f"RGB,{self.rgb_r_pin_var.get()},{self.rgb_g_pin_var.get()},{self.rgb_b_pin_var.get()},{anode},0,0,0")

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
                        # 驗證是否為 Arduino / Webduino
                        try:
                            req = urllib.request.Request(f"http://{ip}/", headers={"User-Agent": "WiFiArduinoHub/1.0"})
                            with urllib.request.urlopen(req, timeout=0.6) as r:
                                s_hdr = r.headers.get("Server", "").lower()
                                if "webduino" in s_hdr or "websocket" in s_hdr or "arduino" in s_hdr:
                                    found_ips.append(ip)
                                    return
                        except Exception:
                            pass
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
        self.client.send_cmd(f"DWRITE,{self.sw_pin_var.get()},{val}")
        self.log(f"💡 [Wi-Fi] 數位開關 (Pin 13): {'開啟' if self.sw_state else '關閉'}")

    def _on_pwm_change(self, val):
        v = int(val)
        pct = int(v / 255.0 * 100)
        self.pwm_lbl.configure(text=f"{v} ({pct}%)")
        self.client.send_cmd(f"PWM,{self.pwm_pin_var.get()},{v}")

    def _on_servo_change(self, val):
        ang = int(val)
        self.srv_lbl.configure(text=f"{ang}°")
        self.client.send_cmd(f"SERVO,{self.srv_pin_var.get()},{ang}")

    def set_rgb_color(self, r: int, g: int, b: int):
        self.stop_dual_effect()
        hex_c = f"#{r:02x}{g:02x}{b:02x}"
        self.rgb_preview.configure(bg=hex_c)
        anode = 1 if self.anode_var.get() else 0
        self.client.send_cmd(f"RGB,{self.rgb_r_pin_var.get()},{self.rgb_g_pin_var.get()},{self.rgb_b_pin_var.get()},{anode},{r},{g},{b}")
        self.log(f"🎨 [Wi-Fi] 設定 RGB 色彩: R={r}, G={g}, B={b}")

    def pick_color(self):
        self.stop_dual_effect()
        clr = colorchooser.askcolor(title="選取 RGB 色彩")
        if clr and clr[0]:
            r, g, b = int(clr[0][0]), int(clr[0][1]), int(clr[0][2])
            self.set_rgb_color(r, g, b)

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

                self.client.send_cmd(f"RGB,{self.rgb_r_pin_var.get()},{self.rgb_g_pin_var.get()},{self.rgb_b_pin_var.get()},{anode},{r1},{g1},{b1}")
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
            self.client.send_cmd(f"RGB,{self.rgb_r_pin_var.get()},{self.rgb_g_pin_var.get()},{self.rgb_b_pin_var.get()},{anode},0,0,0")
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
        self.client.send_cmd(f"MATRIX_ALL,{self.matrix_din_var.get()},{self.matrix_cs_var.get()},{self.matrix_clk_var.get()},{bytes_str}")

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
        self.client.send_cmd(f"MATRIX_CLEAR,{self.matrix_din_var.get()},{self.matrix_cs_var.get()},{self.matrix_clk_var.get()}")
        self.log("🧹 [Wi-Fi] 已清空 8x8 點陣")

    def play_marquee(self):
        txt = self.mq_entry.get().strip() or "HELLO"
        frames = text_to_matrix_frames(txt)
        self.log(f"📜 [Wi-Fi] 正在無線發送跑馬燈文字: 『{txt}』({len(frames)} 幀)")

        def worker():
            for f in frames:
                bytes_str = ",".join(str(b) for b in f)
                self.client.send_cmd(f"MATRIX_ALL,{self.matrix_din_var.get()},{self.matrix_cs_var.get()},{self.matrix_clk_var.get()},{bytes_str}")
                time.sleep(0.08)
        threading.Thread(target=worker, daemon=True).start()

    def play_animation(self, anim_name):
        frames = PRESET_ANIMATIONS.get(anim_name, [])
        self.log(f"🎬 [Wi-Fi] 播放點陣動畫: {anim_name}")

        def worker():
            for _ in range(3):
                for f in frames:
                    bytes_str = ",".join(str(b) for b in f)
                    self.client.send_cmd(f"MATRIX_ALL,{self.matrix_din_var.get()},{self.matrix_cs_var.get()},{self.matrix_clk_var.get()},{bytes_str}")
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
    def open_tunnel_dialog(self):
        """開啟 Cloudflare Tunnel 內網穿透控制視窗"""
        dlg = tk.Toplevel(self.root)
        dlg.title("🌐 Cloudflare Tunnel 外網穿透控制台")
        dlg.geometry("580x430")
        dlg.configure(bg=self.BG_TOP)
        dlg.transient(self.root)

        tk.Label(dlg, text="🌐 Cloudflare Tunnel 內網穿透 (外網遠端操控)", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(dlg, text="自動產生 trycloudflare.com 加密外網通道，手機 (4G/5G) 或任何遠端電腦點擊即可直接連線！", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 10))

        body = tk.Frame(dlg, bg=self.BG_CARD, padx=16, pady=14, bd=1, relief=tk.SOLID)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        # Port 設定
        row_p = tk.Frame(body, bg=self.BG_CARD)
        row_p.pack(fill=tk.X, pady=(0, 10))
        tk.Label(row_p, text="目標本地通訊埠 (Port):", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), width=20, anchor="w").pack(side=tk.LEFT)
        port_ent = tk.Entry(row_p, bg="#11111B", fg=self.TEXT_MAIN, insertbackground=self.TEXT_MAIN, font=("Consolas", 10), width=10, relief=tk.FLAT)
        port_ent.insert(0, str(getattr(self, "tunnel_port", 5000)))
        port_ent.pack(side=tk.LEFT, padx=6)

        # 狀態顯示
        row_s = tk.Frame(body, bg=self.BG_CARD)
        row_s.pack(fill=tk.X, pady=(0, 10))
        tk.Label(row_s, text="目前連線狀態:", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), width=20, anchor="w").pack(side=tk.LEFT)
        from cloudflare_tunnel import tunnel_manager, copy_to_clipboard
        cur_url = tunnel_manager.get_url()
        lbl_st = tk.Label(row_s, text="🟢 已連線" if cur_url else "⚪ 尚未啟動", bg=self.BG_CARD, fg=self.ACCENT_GREEN if cur_url else self.TEXT_MUTED, font=("Segoe UI", 9, "bold"))
        lbl_st.pack(side=tk.LEFT, padx=6)

        # 網址卡片
        box = tk.LabelFrame(body, text="🔗 trycloudflare.com 外網存取網址", bg="#181825", fg=self.ACCENT, font=("Segoe UI", 9, "bold"), bd=1, relief=tk.SOLID, padx=12, pady=10)
        box.pack(fill=tk.X, pady=(0, 12))

        lbl_url = tk.Label(box, text=cur_url or "尚未啟動，請點擊下方「🚀 啟動外網穿透」按鈕", bg="#181825", fg="#A6E3A1" if cur_url else "#F9E2AF", font=("Consolas", 10, "bold"), wraplength=500, justify="left")
        lbl_url.pack(anchor="w", pady=(0, 4))

        # 操作按鈕列
        act_row = tk.Frame(body, bg=self.BG_CARD)
        act_row.pack(fill=tk.X, pady=(6, 0))

        def do_copy():
            u = tunnel_manager.get_url()
            if u:
                copy_to_clipboard(u)
                messagebox.showinfo("已複製", "外網網址已複製至剪貼簿：\n" + str(u) + "\n\n請在手機或遠端瀏覽器開啟！")
            else:
                messagebox.showwarning("提示", "尚未建立外網連線，請先啟動穿透！")

        def do_open():
            u = tunnel_manager.get_url()
            if u:
                import webbrowser
                webbrowser.open(u)
            else:
                messagebox.showwarning("提示", "尚未建立外網連線，請先啟動穿透！")

        def do_start():
            try:
                p = int(port_ent.get().strip())
            except ValueError:
                messagebox.showwarning("錯誤", "通訊埠必須為數字 (如 5000)！")
                return
            self.tunnel_port = p
            lbl_st.configure(text="🟡 正在啟動並捕獲網址...", fg=self.ACCENT_YELLOW)
            lbl_url.configure(text="正在透過 Cloudflare 建立通道，約需 3~5 秒...", fg=self.ACCENT_YELLOW)

            def _bg():
                # 啟動內嵌 Web 遙控伺服器以接收外網請求
                self.web_server.start(port=p)
                ok = tunnel_manager.start(local_port=p)
                if ok:
                    u = tunnel_manager.wait_for_url(timeout=25.0)
                    if u and dlg.winfo_exists():
                        self.root.after(0, lambda: (
                            lbl_st.configure(text="🟢 穿透中", fg=self.ACCENT_GREEN),
                            lbl_url.configure(text=u, fg="#A6E3A1"),
                            self.btn_tunnel.configure(text="🌐 外網就緒", bg=self.ACCENT_GREEN)
                        ))
                    elif dlg.winfo_exists():
                        self.root.after(0, lambda: (
                            lbl_st.configure(text="❌ 逾時", fg=self.ACCENT_RED),
                            lbl_url.configure(text="獲取外網網址逾時，請檢查連線後重試", fg=self.ACCENT_RED)
                        ))

            threading.Thread(target=_bg, daemon=True).start()

        def do_stop():
            tunnel_manager.stop()
            self.web_server.stop()
            if dlg.winfo_exists():
                lbl_st.configure(text="⚪ 已停止", fg=self.TEXT_MUTED)
                lbl_url.configure(text="外網穿透已停止", fg=self.TEXT_MUTED)
                self.btn_tunnel.configure(text="🌐 外網穿透", bg="#89B4FA")

        btn_run = tk.Button(act_row, text="🚀 啟動外網穿透", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=10, pady=4, cursor="hand2", command=do_start)
        btn_run.pack(side=tk.LEFT, padx=(0, 6))

        btn_copy = tk.Button(act_row, text="📋 複製外網網址", bg="#45475A", fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), bd=0, padx=8, pady=4, cursor="hand2", command=do_copy)
        btn_copy.pack(side=tk.LEFT, padx=4)

        btn_browser = tk.Button(act_row, text="↗️ 在瀏覽器中開啟", bg="#313244", fg=self.TEXT_MAIN, font=("Segoe UI", 9), bd=0, padx=8, pady=4, cursor="hand2", command=do_open)
        btn_browser.pack(side=tk.LEFT, padx=4)

        btn_kill = tk.Button(act_row, text="⏹️ 停止", bg=self.ACCENT_RED, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=8, pady=4, cursor="hand2", command=do_stop)
        btn_kill.pack(side=tk.RIGHT)

    def open_flash_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("🛠️ 一鍵燒錄 Wi-Fi 韌體至 Arduino Uno")
        dlg.geometry("580x480")
        dlg.configure(bg=self.BG_TOP)
        dlg.transient(self.root)

        tk.Label(dlg, text="🛠️ 一鍵燒錄 Wi-Fi 韌體至 Arduino Uno", bg=self.BG_TOP, fg=self.ACCENT, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        tk.Label(dlg, text="在拔除 USB 線改用純 Wi-Fi 控制前，請先將 Wi-Fi 韌體燒錄至 Uno 晶片中：", bg=self.BG_TOP, fg=self.TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 8))

        tip_frame = tk.Frame(dlg, bg="#2A2218", padx=10, pady=8, bd=1, relief=tk.SOLID)
        tip_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(tip_frame, text="📌 Webduino Fly 燒錄小撇步 (必看)：\n擴充板的 Wi-Fi 晶片佔用 Uno 第 0/1 腳位。點擊燒錄後，請【按住擴充板上的 ESP RESET 鈕】\n或【暫時將擴充板拔起】約 3 秒完成燒錄，再放開/插回即可！", bg="#2A2218", fg=self.ACCENT_YELLOW, font=("Segoe UI", 8, "bold"), justify="left").pack(anchor="w")

        body = tk.Frame(dlg, bg=self.BG_CARD, padx=14, pady=12, bd=1, relief=tk.SOLID)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        # COM 埠選擇
        row0 = tk.Frame(body, bg=self.BG_CARD)
        row0.pack(fill=tk.X, pady=4)
        tk.Label(row0, text="COM 序列埠:", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), width=16, anchor="w").pack(side=tk.LEFT)
        import serial.tools.list_ports
        all_ports = serial.tools.list_ports.comports()
        ports = [p.device for p in all_ports]
        exact_uno = [p.device for p in all_ports if getattr(p, 'description', None) and "arduino" in str(p.description).lower()]
        sel_port = exact_uno[0] if exact_uno else (ports[0] if ports else "COM5")
        port_var = tk.StringVar(value=sel_port)
        combo = ttk.Combobox(row0, textvariable=port_var, values=ports, width=14)
        combo.pack(side=tk.LEFT, padx=6)

        # Wi-Fi SSID
        row1 = tk.Frame(body, bg=self.BG_CARD)
        row1.pack(fill=tk.X, pady=4)
        tk.Label(row1, text="Wi-Fi 名稱 (SSID):", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), width=16, anchor="w").pack(side=tk.LEFT)
        ssid_var = tk.StringVar(value="jupiter")
        ssid_combo = ttk.Combobox(row1, textvariable=ssid_var, width=18)
        ssid_combo.pack(side=tk.LEFT, padx=6)

        btn_scan_ap = tk.Button(row1, text="🔄 透過 USB 掃描 Wi-Fi AP", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 8, "bold"), bd=0, padx=8, pady=3, cursor="hand2")
        btn_scan_ap.pack(side=tk.LEFT, padx=4)

        # Wi-Fi 密碼
        row2 = tk.Frame(body, bg=self.BG_CARD)
        row2.pack(fill=tk.X, pady=4)
        tk.Label(row2, text="Wi-Fi 密碼 (Password):", bg=self.BG_CARD, fg=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), width=16, anchor="w").pack(side=tk.LEFT)
        pass_entry = tk.Entry(row2, bg="#11111B", fg=self.TEXT_MAIN, relief=tk.FLAT, font=("Segoe UI", 9), width=20, show="*")
        pass_entry.insert(0, "1019b1019b")
        pass_entry.pack(side=tk.LEFT, padx=6)

        lbl_flash_status = tk.Label(body, text="💡 已預先填入 Wi-Fi：jupiter，直接點擊下方「⚡ 開始編譯並燒錄」即可！", bg=self.BG_CARD, fg=self.ACCENT_GREEN, font=("Segoe UI", 8), justify="left")
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
                    try:
                        if not dlg.winfo_exists():
                            return
                        btn_scan_ap.configure(state="normal", text="🔄 透過 USB 掃描 Wi-Fi AP")
                        if found_ssids:
                            ssid_combo["values"] = found_ssids
                            ssid_combo.set(found_ssids[0])
                            lbl_flash_status.configure(text=f"🎉 成功掃描到 {len(found_ssids)} 個 Wi-Fi AP！請在下拉選單中選取您的 Wi-Fi。", fg=self.ACCENT_GREEN)
                        else:
                            lbl_flash_status.configure(text="⚠️ 未能從硬體回傳掃描清單，您可直接在上方輸入 Wi-Fi 名稱。", fg=self.ACCENT_YELLOW)
                            messagebox.showinfo("掃描結果", "未能自動獲取周遭 AP 清單。\n\n提示：您可直接在 Wi-Fi 名稱下拉框中手動輸入家裡的 Wi-Fi 名稱！")
                    except Exception:
                        pass

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

            def safe_status(text, fg):
                try:
                    if dlg.winfo_exists():
                        lbl_flash_status.configure(text=text, fg=fg)
                except Exception:
                    pass

            safe_status(f"⚙️ 正在寫入 Wi-Fi 設定並自動編譯燒錄至 {port}...", self.ACCENT)

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

                    # 先終止可能殘留的 avrdude 避免序列埠被鎖定
                    subprocess.run(["taskkill", "/F", "/IM", "avrdude.exe"], capture_output=True)

                    # 呼叫 Arduino CLI 編譯並燒錄
                    cmd = [
                        ARDUINO_CLI_PATH,
                        "compile",
                        "--fqbn", "arduino:avr:uno",
                        "--upload",
                        "-p", port,
                        WIFI_FIRMWARE_INO
                    ]
                    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
                    if p.returncode == 0:
                        def on_success():
                            safe_status("🎉 燒錄成功！板子正在連線 Wi-Fi，稍後即可拔除 USB 線！", self.ACCENT_GREEN)
                            messagebox.showinfo("燒錄成功", f"Wi-Fi 韌體已成功燒錄至 {port}！\n\nArduino Uno 現在會自動連線到您的 Wi-Fi。\n請留意 Webduino Fly 板上的紅燈熄滅代表連線成功，接著即可點擊「🔍 自動搜尋區網」進行無線操控！")
                        self.root.after(0, on_success)
                    else:
                        err_text = p.stderr or p.stdout or "未知錯誤"
                        def on_fail(msg=err_text):
                            safe_status("❌ 燒錄失敗，擴充板訊號可能干擾序列埠", self.ACCENT_RED)
                            messagebox.showerror(
                                "燒錄未成功",
                                f"Arduino-CLI 燒錄未成功。\n\n"
                                f"若為通訊逾時（stk500），這是 Webduino Fly 擴充板的 ESP8266 佔用 Pin 0/1 所致。\n"
                                f"請嘗試：\n"
                                f"1. 將 Webduino Fly 黑色擴充板垂直拔起（只留 Arduino Uno），再點擊燒錄（3 秒即可成功）！\n"
                                f"2. 燒錄成功後再將擴充板插回即可！\n\n"
                                f"詳細錯誤訊息：\n{msg[-260:]}"
                            )
                        self.root.after(0, on_fail)
                except subprocess.TimeoutExpired:
                    subprocess.run(["taskkill", "/F", "/IM", "avrdude.exe"], capture_output=True)
                    def on_timeout():
                        safe_status("⚠️ 燒錄超時（擴充板佔用 Pin 0/1 序列埠）", self.ACCENT_RED)
                        messagebox.showwarning(
                            "燒錄超時提示 (Webduino Fly 硬體特性)",
                            "燒錄通訊超時！\n\n"
                            "【原因說明】：\n"
                            "Webduino Fly 擴充板的 ESP8266 晶片佔用了 Uno 的序列埠（Pin 0/1），導致電腦燒錄訊號被擋住。\n\n"
                            "【最快解決方法（只需 3 秒，100% 成功）】：\n"
                            "1. 請將上面那片黑色的「Webduino Fly 擴充板」垂直輕輕拔起（只留下底下的 Arduino Uno 主板）。\n"
                            "2. 再次點擊「⚡ 開始編譯並燒錄」，只要 3 秒鐘即可 100% 燒錄成功！\n"
                            "3. 燒錄成功後，再把 Webduino Fly 擴充板插回 Uno 上，即可正常進行 Wi-Fi 全無線連線！"
                        )
                    self.root.after(0, on_timeout)
                except Exception as ex:
                    err_msg = str(ex)
                    def on_err(msg=err_msg):
                        safe_status(f"❌ 錯誤: {msg}", self.ACCENT_RED)
                        messagebox.showerror("例外錯誤", msg)
                    self.root.after(0, on_err)

            threading.Thread(target=flash_worker, daemon=True).start()

        btn_run_flash = tk.Button(dlg, text="⚡ 開始編譯並燒錄 Wi-Fi 韌體", bg=self.ACCENT, fg="#11111B", font=("Segoe UI", 9, "bold"), bd=0, padx=16, pady=6, cursor="hand2", command=start_flash)
        btn_run_flash.pack(side=tk.BOTTOM, pady=10)


def main():
    root = tk.Tk()
    app = WiFiControllerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()