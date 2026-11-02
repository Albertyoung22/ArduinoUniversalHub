# -*- coding: utf-8 -*-
"""
⚡ Cloudflare Tunnel (cloudflared) 內網穿透自動化管理器
============================================================
1. 自動偵測與下載官方 cloudflared-windows-amd64.exe 核心
2. 自動穿透本機指定的 Web Port (如 5000、8080 等)
3. 自動捕獲 trycloudflare.com 公開存取網址供全球外網連線
4. 支援 CLI 獨立運行與 Python 模組導入 (相容 Web / GUI)
"""

import os
import re
import sys
import time
import shutil
import urllib.request
import subprocess
import threading
import argparse
from typing import Optional, Callable

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 工作目錄設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED_EXE = os.path.join(BASE_DIR, "cloudflared.exe")
DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def copy_to_clipboard(text: str) -> bool:
    """自動複製文字至系統剪貼簿 (Windows)"""
    if sys.platform.startswith("win"):
        try:
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-16le"))
            return True
        except Exception:
            pass
    return False


class CloudflareTunnelManager:
    """Cloudflare Quick Tunnel 自動穿透管理核心"""

    def __init__(self, local_port: int = 5000):
        self.local_port = local_port
        self.exe_path = CLOUDFLARED_EXE
        self.process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.is_running = False
        self.on_url_ready: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None

    def log(self, msg: str):
        print(f"[CloudflareTunnel] {msg}", flush=True)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def ensure_cloudflared_installed(self) -> bool:
        """檢查 cloudflared 是否已安裝，若無則自動自 GitHub 下載"""
        # 1. 檢查本機目錄中是否已有 cloudflared.exe 且大小正常
        if os.path.exists(CLOUDFLARED_EXE):
            size_mb = os.path.getsize(CLOUDFLARED_EXE) / (1024 * 1024)
            if size_mb > 15:  # 完整執行檔通常約 50MB+
                self.exe_path = CLOUDFLARED_EXE
                self.log(f"✅ 已偵測到 cloudflared 核心: {CLOUDFLARED_EXE} ({size_mb:.1f} MB)")
                return True
            else:
                self.log(f"⚠️ 既有檔案大小異常 ({size_mb:.1f} MB)，將重新下載完整核心...")

        # 2. 檢查系統環境變數中是否有 cloudflared
        sys_cmd = shutil.which("cloudflared")
        if sys_cmd:
            self.exe_path = sys_cmd
            self.log(f"✅ 已偵測到系統 PATH 中的 cloudflared: {sys_cmd}")
            return True

        # 3. 自動從官方 GitHub Releases 下載
        self.log("🚀 正在自動下載 Cloudflare Tunnel 官方核心 (cloudflared-windows-amd64.exe)...")
        self.log(f"🔗 下載來源: {DOWNLOAD_URL}")
        temp_file = CLOUDFLARED_EXE + ".tmp"
        try:
            req = urllib.request.Request(
                DOWNLOAD_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )

            with urllib.request.urlopen(req, timeout=90) as response, open(temp_file, "wb") as out_file:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1024 * 512  # 512 KB
                last_pct = -1

                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded / total_size * 100)
                        if pct != last_pct and pct % 10 == 0:
                            self.log(f"📥 下載進度: {pct}% ({downloaded / (1024 * 1024):.1f} MB / {total_size / (1024 * 1024):.1f} MB)")
                            last_pct = pct

            if os.path.exists(temp_file):
                if os.path.exists(CLOUDFLARED_EXE):
                    try:
                        os.remove(CLOUDFLARED_EXE)
                    except Exception:
                        pass
                os.rename(temp_file, CLOUDFLARED_EXE)
                self.exe_path = CLOUDFLARED_EXE
                self.log(f"🎉 cloudflared 核心下載完成並成功部署至: {CLOUDFLARED_EXE}")
                return True
        except Exception as e:
            self.log(f"❌ 自動下載 cloudflared 失敗: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            return False

    def start(self, local_port: Optional[int] = None, on_url_ready: Optional[Callable[[str], None]] = None) -> bool:
        """啟動 Cloudflare Tunnel 並非同步捕獲 trycloudflare.com 網址"""
        if local_port:
            self.local_port = local_port
        if on_url_ready:
            self.on_url_ready = on_url_ready

        if not self.ensure_cloudflared_installed():
            self.log("❌ 無法啟動 Tunnel: cloudflared 核心未安裝")
            return False

        self.stop()
        self.public_url = None
        self.is_running = True

        cmd = [
            self.exe_path,
            "tunnel",
            "--url",
            f"http://127.0.0.1:{self.local_port}",
            "--no-autoupdate"
        ]

        self.log(f"🌐 正在啟動 Cloudflare Tunnel 穿透本地 Port {self.local_port}...")

        # 啟動子行程，將 stderr 與 stdout 合併以方便即時捕獲穿透網址
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # 隱藏終端黑視窗

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo
            )
        except Exception as e:
            self.log(f"❌ 啟動 cloudflared 子行程失敗: {e}")
            self.is_running = False
            return False

        def _monitor():
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            while self.is_running and self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    break
                line_str = line.strip()
                if not line_str:
                    continue

                # 尋找 trycloudflare.com 網址
                match = url_pattern.search(line_str)
                if match and not self.public_url:
                    self.public_url = match.group(0)
                    self.log("=" * 65)
                    self.log("🎉 成功建立 Cloudflare 內網穿透 (Quick Tunnel)！")
                    self.log(f"🔗 外網公開存取網址: {self.public_url}")
                    self.log(f"📱 本地轉發目標: http://127.0.0.1:{self.local_port}")
                    self.log("🌍 任何人在任何地點 (手機4G/5G、其他電腦) 均可透過此網址操控！")
                    self.log("=" * 65)
                    if self.on_url_ready:
                        try:
                            self.on_url_ready(self.public_url)
                        except Exception as ex:
                            self.log(f"回呼處理異常: {ex}")

            self.is_running = False
            self.log("ℹ️ Cloudflare Tunnel 監控連線已結束")

        self._monitor_thread = threading.Thread(target=_monitor, daemon=True)
        self._monitor_thread.start()
        return True

    def wait_for_url(self, timeout: float = 30.0) -> Optional[str]:
        """阻塞等待直到獲取公開穿透網址或逾時 (秒)"""
        start = time.time()
        while time.time() - start < timeout:
            if self.public_url:
                return self.public_url
            if not self.is_running:
                break
            time.sleep(0.4)
        return self.public_url

    def stop(self):
        """停止並關閉 Tunnel 行程"""
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.public_url = None
        if os.name == 'nt':
            try:
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True, check=False)
            except Exception:
                pass
        self.log("⏹️ Cloudflare Tunnel 已完全停止")

    def get_url(self) -> Optional[str]:
        """取得目前活躍的 trycloudflare.com 網址"""
        return self.public_url


# 全域共用單例
tunnel_manager = CloudflareTunnelManager(local_port=5000)


def main():
    parser = argparse.ArgumentParser(description="Cloudflare Tunnel 內網穿透工具")
    parser.add_argument("--port", "-p", type=int, default=5000, help="要穿透的本地通訊埠 (預設 5000)")
    parser.add_argument("--open", "-o", action="store_true", help="網址捕獲後自動在瀏覽器中開啟")
    parser.add_argument("--copy", "-c", action="store_true", help="網址捕獲後自動複製至剪貼簿")
    args = parser.parse_args()

    print("=" * 65)
    print("⚡ Cloudflare Tunnel (cloudflared) 內網穿透自動化啟動器")
    print(f"🎯 目標本機通訊埠: {args.port}")
    print("=" * 65)

    manager = CloudflareTunnelManager(local_port=args.port)
    if not manager.ensure_cloudflared_installed():
        print("❌ cloudflared 核心安裝失敗，請檢查網路連線後重試。")
        sys.exit(1)

    print("🚀 正在啟動 Tunnel 並捕獲 trycloudflare.com 外網網址...")
    manager.start()

    url = manager.wait_for_url(timeout=30.0)
    if url:
        print("\n" + "=" * 65)
        print(f"✅ 穿透成功！公開網址為: {url}")
        print("=" * 65 + "\n")

        if args.copy:
            if copy_to_clipboard(url):
                print("📋 網址已自動複製到系統剪貼簿！")

        if args.open:
            import webbrowser
            print("🌐 正在瀏覽器中開啟外網網址...")
            webbrowser.open(url)

        print("\n按 Ctrl+C 可停止穿透並退出程序...\n")
        try:
            while manager.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n正在停止 Cloudflare Tunnel...")
            manager.stop()
            print("已完全退出。")
    else:
        print("❌ 等待網址逾時，請檢查本機網路或防火牆設定。")
        manager.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
