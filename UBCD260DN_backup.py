#!/usr/bin/env python3
"""
UBCD260DN Backup & Restore Tool
==================================
Backs up all settings and channel memories from a Uniden UBCD260DN
scanner to a JSON file, and can restore them after a factory reset.

The UBCD260DN has no published remote-control protocol document.
This tool is based on the BCD996XT v1.04.00 protocol specification.

Memory model:
  10 banks × 100 channels = 1000 total slots
  Flat CIN index: bank 0 = slots 0-99, bank 1 = 100-199, ..., bank 9 = 900-999
  Empty slots have frequency 00000000 and are skipped during restore.

Confirmed supported commands (from probe on firmware 1.00.07):
  BKL COM KBP OMS PRI CNT DUD SCN VOL SQL BSP SCO SHK CSG
  SSP(2-15) CSP(1-10) WXS SGP(1-5) TON(1-10) DBC(1-31)
  CIN(0-999) GLF GIE P25

Usage:
  python UBCD260DN_backup.py info    --port /dev/ttyACM0
  python UBCD260DN_backup.py backup  --port /dev/ttyACM0 --out backup.json
  python UBCD260DN_backup.py restore --port /dev/ttyACM0 --file backup.json
  python UBCD260DN_backup.py probe   --port /dev/ttyACM0

Requirements:  pip install pyserial
"""

import argparse
import json
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

try:
    import serial
except ImportError:
    print("ERROR: pyserial not installed.  Run:  pip install pyserial")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("UBCD260DN_backup")

_UNSUPPORTED  = "__UNSUPPORTED__"
NUM_BANKS     = 10
CH_PER_BANK   = 100
TOTAL_SLOTS   = NUM_BANKS * CH_PER_BANK   # 1000


# ---------------------------------------------------------------------------
# Radio serial interface
# ---------------------------------------------------------------------------

class Radio:
    DEFAULT_BAUD    = 115200
    TIMEOUT         = 3.0
    INTER_CMD_DELAY = 0.05

    def __init__(self, port: str, baud: int = DEFAULT_BAUD):
        self.port = port
        self.baud = baud
        self._ser = None

    def open(self):
        self._ser = serial.Serial(
            self.port, baudrate=self.baud,
            bytesize=8, parity=serial.PARITY_NONE,
            stopbits=1, timeout=self.TIMEOUT,
        )
        time.sleep(0.3)

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def _send(self, cmd: str) -> str:
        self._ser.reset_input_buffer()
        self._ser.write((cmd + "\r").encode("ascii"))
        resp = self._ser.read_until(b"\r").decode("ascii", errors="replace").strip()
        time.sleep(self.INTER_CMD_DELAY)
        log.debug(">> %-28s  << %s", cmd, resp)
        return resp

    def cmd(self, command: str) -> str:
        """Send command; raise RuntimeError on radio error responses."""
        resp = self._send(command)
        if resp in ("ERR", "FER", "ORER", "NG"):
            raise RuntimeError(f"Radio error '{resp}' for: {command}")
        return resp

    def try_cmd(self, command: str) -> str:
        """Like cmd() but returns _UNSUPPORTED on error."""
        try:
            return self.cmd(command)
        except RuntimeError as e:
            log.debug("  skip: %s", e)
            return _UNSUPPORTED

    def cmd_ok(self, command: str) -> bool:
        """Send set-command; return True on OK."""
        try:
            resp = self.cmd(command)
        except RuntimeError as e:
            log.warning("  set failed: %s", e)
            return False
        if not (resp.endswith(",OK") or resp == "OK"):
            log.warning("  Expected OK, got %r  (cmd=%s)", resp, command)
            return False
        return True

    def enter_program_mode(self):
        resp = self._send("PRG")
        if "NG" in resp:
            raise RuntimeError("Cannot enter Program Mode.")
        log.info("Entered Program Mode.")

    def exit_program_mode(self):
        self._send("EPG")
        log.info("Exited Program Mode.")

    @staticmethod
    def strip_prefix(resp: str, cmd_name: str) -> str:
        """'BKL,MIDL,YELLOW' → 'MIDL,YELLOW'"""
        prefix = cmd_name + ","
        return resp[len(prefix):] if resp.startswith(prefix) else resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(data: dict, key: str, radio: Radio, cmd: str):
    val = radio.try_cmd(cmd)
    if val != _UNSUPPORTED:
        data[key] = val


def _restore_setting(radio: Radio, cmd_prefix: str, data: dict, key: str):
    if key not in data:
        return
    resp     = data[key]
    cmd_name = cmd_prefix.rstrip(",")
    vals     = Radio.strip_prefix(resp, cmd_name)
    radio.cmd_ok(f"{cmd_prefix}{vals}")


def _field(fields: list, idx: int, default: str = "") -> str:
    return fields[idx] if idx < len(fields) else default


def _cin_frequency(raw_cin: str) -> str:
    """
    Extract frequency from a raw CIN response string.
    Radio response format: CIN,<slot_idx>,<NAME>,<FRQ>,<MOD>,...
    Field 0=CIN  1=slot_idx  2=NAME  3=FRQ
    """
    parts = raw_cin.split(",")
    return parts[3] if len(parts) > 3 else ""


def _cin_is_empty(raw_cin: str) -> bool:
    return _cin_frequency(raw_cin) in ("00000000", "", "0")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(radio: Radio) -> dict:
    data: dict = {
        "meta": {
            "tool":      "UBCD260DN_backup.py",
            "timestamp": datetime.now().isoformat(),
        }
    }

    log.info("Reading model and firmware...")
    data["model"]    = Radio.strip_prefix(radio.try_cmd("MDL"), "MDL")
    data["firmware"] = Radio.strip_prefix(radio.try_cmd("VER"), "VER")

    radio.enter_program_mode()
    try:
        _backup_settings(radio, data)
        _backup_channels(radio, data)
    finally:
        radio.exit_program_mode()

    filled = sum(1 for b in data["banks"] for c in b["channels"] if c is not None)
    log.info("Backup complete — %d / %d channels have data", filled, TOTAL_SLOTS)
    return data


def _backup_settings(radio: Radio, data: dict):
    log.info("Reading system settings...")
    # Only commands confirmed working on UBCD260DN firmware 1.00.07
    for key, cmd in [
        ("backlight",       "BKL"),
        ("com_port",        "COM"),
        ("key_beep",        "KBP"),
        ("opening_message", "OMS"),
        ("priority_mode",   "PRI"),
        ("lcd_contrast",    "CNT"),
        ("lcd_upside_down", "DUD"),
        ("scanner_options", "SCN"),
        ("volume",          "VOL"),
        ("squelch",         "SQL"),
        ("band_scope",      "BSP"),
        ("p25_settings",    "P25"),
    ]:
        _save(data, key, radio, cmd)

    log.info("Reading search settings...")
    for key, cmd in [
        ("search_close_call",   "SCO"),
        ("search_key",          "SHK"),
        ("custom_search_group", "CSG"),
    ]:
        _save(data, key, radio, cmd)

    # Service search — index 1 returns SSP,ERR on UBCD260DN; start from 2
    log.info("Reading service search settings...")
    ssp = {}
    for idx in [2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 15]:
        val = radio.try_cmd(f"SSP,{idx}")
        if val != _UNSUPPORTED:
            ssp[str(idx)] = val
    if ssp:
        data["service_search"] = ssp

    # Custom search (1-10; index 0 = slot 10)
    log.info("Reading custom search settings...")
    csp = {}
    for i in range(1, 11):
        idx = 0 if i == 10 else i
        val = radio.try_cmd(f"CSP,{idx}")
        if val != _UNSUPPORTED:
            csp[str(i)] = val
    if csp:
        data["custom_search"] = csp

    log.info("Reading weather settings...")
    _save(data, "weather", radio, "WXS")
    same = {}
    for i in range(1, 6):
        val = radio.try_cmd(f"SGP,{i}")
        if val != _UNSUPPORTED:
            same[str(i)] = val
    if same:
        data["same_groups"] = same

    log.info("Reading tone-out settings...")
    ton = {}
    for i in range(1, 11):
        idx = 0 if i == 10 else i
        val = radio.try_cmd(f"TON,{idx}")
        if val != _UNSUPPORTED:
            ton[str(i)] = val
    if ton:
        data["tone_out"] = ton

    log.info("Reading default band coverage...")
    dbc = {}
    for i in range(1, 32):
        val = radio.try_cmd(f"DBC,{i}")
        if val != _UNSUPPORTED:
            dbc[str(i)] = val
    if dbc:
        data["default_band_coverage"] = dbc

    log.info("Reading global lockout frequencies...")
    glf = []
    while True:
        val = radio.try_cmd("GLF")
        if val == _UNSUPPORTED:
            break
        frq = Radio.strip_prefix(val, "GLF")
        if frq == "-1":
            break
        glf.append(frq)
    data["global_lockout_freqs"] = glf

    log.info("Reading IF exchange frequencies...")
    gie = []
    while True:
        val = radio.try_cmd("GIE")
        if val == _UNSUPPORTED:
            break
        frq = Radio.strip_prefix(val, "GIE")
        if frq == "-1":
            break
        gie.append(frq)
    data["if_exchange_freqs"] = gie


def _backup_channels(radio: Radio, data: dict):
    """
    Read all 1000 channel slots.
    CIN response format: CIN,<slot>,<NAME>,<FRQ>,<MOD>,<CTCSS/DCS>,<TLOCK>,
                         <LOUT>,<PRI>,<ATT>,<ALT>,<ALTL>,<REV>,<FWD>,<SYS>,
                         <GRP>,<RECORD>,<AUDIO_TYPE>,<P25NAC>,<NUMBER_TAG>,
                         <ALT_COLOR>,<ALT_PATTERN>,<VOL_OFFSET>
    Slots where FRQ == 00000000 are empty; stored as null.
    """
    log.info("Reading channel memories (10 banks × 100 channels)...")
    banks = []

    for bank in range(NUM_BANKS):
        channels = []
        filled   = 0
        base     = bank * CH_PER_BANK

        for ch in range(CH_PER_BANK):
            idx = base + ch
            val = radio.try_cmd(f"CIN,{idx}")
            if val == _UNSUPPORTED:
                channels.append(None)
                continue
            if _cin_is_empty(val):
                channels.append(None)
            else:
                channels.append(val)
                filled += 1

        banks.append({"bank": bank, "channels": channels})
        log.info("  Bank %d: %3d / %d channels filled", bank, filled, CH_PER_BANK)

    data["banks"] = banks


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore(radio: Radio, data: dict):
    radio.enter_program_mode()
    try:
        _restore_settings(radio, data)
        _restore_channels(radio, data)
    finally:
        radio.exit_program_mode()
    log.info("Restore complete!")


def _restore_settings(radio: Radio, data: dict):
    log.info("Restoring system settings...")
    for key, cmd_prefix in [
        ("key_beep",          "KBP,"),
        ("opening_message",   "OMS,"),
        ("priority_mode",     "PRI,"),
        ("lcd_contrast",      "CNT,"),
        ("lcd_upside_down",   "DUD,"),
        ("scanner_options",   "SCN,"),
        ("volume",            "VOL,"),
        ("squelch",           "SQL,"),
        ("band_scope",        "BSP,"),
    ]:
        _restore_setting(radio, cmd_prefix, data, key)

    log.info("Restoring search settings...")
    for key, cmd_prefix in [
        ("search_close_call",   "SCO,"),
        ("search_key",          "SHK,"),
        ("custom_search_group", "CSG,"),
    ]:
        _restore_setting(radio, cmd_prefix, data, key)

    if "service_search" in data:
        log.info("Restoring service search settings...")
        for idx, resp in data["service_search"].items():
            # resp already contains the index e.g. "SSP,2,2,0,0,400" — send as-is
            radio.cmd_ok(resp)

    if "custom_search" in data:
        log.info("Restoring custom search settings...")
        for i in range(1, 11):
            key = str(i)
            if key in data["custom_search"]:
                # resp already contains the index e.g. "CSP,1,Custom 1,..." — send as-is
                radio.cmd_ok(data["custom_search"][key])

    log.info("Restoring weather settings...")
    _restore_setting(radio, "WXS,", data, "weather")
    if "same_groups" in data:
        for idx, resp in data["same_groups"].items():
            # resp already contains index e.g. "SGP,1,SAME 1,..." — send as-is
            radio.cmd_ok(resp)

    if "tone_out" in data:
        log.info("Restoring tone-out settings...")
        for key, resp in data["tone_out"].items():
            # resp already contains index e.g. "TON,1,Tone-Out 1,..." — send as-is
            radio.cmd_ok(resp)

    if "default_band_coverage" in data:
        log.info("Restoring default band coverage...")
        for band_no, resp in data["default_band_coverage"].items():
            # resp already contains index e.g. "DBC,1,500,FM" — send as-is
            radio.cmd_ok(resp)

    for frq in data.get("global_lockout_freqs", []):
        radio.cmd_ok(f"LOF,{frq}")

    for frq in data.get("if_exchange_freqs", []):
        radio.cmd_ok(f"RIE,{frq}")

    # Backlight last (cosmetic)
    _restore_setting(radio, "BKL,", data, "backlight")


def _restore_channels(radio: Radio, data: dict):
    """
    Write non-empty channel slots back via CIN set-command.

    The UBCD260DN CIN get-response has exactly 21 fields:
      CIN,slot,NAME,FRQ,MOD,CTCSS/DCS,TLOCK,LOUT,PRI,ATT,ALT,ALTL,
      REV,FWD,SYS,GRP,RECORD,AUDIO_TYPE,P25NAC,NUMBER_TAG,ALT_COLOR

    The set-command accepts the same 21-field format verbatim.
    REV/FWD/SYS/GRP are ignored by the radio on set (internal indices),
    so replaying them from the backup is safe and keeps the field count correct.
    """
    banks = data.get("banks", [])
    if not banks:
        log.info("No channel data in backup — skipping.")
        return

    log.info("Restoring channel memories...")
    total = 0

    for bank_data in banks:
        bank     = bank_data["bank"]
        channels = bank_data["channels"]
        written  = 0

        for val in channels:
            if val is None:
                continue
            # val is the full stored get-response e.g. "CIN,1,OH6DMR,01455750,..."
            # Send it verbatim — the radio accepts its own get format as a set command.
            if radio.cmd_ok(val):
                written += 1

        log.info("  Bank %d: %d channels restored", bank, written)
        total += written

    log.info("Channel restore complete — %d channels written", total)


# ---------------------------------------------------------------------------
# Info
# ---------------------------------------------------------------------------

def show_info(radio: Radio):
    def _q(cmd):
        val = radio.try_cmd(cmd)
        return "(not supported)" if val == _UNSUPPORTED else Radio.strip_prefix(val, cmd.split(",")[0])

    print(f"\n{'='*52}")
    print(f"  UBCD260DN Radio Info")
    print(f"{'='*52}")
    print(f"  Model    : {_q('MDL')}")
    print(f"  Firmware : {_q('VER')}")

    radio.enter_program_mode()
    try:
        filled = 0
        for slot in range(TOTAL_SLOTS):
            val = radio.try_cmd(f"CIN,{slot}")
            if val != _UNSUPPORTED and not _cin_is_empty(val):
                filled += 1

        print(f"  {'Channels':<10}: {filled} / {TOTAL_SLOTS} slots used")
        for label, cmd in [
            ("Volume",   "VOL"),
            ("Squelch",  "SQL"),
            ("Backlight","BKL"),
            ("Com port", "COM"),
        ]:
            print(f"  {label:<10}: {_q(cmd)}")
    finally:
        radio.exit_program_mode()
    print()


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def probe_commands(radio: Radio):
    """Test every known command and show what the UBCD260DN accepts."""

    outside_prg = [
        "MDL", "VER", "STS", "GLG", "PWR", "VOL", "SQL",
    ]

    inside_prg = [
        # Settings
        "BKL", "COM", "KBP", "OMS", "PRI", "AGV", "CNT", "DUD",
        "SCN", "VOL", "SQL", "GDO", "BSP", "QSL",
        # BCD996XT linked-list navigation (likely unsupported)
        "SCT", "SIH", "SIT", "RMB", "MEM",
        "SIN,0", "TRN,0", "QGL,0", "GIN,0", "TIN,0", "TFQ,0",
        "SIF,0", "MCP,0", "ABP,0", "FWD,0", "REV,0",
        # Flat channel access
        "CIN,0", "CIN,100", "CIN,500", "CIN,999",
        # Search / CC
        "SCO", "CLC", "SHK", "CSG", "BBS,1",
        "SSP,1", "SSP,2", "CSP,1", "CBP,1",
        # Weather
        "WXS", "SGP,1",
        # Tone-Out
        "TON,1",
        # Band
        "DBC,1",
        # Lockout / IF
        "GLF", "GIE",
        # Location alerts
        "LIH,POI", "LIH,DROAD",
        # GPS / P25
        "GGA", "RMC", "P25",
    ]

    print(f"\n{'='*62}")
    print(f"  UBCD260DN Command Probe")
    print(f"{'='*62}")

    print(f"\n--- Outside Program Mode ---")
    for cmd in outside_prg:
        raw  = radio._send(cmd)
        mark = "✔" if raw not in ("ERR", "NG", "FER", "ORER", "") else "✘"
        print(f"  {mark} {cmd:<18} → {raw!r}")

    print(f"\n--- Inside Program Mode ---")
    radio.enter_program_mode()
    try:
        for cmd in inside_prg:
            raw  = radio._send(cmd)
            mark = "✔" if raw not in ("ERR", "NG", "FER", "ORER", "") else "✘"
            print(f"  {mark} {cmd:<18} → {raw!r}")
    finally:
        radio.exit_program_mode()
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="UBCD260DN Backup & Restore Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "action", choices=["backup", "restore", "info", "probe"],
        help="backup / restore / info / probe",
    )
    parser.add_argument("--port", "-p", default="/dev/ttyACM0",
                        help="Serial port  (default: /dev/ttyACM0)")
    parser.add_argument("--baud", "-b", type=int, default=Radio.DEFAULT_BAUD,
                        help=f"Baud rate  (default: {Radio.DEFAULT_BAUD})")
    parser.add_argument("--out", "-o", default="UBCD260DN_backup.json",
                        help="Output backup file  (default: UBCD260DN_backup.json)")
    parser.add_argument("--file", "-f", default="UBCD260DN_backup.json",
                        help="Input file for restore  (default: UBCD260DN_backup.json)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show every serial command")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print(f"\nUBCD260DN Backup/Restore Tool")
    print(f"Port: {args.port}   Baud: {args.baud}")
    print()

    try:
        with Radio(args.port, args.baud) as radio:

            if args.action == "probe":
                probe_commands(radio)

            elif args.action == "info":
                show_info(radio)

            elif args.action == "backup":
                log.info("Starting backup...")
                bd       = backup(radio)
                out_path = Path(args.out)
                out_path.write_text(json.dumps(bd, indent=2), encoding="utf-8")
                filled   = sum(1 for b in bd["banks"] for c in b["channels"] if c)
                size_kb  = out_path.stat().st_size / 1024
                print(f"\n✔  Backup saved: {out_path}  ({size_kb:.1f} KB)")
                print(f"   Model           : {bd.get('model', '?')}")
                print(f"   Channels backed : {filled} / {TOTAL_SLOTS}  (empty slots skipped)")
                print(f"   Global L/O freqs: {len(bd.get('global_lockout_freqs', []))}")

            elif args.action == "restore":
                file_path = Path(args.file)
                if not file_path.exists():
                    print(f"ERROR: File not found: {file_path}")
                    sys.exit(1)
                bd     = json.loads(file_path.read_text(encoding="utf-8"))
                filled = sum(1 for b in bd.get("banks", []) for c in b["channels"] if c)
                print(f"Backup timestamp   : {bd['meta'].get('timestamp', '?')}")
                print(f"Backed-up model    : {bd.get('model', '?')}")
                print(f"Channels to restore: {filled}")
                ans = input("\nProceed? This will OVERWRITE the radio. [y/N] ")
                if ans.strip().lower() != "y":
                    print("Aborted.")
                    sys.exit(0)
                restore(radio, bd)
                print("\n✔  Restore complete!")

    except serial.SerialException as e:
        print(f"\nERROR: Cannot open {args.port}: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
