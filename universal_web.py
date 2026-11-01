# -*- coding: utf-8 -*-
"""
⚡ Arduino Universal Web Hub (萬能硬體控制中心 - Flask + Waitress + Cloudflare Tunnel)
使用 Flask 框架 + Waitress 高性能 WSGI 伺服器
整合 Cloudflare Tunnel 內網穿透，自動捕獲 trycloudflare.com 外網存取網址
"""

import os
import sys
import json
import time
import math
import random
import queue
import threading
from typing import List, Dict, Any, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import serial
import serial.tools.list_ports
from flask import Flask, request, Response, jsonify, send_file
import waitress

from universal_shared import (
    FONT_5X7,
    PRESET_MATRIX,
    PRESET_ANIMATIONS,
    text_to_matrix_frames,
    DEFAULT_PROFILE_PATH,
    WORKSPACE_DIR
)
from cloudflare_tunnel import CloudflareTunnelManager

# ==========================
# Web Hub 通訊與硬體中樞核心
# ==========================
class UniversalWebHub:
    def __init__(self, gui_hub=None, port: int = 5000):
        self.gui_hub = gui_hub  # 若存在則橋接 Desktop GUI
        self.local_port = port
        self.ser: Optional[serial.Serial] = None
        self.port: str = ""
        self.baud: int = 115200
        self.serial_lock = threading.Lock()
        self.rx_running = False
        self.rx_thread: Optional[threading.Thread] = None

        # 資料配置
        self.profile_path = DEFAULT_PROFILE_PATH
        self.components: List[Dict[str, Any]] = []
        self.workflows: List[Dict[str, Any]] = []
        self.load_profile()

        # SSE (Server-Sent Events) 連線用戶端隊列池
        self.sse_clients: List[queue.Queue] = []
        self.sse_lock = threading.Lock()

        # 跑馬燈執行緒管理 (comp_id -> threading.Event)
        self.marquee_stops: Dict[str, threading.Event] = {}

        # Web 自訂流程引擎
        self.wf_stop_event = threading.Event()
        self.wf_thread: Optional[threading.Thread] = None
        self.wf_running = False

        # 雙燈即時連線特效 (18 款炫彩即時特效)
        self.effect_stop_event = threading.Event()
        self.effect_thread: Optional[threading.Thread] = None
        self.current_effect_name: Optional[str] = None

        # Cloudflare Tunnel 管理器
        self.tunnel_manager = CloudflareTunnelManager(local_port=self.local_port)
        self.tunnel_manager.on_url_ready = self._on_tunnel_url_captured

    def _on_tunnel_url_captured(self, url: str):
        self.broadcast({"type": "tunnel_url", "url": url})
        self.log(f"🌐 Cloudflare Tunnel 公開存取網址: {url}")
        if self.gui_hub and hasattr(self.gui_hub, "log"):
            self.gui_hub.log(f"🌐 Cloudflare 外網穿透就緒: {url}")

    def load_profile(self):
        if self.gui_hub:
            self.components = self.gui_hub.components
            self.workflows = getattr(self.gui_hub, "workflows", [])
            return

        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.components = data.get("components", [])
                    self.workflows = data.get("workflows", [])
                    print(f"✅ Web 成功載入配置檔: {len(self.components)} 個配件, {len(self.workflows)} 個流程")
            except Exception as e:
                print(f"⚠️ 載入配置檔失敗: {e}")

    def save_profile(self, new_components=None, new_workflows=None):
        if new_components is not None:
            self.components = new_components
            if self.gui_hub:
                self.gui_hub.components = new_components
                if hasattr(self.gui_hub, "refresh_cards"):
                    self.gui_hub.dispatch_ui(self.gui_hub.refresh_cards)
        if new_workflows is not None:
            self.workflows = new_workflows
            if self.gui_hub:
                self.gui_hub.workflows = new_workflows
        elif self.gui_hub and new_components is None:
            self.components = self.gui_hub.components
            self.workflows = getattr(self.gui_hub, "workflows", [])
        data = {
            "profile_name": "Arduino Universal Hub Profile",
            "components": self.components,
            "workflows": self.workflows
        }
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log(f"💾 配件與腳位設定已儲存至 {os.path.basename(self.profile_path)}")
            self.broadcast({
                "type": "profile_update",
                "components": self.components,
                "workflows": self.workflows
            })
            return True
        except Exception as e:
            self.log(f"❌ 儲存配置失敗: {e}")
            return False

    # ==========================
    # 序列通訊管理
    # ==========================
    def list_ports(self) -> List[str]:
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports]

    def auto_connect(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        if not port_list:
            return
        exact_uno = [p.device for p in ports if "arduino" in p.description.lower()]
        ch340_ports = [p.device for p in ports if "ch340" in p.description.lower() or "usb-serial" in p.description.lower()]
        target = exact_uno[0] if exact_uno else (ch340_ports[0] if ch340_ports else port_list[0])
        self.connect(target)

    def connect(self, port_name: str) -> bool:
        if self.gui_hub:
            if not self.gui_hub.ser or not self.gui_hub.ser.is_open:
                self.gui_hub.port_combobox.set(port_name)
                self.gui_hub.connect()
            self.port = self.gui_hub.port_combobox.get()
            self.broadcast({"type": "status", "connected": True, "port": self.port})
            return True

        self.disconnect()
        try:
            self.ser = serial.Serial(port_name, self.baud, timeout=0.1, write_timeout=0.3)
            self.port = port_name
            self.rx_running = True
            self.rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
            self.rx_thread.start()
            self.log(f"🔌 Web 服務已連線序列埠: {port_name} (Baud: {self.baud})")
            self.broadcast({"type": "status", "connected": True, "port": self.port})
            time.sleep(1.8)
            self.send_cmd("PING")
            return True
        except Exception as e:
            self.log(f"❌ 連線 {port_name} 失敗: {e}")
            return False

    def disconnect(self):
        if self.gui_hub:
            self.gui_hub.disconnect()
            self.broadcast({"type": "status", "connected": False, "port": ""})
            return

        self.rx_running = False
        if self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.port = ""
        self.broadcast({"type": "status", "connected": False, "port": ""})
        self.log("🔌 序列埠已斷開連線")

    def is_connected(self) -> bool:
        if self.gui_hub:
            return bool(self.gui_hub.ser and self.gui_hub.ser.is_open)
        return bool(self.ser and self.ser.is_open)

    def send_cmd(self, cmd_str: str):
        if self.gui_hub:
            self.gui_hub.send_cmd(cmd_str)
            return

        if not self.ser or not self.ser.is_open:
            if not cmd_str.startswith("RGB,"):
                self.log(f"⚠️ 序列埠未連線，無法發送: {cmd_str.strip()}")
            return
        acquired = self.serial_lock.acquire(timeout=0.2)
        if not acquired:
            if not cmd_str.startswith("RGB,"):
                self.log(f"⚠️ 序列通訊繁忙，略過指令: {cmd_str.strip()}")
            return
        try:
            line = (cmd_str.strip() + "\n").encode("utf-8")
            self.ser.write(line)
            if not cmd_str.startswith("RGB,"):
                self.broadcast({"type": "log", "data": f">> {cmd_str.strip()}"})
        except Exception as e:
            self.log(f"❌ 指令發送異常: {e}")
        finally:
            self.serial_lock.release()

    def _rx_worker(self):
        while self.rx_running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.handle_incoming_line(line)
            except Exception:
                if self.rx_running:
                    self.log("❌ 序列埠通訊中斷")
                    self.disconnect()
                break

    def handle_incoming_line(self, line: str):
        self.broadcast({"type": "log", "data": f"<< {line}"})
        parts = line.split(",")
        tag = parts[0].upper()
        if (tag == "STREAM_DATA" or tag == "STREAM") and len(parts) >= 3:
            try:
                pin = parts[1]
                val = int(parts[2])
                self.broadcast({"type": "sensor_data", "pin": pin, "val": val})
            except ValueError:
                pass
        elif (tag == "SONAR_RES" or tag == "DIST") and len(parts) >= 3:
            try:
                trig = parts[1]
                dist = float(parts[2])
                self.broadcast({"type": "sonar_data", "trig": trig, "dist": dist})
            except ValueError:
                pass

    def log(self, msg: str):
        print(f"[WebHub] {msg}")
        self.broadcast({"type": "log", "data": msg})

    # ==========================
    # SSE 廣播管理
    # ==========================
    def add_sse_client(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self.sse_lock:
            self.sse_clients.append(q)
        return q

    def remove_sse_client(self, q: queue.Queue):
        with self.sse_lock:
            if q in self.sse_clients:
                self.sse_clients.remove(q)

    def broadcast(self, message: Dict[str, Any]):
        msg_str = json.dumps(message, ensure_ascii=False)
        with self.sse_lock:
            for q in list(self.sse_clients):
                try:
                    q.put_nowait(msg_str)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(msg_str)
                    except Exception:
                        pass

    # ==========================
    # 配件即時控制
    # ==========================
    def handle_rgb(self, comp_id: str, r: int, g: int, b: int, broadcast_state: bool = True):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        pins = comp.get("pins", {})
        rp, gp, bp = pins.get("r", 6), pins.get("g", 3), pins.get("b", 5)
        anode = 1 if comp.get("common_anode", True) else 0
        comp["state"] = comp.get("state", {})
        comp["state"]["r"], comp["state"]["g"], comp["state"]["b"] = r, g, b
        self.send_cmd(f"RGB,{rp},{gp},{bp},{anode},{r},{g},{b}")
        if broadcast_state:
            self.broadcast({"type": "comp_state", "id": comp_id, "state": comp["state"]})

        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "sync_ui"):
                self.gui_hub.dispatch_ui(card.sync_ui, r, g, b)

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

    def start_dual_effect(self, effect_name: str):
        """雙燈即時連線特效 (18 款炫彩即時特效)"""
        # 若與 universal_gui 同進程運行，委派給 GUI 中樞以保證單一核心線程控制
        if getattr(self, "gui_hub", None):
            self.gui_hub.start_dual_effect(effect_name)
            self.broadcast({"type": "dual_effect_start", "effect": effect_name})
            return

        self.stop_dual_effect()

        rgbs = [c for c in self.components if c.get("type") == "rgb"]
        if not rgbs:
            return
        comp1 = rgbs[0]
        comp2 = rgbs[1] if len(rgbs) > 1 else rgbs[0]

        stop_evt = self.effect_stop_event

        def worker():
            t0 = time.time()
            self.log(f"✨ 啟動雙燈即時連線特效: [{effect_name}]")
            self.broadcast({"type": "dual_effect_start", "effect": effect_name})
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

                self.handle_rgb(comp1["id"], r1, g1, b1, broadcast_state=False)
                if comp2["id"] != comp1["id"]:
                    self.handle_rgb(comp2["id"], r2, g2, b2, broadcast_state=False)

                self.broadcast({
                    "type": "dual_rgb_frame",
                    "id1": comp1["id"], "r1": r1, "g1": g1, "b1": b1,
                    "id2": comp2["id"], "r2": r2, "g2": g2, "b2": b2
                })

                # 使用 Event.wait 替代 time.sleep，收到停止訊號瞬間 0ms 立即喚醒跳出
                if stop_evt.wait(sleep_t):
                    break

            # 迴圈退出時，由 worker 執行緒親自熄滅燈光，100% 確保最後一刻雙燈熄滅
            self.handle_rgb(comp1["id"], 0, 0, 0, broadcast_state=True)
            if comp2["id"] != comp1["id"]:
                self.handle_rgb(comp2["id"], 0, 0, 0, broadcast_state=True)
            self.broadcast({
                "type": "dual_rgb_frame",
                "id1": comp1["id"], "r1": 0, "g1": 0, "b1": 0,
                "id2": comp2["id"], "r2": 0, "g2": 0, "b2": 0
            })
            self.log(f"⏹️ 特效 [{effect_name}] 已停止")
            self.broadcast({"type": "dual_effect_stop"})

        self.effect_thread = threading.Thread(target=worker, daemon=True)
        self.effect_thread.start()

    def stop_dual_effect(self, turn_off=True):
        """停止雙燈特效並視需要關閉/熄滅雙 RGB 燈光"""
        # 若與 universal_gui 同進程運行，委派給 GUI 中樞以保證單一核心線程控制
        if getattr(self, "gui_hub", None):
            self.gui_hub.stop_dual_effect(turn_off=turn_off)
            return

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
            # 主動熄滅所有 RGB 配件實體硬體狀態
            rgbs = [c for c in self.components if c.get("type") == "rgb"]
            for comp in rgbs:
                self.handle_rgb(comp["id"], 0, 0, 0)
            self.broadcast({"type": "dual_effect_stop"})
        else:
            self.broadcast({"type": "dual_effect_clear_badge"})

    def handle_matrix_all(self, comp_id: str, matrix_bytes: List[int]):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        pins = comp.get("pins", {})
        din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
        comp["state"] = comp.get("state", {})
        comp["state"]["matrix"] = list(matrix_bytes)
        bytes_str = ",".join(str(b) for b in matrix_bytes)
        self.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},{bytes_str}")
        self.broadcast({"type": "matrix_frame", "id": comp_id, "matrix": list(matrix_bytes)})

        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "sync_matrix"):
                self.gui_hub.dispatch_ui(card.sync_matrix, list(matrix_bytes))

    def handle_matrix_preset(self, comp_id: str, preset_name: str):
        if preset_name in PRESET_MATRIX:
            self.handle_matrix_all(comp_id, PRESET_MATRIX[preset_name])

    def start_marquee(self, comp_id: str, mode: str, text: str, speed_ms: int, loop: bool):
        # 若與 universal_gui 同進程運行，委派給 GUI 卡片主導播放，以保證與桌面完全同步
        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "start_marquee_from_web"):
                self.gui_hub.dispatch_ui(card.start_marquee_from_web, text, speed_ms, loop, mode)
                return

        self.stop_marquee(comp_id)
        stop_evt = threading.Event()
        self.marquee_stops[comp_id] = stop_evt

        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        pins = comp.get("pins", {})
        din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)

        if mode == "text":
            frames = text_to_matrix_frames(text)
        else:
            frames = PRESET_ANIMATIONS.get(mode, [])
        if not frames:
            return

        def worker():
            comp["state"] = comp.get("state", {})
            comp["state"]["marquee_speed"] = speed_ms
            self.log(f"🏃‍♂️ Web 啟動跑馬燈/動畫: [{mode}] (幀數: {len(frames)}, 初始間隔: {speed_ms}ms)")
            while not stop_evt.is_set():
                for f in frames:
                    if stop_evt.is_set():
                        break
                    bytes_str = ",".join(str(b) for b in f)
                    self.send_cmd(f"MATRIX_ALL,{din},{cs},{clk},{bytes_str}")
                    self.broadcast({"type": "matrix_frame", "id": comp_id, "matrix": list(f)})
                    if self.gui_hub and comp_id in self.gui_hub.card_widgets:
                        card = self.gui_hub.card_widgets[comp_id]
                        if hasattr(card, "sync_matrix"):
                            self.gui_hub.dispatch_ui(card.sync_matrix, list(f))

                    curr_spd = float(comp.get("state", {}).get("marquee_speed", speed_ms))
                    delay_s = max(0.035, curr_spd / 1000.0)
                    if stop_evt.wait(delay_s):
                        break
                if not loop:
                    break
            self.log(f"⏹️ 跑馬燈/動畫 [{mode}] 已停止")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def stop_marquee(self, comp_id: str):
        # 若與 universal_gui 同進程運行，委派給 GUI 卡片主導停止
        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "stop_marquee"):
                self.gui_hub.dispatch_ui(card.stop_marquee)
                return

        if comp_id in self.marquee_stops:
            self.marquee_stops[comp_id].set()
            del self.marquee_stops[comp_id]

    def handle_servo(self, comp_id: str, angle: int):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        p = comp.get("pins", {}).get("pin", 9)
        comp["state"] = comp.get("state", {})
        comp["state"]["angle"] = angle
        self.send_cmd(f"SERVO,{p},{angle}")
        self.broadcast({"type": "comp_state", "id": comp_id, "state": comp["state"]})
        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "sync_ui"):
                self.gui_hub.dispatch_ui(card.sync_ui, angle)

    def handle_pwm(self, comp_id: str, val: int):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        p = comp.get("pins", {}).get("pin", 9)
        comp["state"] = comp.get("state", {})
        comp["state"]["val"] = val
        self.send_cmd(f"PWM,{p},{val}")
        self.broadcast({"type": "comp_state", "id": comp_id, "state": comp["state"]})
        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "sync_ui"):
                self.gui_hub.dispatch_ui(card.sync_ui, val)

    def handle_switch(self, comp_id: str, on: bool):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        p = comp.get("pins", {}).get("pin", 13)
        comp["state"] = comp.get("state", {})
        comp["state"]["on"] = on
        self.send_cmd(f"DWRITE,{p},{1 if on else 0}")
        self.broadcast({"type": "comp_state", "id": comp_id, "state": comp["state"]})
        if self.gui_hub and comp_id in self.gui_hub.card_widgets:
            card = self.gui_hub.card_widgets[comp_id]
            if hasattr(card, "sync_ui"):
                self.gui_hub.dispatch_ui(card.sync_ui, on)

    def handle_sensor_stream(self, comp_id: str, streaming: bool):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        p = comp.get("pins", {}).get("pin", 0)
        s_type = comp.get("sensor_type", "A")
        interval = comp.get("interval_ms", 200)
        comp["state"] = comp.get("state", {})
        comp["state"]["streaming"] = streaming
        if streaming:
            self.send_cmd(f"STREAM,{p},{s_type},1,{interval}")
        else:
            self.send_cmd(f"STREAM,{p},{s_type},0,{interval}")

    def handle_sonar(self, comp_id: str):
        comp = next((c for c in self.components if c["id"] == comp_id), None)
        if not comp:
            return
        pins = comp.get("pins", {})
        trig = pins.get("trig", 2)
        echo = pins.get("echo", 3)
        self.send_cmd(f"SONAR,{trig},{echo}")

    # ==========================
    # Web 自訂流程引擎 (Sequencer)
    # ==========================
    def start_workflow(self, wf_idx: int):
        if wf_idx < 0 or wf_idx >= len(self.workflows):
            return
        self.stop_workflow()
        self.wf_stop_event.clear()
        wf = self.workflows[wf_idx]
        wf_name = wf.get("name", "未命名流程")
        steps = wf.get("steps", [])
        loop = wf.get("loop", False)

        def worker():
            self.wf_running = True
            self.log(f"🎭 [Web] 啟動自動流程: 『{wf_name}』(共 {len(steps)} 個步驟, 循環: {'是' if loop else '否'})")
            try:
                while not self.wf_stop_event.is_set():
                    for idx, step in enumerate(steps):
                        if self.wf_stop_event.is_set():
                            break
                        self.broadcast({"type": "workflow_step", "idx": idx})
                        self.execute_step(step)

                        # 微步進安全間隔
                        if step.get("action") != "delay":
                            elapsed = 0
                            while elapsed < 30 and not self.wf_stop_event.is_set():
                                time.sleep(0.005)
                                elapsed += 5

                    if not loop or self.wf_stop_event.is_set():
                        break

                self.broadcast({"type": "workflow_step", "idx": -1})
                self.broadcast({"type": "workflow_finish"})
                self.log(f"🏁 [Web] 流程『{wf_name}』執行完畢。")
            except Exception as e:
                self.log(f"❌ 流程執行異常: {e}")
            finally:
                self.wf_running = False

        self.wf_thread = threading.Thread(target=worker, daemon=True)
        self.wf_thread.start()

    def stop_workflow(self):
        self.wf_stop_event.set()
        if self.wf_thread and self.wf_thread.is_alive():
            self.wf_thread.join(timeout=0.3)
        self.wf_thread = None
        self.wf_running = False
        self.broadcast({"type": "workflow_step", "idx": -1})

    def execute_step(self, step: Dict[str, Any]):
        action = step.get("action")
        params = step.get("params", {})
        target_id = step.get("target_id")

        if action == "delay":
            ms = params.get("ms", 500)
            elapsed = 0
            while elapsed < ms and not self.wf_stop_event.is_set():
                chunk = min(20, ms - elapsed)
                time.sleep(chunk / 1000.0)
                elapsed += chunk
            return

        if action == "dual_effect":
            effect_name = params.get("effect", "sync_rainbow")
            duration_ms = params.get("duration_ms", 3000)
            self.start_dual_effect(effect_name)
            elapsed = 0
            while elapsed < duration_ms and not self.wf_stop_event.is_set():
                chunk = min(30, duration_ms - elapsed)
                time.sleep(chunk / 1000.0)
                elapsed += chunk
            self.stop_dual_effect(turn_off=True)
            return

        comp = next((c for c in self.components if c["id"] == target_id), None)
        if not comp:
            return

        pins = comp.get("pins", {})
        if action == "rgb":
            r, g, b = params.get("r", 0), params.get("g", 0), params.get("b", 0)
            self.handle_rgb(target_id, r, g, b)
        elif action == "matrix":
            pat = params.get("pattern", "❤️ 愛心")
            if pat in PRESET_MATRIX:
                bmp = PRESET_MATRIX[pat]
            else:
                bmp = params.get("matrix", [0] * 8)
            self.handle_matrix_all(target_id, bmp)
        elif action == "matrix_marquee":
            din, cs, clk = pins.get("din", 12), pins.get("cs", 8), pins.get("clk", 7)
            txt = params.get("text", "HELLO")
            spd = max(25, params.get("speed_ms", 70))
            loops = max(1, params.get("loops", 1))
            frames = text_to_matrix_frames(txt)
            for _ in range(loops):
                for f in frames:
                    if self.wf_stop_event.is_set():
                        break
                    self.handle_matrix_all(target_id, f)
                    time.sleep(spd / 1000.0)
        elif action == "matrix_anim":
            anim_name = params.get("anim", "💓 心跳搏動動畫")
            spd = max(30, params.get("speed_ms", 90))
            repeats = max(1, params.get("repeats", 2))
            frames = PRESET_ANIMATIONS.get(anim_name, [])
            for _ in range(repeats):
                for f in frames:
                    if self.wf_stop_event.is_set():
                        break
                    self.handle_matrix_all(target_id, f)
                    time.sleep(spd / 1000.0)
        elif action == "servo":
            self.handle_servo(target_id, params.get("angle", 90))
        elif action == "pwm":
            self.handle_pwm(target_id, params.get("val", 0))
        elif action == "switch":
            self.handle_switch(target_id, params.get("on", False))

    def trigger_single_step(self, wf_idx: int, step_idx: int):
        """單步即時測試：點到哪就執行到哪！"""
        if 0 <= wf_idx < len(self.workflows):
            steps = self.workflows[wf_idx].get("steps", [])
            if 0 <= step_idx < len(steps):
                step = steps[step_idx]
                self.log(f"⚡ [Web] 單步即時觸發 [步驟 {step_idx + 1}]: {step.get('desc')}")
                threading.Thread(target=lambda: self.execute_step(step), daemon=True).start()

    def handle_action(self, data: dict):
        action = data.get("action")
        cid = data.get("id")

        if action == "rgb_set":
            self.stop_dual_effect(turn_off=False)
            self.handle_rgb(cid, data.get("r", 0), data.get("g", 0), data.get("b", 0))
        elif action == "dual_rgb_effect":
            self.start_dual_effect(data.get("effect", "sync_rainbow"))
        elif action == "stop_dual_rgb_effect":
            self.stop_dual_effect(turn_off=True)
        elif action == "matrix_all":
            self.handle_matrix_all(cid, data.get("matrix", [0] * 8))
        elif action == "matrix_preset":
            self.handle_matrix_preset(cid, data.get("preset", ""))
        elif action == "matrix_start_marquee":
            self.start_marquee(
                cid,
                data.get("mode", "text"),
                data.get("text", "HELLO"),
                data.get("speed_ms", 150),
                data.get("loop", True)
            )
        elif action == "matrix_stop_marquee":
            self.stop_marquee(cid)
        elif action == "matrix_text_sync":
            text = data.get("text", "")
            comp = next((c for c in self.components if c["id"] == cid), None)
            if comp:
                comp.setdefault("state", {})["marquee_text"] = text
            if self.gui_hub and cid in self.gui_hub.card_widgets:
                card = self.gui_hub.card_widgets[cid]
                if hasattr(card, "sync_marquee_text"):
                    self.gui_hub.dispatch_ui(card.sync_marquee_text, text)
            self.broadcast({"type": "matrix_text_sync", "id": cid, "text": text})
        elif action == "matrix_speed_sync":
            speed = int(data.get("speed", 150))
            comp = next((c for c in self.components if c["id"] == cid), None)
            if comp:
                comp.setdefault("state", {})["marquee_speed"] = speed
            if self.gui_hub and cid in self.gui_hub.card_widgets:
                card = self.gui_hub.card_widgets[cid]
                if hasattr(card, "sync_speed"):
                    self.gui_hub.dispatch_ui(card.sync_speed, speed)
            self.broadcast({"type": "matrix_speed_sync", "id": cid, "speed": speed})
        elif action == "servo_set":
            self.handle_servo(cid, data.get("angle", 90))
        elif action == "pwm_set":
            self.handle_pwm(cid, data.get("val", 0))
        elif action == "switch_set":
            self.handle_switch(cid, data.get("on", False))
        elif action == "sensor_stream":
            self.handle_sensor_stream(cid, data.get("streaming", False))
        elif action == "sonar_measure":
            self.handle_sonar(cid)
        elif action == "workflow_start":
            self.start_workflow(data.get("workflow_idx", 0))
        elif action == "workflow_stop":
            self.stop_workflow()
        elif action == "workflow_execute_step":
            self.trigger_single_step(data.get("workflow_idx", 0), data.get("step_idx", 0))
        elif action == "workflow_update_loop":
            w_idx = data.get("workflow_idx", 0)
            if 0 <= w_idx < len(self.workflows):
                self.workflows[w_idx]["loop"] = data.get("loop", False)
                if self.gui_hub and 0 <= w_idx < len(getattr(self.gui_hub, "workflows", [])):
                    self.gui_hub.workflows[w_idx]["loop"] = data.get("loop", False)
                self.broadcast({
                    "type": "workflow_loop_sync",
                    "idx": w_idx,
                    "loop": data.get("loop", False)
                })
        elif action == "profile_sync":
            self.workflows = data.get("workflows", self.workflows)
            if self.gui_hub:
                self.gui_hub.workflows = self.workflows
            self.broadcast({
                "type": "profile_update",
                "components": self.components,
                "workflows": self.workflows
            })

    def flash_standalone_workflow(self, wf_idx: int) -> dict:
        """將指定自訂流程編譯生成獨立脫機韌體並直接燒錄至 Arduino Uno"""
        if wf_idx < 0 or wf_idx >= len(self.workflows):
            return {"ok": False, "error": "無效的流程索引"}
        wf = self.workflows[wf_idx]
        wf_name = wf.get("name", f"流程_{wf_idx + 1}")
        port = self.port or (self.list_ports()[0] if self.list_ports() else "")
        if not port:
            return {"ok": False, "error": "尚未連接任何 COM 埠，無法燒錄！"}

        self.disconnect()

        def worker():
            try:
                import standalone_generator
                self.log(f"🛠️ [Web] 正在生成【{wf_name}】脫機獨立 C++ 原始碼...")
                sketch_code = standalone_generator.generate_standalone_sketch(wf, self.components)
                out_dir = os.path.join(WORKSPACE_DIR, "standalone_sketch")
                os.makedirs(out_dir, exist_ok=True)
                sketch_file = os.path.join(out_dir, "standalone_sketch.ino")
                with open(sketch_file, "w", encoding="utf-8") as f:
                    f.write(sketch_code)
                self.log(f"📄 原始碼已生成 ({len(sketch_code)} 字元)，開始調用 arduino-cli 編譯...")
                ARDUINO_CLI_PATH = r"C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
                cmd_compile = [ARDUINO_CLI_PATH, "compile", "--fqbn", "arduino:avr:uno", out_dir]
                subprocess.run(cmd_compile, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log("✅ 編譯成功！正在上傳脫機自訂流程韌體至 Arduino Uno...")
                cmd_upload = [ARDUINO_CLI_PATH, "upload", "-p", port, "--fqbn", "arduino:avr:uno", out_dir]
                subprocess.run(cmd_upload, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
                self.log(f"🎉 脫機獨立自訂流程【{wf_name}】已成功燒錄！")
                self.broadcast({"type": "flash_result", "ok": True, "message": f"自訂流程【{wf_name}】脫機燒錄成功！已獨立運行。"})
                time.sleep(1.5)
                self.connect(port)
            except Exception as e:
                self.log(f"❌ 脫機燒錄失敗: {e}")
                self.broadcast({"type": "flash_result", "ok": False, "message": str(e)})
                self.connect(port)

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "message": f"已啟動自訂流程【{wf_name}】脫機燒錄程序..."}


# ==========================
# Flask 應用建構
# ==========================
DEFAULT_WEB_PORT = 5000
hub = UniversalWebHub(port=DEFAULT_WEB_PORT)
app = Flask(__name__, static_folder=None)

WEB_DIR = os.path.join(WORKSPACE_DIR, "web")
INDEX_HTML_PATH = os.path.join(WEB_DIR, "index.html")


@app.route("/")
def index():
    if os.path.exists(INDEX_HTML_PATH):
        return send_file(INDEX_HTML_PATH, mimetype="text/html")
    return "<h3>404: web/index.html not found</h3>", 404


@app.route("/events")
def sse_events():
    """Server-Sent Events (SSE) 即時單向事件推播，100% 完美相容 Waitress 與 Cloudflare Tunnel"""
    def event_stream():
        q = hub.add_sse_client()
        try:
            # 關鍵防緩衝襯墊：Cloudflare 與反向代理預設會緩衝小於 4KB 的資料
            # 發送 4KB 的註解註記，強迫 Cloudflare 即時 Flush 邊緣快取，達成 0ms 即時直通
            padding = " " * 4096
            yield f": {padding}\n\n"

            # 連線初始狀態推播
            connected = hub.is_connected()
            port = (hub.gui_hub.port_combobox.get() if hub.gui_hub else hub.port) or hub.port
            init_payload = {
                "type": "status",
                "connected": connected,
                "port": port,
                "tunnel_url": hub.tunnel_manager.get_url()
            }
            yield f"data: {json.dumps(init_payload, ensure_ascii=False)}\n\n"

            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    # 發送保活心跳註解，防止代理伺服器 (如 Cloudflare) 超時斷開
                    yield ": ping\n\n"
        finally:
            hub.remove_sse_client(q)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no"
    })


@app.route("/api/action", methods=["POST"])
def api_action():
    """統整動作指令分發入口 (REST API)，相容任何瀏覽器與內網穿透代理"""
    data = request.get_json(silent=True) or {}
    try:
        hub.handle_action(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/flash_workflow", methods=["POST"])
def api_flash_workflow():
    """脫機獨立自訂流程燒錄入口"""
    data = request.get_json(silent=True) or {}
    wf_idx = data.get("workflow_index", 0)
    res = hub.flash_standalone_workflow(wf_idx)
    return jsonify(res)


@app.route("/api/status", methods=["GET"])
def get_status():
    connected = hub.is_connected()
    port = (hub.gui_hub.port_combobox.get() if hub.gui_hub else hub.port) or hub.port
    comps = hub.gui_hub.components if hub.gui_hub else hub.components
    wfs = getattr(hub.gui_hub, "workflows", hub.workflows) if hub.gui_hub else hub.workflows
    active_fx = getattr(hub.gui_hub, "current_effect_name", None) if hub.gui_hub else hub.current_effect_name
    return jsonify({
        "connected": connected,
        "port": port,
        "ports": hub.list_ports(),
        "components": comps,
        "workflows": wfs,
        "active_effect": active_fx or "",
        "tunnel_url": hub.tunnel_manager.get_url()
    })


@app.route("/api/ports", methods=["POST"])
def scan_ports():
    ports = hub.list_ports()
    return jsonify({"ports": ports, "selected": hub.port or (ports[0] if ports else "")})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(silent=True) or {}
    port = data.get("port", "")
    ok = hub.connect(port)
    return jsonify({"ok": ok, "connected": hub.is_connected(), "port": hub.port})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    hub.disconnect()
    return jsonify({"ok": True})


@app.route("/api/emergency_stop", methods=["POST"])
def api_emergency_stop():
    if hub.gui_hub:
        hub.gui_hub.dispatch_ui(hub.gui_hub.emergency_stop)
    else:
        hub.stop_dual_effect()
        hub.stop_workflow()
        hub.send_cmd("STOP")
    hub.log("🛑 Web 觸發緊急安全停機 (Emergency Stop)！")
    hub.broadcast({"type": "emergency_stop"})
    return jsonify({"ok": True})


@app.route("/api/diagnostics", methods=["POST"])
def api_diagnostics():
    hub.send_cmd("PING")
    return jsonify({"ok": True})


@app.route("/api/profile/save", methods=["POST"])
def api_profile_save():
    data = request.get_json(silent=True) or {}
    new_comps = data.get("components")
    new_wfs = data.get("workflows")
    ok = hub.save_profile(new_components=new_comps, new_workflows=new_wfs)
    return jsonify({"ok": ok})


@app.route("/api/profile/load", methods=["POST"])
def api_profile_load():
    hub.load_profile()
    return jsonify({"ok": True})


@app.route("/api/tunnel", methods=["GET"])
def api_tunnel():
    return jsonify({
        "url": hub.tunnel_manager.get_url(),
        "running": hub.tunnel_manager.is_running
    })


@app.route("/api/tunnel/start", methods=["POST"])
def api_tunnel_start():
    ok = hub.tunnel_manager.start(local_port=hub.local_port)
    return jsonify({"ok": ok, "running": hub.tunnel_manager.is_running, "url": hub.tunnel_manager.get_url()})


@app.route("/api/tunnel/stop", methods=["POST"])
def api_tunnel_stop():
    hub.tunnel_manager.stop()
    return jsonify({"ok": True})


@app.route("/healthz")
@app.route("/health")
def healthz():
    return jsonify({"status": "ok", "app": "ArduinoUniversalHub"})


# ==========================
# 啟動函式 (Standalone & GUI 嵌入模式)
# ==========================
def run_standalone(host="0.0.0.0", port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5000))

    hub.local_port = port
    hub.auto_connect()

    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("PORT"))

    print("=" * 65)
    print("⚡ Arduino Universal Web Hub 萬能硬體控制中心 (Flask + Waitress)")
    print(f"🏠 本地存取網址: http://127.0.0.1:{port}")
    print(f"📱 區網存取網址: http://0.0.0.0:{port}")
    if not is_cloud:
        print("🌐 正在背景啟動 Cloudflare Tunnel 內網穿透...")
        hub.tunnel_manager.start(local_port=port)
        try:
            import webbrowser
            threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
        except Exception:
            pass
    else:
        print("☁️ 正在雲端環境 (Render) 運行，健康檢查路由: /healthz")
    print("=" * 65)

    # 以 Waitress 正式生產伺服器運行
    waitress.serve(app, host=host, port=port, threads=8, _quiet=True)


def start_web_server_thread(gui_app, host="0.0.0.0", port=5000):
    """供 universal_gui.py 在同一個行程中後台無縫啟動 Web 服務，共享 COM4 硬體通訊"""
    global hub
    hub.gui_hub = gui_app
    hub.local_port = port
    hub.components = gui_app.components
    hub.workflows = getattr(gui_app, "workflows", [])
    hub.port = gui_app.port_combobox.get() if hasattr(gui_app, "port_combobox") else ""

    # 橋接 GUI 的 log 訊息至 Web
    orig_gui_log = gui_app.log
    def hooked_log(msg):
        orig_gui_log(msg)
        hub.broadcast({"type": "log", "data": msg})
    gui_app.log = hooked_log

    # 啟動 Cloudflare Tunnel 穿透
    hub.tunnel_manager.start(local_port=port)

    # 啟動 Waitress 執行緒
    def _serve():
        waitress.serve(app, host=host, port=port, threads=8, _quiet=True)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    run_standalone()
