# -*- coding: utf-8 -*-
"""
🐼 Arduino Block Studio (兒童視覺化積木程式設計環境 - mBlock 5 風格)
========================================================================
原生整合：
1. USB 串列埠自動偵測與雙向控制 (COM4: Arduino Uno / DWRITE, AWRITE, SERVO, RGB)
2. ESP-01 雙路 Wi-Fi 繼電器 (A0 01 01 A2 / 192.168.4.1)
3. 綠旗 🚩「一鍵執行」與 🛑「安全急停」
4. 即時 Python 代碼動態生成與終端除錯
5. 原生桌面視窗 (PyWebView) 與 瀏覽器雙模
"""

import os
import sys
import time
import socket
import threading
import webbrowser
import queue
from typing import Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import serial
import serial.tools.list_ports
import json
from flask import Flask, request, jsonify, send_from_directory
try:
    from ortools.sat.python import cp_model
    HAS_ORTOOLS = True
except ImportError:
    cp_model = None
    HAS_ORTOOLS = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
BLOCKLY_DIR = os.path.join(WEB_DIR, "blockly")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_hardware_config():
    defaults = {
        "m1_r_pin": "6",
        "m1_g_pin": "3",
        "m1_b_pin": "5",
        "m2_r_pin": "11",
        "m2_g_pin": "9",
        "m2_b_pin": "10",
        "common_anode": True,
        "servo_pin": "4",
        "relay1_pin": "13",
        "relay2_pin": "12",
        "matrix_din_pin": "12",
        "matrix_cs_pin": "8",
        "matrix_clk_pin": "7"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_hardware_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


hardware_config = load_hardware_config()

app = Flask(__name__, static_folder=None)

# ==========================================
# USB 串列埠管理器 (Arduino Serial Manager)
# ==========================================
class ArduinoSerialManager:
    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self.port: str = ""
        self.baudrate: int = 115200
        self.is_connected: bool = False
        self.lock = threading.Lock()
        self.log_queue = queue.Queue(maxsize=100)

    def log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        msg = f"[{ts}] {text}"
        print(f"[Serial] {msg}")
        try:
            self.log_queue.put_nowait(msg)
        except queue.Full:
            try:
                self.log_queue.get_nowait()
                self.log_queue.put_nowait(msg)
            except Exception:
                pass

    def list_ports(self):
        # 加入 3 秒快取，避免前端輪詢重複向 Windows 註冊表/設備管理員查詢造成卡頓
        now = time.time()
        if hasattr(self, "_ports_cache") and (now - getattr(self, "_ports_cache_time", 0)) < 3.0:
            return self._ports_cache

        result = []
        for p in serial.tools.list_ports.comports():
            desc = p.description or ""
            is_official = "arduino" in desc.lower() or p.vid == 0x2341
            is_ch340 = "ch340" in desc.lower() or p.vid == 0x1A86
            score = 3 if is_official else (2 if is_ch340 else 0)
            result.append({
                "port": p.device,
                "desc": f"{p.device}: {desc}",
                "is_arduino": is_official or is_ch340,
                "score": score
            })
        result.sort(key=lambda x: x["score"], reverse=True)
        self._ports_cache = result
        self._ports_cache_time = now
        return result

    def auto_connect(self):
        ports = self.list_ports()
        self.log(f"🔍 自動搜尋 Arduino 設備 (發現 {len(ports)} 個串列埠)...")
        # 1. 優先尋找能回覆 PONG 握手訊號的序列埠
        for p in ports:
            if p["is_arduino"]:
                self.log(f"嘗試握手 {p['desc']} ...")
                ok, _ = self.connect(p["port"], verify_pong=True)
                if ok:
                    self.log(f"🎯 成功鎖定並連線 Arduino 韌體: {p['port']}")
                    return True
        # 2. 若無回應 PONG，嘗試直接連線分數最高的 Arduino 埠
        for p in ports:
            if p["score"] >= 3:
                self.log(f"備用連線官方 Arduino 埠: {p['port']}")
                ok, _ = self.connect(p["port"], verify_pong=False)
                if ok:
                    return True
        self.log("⚠️ 未能自動偵測到 Arduino，可於介面手動選擇 COM 埠連線")
        return False

    def connect(self, port_name: str, baud: int = 115200, verify_pong: bool = False):
        self.disconnect()
        with self.lock:
            try:
                self.log(f"正在連線 USB 串列埠 {port_name} (波特率 {baud})...")
                s = serial.Serial(port_name, baud, timeout=1.2)
                time.sleep(1.8)  # 等待 Arduino 重置穩定
                s.reset_input_buffer()
                
                # 發送 PING 測試
                s.write(b"PING\n")
                resp = s.readline().decode("utf-8", errors="replace").strip()
                if "PONG" in resp:
                    self.log(f"✅ 成功與 Arduino 握手！韌體回應: {resp}")
                else:
                    if verify_pong:
                        s.close()
                        self.log(f"ℹ️ {port_name} 未回應 PONG ('{resp}')，切換下一個...")
                        return False, f"未回應 PONG ('{resp}')"
                    self.log(f"⚠️ 連線建立，握手回應: {resp}")

                self.ser = s
                self.port = port_name
                self.baudrate = baud
                self.is_connected = True
                return True, f"成功連線 {port_name}"
            except Exception as e:
                self.is_connected = False
                if self.ser:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None
                self.log(f"❌ 連線失敗: {e}")
                return False, str(e)

    def disconnect(self):
        with self.lock:
            self.is_connected = False
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                self.log("已安全中斷 USB 連線")

    def send_command(self, cmd: str) -> str:
        with self.lock:
            if not self.is_connected or not self.ser or not self.ser.is_open:
                return "ERR:NOT_CONNECTED"
            try:
                self.ser.write((cmd.strip() + "\n").encode("utf-8"))
                resp = self.ser.readline().decode("utf-8", errors="replace").strip()
                return resp
            except Exception as e:
                self.is_connected = False
                self.log(f"通訊中斷: {e}")
                return f"ERR:{e}"


arduino_serial = ArduinoSerialManager()

# ==========================================
# Wi-Fi 繼電器與執行器管理器
# ==========================================
runner_thread = None
stop_event = threading.Event()
relay_state = {1: False, 2: False}
wifi_relay_ip = "192.168.4.1"
wifi_relay_port = 8080

CMD_MAP = {
    (1, True): bytes.fromhex("A0 01 01 A2"),
    (1, False): bytes.fromhex("A0 01 00 A1"),
    (2, True): bytes.fromhex("A0 02 01 A3"),
    (2, False): bytes.fromhex("A0 02 00 A2"),
}


def send_wifi_relay(ch: int, state: bool):
    global relay_state
    cmd = CMD_MAP.get((ch, state))
    if not cmd:
        return False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        try:
            hostname = socket.gethostname()
            local_ips = socket.gethostbyname_ex(hostname)[2]
            prefix = ".".join(wifi_relay_ip.split(".")[:3])
            matched_ip = next((ip for ip in local_ips if ip.startswith(prefix)), None)
            if matched_ip:
                s.bind((matched_ip, 0))
        except Exception:
            pass
        s.connect((wifi_relay_ip, wifi_relay_port))
        s.close()
        relay_state[ch] = state
        arduino_serial.log(f"⚡ [Wi-Fi 繼電器] 第 {ch} 路 -> {'開啟 (ON)' if state else '關閉 (OFF)'}")
        return True
    except Exception as e:
        arduino_serial.log(f"⚠️ [Wi-Fi 繼電器] 離線或無法連線 ({e})")
        return False


def interruptible_sleep(seconds: float):
    steps = int(seconds * 20)
    for _ in range(steps):
        if stop_event.is_set():
            break
        time.sleep(0.05)


# ==========================================
# Web API 路由
# ==========================================

@app.route("/healthz")
@app.route("/api/ping")
def healthz():
    return jsonify({
        "status": "healthy",
        "app": "ArduinoBlockStudio",
        "framework": "Flask+Waitress",
        "serial_connected": arduino_serial.is_connected,
        "port": arduino_serial.port
    })


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "blockly_studio.html")


@app.route("/sophia_logo.svg")
def serve_sophia_logo():
    return send_from_directory(WEB_DIR, "sophia_logo.svg")


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(WEB_DIR, filename)


@app.route("/static/blockly/<path:filename>")
def serve_blockly(filename):
    return send_from_directory(BLOCKLY_DIR, filename)


@app.route("/api/serial/ports", methods=["GET"])
def api_serial_ports():
    return jsonify({
        "ports": arduino_serial.list_ports(),
        "connected": arduino_serial.is_connected,
        "current_port": arduino_serial.port
    })


@app.route("/api/serial/connect", methods=["POST"])
def api_serial_connect():
    data = request.get_json(silent=True) or {}
    port_name = data.get("port", "")
    if not port_name:
        return jsonify({"ok": False, "error": "未指定 COM 埠"}), 400
    ok, msg = arduino_serial.connect(port_name, verify_pong=False)
    return jsonify({"ok": ok, "message": msg, "connected": arduino_serial.is_connected})
@app.route("/api/serial/disconnect", methods=["POST"])
def api_serial_disconnect():
    arduino_serial.disconnect()
    return jsonify({"ok": True, "connected": False})

@app.route("/api/serial/send", methods=["POST"])
def api_serial_send():
    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd", "")
    if not cmd:
        return jsonify({"ok": False, "error": "未提供指令內容"}), 400
    if not arduino_serial.is_connected:
        return jsonify({"ok": False, "error": "USB 尚未連線"}), 400
    resp = arduino_serial.send_command(cmd)
    return jsonify({"ok": True, "resp": resp})


execution_state = {
    "running": False,
    "line": 0,
    "block_id": None
}

hardware_command_queue = queue.Queue(maxsize=500)

def dispatch_hardware_command(cmd: str):
    """將硬體控制指令統一分發至：
    1. 本地實體 serial (若後端有連線 COM 埠)
    2. hardware_command_queue (供前端 Web Serial 瀏覽器直連時提取寫入 USB)
    """
    if arduino_serial.is_connected:
        arduino_serial.send_command(cmd)
    try:
        hardware_command_queue.put_nowait(cmd)
    except queue.Full:
        try:
            hardware_command_queue.get_nowait()
            hardware_command_queue.put_nowait(cmd)
        except Exception:
            pass


def make_trace_func(stop_evt, state):
    def trace_func(frame, event, arg):
        if stop_evt.is_set():
            raise KeyboardInterrupt("Stopped by user")
        if event == "line":
            if frame.f_code.co_filename == "<block_code>":
                state["line"] = frame.f_lineno
        return trace_func
    return trace_func


@app.route("/api/status", methods=["GET"])
def api_get_status():
    logs = []
    while not arduino_serial.log_queue.empty():
        logs.append(arduino_serial.log_queue.get_nowait())

    cmds = []
    while not hardware_command_queue.empty():
        try:
            cmds.append(hardware_command_queue.get_nowait())
        except Exception:
            break

    return jsonify({
        "running": execution_state["running"],
        "line": execution_state["line"],
        "block_id": execution_state["block_id"],
        "logs": logs,
        "commands": cmds,
        "ports": arduino_serial.list_ports(),
        "connected": arduino_serial.is_connected,
        "current_port": arduino_serial.port
    })


@app.route("/api/logs", methods=["GET"])
def api_get_logs():
    logs = []
    while not arduino_serial.log_queue.empty():
        logs.append(arduino_serial.log_queue.get_nowait())
    return jsonify({"logs": logs})


@app.route("/api/run_blocks", methods=["POST"])
def api_run_blocks():
    global runner_thread, stop_event
    data = request.get_json(silent=True) or {}
    code_text = data.get("code", "")

    if not code_text.strip():
        return jsonify({"ok": False, "error": "代碼為空"}), 400

    stop_event.set()
    if runner_thread and runner_thread.is_alive():
        runner_thread.join(timeout=1.0)
    stop_event.clear()

    def execute_environment():
        def set_relay(channel, state_str):
            if stop_event.is_set():
                return
            st = str(state_str).upper() in ["ON", "TRUE", "1"]
            # 優先透過 Arduino USB 腳位控制板載輸出 (Pin 13 & Pin 12)
            if arduino_serial.is_connected:
                pin = 13 if int(channel) == 1 else 12
                resp = arduino_serial.send_command(f"DWRITE,{pin},{1 if st else 0}")
                arduino_serial.log(f"💡 [Arduino 腳位 {pin}] -> {'開啟 (HIGH)' if st else '關閉 (LOW)'} | 回應: {resp}")
            # 同步發送到 Wi-Fi 繼電器 (若有在 AP 範圍內)
            send_wifi_relay(int(channel), st)

        def pulse_relay(channel, duration):
            if stop_event.is_set():
                return
            set_relay(channel, "ON")
            interruptible_sleep(float(duration))
            set_relay(channel, "OFF")

        def set_all_relays(state_str):
            if stop_event.is_set():
                return
            st = str(state_str).upper() in ["ON", "TRUE", "1"]
            if arduino_serial.is_connected:
                arduino_serial.send_command(f"DWRITE,13,{1 if st else 0}")
                arduino_serial.send_command(f"DWRITE,12,{1 if st else 0}")
            send_wifi_relay(1, st)
            time.sleep(0.05)
            send_wifi_relay(2, st)

        def invert_relays():
            if stop_event.is_set():
                return
            s1 = not relay_state.get(1, False)
            s2 = not relay_state.get(2, False)
            if arduino_serial.is_connected:
                arduino_serial.send_command(f"DWRITE,13,{1 if s1 else 0}")
                arduino_serial.send_command(f"DWRITE,12,{1 if s2 else 0}")
            send_wifi_relay(1, s1)
            time.sleep(0.05)
            send_wifi_relay(2, s2)

        def sleep(sec):
            interruptible_sleep(float(sec))

        def arduino_write_digital(pin, val):
            if stop_event.is_set():
                return
            v = 1 if str(val).upper() in ["HIGH", "1", "TRUE"] else 0
            dispatch_hardware_command(f"DWRITE,{pin},{v}")
            arduino_serial.log(f"💡 [數位輸出] 腳位 {pin} -> {'高電位 (HIGH)' if v else '低電位 (LOW)'}")

        def arduino_write_pwm(pin, val):
            if stop_event.is_set():
                return
            v = max(0, min(255, int(val)))
            dispatch_hardware_command(f"AWRITE,{pin},{v}")
            arduino_serial.log(f"💡 [PWM 輸出] 腳位 {pin} -> 數值 {v}")

        def arduino_set_servo(pin, angle):
            if stop_event.is_set():
                return
            a = max(0, min(180, int(angle)))
            dispatch_hardware_command(f"SERVO,{pin},{a}")
            arduino_serial.log(f"🦾 [舵機角度] 腳位 {pin} -> 角度 {a}°")

        def set_dual_rgb(r1, g1, b1, r2=None, g2=None, b2=None):
            if r2 is None:
                r2, g2, b2 = r1, g1, b1
            anode_int = 1 if hardware_config.get("common_anode", True) else 0
            m1_r = hardware_config.get("m1_r_pin", "6")
            m1_g = hardware_config.get("m1_g_pin", "3")
            m1_b = hardware_config.get("m1_b_pin", "5")
            m2_r = hardware_config.get("m2_r_pin", "11")
            m2_g = hardware_config.get("m2_g_pin", "9")
            m2_b = hardware_config.get("m2_b_pin", "10")
            dispatch_hardware_command(f"RGB,{m1_r},{m1_g},{m1_b},{anode_int},{r1},{g1},{b1}")
            dispatch_hardware_command(f"RGB,{m2_r},{m2_g},{m2_b},{anode_int},{r2},{g2},{b2}")

        def play_rgb_effect(effect_name):
            if stop_event.is_set():
                return
            arduino_serial.log(f"✨ 播放炫彩燈效: {effect_name} (驅動 RGB 1[6,3,5], RGB 2[11,9,10] & 板載 Pin 13)")
            import random
            if effect_name == "police_strobe":
                # 警車雙閃燈效：左紅右藍交替爆閃
                for _ in range(8):
                    if stop_event.is_set(): break
                    for _ in range(3):
                        if stop_event.is_set(): break
                        arduino_write_digital(13, 1)
                        set_dual_rgb(255, 0, 0, 0, 0, 0)
                        interruptible_sleep(0.06)
                        arduino_write_digital(13, 0)
                        set_dual_rgb(0, 0, 0, 0, 0, 0)
                        interruptible_sleep(0.06)
                    for _ in range(3):
                        if stop_event.is_set(): break
                        arduino_write_digital(12, 1)
                        set_dual_rgb(0, 0, 0, 0, 0, 255)
                        interruptible_sleep(0.06)
                        arduino_write_digital(12, 0)
                        set_dual_rgb(0, 0, 0, 0, 0, 0)
                        interruptible_sleep(0.06)
            elif effect_name == "fire_flicker":
                # 壁爐跳火燈效 (橙黃隨機抖動)
                for _ in range(30):
                    if stop_event.is_set(): break
                    flicker = random.randint(160, 255)
                    g_val = max(0, int(flicker * 0.35 + random.randint(-15, 15)))
                    set_dual_rgb(flicker, g_val, 0)
                    arduino_write_pwm(13, int(flicker * 0.8))
                    interruptible_sleep(random.uniform(0.04, 0.12))
                set_dual_rgb(0, 0, 0)
                arduino_write_digital(13, 0)
            else:
                # 預設極光/彩虹漸變
                for h in range(0, 360, 20):
                    if stop_event.is_set(): break
                    # 簡易 HSV 轉 RGB
                    c = 255
                    x = int(c * (1 - abs((h / 60) % 2 - 1)))
                    if h < 60: r, g, b = c, x, 0
                    elif h < 120: r, g, b = x, c, 0
                    elif h < 180: r, g, b = 0, c, x
                    elif h < 240: r, g, b = 0, x, c
                    elif h < 300: r, g, b = x, 0, c
                    else: r, g, b = c, 0, x
                    set_dual_rgb(r, g, b)
                    arduino_write_pwm(13, max(r, g, b))
                    interruptible_sleep(0.08)
                set_dual_rgb(0, 0, 0)
                arduino_write_digital(13, 0)

        def set_rgb_color(target, r, g, b):
            if stop_event.is_set():
                return
            r_val = max(0, min(255, int(r)))
            g_val = max(0, min(255, int(g)))
            b_val = max(0, min(255, int(b)))
            anode_int = 1 if hardware_config.get("common_anode", True) else 0

            m1_r = hardware_config.get("m1_r_pin", "6")
            m1_g = hardware_config.get("m1_g_pin", "3")
            m1_b = hardware_config.get("m1_b_pin", "5")
            m2_r = hardware_config.get("m2_r_pin", "11")
            m2_g = hardware_config.get("m2_g_pin", "9")
            m2_b = hardware_config.get("m2_b_pin", "10")

            if str(target) == "1":
                dispatch_hardware_command(f"RGB,{m1_r},{m1_g},{m1_b},{anode_int},{r_val},{g_val},{b_val}")
            elif str(target) == "2":
                dispatch_hardware_command(f"RGB,{m2_r},{m2_g},{m2_b},{anode_int},{r_val},{g_val},{b_val}")
            else:
                dispatch_hardware_command(f"RGB,{m1_r},{m1_g},{m1_b},{anode_int},{r_val},{g_val},{b_val}")
                dispatch_hardware_command(f"RGB,{m2_r},{m2_g},{m2_b},{anode_int},{r_val},{g_val},{b_val}")
            arduino_serial.log(f"🎨 [RGB 顏色] {target} -> R:{r_val} G:{g_val} B:{b_val}")

        def set_custom_rgb(r_pin, g_pin, b_pin, is_anode, r, g, b):
            if stop_event.is_set():
                return
            r_val = max(0, min(255, int(r)))
            g_val = max(0, min(255, int(g)))
            b_val = max(0, min(255, int(b)))
            anode_val = 1 if str(is_anode) in ["1", "true", "True", "ANODE"] else 0
            dispatch_hardware_command(f"RGB,{r_pin},{g_pin},{b_pin},{anode_val},{r_val},{g_val},{b_val}")
            arduino_serial.log(f"🎨 [自訂 RGB] 腳位 R:{r_pin} G:{g_pin} B:{b_pin} ({'共陽極' if anode_val else '共陰極'}) -> R:{r_val} G:{g_val} B:{b_val}")

        def matrix_clear():
            if stop_event.is_set():
                return
            din = hardware_config.get("matrix_din_pin", "12")
            cs = hardware_config.get("matrix_cs_pin", "8")
            clk = hardware_config.get("matrix_clk_pin", "7")
            dispatch_hardware_command(f"MATRIX_CLEAR,{din},{cs},{clk}")
            arduino_serial.log("📟 [8x8點陣] 清除畫面")

        def matrix_show_bitmap(b0, b1, b2, b3, b4, b5, b6, b7):
            if stop_event.is_set():
                return
            din = hardware_config.get("matrix_din_pin", "12")
            cs = hardware_config.get("matrix_cs_pin", "8")
            clk = hardware_config.get("matrix_clk_pin", "7")
            dispatch_hardware_command(f"MATRIX_ALL,{din},{cs},{clk},{b0},{b1},{b2},{b3},{b4},{b5},{b6},{b7}")

        def matrix_show_icon(icon_name):
            if stop_event.is_set():
                return
            icon_key = str(icon_name).lower()
            bm = None
            for k, v in PRESET_MATRIX.items():
                if icon_key in k.lower():
                    bm = v
                    break
            if not bm:
                bm = PRESET_MATRIX.get("❤️ 愛心", [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18])
            matrix_show_bitmap(*bm)
            arduino_serial.log(f"📟 [8x8點陣] 顯示圖案: {icon_name}")

        def matrix_scroll_text(text, speed=0.08):
            if stop_event.is_set():
                return
            frames = text_to_matrix_frames(str(text), padding=True)
            arduino_serial.log(f"📟 [8x8點陣] 滾動字幕: '{text}' (共 {len(frames)} 影格)")
            for frame in frames:
                if stop_event.is_set():
                    break
                matrix_show_bitmap(*frame)
                interruptible_sleep(float(speed))

        matrix_pixel_buf = [0] * 8

        def matrix_play_animation(anim_name, repeat=1, speed=0.1):
            if stop_event.is_set():
                return
            anim_key = str(anim_name).lower()
            frames = None
            for k, v in PRESET_ANIMATIONS.items():
                if anim_key in k.lower():
                    frames = v
                    break
            if not frames:
                # 模糊比對常用英文代號
                aliases = {
                    "heartbeat": "💓 心跳搏動動畫",
                    "heart": "💓 心跳搏動動畫",
                    "rocket": "🚀 火箭升空動畫",
                    "wave": "🌊 像素海浪動畫",
                    "radar": "⏳ 旋轉雷達動畫",
                    "pacman": "ᗧ 吃豆人動態",
                    "alien": "👾 外星人跳舞",
                    "rain": "🌧️ 矩陣數位雨",
                    "ripple": "🌀 同心方塊波紋",
                    "flame": "🔥 像素跳動火焰",
                    "hourglass": "⏳ 翻轉沙漏",
                }
                actual_key = aliases.get(anim_key, "💓 心跳搏動動畫")
                frames = PRESET_ANIMATIONS.get(actual_key, [])
            
            arduino_serial.log(f"📟 [8x8點陣] 播放動態特效: {anim_name} (重複 {repeat} 次, 每幀 {speed}s)")
            for r in range(max(1, int(repeat))):
                if stop_event.is_set():
                    break
                for frame in frames:
                    if stop_event.is_set():
                        break
                    matrix_show_bitmap(*frame)
                    interruptible_sleep(float(speed))

        def matrix_set_pixel(x, y, state=True):
            if stop_event.is_set():
                return
            col = max(0, min(7, int(x)))
            row = max(0, min(7, int(y)))
            st = str(state).lower() in ["1", "true", "on", "yes"]
            if st:
                matrix_pixel_buf[row] |= (1 << (7 - col))
            else:
                matrix_pixel_buf[row] &= ~(1 << (7 - col))
            matrix_show_bitmap(*matrix_pixel_buf)

        def __step__(block_id):
            if stop_event.is_set():
                raise KeyboardInterrupt("Stopped by user")
            clean_id = str(block_id).strip().strip("'\"")
            execution_state["block_id"] = clean_id

        safe_globals = {
            "__step__": __step__,
            "set_relay": set_relay,
            "pulse_relay": pulse_relay,
            "set_all_relays": set_all_relays,
            "invert_relays": invert_relays,
            "sleep": sleep,
            "arduino_write_digital": arduino_write_digital,
            "arduino_write_pwm": arduino_write_pwm,
            "arduino_set_servo": arduino_set_servo,
            "set_rgb_color": set_rgb_color,
            "set_custom_rgb": set_custom_rgb,
            "play_rgb_effect": play_rgb_effect,
            "matrix_clear": matrix_clear,
            "matrix_show_bitmap": matrix_show_bitmap,
            "matrix_show_icon": matrix_show_icon,
            "matrix_scroll_text": matrix_scroll_text,
            "matrix_play_animation": matrix_play_animation,
            "matrix_set_pixel": matrix_set_pixel,
            "time": time,
            "True": True,
            "False": False,
        }

        try:
            compiled_code = compile(code_text, "<block_code>", "exec")
            execution_state["running"] = True
            execution_state["line"] = 1
            tracer = make_trace_func(stop_event, execution_state)
            sys.settrace(tracer)
            arduino_serial.log("🚩 【綠旗啟動】開始執行積木代碼...")
            exec(compiled_code, safe_globals)
            arduino_serial.log("🏁 程式順利執行完畢！")
        except KeyboardInterrupt:
            arduino_serial.log("🛑 程式已被使用者中止。")
        except Exception as err:
            arduino_serial.log(f"❌ 執行中斷或異常: {err}")
        finally:
            sys.settrace(None)
            execution_state["running"] = False
            execution_state["line"] = 0

    runner_thread = threading.Thread(target=execute_environment, daemon=True)
    runner_thread.start()
    return jsonify({"ok": True})


@app.route("/api/stop_blocks", methods=["POST"])
def api_stop_blocks():
    global stop_event, execution_state
    stop_event.set()
    execution_state["running"] = False
    execution_state["line"] = 0
    execution_state["block_id"] = None
    send_wifi_relay(1, False)
    time.sleep(0.05)
    send_wifi_relay(2, False)
    anode_int = 1 if hardware_config.get("common_anode", True) else 0
    m1_r = hardware_config.get("m1_r_pin", "6")
    m1_g = hardware_config.get("m1_g_pin", "3")
    m1_b = hardware_config.get("m1_b_pin", "5")
    m2_r = hardware_config.get("m2_r_pin", "11")
    m2_g = hardware_config.get("m2_g_pin", "9")
    m2_b = hardware_config.get("m2_b_pin", "10")
    dispatch_hardware_command(f"RGB,{m1_r},{m1_g},{m1_b},{anode_int},0,0,0")
    dispatch_hardware_command(f"RGB,{m2_r},{m2_g},{m2_b},{anode_int},0,0,0")
    dispatch_hardware_command("DWRITE,13,0")
    if arduino_serial.is_connected:
        arduino_serial.send_command("STOP")
    arduino_serial.log("🛑 程式已停止，RGB 與外設已安全歸位熄滅。")
    return jsonify({"ok": True})


# ==========================================
# Google OR-Tools CP-SAT 智慧燈光特效排程引擎
# ==========================================

CPSAT_EFFECT_CATALOG = [
    {
        "id": "rainbow",
        "name": "🌈 雙燈七彩虹霓流光",
        "min_sec": 4,
        "max_sec": 16,
        "power": 7,
        "excitement": 8,
        "is_strobe": False,
        "styles": {"party": 9, "relax": 4, "cyberpunk": 7, "police": 2, "balanced": 8}
    },
    {
        "id": "police",
        "name": "🚨 警車雙燈爆閃警笛",
        "min_sec": 3,
        "max_sec": 8,
        "power": 6,
        "excitement": 10,
        "is_strobe": True,
        "styles": {"party": 8, "relax": 0, "cyberpunk": 6, "police": 10, "balanced": 5}
    },
    {
        "id": "complementary",
        "name": "☯ 雙燈互補強烈對撞",
        "min_sec": 4,
        "max_sec": 14,
        "power": 7,
        "excitement": 8,
        "is_strobe": False,
        "styles": {"party": 7, "relax": 5, "cyberpunk": 9, "police": 3, "balanced": 8}
    },
    {
        "id": "heartbeat",
        "name": "💓 雙燈深情心跳脈衝",
        "min_sec": 3,
        "max_sec": 12,
        "power": 4,
        "excitement": 6,
        "is_strobe": False,
        "styles": {"party": 3, "relax": 9, "cyberpunk": 5, "police": 1, "balanced": 6}
    },
    {
        "id": "cyberpunk",
        "name": "🛸 賽博龐克霓虹",
        "min_sec": 4,
        "max_sec": 14,
        "power": 8,
        "excitement": 9,
        "is_strobe": False,
        "styles": {"party": 8, "relax": 3, "cyberpunk": 10, "police": 4, "balanced": 8}
    },
    {
        "id": "thunder",
        "name": "⚡ 雷雨暴風閃電",
        "min_sec": 3,
        "max_sec": 8,
        "power": 9,
        "excitement": 10,
        "is_strobe": True,
        "styles": {"party": 8, "relax": 1, "cyberpunk": 8, "police": 5, "balanced": 5}
    },
    {
        "id": "aurora",
        "name": "🌌 歐若拉極光流轉",
        "min_sec": 4,
        "max_sec": 16,
        "power": 5,
        "excitement": 6,
        "is_strobe": False,
        "styles": {"party": 4, "relax": 10, "cyberpunk": 7, "police": 1, "balanced": 8}
    },
    {
        "id": "disco",
        "name": "🪩 迪斯可狂歡舞會",
        "min_sec": 3,
        "max_sec": 12,
        "power": 8,
        "excitement": 9,
        "is_strobe": False,
        "styles": {"party": 10, "relax": 1, "cyberpunk": 7, "police": 3, "balanced": 7}
    },
    {
        "id": "amber",
        "name": "🚑 救護車琥珀警示",
        "min_sec": 3,
        "max_sec": 8,
        "power": 6,
        "excitement": 9,
        "is_strobe": True,
        "styles": {"party": 5, "relax": 0, "cyberpunk": 4, "police": 10, "balanced": 4}
    },
    {
        "id": "fire",
        "name": "🔥 壁爐跳火燭光",
        "min_sec": 3,
        "max_sec": 12,
        "power": 5,
        "excitement": 5,
        "is_strobe": False,
        "styles": {"party": 2, "relax": 10, "cyberpunk": 3, "police": 1, "balanced": 7}
    }
]


def solve_lightshow_with_cpsat(style="balanced", target_sec=30, max_power_rate=8):
    """
    使用 Google OR-Tools CP-SAT (ortools.sat.python.cp_model) 求解器進行多約束最佳化：
    1. 總時長之和嚴格守恆 (Exact Duration Balance)
    2. 兒童護眼爆閃上限約束 (Strobe Cap <= 25%)
    3. 硬體功率安全負載約束 (Power Load Integral Constraint)
    4. 特效風格滿意度目標函數最大化 (Objective Function Maximization)
    """
    if not HAS_ORTOOLS:
        return None, "伺服器環境尚未安裝 ortools (請執行 pip install ortools)"

    model = cp_model.CpModel()
    candidates = [e for e in CPSAT_EFFECT_CATALOG if e["styles"].get(style, 5) > 0]
    n = len(candidates)

    dur_vars = []
    active_vars = []

    for e in candidates:
        d_var = model.NewIntVar(0, e["max_sec"], f"dur_{e['id']}")
        a_var = model.NewBoolVar(f"act_{e['id']}")

        model.Add(d_var >= e["min_sec"]).OnlyEnforceIf(a_var)
        model.Add(d_var == 0).OnlyEnforceIf(a_var.Not())

        dur_vars.append(d_var)
        active_vars.append(a_var)

    # 約束 1: 總時長嚴格相等
    model.Add(sum(dur_vars) == target_sec)

    # 約束 2: 演出的特效段數多樣性 (3 到 5 段)
    model.Add(sum(active_vars) >= min(3, n))
    model.Add(sum(active_vars) <= min(5, n))

    # 約束 3: 功率上限約束
    total_power = sum(dur_vars[i] * candidates[i]["power"] for i in range(n))
    model.Add(total_power <= target_sec * max_power_rate)

    # 約束 4: 護眼限制 (高頻爆閃總時長 <= 總時長的 25%)
    strobe_durs = [dur_vars[i] for i, e in enumerate(candidates) if e.get("is_strobe")]
    if strobe_durs:
        model.Add(sum(strobe_durs) <= int(target_sec * 0.25))

    # 目標函數：最大化風格偏好加權分 + 多樣性獎勵
    objectives = []
    for i, e in enumerate(candidates):
        w = e["styles"].get(style, 5)
        objectives.append(dur_vars[i] * w + active_vars[i] * 6)

    model.Maximize(sum(objectives))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, "CP-SAT 無可行解"

    result_segments = []
    for i, e in enumerate(candidates):
        val = solver.Value(dur_vars[i])
        if val > 0:
            result_segments.append({
                "id": e["id"],
                "name": e["name"],
                "duration": val,
                "power": e["power"]
            })

    return {
        "status": solver.StatusName(status),
        "score": solver.ObjectiveValue(),
        "target_sec": target_sec,
        "style": style,
        "segments": result_segments
    }, None


def build_blockly_xml_from_schedule(segments):
    """根據 CP-SAT 最優排程段落，動態生成完全展開的 Blockly 原始積木 XML 樹"""
    block_snippets = []
    for seg in segments:
        s_id = seg["id"]
        sec = seg["duration"]
        if s_id == "rainbow":
            step = round(sec / 7.0, 2)
            colors = [(255, 0, 0), (255, 128, 0), (255, 230, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (180, 0, 255)]
            for r, g, b in colors:
                block_snippets.append(f"""
                <block type="arduino_rgb_color">
                  <field name="TARGET">ALL</field>
                  <value name="R"><shadow type="math_number"><field name="NUM">{r}</field></shadow></value>
                  <value name="G"><shadow type="math_number"><field name="NUM">{g}</field></shadow></value>
                  <value name="B"><shadow type="math_number"><field name="NUM">{b}</field></shadow></value>
                  <next>
                    <block type="control_wait">
                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">{step}</field></shadow></value>
                      <next>__NEXT__</next>
                    </block>
                  </next>
                </block>""")
        elif s_id == "police":
            repeats = max(2, int(sec / 1.2))
            block_snippets.append(f"""
            <block type="controls_repeat_ext">
              <value name="TIMES"><shadow type="math_number"><field name="NUM">{repeats}</field></shadow></value>
              <statement name="DO">
                <block type="arduino_rgb_color">
                  <field name="TARGET">1</field>
                  <value name="R"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
                  <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                  <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                  <next>
                    <block type="arduino_rgb_color">
                      <field name="TARGET">2</field>
                      <value name="R"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                      <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                      <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                      <next>
                        <block type="control_wait">
                          <value name="SECONDS"><shadow type="math_number"><field name="NUM">0.08</field></shadow></value>
                          <next>
                            <block type="arduino_rgb_color">
                              <field name="TARGET">1</field>
                              <value name="R"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                              <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                              <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                              <next>
                                <block type="arduino_rgb_color">
                                  <field name="TARGET">2</field>
                                  <value name="R"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                                  <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                                  <value name="B"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
                                  <next>
                                    <block type="control_wait">
                                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">0.08</field></shadow></value>
                                    </block>
                                  </next>
                                </block>
                              </next>
                            </block>
                          </next>
                        </block>
                      </next>
                    </block>
                  </next>
                </block>
              </statement>
              <next>__NEXT__</next>
            </block>""")
        elif s_id == "aurora":
            step = round(sec / 4.0, 2)
            colors = [(0, 255, 120), (0, 160, 255), (140, 0, 255), (0, 230, 180)]
            for r, g, b in colors:
                block_snippets.append(f"""
                <block type="arduino_rgb_color">
                  <field name="TARGET">ALL</field>
                  <value name="R"><shadow type="math_number"><field name="NUM">{r}</field></shadow></value>
                  <value name="G"><shadow type="math_number"><field name="NUM">{g}</field></shadow></value>
                  <value name="B"><shadow type="math_number"><field name="NUM">{b}</field></shadow></value>
                  <next>
                    <block type="control_wait">
                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">{step}</field></shadow></value>
                      <next>__NEXT__</next>
                    </block>
                  </next>
                </block>""")
        elif s_id == "cyberpunk":
            step = round(sec / 3.0, 2)
            block_snippets.append(f"""
            <block type="arduino_rgb_color">
              <field name="TARGET">1</field>
              <value name="R"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
              <value name="G"><shadow type="math_number"><field name="NUM">20</field></shadow></value>
              <value name="B"><shadow type="math_number"><field name="NUM">147</field></shadow></value>
              <next>
                <block type="arduino_rgb_color">
                  <field name="TARGET">2</field>
                  <value name="R"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                  <value name="G"><shadow type="math_number"><field name="NUM">240</field></shadow></value>
                  <value name="B"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
                  <next>
                    <block type="control_wait">
                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">{step}</field></shadow></value>
                      <next>
                        <block type="arduino_rgb_color">
                          <field name="TARGET">ALL</field>
                          <value name="R"><shadow type="math_number"><field name="NUM">160</field></shadow></value>
                          <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                          <value name="B"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
                          <next>
                            <block type="control_wait">
                              <value name="SECONDS"><shadow type="math_number"><field name="NUM">{step}</field></shadow></value>
                              <next>__NEXT__</next>
                            </block>
                          </next>
                        </block>
                      </next>
                    </block>
                  </next>
                </block>
              </next>
            </block>""")
        elif s_id == "heartbeat":
            repeats = max(2, int(sec / 1.0))
            block_snippets.append(f"""
            <block type="controls_repeat_ext">
              <value name="TIMES"><shadow type="math_number"><field name="NUM">{repeats}</field></shadow></value>
              <statement name="DO">
                <block type="arduino_rgb_color">
                  <field name="TARGET">ALL</field>
                  <value name="R"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
                  <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                  <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                  <next>
                    <block type="control_wait">
                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">0.1</field></shadow></value>
                      <next>
                        <block type="arduino_rgb_color">
                          <field name="TARGET">ALL</field>
                          <value name="R"><shadow type="math_number"><field name="NUM">200</field></shadow></value>
                          <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                          <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                          <next>
                            <block type="control_wait">
                              <value name="SECONDS"><shadow type="math_number"><field name="NUM">0.15</field></shadow></value>
                              <next>
                                <block type="arduino_rgb_color">
                                  <field name="TARGET">ALL</field>
                                  <value name="R"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                                  <value name="G"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                                  <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
                                  <next>
                                    <block type="control_wait">
                                      <value name="SECONDS"><shadow type="math_number"><field name="NUM">0.6</field></shadow></value>
                                    </block>
                                  </next>
                                </block>
                              </next>
                            </block>
                          </next>
                        </block>
                      </next>
                    </block>
                  </next>
                </block>
              </statement>
              <next>__NEXT__</next>
            </block>""")
        else:
            step = round(sec / 2.0, 2)
            block_snippets.append(f"""
            <block type="arduino_rgb_color">
              <field name="TARGET">ALL</field>
              <value name="R"><shadow type="math_number"><field name="NUM">255</field></shadow></value>
              <value name="G"><shadow type="math_number"><field name="NUM">160</field></shadow></value>
              <value name="B"><shadow type="math_number"><field name="NUM">0</field></shadow></value>
              <next>
                <block type="control_wait">
                  <value name="SECONDS"><shadow type="math_number"><field name="NUM">{step}</field></shadow></value>
                  <next>__NEXT__</next>
                </block>
              </next>
            </block>""")

    # 串聯所有積木節點 (替換 __NEXT__)
    chain = ""
    for snip in reversed(block_snippets):
        if not chain:
            chain = snip.replace("<next>__NEXT__</next>", "")
        else:
            chain = snip.replace("__NEXT__", chain)

    xml = f"""<xml xmlns="https://developers.google.com/blockly/xml">
      <block type="event_when_flag_clicked" x="60" y="40">
        <next>
          <block type="control_forever">
            <statement name="DO">
              {chain}
            </statement>
          </block>
        </next>
      </block>
    </xml>"""
    return xml


@app.route("/api/cpsat/optimize", methods=["POST"])
def api_cpsat_optimize():
    data = request.get_json(silent=True) or {}
    style = data.get("style", "balanced")
    total_sec = max(10, min(120, int(data.get("total_sec", 30))))
    max_power = int(data.get("max_power", 8))

    solution, err = solve_lightshow_with_cpsat(style, total_sec, max_power)
    if err or not solution:
        return jsonify({"ok": False, "error": err or "求解失敗"}), 400

    xml_text = build_blockly_xml_from_schedule(solution["segments"])
    solution["xml"] = xml_text
    arduino_serial.log(f"🧠 [OR-Tools CP-SAT] 最佳化求解成功！狀態: {solution['status']} | 滿意度得分: {solution['score']} | 包含 {len(solution['segments'])} 段時序")
    for s in solution["segments"]:
        arduino_serial.log(f"   ⏱️ {s['name']}: {s['duration']} 秒 (功耗等級 {s['power']})")

    return jsonify({"ok": True, "solution": solution})


@app.route("/api/hardware/config", methods=["GET", "POST"])
def api_hardware_config():
    global hardware_config
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        for k in ["m1_r_pin", "m1_g_pin", "m1_b_pin", "m2_r_pin", "m2_g_pin", "m2_b_pin", "common_anode", "servo_pin", "relay1_pin", "relay2_pin", "matrix_din_pin", "matrix_cs_pin", "matrix_clk_pin"]:
            if k in data:
                hardware_config[k] = data[k]
        save_hardware_config(hardware_config)
        arduino_serial.log(f"⚙️ 硬體腳位配置已更新: M1({hardware_config.get('m1_r_pin')},{hardware_config.get('m1_g_pin')},{hardware_config.get('m1_b_pin')}), M2({hardware_config.get('m2_r_pin')},{hardware_config.get('m2_g_pin')},{hardware_config.get('m2_b_pin')}), 點陣({hardware_config.get('matrix_din_pin')},{hardware_config.get('matrix_cs_pin')},{hardware_config.get('matrix_clk_pin')})")
        return jsonify({"ok": True, "config": hardware_config})
    return jsonify(hardware_config)


@app.route("/api/hardware/test", methods=["POST"])
def api_hardware_test():
    global hardware_config
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "1"))

    if target == "matrix":
        din = hardware_config.get("matrix_din_pin", "12")
        cs = hardware_config.get("matrix_cs_pin", "8")
        clk = hardware_config.get("matrix_clk_pin", "7")
        icon = data.get("icon", "heart")
        if not arduino_serial.is_connected:
            arduino_serial.log(f"⚠️ [USB 未連線] 測試點陣 腳位 DIN:{din} CS:{cs} CLK:{clk} -> {icon}")
            return jsonify({"ok": False, "error": "USB 尚未連線"}), 400

        if icon == "clear":
            arduino_serial.send_command(f"MATRIX_CLEAR,{din},{cs},{clk}")
            arduino_serial.log(f"🧪 [測試點陣] 清除畫面全滅")
            return jsonify({"ok": True})

        # 動態動畫測試
        matched_anim = None
        for k, v in PRESET_ANIMATIONS.items():
            if icon in k.lower():
                matched_anim = v
                break
        if matched_anim:
            for frame in matched_anim:
                cmd = f"MATRIX_ALL,{din},{cs},{clk}," + ",".join(str(b) for b in frame)
                arduino_serial.send_command(cmd)
                time.sleep(0.08)
            arduino_serial.log(f"🧪 [測試點陣動畫] 腳位 DIN:{din} CS:{cs} CLK:{clk} -> 播放動態 {icon}")
            return jsonify({"ok": True, "type": "animation"})

        # 靜態圖形測試
        matched_bm = None
        for k, v in PRESET_MATRIX.items():
            if icon in k.lower():
                matched_bm = v
                break
        if not matched_bm:
            matched_bm = PRESET_MATRIX.get("❤️ 愛心", [0x00, 0x66, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C, 0x18])
        cmd = f"MATRIX_ALL,{din},{cs},{clk}," + ",".join(str(b) for b in matched_bm)
        resp = arduino_serial.send_command(cmd)
        arduino_serial.log(f"🧪 [測試點陣圖示] 腳位 DIN:{din} CS:{cs} CLK:{clk} -> 顯示 {icon} | {resp}")
        return jsonify({"ok": True, "resp": resp})

    r = max(0, min(255, int(data.get("r", 255))))
    g = max(0, min(255, int(data.get("g", 0))))
    b = max(0, min(255, int(data.get("b", 0))))
    anode_int = 1 if hardware_config.get("common_anode", True) else 0

    if target == "1":
        r_pin = hardware_config.get("m1_r_pin", "6")
        g_pin = hardware_config.get("m1_g_pin", "3")
        b_pin = hardware_config.get("m1_b_pin", "5")
    else:
        r_pin = hardware_config.get("m2_r_pin", "11")
        g_pin = hardware_config.get("m2_g_pin", "9")
        b_pin = hardware_config.get("m2_b_pin", "10")

    if arduino_serial.is_connected:
        resp = arduino_serial.send_command(f"RGB,{r_pin},{g_pin},{b_pin},{anode_int},{r},{g},{b}")
        arduino_serial.log(f"🧪 [測試點燈] M{target} 腳位({r_pin},{g_pin},{b_pin}) -> R:{r} G:{g} B:{b} | {resp}")
        return jsonify({"ok": True, "resp": resp})
    else:
        arduino_serial.log(f"⚠️ [USB 未連線] 測試 M{target} 腳位({r_pin},{g_pin},{b_pin}) -> R:{r} G:{g} B:{b}")
        return jsonify({"ok": False, "error": "USB 尚未連線"}), 400
# ==========================================

def find_available_port(start_port=5050):
    for p in range(start_port, start_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start_port


def launch_desktop_window(app_url: str):
    """優先以獨立無邊框 App 視窗模式 (Chrome / Edge) 啟動，外觀如同原生 mBlock 5 桌面應用程式"""
    browser_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for b_path in browser_candidates:
        if os.path.exists(b_path):
            try:
                import subprocess
                subprocess.Popen([
                    b_path,
                    f"--app={app_url}",
                    "--start-maximized",
                    "--window-size=1400,900",
                    "--window-position=50,50"
                ])
                print(f"🚀 已成功以獨立桌面視窗啟動工作室: {os.path.basename(b_path)}", flush=True)
                return True
            except Exception:
                pass
    # 若上述皆無，使用系統預設瀏覽器開啟
    print("🌐 使用預設瀏覽器開啟工作室...", flush=True)
    webbrowser.open(app_url)
    return True


def is_running_in_cloud():
    return bool(
        os.environ.get("RENDER")
        or os.environ.get("DYNO")
        or os.environ.get("KUBERNETES_SERVICE_HOST")
        or (os.environ.get("PORT") and sys.platform != "win32")
    )


def main():
    port = int(os.environ.get("PORT", 5050))
    in_cloud = is_running_in_cloud()
    host = "0.0.0.0" if in_cloud else "127.0.0.1"

    if not in_cloud:
        # 單實例檢查：若 5050 埠已被佔用，表示已有工作室在背景運作並連線 COM 埠，直接喚起視窗避免重複搶佔 COM
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                print(f"⚠️ 偵測到已有 Block Studio 正在背景執行中 ({port} 埠使用中)。", flush=True)
                print("🚀 為您喚起已連線之工作室桌面視窗...", flush=True)
                launch_desktop_window(f"http://127.0.0.1:{port}")
                return

    app_url = f"http://{'localhost' if host == '0.0.0.0' else host}:{port}"
    print("=================================================================", flush=True)
    print("👧 昕蓉Sophia - 智慧兒童視覺化積木程式設計工作室 (Flask + Waitress)", flush=True)
    print(f"🌐 伺服器啟動於: http://{host}:{port}", flush=True)
    if in_cloud:
        print("☁️ 正在雲端環境 (Render/Cloud) 運行，健康檢查路由: /healthz", flush=True)
    print("=================================================================", flush=True)

    # 啟動時自動尋找並連線 Arduino USB
    threading.Thread(target=arduino_serial.auto_connect, daemon=True).start()

    if not in_cloud:
        threading.Thread(target=lambda: (time.sleep(0.8), launch_desktop_window(app_url)), daemon=True).start()

    # 以 Waitress WSGI 高性能生產級伺服器運行
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
    except KeyboardInterrupt:
        print("\n👋 積木工作室已安全關閉。")
        arduino_serial.disconnect()


if __name__ == "__main__":
    main()
