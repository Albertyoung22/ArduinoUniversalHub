"""
Arduino Real-Time USB Controller (Python SDK)
============================================
Communicates with Arduino Uno over USB Serial.
Supports automatic COM port detection.
"""

import time
import serial
import serial.tools.list_ports


def find_arduino_port(probe_handshake: bool = False) -> str or None:
    """
    Automatically search all connected serial ports and return the COM port of Arduino.
    Priority:
      1. Official Arduino (VID: 0x2341, description contains 'Arduino')
      2. Clone Arduino (CH340 / CP210x / FTDI USB-Serial chips)
    """
    candidates = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        
        score = 0
        if "arduino" in desc or "arduino" in mfg or p.vid == 0x2341:
            score += 100
        elif p.vid == 0x1A86 or "ch340" in desc or "ch341" in desc:
            score += 50
        elif p.vid in [0x10C4, 0x0403]:  # CP210x, FTDI
            score += 40
        elif "usb-serial" in desc or "usb serial" in desc:
            score += 30

        if score > 0:
            candidates.append((score, p.device, p.description))

    candidates.sort(key=lambda x: x[0], reverse=True)

    if not candidates:
        return None

    if not probe_handshake or len(candidates) == 1:
        return candidates[0][1]

    # Optional active probe with PING
    for _, port, _ in candidates:
        try:
            with serial.Serial(port, 115200, timeout=1.0) as s:
                time.sleep(1.8)
                s.reset_input_buffer()
                s.write(b"PING\n")
                if s.readline().decode().strip() == "PONG":
                    return port
        except Exception:
            continue

    return candidates[0][1]


class Arduino:
    def __init__(self, port=None, baudrate=115200, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        """Open serial connection and wait for Arduino reset to settle."""
        if not self.port:
            print("Auto-detecting Arduino COM port...")
            detected = find_arduino_port()
            if not detected:
                raise RuntimeError("Could not automatically find any connected Arduino! Please specify port manually.")
            self.port = detected
            print(f"Auto-detected Arduino on port: {self.port}")

        print(f"Connecting to Arduino on {self.port} at {self.baudrate} baud...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        time.sleep(2.0)  # Arduino Uno resets upon DTR assert
        self.ser.reset_input_buffer()
        # Verify connection
        resp = self.send_command("PING")
        if resp != "PONG":
            raise RuntimeError(f"Unexpected handshake response from Arduino: {resp}")
        print(f"Successfully connected to Arduino on {self.port}!")

    def disconnect(self):
        """Close serial connection safely."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected from Arduino.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def send_command(self, cmd: str) -> str:
        """Send a single-line command and return the trimmed response."""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial connection is not open.")
        
        self.ser.write((cmd.strip() + "\n").encode("utf-8"))
        line = self.ser.readline().decode("utf-8", errors="replace").strip()
        return line

    def pin_mode(self, pin: int, mode: str = "OUTPUT") -> bool:
        """Set pin mode: 'OUTPUT', 'INPUT', or 'INPUT_PULLUP'."""
        mode = mode.upper()
        resp = self.send_command(f"PINMODE {pin} {mode}")
        return resp == "OK"

    def digital_write(self, pin: int, value: int or bool) -> bool:
        """Write HIGH (1) or LOW (0) to a digital pin."""
        val = 1 if value else 0
        resp = self.send_command(f"DW {pin} {val}")
        return resp == "OK"

    def digital_read(self, pin: int) -> int:
        """Read digital value (0 or 1) from a pin."""
        resp = self.send_command(f"DR {pin}")
        try:
            return int(resp)
        except ValueError:
            return -1

    def analog_write(self, pin: int, value: int) -> bool:
        """PWM output to PWM-capable pins (3, 5, 6, 9, 10, 11). Value: 0~255."""
        val = max(0, min(255, int(value)))
        resp = self.send_command(f"AW {pin} {val}")
        return resp == "OK"

    def analog_read(self, analog_pin: int) -> int:
        """Read 10-bit ADC value (0~1023) from analog pin A0~A5 (pass 0 for A0, 1 for A1...)."""
        resp = self.send_command(f"AR {analog_pin}")
        try:
            return int(resp)
        except ValueError:
            return -1

    def get_status(self) -> str:
        """Return firmware status."""
        return self.send_command("STATUS")


if __name__ == "__main__":
    # Test auto-detection
    print("Testing auto-detection:")
    with Arduino() as uno:  # port=None means auto-detect!
        print("Connected via auto-detect!")
        print("Firmware status:", uno.get_status())
