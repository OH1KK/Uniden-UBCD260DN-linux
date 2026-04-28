When you connect UBCD260DN into PC, it detects serial port

````
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: new full-speed USB device number 7 using xhci_hcd
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: New USB device found, idVendor=1965, idProduct=001a, bcdDevice= 1.00
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: New USB device strings: Mfr=1, Product=2, SerialNumber=0
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: Product: UBCD260DN Serial Port 
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: Manufacturer: UNIDEN AMERICA CORP.   
huhti 28 23:28:29 radiolinux kernel: cdc_acm 3-4.1:1.0: ttyACM0: USB ACM device
````
You can use port /dev/ttyACM0 to talk with a scanner.

Serial port commands detected so far

# UBCD260DN / BCD260DN Serial Commands

## ✅ Fully Working Commands

| Command          | Example                  | Direction     | Description                              | Response Example                  | Notes |
|------------------|--------------------------|---------------|------------------------------------------|-----------------------------------|-------|
| `VER`            | `VER`                    | Get           | Firmware version                         | `VER,Version 1.00.07`             | - |
| `STS`            | `STS`                    | Get           | Full scanner status                      | `STS,011000,...145.4250...`       | Very detailed |
| `GLG`            | `GLG`                    | Get           | Current frequency, mode and search info  | `GLG,0145.4250,FM,0,0,...`        | Most useful for current freq |
| `VOL`            | `VOL`                    | Get           | Get current volume level                 | `VOL,9`                           | - |
| `VOL,n`          | `VOL,10`                 | Set           | Set volume level (0-15)                  | `VOL,OK`                          | Works reliably |
| `SQL`            | `SQL`                    | Get           | Get current squelch level                | `SQL,3`                           | - |
| `SQL,n`          | `SQL,8`                  | Set           | Set squelch level (0-15 recommended)     | `SQL,OK`                          | Works reliably |
| `QSH,kHz`        | `QSH,1037000`            | Set           | **Tune to frequency** (in kHz)           | `QSH,OK`                          | **Best frequency command found** |

### Frequency Format
- Must be sent in **kHz** (not MHz).
- Examples:
  - 103.7 MHz → `QSH,1037000`
  - 145.425 MHz → `QSH,1454250`
  - 446.00625 MHz → `QSH,4460062`

---

## Python Example

```python
def tune(mhz: float):
    khz = int(mhz * 1000)
    ser.write(f"QSH,{khz}\r".encode('ascii'))
    time.sleep(0.4)
    print("Tuned to", mhz, "MHz")
