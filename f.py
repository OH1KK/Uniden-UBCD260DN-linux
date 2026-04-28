#!/usr/bin/env python3
"""
UBCD260DN Quick Frequency Setter
Usage: ./f.py 103.7
"""

import serial
import sys
import time

def main():
    if len(sys.argv) != 2:
        print("Usage: f.py <frequency_MHz>")
        print("Example: f.py 103.7")
        sys.exit(1)

    try:
        mhz = float(sys.argv[1])
    except ValueError:
        print("Error: Frequency must be a number (e.g. 103.7 or 145.425)")
        sys.exit(1)

    # Connect to scanner
    try:
        ser = serial.Serial('/dev/ttyACM0', 115200, timeout=0.6)
    except Exception as e:
        print(f"Error: Cannot open scanner port /dev/ttyACM0")
        print(f"Details: {e}")
        sys.exit(1)

    # Convert MHz to scanner format (100 Hz units)
    units = int(mhz * 10000)          # 103.7 → 1037000
    cmd = f"QSH,{units}"

    # Send command
    ser.write((cmd + "\r").encode("ascii"))
    time.sleep(0.4)
    response = ser.read(ser.in_waiting or 256).decode("ascii", errors="ignore").strip()

    print(f"📻 Tuned to {mhz} MHz  →  {cmd}")
    if "OK" in response:
        print("✅ Success")
    elif "ERR" in response:
        print("❌ Error - Frequency may be out of range")
    else:
        print(f"Response: {response}")

    ser.close()

if __name__ == "__main__":
    main()
