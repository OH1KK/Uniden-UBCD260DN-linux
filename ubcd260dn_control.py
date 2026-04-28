#!/usr/bin/env python3
"""
UBCD260DN / BCD260DN Python Controller
Full featured script - Fixed frequency command

Tested & Working:
- Frequency setting
- Volume & Squelch
- Status with squelch open/closed detection
"""

import serial
import time
import sys
from typing import Dict, Optional


class UnidenUBCD260DN:
    def __init__(self, port: str = "/dev/ttyACM0", baud: int = 115200):
        self.port = port
        self.baud = baud
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        """Connect to the scanner."""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.6)
            print(f"✅ Connected to {self.port} at {self.baud} baud")
            self._send("VER")  # handshake
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    def _send(self, cmd: str) -> str:
        """Send command and return response."""
        if not self.ser:
            return "Not connected"
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii"))
        time.sleep(0.4)
        resp = self.ser.read(self.ser.in_waiting or 512).decode("ascii", errors="ignore").strip()
        return resp or "(no response)"

    def set_frequency(self, mhz: float) -> str:
        """Tune scanner to frequency. Corrected scaling (100 Hz units)."""
        # Correct format: MHz * 10000 → 100 Hz units
        # Example: 103.7 MHz → 1037000, 88.8 MHz → 888000
        units = int(mhz * 10000)
        cmd = f"QSH,{units}"
        
        response = self._send(cmd)
        print(f"📻 Tuned to {mhz} MHz  →  {cmd}  Response: {response}")
        
        if "ERR" in response.upper():
            print("⚠️  Error - Frequency may be out of band or invalid step.")
        return response

    def set_volume(self, level: int) -> str:
        """Set volume level (0-15)."""
        if not 0 <= level <= 15:
            print("⚠️  Volume must be between 0 and 15")
            return "Invalid"
        response = self._send(f"VOL,{level}")
        print(f"🔊 Volume set to {level}  →  Response: {response}")
        return response

    def set_squelch(self, level: int) -> str:
        """Set squelch level (0-15)."""
        if not 0 <= level <= 15:
            print("⚠️  Squelch must be between 0 and 15")
            return "Invalid"
        response = self._send(f"SQL,{level}")
        print(f"🔇 Squelch set to {level}  →  Response: {response}")
        return response

    def get_status(self) -> Dict:
        """Get detailed status and detect if squelch is open."""
        sts = self._send("STS")
        glg = self._send("GLG")

        squelch_open = "Unknown"
        if sts.startswith("STS,"):
            parts = [p.strip() for p in sts.split(",")]
            # Look for signal indicator in the flag fields
            if len(parts) > 15:
                flags = parts[15:25]
                if any(x in ("1", "2", "3") for x in flags if x.isdigit()):
                    squelch_open = "OPEN - Signal detected"
                else:
                    squelch_open = "CLOSED - No signal"

        status = {
            "raw_sts": sts,
            "raw_glg": glg,
            "squelch_status": squelch_open,
        }

        print("\n" + "="*50)
        print("📊 SCANNER STATUS")
        print("="*50)
        print(f"Squelch       : {squelch_open}")
        print(f"Raw STS       : {sts}")
        print(f"Raw GLG       : {glg}")
        print("="*50)
        return status

    def close(self):
        """Close serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("🔌 Disconnected from scanner")


# ====================== MAIN ======================
if __name__ == "__main__":
    scanner = UnidenUBCD260DN()

    if not scanner.connect():
        sys.exit(1)

    print("\n🚀 UBCD260DN Controller Ready!")
    print("Available commands:")
    print("   freq 103.7     → tune frequency")
    print("   vol 10         → set volume (0-15)")
    print("   sql 8          → set squelch (0-15)")
    print("   status         → show full status + squelch state")
    print("   q              → quit\n")

    try:
        while True:
            user_input = input("> ").strip().lower()

            if user_input.startswith("freq "):
                try:
                    mhz = float(user_input.split()[1])
                    scanner.set_frequency(mhz)
                except:
                    print("Usage: freq 103.7   or   freq 88.8")

            elif user_input.startswith("vol "):
                try:
                    level = int(user_input.split()[1])
                    scanner.set_volume(level)
                except:
                    print("Usage: vol 10")

            elif user_input.startswith("sql "):
                try:
                    level = int(user_input.split()[1])
                    scanner.set_squelch(level)
                except:
                    print("Usage: sql 8")

            elif user_input == "status":
                scanner.get_status()

            elif user_input in ["q", "quit", "exit"]:
                break

            else:
                print("Unknown command. Try: freq, vol, sql, status, q")

    except KeyboardInterrupt:
        print("\n👋 Exiting...")
    finally:
        scanner.close()

