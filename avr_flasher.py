"""
AVR Toolchain Direct Compiler & Flasher for Arduino Uno
======================================================
Compiles Arduino .ino sketches and uploads them directly via avrdude.
Works seamlessly without needing arduino-cli.exe installed.
"""

import glob
import os
import subprocess
import sys

# 本機 AVR 工具鏈路徑
DEFAULT_AVR_ROOT = os.path.expandvars(r"%LOCALAPPDATA%\Arduino15\packages\arduino")
AVR_BIN_DIR = os.path.join(DEFAULT_AVR_ROOT, r"tools\avr-gcc\7.3.0-atmel3.6.1-arduino7\bin")
AVRDUDE_DIR = os.path.join(DEFAULT_AVR_ROOT, r"tools\avrdude\6.3.0-arduino17")
CORE_DIR = os.path.join(DEFAULT_AVR_ROOT, r"hardware\avr\1.8.6\cores\arduino")
VARIANT_DIR = os.path.join(DEFAULT_AVR_ROOT, r"hardware\avr\1.8.6\variants\standard")

GCC_EXE = os.path.join(AVR_BIN_DIR, "avr-gcc.exe")
GPP_EXE = os.path.join(AVR_BIN_DIR, "avr-g++.exe")
OBJCOPY_EXE = os.path.join(AVR_BIN_DIR, "avr-objcopy.exe")
AVRDUDE_EXE = os.path.join(AVRDUDE_DIR, r"bin\avrdude.exe")
AVRDUDE_CONF = os.path.join(AVRDUDE_DIR, r"etc\avrdude.conf")


def check_toolchain():
    """確認本機 AVR 編譯與燒錄工具是否齊全"""
    required = [GCC_EXE, GPP_EXE, OBJCOPY_EXE, AVRDUDE_EXE, AVRDUDE_CONF, CORE_DIR, VARIANT_DIR]
    missing = [p for p in required if not os.path.exists(p)]
    return len(missing) == 0, missing


def compile_sketch(ino_path: str, build_dir: str = None, log_cb=print) -> str:
    """將 .ino 程式編譯為 ATmega328P 的 .hex 檔案"""
    if not os.path.exists(ino_path):
        raise FileNotFoundError(f"找不到韌體檔案: {ino_path}")

    ok, missing = check_toolchain()
    if not ok:
        raise RuntimeError(f"AVR 工具鏈元件缺失: {missing}")

    if not build_dir:
        build_dir = os.path.join(os.path.dirname(ino_path), "build_cache")
    os.makedirs(build_dir, exist_ok=True)

    log_cb("🔨 正在編譯 Arduino 核心庫與韌體 (AVR-GCC)...")

    c_flags = [
        "-c", "-g", "-Os", "-w",
        "-ffunction-sections", "-fdata-sections", "-flto",
        "-mmcu=atmega328p", "-DF_CPU=16000000L",
        "-DARDUINO=10819", "-DARDUINO_AVR_UNO", "-DARDUINO_ARCH_AVR",
        f"-I{CORE_DIR}", f"-I{VARIANT_DIR}"
    ]
    cpp_flags = c_flags + ["-std=gnu++11", "-fpermissive", "-fno-exceptions", "-fno-threadsafe-statics"]

    objs = []

    # 1. 編譯 Core C/CPP/S
    for c_file in glob.glob(os.path.join(CORE_DIR, "*.c")):
        obj = os.path.join(build_dir, os.path.basename(c_file) + ".o")
        if not os.path.exists(obj):
            subprocess.run([GCC_EXE] + c_flags + [c_file, "-o", obj], check=True, capture_output=True)
        objs.append(obj)

    for cpp_file in glob.glob(os.path.join(CORE_DIR, "*.cpp")):
        obj = os.path.join(build_dir, os.path.basename(cpp_file) + ".o")
        if not os.path.exists(obj):
            subprocess.run([GPP_EXE] + cpp_flags + [cpp_file, "-o", obj], check=True, capture_output=True)
        objs.append(obj)

    for s_file in glob.glob(os.path.join(CORE_DIR, "*.S")):
        obj = os.path.join(build_dir, os.path.basename(s_file) + ".o")
        if not os.path.exists(obj):
            subprocess.run([GCC_EXE] + c_flags + ["-x", "assembler-with-cpp", s_file, "-o", obj], check=True, capture_output=True)
        objs.append(obj)

    # 檢查是否有用到 Servo 庫
    with open(ino_path, "r", encoding="utf-8", errors="replace") as fin:
        content = fin.read()

    servo_src = os.path.expandvars(r"%LOCALAPPDATA%\Arduino15\libraries\Servo\src")
    if "<Servo.h>" in content or '"Servo.h"' in content:
        servo_avr = os.path.join(servo_src, "avr")
        cpp_flags.extend([f"-I{servo_src}", f"-I{servo_avr}"])
        servo_cpp = os.path.join(servo_avr, "Servo.cpp")
        if os.path.exists(servo_cpp):
            servo_obj = os.path.join(build_dir, "Servo.o")
            subprocess.run([GPP_EXE] + cpp_flags + [servo_cpp, "-o", servo_obj], check=True, capture_output=True)
            objs.append(servo_obj)

    # 2. 將 .ino 轉為 cpp 並編譯
    sketch_cpp = os.path.join(build_dir, "sketch.cpp")
    with open(sketch_cpp, "w", encoding="utf-8") as fout:
        fout.write("#include <Arduino.h>\n" + content)

    sketch_obj = os.path.join(build_dir, "sketch.o")
    res = subprocess.run([GPP_EXE] + cpp_flags + [sketch_cpp, "-o", sketch_obj], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"草稿編譯失敗:\n{res.stderr}")
    objs.append(sketch_obj)

    # 3. 連結 ELF
    elf = os.path.join(build_dir, "firmware.elf")
    link_cmd = [GCC_EXE, "-w", "-Os", "-g", "-flto", "-fuse-linker-plugin", "-Wl,--gc-sections", "-mmcu=atmega328p", "-o", elf] + objs + ["-lm"]
    res_link = subprocess.run(link_cmd, capture_output=True, text=True)
    if res_link.returncode != 0:
        raise RuntimeError(f"連結失敗:\n{res_link.stderr}")

    # 4. 產出 HEX
    hex_path = os.path.join(build_dir, "firmware.hex")
    subprocess.run([OBJCOPY_EXE, "-O", "ihex", "-R", ".eeprom", elf, hex_path], check=True, timeout=10)
    log_cb(f"✅ 編譯成功！二進位檔案大小: {os.path.getsize(hex_path)} bytes")
    return hex_path


def upload_hex(hex_path: str, port: str = "COM4", log_cb=print) -> bool:
    """使用 avrdude 將 .hex 韌體燒錄至指定的 COM 埠"""
    if not os.path.exists(hex_path):
        raise FileNotFoundError(f"找不到 hex 韌體: {hex_path}")

    log_cb(f"⚡ 正在透過 avrdude 燒錄至 Arduino Uno ({port})...")
    cmd = [
        AVRDUDE_EXE,
        "-C", AVRDUDE_CONF,
        "-v",
        "-p", "atmega328p",
        "-c", "arduino",
        "-P", port,
        "-b", "115200",
        "-D",
        "-U", f"flash:w:{hex_path}:i"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=25)
        if res.returncode != 0:
            log_cb(f"❌ 燒錄失敗:\n{res.stderr}")
            return False
        log_cb("🎉 燒錄成功！韌體已固化至 ATmega328P Flash 晶片。")
        return True
    except subprocess.TimeoutExpired:
        log_cb(f"❌ 燒錄超時 (25 秒): 序列埠 {port} 無回應，可能被其他軟體佔用！")
        return False


def find_arduino_port() -> str:
    """自動偵測 Arduino Uno 所在的 COM 埠"""
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        # 1. 優先匹配包含 "Arduino" 的 COM 埠
        for p in ports:
            desc = (p.description or "").lower()
            mfg = (getattr(p, "manufacturer", "") or "").lower()
            if "arduino" in desc or "arduino" in mfg:
                return p.device
        # 2. 其次匹配常見 USB-TTL (CH340 / CP210x / FTDI)
        for p in ports:
            desc = (p.description or "").lower()
            if any(k in desc for k in ["ch340", "usb-serial", "cp210", "ftdi"]):
                return p.device
        # 3. 排除一般系統主機板 COM1/COM2，選取第一個實體 USB COM 埠
        for p in ports:
            if p.device.upper() not in ("COM1", "COM2"):
                return p.device
        if ports:
            return ports[0].device
    except Exception:
        pass
    return "COM4"


def compile_and_upload(ino_path: str, port: str = "COM4", log_cb=print) -> bool:
    """一步完成編譯與燒錄"""
    if not port or port.lower() in ("auto", "none"):
        port = find_arduino_port()
        log_cb(f"🔍 自動偵測目標序列埠: {port}")
    hex_file = compile_sketch(ino_path, log_cb=log_cb)
    return upload_hex(hex_file, port, log_cb=log_cb)


if __name__ == "__main__":
    default_ino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universal_firmware", "universal_firmware.ino")
    if not os.path.exists(default_ino):
        default_ino = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_in_one_firmware", "all_in_one_firmware.ino")

    target_ino = sys.argv[1] if len(sys.argv) > 1 else default_ino
    target_port = sys.argv[2] if len(sys.argv) > 2 else "auto"

    print(f"🚀 [AVR Flasher] 準備燒錄: {target_ino}")
    print(f"🔌 [AVR Flasher] 目標序列埠: {target_port}")
    success = compile_and_upload(target_ino, target_port)
    if success:
        print("🎉 燒錄成功！")
        sys.exit(0)
    else:
        print("❌ 燒錄失敗！")
        sys.exit(1)

