When you connect Uniden UBCD260DN scanner into PC, it detects radio's serial port

````
journalctl -k --grep usb 
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: new full-speed USB device number 7 using xhci_hcd
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: New USB device found, idVendor=1965, idProduct=001a, bcdDevice= 1.00
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: New USB device strings: Mfr=1, Product=2, SerialNumber=0
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: Product: UBCD260DN Serial Port 
huhti 28 23:28:29 radiolinux kernel: usb 3-4.1: Manufacturer: UNIDEN AMERICA CORP.   
huhti 28 23:28:29 radiolinux kernel: cdc_acm 3-4.1:1.0: ttyACM0: USB ACM device
````
You can use port /dev/ttyACM0 to talk with a scanner. Use 115200-n-8-1 baudrate.

````
picocom -s 115200 --echo /dev/ttyACM0
````

Serial port commands detected so far

# UBCD260DN / BCD260DN Serial Commands

## Fully Working Commands

| Command          | Example                  | Direction     | Description                              | Response Example                  | Notes |
|------------------|--------------------------|---------------|------------------------------------------|-----------------------------------|-------|
| `VER`            | `VER`                    | Get           | Firmware version                         | `VER,Version 1.00.07`             | - |
| `STS`            | `STS`                    | Get           | Full scanner status                      | `STS,011000,...145.4250...`       | - |
| `VOL`            | `VOL`                    | Get           | Get current volume level                 | `VOL,9`                           | - |
| `VOL,n`          | `VOL,10`                 | Set           | Set volume level (0-15)                  | `VOL,OK`                          | - |
| `SQL`            | `SQL`                    | Get           | Get current squelch level                | `SQL,3`                           | - |
| `SQL,n`          | `SQL,8`                  | Set           | Set squelch level (0-15 recommended)     | `SQL,OK`                          | - |
| `QSH,freq`       | `QSH,1037000`            | Set           | **Tune to frequency** (in 100 Hz)        | `QSH,OK`                          | For example 103.7Mhz -> 1037000 |

---

## Other commands

Radio seems to have similator protocol like BCD996XT, with some changes. BCD996XT protocol spec is available at https://info.uniden.com/twiki/pub/UnidenMan4/BCD996XTFirmwareUpdate/BCD996XT_v1.04.00_Protocol.pdf

## Python Examples

* f.py - quicky set frequency
* ubcd260dn_control.py - interactive shell example
* UBCD260DN_backup.py - script to backup/resotre radio settings and memory channels
