"""
Interactive Command-Line Controller for Arduino Uno
===================================================
Run this script to control pins and read sensors interactively.

Usage:
  python interactive_cli.py
"""

import sys
from arduino_controller import Arduino


def print_help():
    print("""
=====================================================
  Arduino 即時終端控制選單 (COM4)
=====================================================
 指令範例：
   on <pin>          - 開啟數位腳位 (例: on 13)
   off <pin>         - 關閉數位腳位 (例: off 13)
   toggle <pin>      - 切換數位腳位狀態 (例: toggle 13)
   pwm <pin> <val>   - 輸出 PWM (0~255) (例: pwm 9 128)
   read <pin>        - 讀取數位腳位 (例: read 2)
   analog <0-5>      - 讀取類比腳位 A0~A5 (例: analog 0)
   blink <pin> <次數>- 連續閃爍 (例: blink 13 5)
   status            - 查看連線狀態
   help              - 顯示此說明
   quit / exit       - 結束程式
=====================================================
""")


def main():
    pin_states = {}
    try:
        uno = Arduino("COM4", 115200)
        uno.connect()
    except Exception as e:
        print(f"無法連線至 Arduino: {e}")
        sys.exit(1)

    print_help()

    try:
        while True:
            cmd = input("Arduino> ").strip()
            if not cmd:
                continue

            parts = cmd.split()
            action = parts[0].lower()

            if action in ["quit", "exit", "q"]:
                break
            elif action == "help":
                print_help()
            elif action == "status":
                print(uno.get_status())
            elif action == "on":
                if len(parts) < 2:
                    print("請指定腳位，例如: on 13")
                    continue
                pin = int(parts[1])
                uno.digital_write(pin, 1)
                pin_states[pin] = 1
                print(f"[OK] Pin {pin} -> HIGH (ON)")
            elif action == "off":
                if len(parts) < 2:
                    print("請指定腳位，例如: off 13")
                    continue
                pin = int(parts[1])
                uno.digital_write(pin, 0)
                pin_states[pin] = 0
                print(f"[OK] Pin {pin} -> LOW (OFF)")
            elif action == "toggle":
                if len(parts) < 2:
                    print("請指定腳位，例如: toggle 13")
                    continue
                pin = int(parts[1])
                curr = pin_states.get(pin, 0)
                nxt = 0 if curr == 1 else 1
                uno.digital_write(pin, nxt)
                pin_states[pin] = nxt
                print(f"[OK] Pin {pin} -> {'HIGH (ON)' if nxt else 'LOW (OFF)'}")
            elif action == "pwm":
                if len(parts) < 3:
                    print("請指定腳位與數值 (0~255)，例如: pwm 9 128")
                    continue
                pin = int(parts[1])
                val = int(parts[2])
                uno.analog_write(pin, val)
                print(f"[OK] Pin {pin} PWM -> {val}")
            elif action == "read":
                if len(parts) < 2:
                    print("請指定數位腳位，例如: read 2")
                    continue
                pin = int(parts[1])
                val = uno.digital_read(pin)
                print(f"[READ] Pin {pin} = {val}")
            elif action == "analog":
                if len(parts) < 2:
                    print("請指定類比通道 (0~5 代表 A0~A5)，例如: analog 0")
                    continue
                ch = int(parts[1])
                val = uno.analog_read(ch)
                print(f"[ANALOG] A{ch} = {val} / 1023 (約 {val * 5.0 / 1023:.2f} V)")
            elif action == "blink":
                pin = int(parts[1]) if len(parts) > 1 else 13
                times = int(parts[2]) if len(parts) > 2 else 3
                print(f"Pin {pin} 閃爍 {times} 次...")
                import time
                for i in range(times):
                    uno.digital_write(pin, 1)
                    time.sleep(0.3)
                    uno.digital_write(pin, 0)
                    time.sleep(0.3)
                print("[OK] 閃爍完成")
            else:
                print(f"未知指令 '{cmd}'，輸入 'help' 查看指令選單")
    except KeyboardInterrupt:
        print("\n中斷指令")
    finally:
        uno.disconnect()


if __name__ == "__main__":
    main()

