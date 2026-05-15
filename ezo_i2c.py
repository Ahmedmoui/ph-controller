"""
ezo_i2c.py -- Atlas Scientific EZO I2C driver
Covers: EZO-pH (V6.1) and EZO-PMP (V3.0)
I2C only -- UART mode not supported.

Quick start:
    from ezo_i2c import EZOPH, EZOPump, scan_ezo_bus

    ph   = EZOPH(address=99, bus=1)
    pump = EZOPump(address=103, bus=1)
    print(ph.read_ph())
    pump.dispense(1.0)
"""

from __future__ import annotations

import fcntl
import io
import time
from dataclasses import dataclass
from typing import Optional

_I2C_SLAVE = 0x0703

STATUS_OK      = 1
STATUS_SYNTAX  = 2
STATUS_PENDING = 254
STATUS_NO_DATA = 255

_DELAY_READ    = 0.9
_DELAY_CAL_PH  = 0.9
_DELAY_DEFAULT = 0.3
_READ_LEN = 40


@dataclass
class DeviceInfo:
    device_type: str
    firmware: str


@dataclass
class DeviceStatus:
    restart_reason: str
    voltage: float


@dataclass
class PHSlope:
    acid_pct: float
    base_pct: float
    zero_mv: float


@dataclass
class DispenseStatus:
    volume: str
    pumping: bool


class EZOBase:
    """
    I2C transport and universal commands for all Atlas Scientific EZO modules.

    Protocol: send command + null byte, wait processing delay, read response.
    Response first byte = status: 1=OK, 2=syntax error, 254=processing, 255=no data.
    All commands are case-insensitive ASCII. Commands not marked otherwise use 300 ms.

    NOTE on certain commands in I2C mode:
      sleep()        -- do NOT read status byte after sending (per datasheet)
      factory_reset()-- no response given, device reboots instantly
      set_i2c_address()-- no response given, device reboots instantly
    """

    STATUS_OK      = STATUS_OK
    STATUS_SYNTAX  = STATUS_SYNTAX
    STATUS_PENDING = STATUS_PENDING
    STATUS_NO_DATA = STATUS_NO_DATA

    def __init__(self, address: int, bus: int = 1, name: str = ""):
        self.address = address
        self.bus     = bus
        self.name    = name or f"0x{address:02X}"
        self._fd     = io.open(f"/dev/i2c-{bus}", "r+b", buffering=0)
        self._select(address)

    def _select(self, addr: int) -> None:
        fcntl.ioctl(self._fd, _I2C_SLAVE, addr)

    def send(self, cmd: str) -> None:
        self._fd.write((cmd + "\x00").encode("latin-1"))

    def recv(self, length: int = _READ_LEN) -> tuple[int, str]:
        raw = self._fd.read(length)
        if not raw:
            return STATUS_NO_DATA, ""
        status = raw[0]
        data   = bytes(b & 0x7F for b in raw[1:])
        text   = data.split(b"\x00", 1)[0].decode("latin-1").strip()
        return status, text

    def query(self, cmd: str, delay: float = _DELAY_DEFAULT) -> tuple[int, str]:
        """Send cmd, wait, read response. Returns (STATUS_NO_DATA, "") on I2C bus errors."""
        try:
            self.send(cmd)
            time.sleep(delay)
            return self.recv()
        except OSError as exc:
            return STATUS_NO_DATA, ""

    def close(self) -> None:
        self._fd.close()

    def __enter__(self) -> "EZOBase":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(addr={self.address}, bus={self.bus}, name={self.name!r})"

    # ---- Universal commands ------------------------------------------------

    def get_info(self) -> Optional[DeviceInfo]:
        """i -- device type and firmware. Response: ?i,pH,1.98"""
        status, data = self.query("i")
        if status != STATUS_OK:
            return None
        parts = data.split(",")
        if len(parts) >= 3:
            return DeviceInfo(device_type=parts[1].strip(), firmware=parts[2].strip())
        return None

    def get_status(self) -> Optional[DeviceStatus]:
        """Status -- last restart reason and VCC voltage. Response: ?Status,P,5.038
        Reason: P=power-on, S=software, B=brown-out, W=watchdog, U=unknown."""
        status, data = self.query("Status")
        if status != STATUS_OK:
            return None
        parts = data.split(",")
        if len(parts) >= 3:
            try:
                return DeviceStatus(restart_reason=parts[1].strip(), voltage=float(parts[2]))
            except ValueError:
                pass
        return None

    def set_led(self, on: bool) -> bool:
        """L,1 / L,0 -- LED on or off."""
        status, _ = self.query(f"L,{'1' if on else '0'}")
        return status == STATUS_OK

    def get_led(self) -> Optional[bool]:
        """L,? -- True=on, False=off."""
        status, data = self.query("L,?")
        if status != STATUS_OK:
            return None
        return data.split(",")[-1].strip() == "1"

    def find(self) -> bool:
        """Find -- blink LED white rapidly for ~10 s to locate device. Any command stops it."""
        status, _ = self.query("Find")
        return status == STATUS_OK

    def sleep(self) -> None:
        """Sleep -- enter low-power mode. Do NOT read status byte after this command.
        Any I2C write wakes the device."""
        self.send("Sleep")

    def wake(self) -> None:
        """Wake a sleeping device: send a dummy byte then wait 10 ms."""
        try:
            self._fd.write(b"\x00")
        except OSError:
            pass
        time.sleep(0.01)

    def factory_reset(self) -> None:
        """Factory -- restore defaults (clears cal, name, LED). I2C address unchanged.
        No response in I2C mode; device reboots immediately."""
        self.send("Factory")

    def set_i2c_address(self, new_addr: int) -> None:
        """I2C,n -- change address (1-127) and reboot. No response; device reboots immediately.
        Create a new instance at new_addr to continue: e.g. EZOPH(new_addr)"""
        if not 1 <= new_addr <= 127:
            raise ValueError(f"I2C address must be 1-127, got {new_addr}")
        self.send(f"I2C,{new_addr}")

    def set_name(self, name: str) -> bool:
        """Name,xxx -- store label (max 16 chars, no spaces)."""
        if len(name) > 16 or " " in name:
            raise ValueError("Name must be <=16 chars with no spaces")
        status, _ = self.query(f"Name,{name}")
        return status == STATUS_OK

    def clear_name(self) -> bool:
        """Name, -- clear the stored name."""
        status, _ = self.query("Name,")
        return status == STATUS_OK

    def get_name(self) -> Optional[str]:
        """Name,? -- retrieve the stored name. Response: ?Name,zzt"""
        status, data = self.query("Name,?")
        if status != STATUS_OK:
            return None
        parts = data.split(",")
        return parts[-1].strip() if len(parts) >= 2 else ""

    def set_plock(self, enabled: bool) -> bool:
        """Plock,1/0 -- lock/unlock protocol to I2C only (prevents Baud/UART switching)."""
        status, _ = self.query(f"Plock,{'1' if enabled else '0'}")
        return status == STATUS_OK

    def get_plock(self) -> Optional[bool]:
        """Plock,? -- True if locked to I2C."""
        status, data = self.query("Plock,?")
        if status != STATUS_OK:
            return None
        return data.split(",")[-1].strip() == "1"


class EZOPH(EZOBase):
    """
    Atlas Scientific EZO-pH circuit (datasheet V6.1).
    Default I2C address: 99 (0x63). VCC: 3.3-5.5V. Range: 0.001-14.000. Accuracy: +/-0.002.

    Calibration order (mid-point always first):
        ph.calibrate_mid(7.0)    # soak in pH 7 buffer, wait for stable readings
        ph.calibrate_low(4.0)    # rinse with DI water, soak in pH 4 buffer
        ph.calibrate_high(10.0)  # rinse with DI water, soak in pH 10 buffer (optional)

    WARNING: calling calibrate_mid() on an already-calibrated probe clears all
    existing calibration data. Full recalibration is then required.

    Temperature compensation defaults to 25 deg C and is NOT retained after power cycle.
    """

    DEFAULT_ADDRESS = 99

    def __init__(self, address: int = DEFAULT_ADDRESS, bus: int = 1, name: str = "pH"):
        super().__init__(address, bus, name)

    def read_ph(self) -> Optional[float]:
        """R -- take a single pH reading (900 ms). Returns float e.g. 7.230."""
        status, data = self.query("R", delay=_DELAY_READ)
        if status == STATUS_OK:
            try:
                return float(data)
            except ValueError:
                pass
        return None

    def read_ph_with_temp(self, temp_c: float) -> Optional[float]:
        """RT,n -- set temperature compensation AND take a reading in one step (900 ms).
        More efficient than set_temperature() + read_ph() when temp changes often.
        Compensation is NOT retained after power cycle."""
        status, data = self.query(f"RT,{temp_c:.2f}", delay=_DELAY_READ)
        if status == STATUS_OK:
            try:
                return float(data)
            except ValueError:
                pass
        return None

    # ---- Calibration -------------------------------------------------------

    def calibrate_mid(self, value: float = 7.0) -> bool:
        """Cal,mid,n -- single-point or midpoint calibration (900 ms). Always do first.
        Calling this on an already-calibrated probe clears all other calibration points."""
        status, _ = self.query(f"Cal,mid,{value:.2f}", delay=_DELAY_CAL_PH)
        return status == STATUS_OK

    def calibrate_low(self, value: float = 4.0) -> bool:
        """Cal,low,n -- low (acid) calibration point (900 ms). Do after calibrate_mid."""
        status, _ = self.query(f"Cal,low,{value:.2f}", delay=_DELAY_CAL_PH)
        return status == STATUS_OK

    def calibrate_high(self, value: float = 10.0) -> bool:
        """Cal,high,n -- high (base) calibration point (900 ms). Do after calibrate_low."""
        status, _ = self.query(f"Cal,high,{value:.2f}", delay=_DELAY_CAL_PH)
        return status == STATUS_OK

    def get_calibration_points(self) -> Optional[int]:
        """Cal,? -- number of calibration points stored: 0 (none), 1, 2, or 3."""
        status, data = self.query("Cal,?")
        if status != STATUS_OK:
            return None
        try:
            return int(data.split(",")[-1])
        except ValueError:
            return None

    def clear_calibration(self) -> bool:
        """Cal,clear -- erase all calibration data."""
        status, _ = self.query("Cal,clear")
        return status == STATUS_OK

    def export_calibration(self) -> Optional[list[str]]:
        """Export/Export,? -- download calibration as hex strings for backup/transfer."""
        status, info = self.query("Export,?")
        if status != STATUS_OK:
            return None
        try:
            n_strings = int(info.split(",")[0])
        except (ValueError, IndexError):
            return None
        strings: list[str] = []
        for _ in range(n_strings):
            st, chunk = self.query("Export")
            if st != STATUS_OK:
                return None
            if chunk.startswith("*DONE"):
                break
            strings.append(chunk)
        return strings

    def import_calibration(self, strings: list[str]) -> bool:
        """Import,n -- upload calibration strings to a new device. Device reboots on success."""
        for chunk in strings:
            status, _ = self.query(f"Import,{chunk}")
            if status != STATUS_OK:
                return False
        return True

    # ---- Temperature compensation ------------------------------------------

    def set_temperature(self, temp_c: float) -> bool:
        """T,n -- set temperature compensation in deg C (300 ms). Default: 25.0.
        Not retained after power cycle. Use read_ph_with_temp() to set+read in one step."""
        status, _ = self.query(f"T,{temp_c:.2f}")
        return status == STATUS_OK

    def get_temperature(self) -> Optional[float]:
        """T,? -- current temperature compensation value in deg C."""
        status, data = self.query("T,?")
        if status != STATUS_OK:
            return None
        try:
            return float(data.split(",")[-1])
        except ValueError:
            return None

    # ---- Extended pH scale -------------------------------------------------

    def set_extended_scale(self, enabled: bool) -> bool:
        """pHext,1/0 -- enable/disable extended pH scale.
        Normal: 0.000-14.000 (default). Extended: -1.600-15.600 for strong acids/bases."""
        status, _ = self.query(f"pHext,{'1' if enabled else '0'}")
        return status == STATUS_OK

    def get_extended_scale(self) -> Optional[bool]:
        """pHext,? -- True if extended scale is enabled."""
        status, data = self.query("pHext,?")
        if status != STATUS_OK:
            return None
        return data.split(",")[-1].strip() == "1"

    # ---- Slope -------------------------------------------------------------

    def get_slope(self) -> Optional[PHSlope]:
        """Slope,? -- calibration slope report (300 ms).

        acid_pct / base_pct: % of ideal Nernstian slope.
            ~99.7% / ~100.3% = healthy new probe. Below 90% = nearing end-of-life.
        zero_mv: mV at pH 7. New probe <=5 mV; >10 mV causes noticeable errors.
        Uncalibrated probes return 100, 100, 0 (perfect theoretical, indicates no cal).

        Response: ?Slope,99.7,100.3,-0.89
        """
        status, data = self.query("Slope,?")
        if status != STATUS_OK:
            return None
        parts = data.split(",")
        if len(parts) >= 4:
            try:
                return PHSlope(
                    acid_pct=float(parts[1]),
                    base_pct=float(parts[2]),
                    zero_mv=float(parts[3]),
                )
            except ValueError:
                pass
        return None


class EZOPump(EZOBase):
    """
    Atlas Scientific EZO-PMP peristaltic pump (datasheet V3.0).
    Default I2C address: 103 (0x67).

    REQUIRES TWO POWER SUPPLIES:
      - 3.3V-5.5V for the control PCB  (VCC on the data cable)
      - 12V-24V   for the motor        (separate motor power input)

    Max flow rate: ~105 mL/min (with supplied tubing). Min dispense: 0.5 mL.
    Accuracy: +/-1% calibrated, +/-5% uncalibrated.

    All dispense commands acknowledge immediately while the motor runs asynchronously.
    Use is_pumping() or wait_until_done() to track completion.

    Calibration procedure:
        1. Fill tubing with water; tap out all air bubbles while running.
        2. pump.dispense(10.0)
        3. Measure actual output (graduated cylinder or scale; 1g water = 1mL).
        4. pump.calibrate(measured_ml)
    """

    DEFAULT_ADDRESS = 103

    def __init__(self, address: int = DEFAULT_ADDRESS, bus: int = 1, name: str = "PMP"):
        super().__init__(address, bus, name)

    def read_volume(self) -> Optional[float]:
        """R -- current dispensed volume (300 ms).
        Returns partial volume while pumping, final volume when done."""
        status, data = self.query("R")
        if status == STATUS_OK:
            try:
                return float(data)
            except ValueError:
                pass
        return None

    # ---- Dispensing --------------------------------------------------------

    def dispense(self, ml: float) -> bool:
        """D,[ml] -- dispense a specific volume (300 ms to acknowledge).
        Positive=forward, negative=reverse. Minimum: 0.5 mL."""
        status, _ = self.query(f"D,{ml:.2f}")
        return status == STATUS_OK

    def dispense_continuous(self, reverse: bool = False) -> bool:
        """D,* or D,-* -- run continuously at ~105 mL/min until stop() is called.
        Device auto-resets after 20 consecutive days of continuous mode."""
        status, _ = self.query("D,-*" if reverse else "D,*")
        return status == STATUS_OK

    def dispense_over_time(self, ml: float, minutes: float) -> bool:
        """D,[ml],[min] -- dispense ml mL spread over minutes (300 ms).
        Useful for slow drip-style additions to avoid pH spikes."""
        if minutes <= 0:
            raise ValueError("minutes must be > 0")
        status, _ = self.query(f"D,{ml:.2f},{minutes:.2f}")
        return status == STATUS_OK

    def dispense_at_rate(self, ml_per_min: float, duration: "float | str" = "*") -> bool:
        """DC,[ml/min],[min or *] -- constant flow rate (300 ms).
        ml_per_min: desired rate (negative=reverse). Must not exceed calibrated max.
                    If too fast the device ignores the command and returns *TOOFAST.
        duration:   number of minutes, or '*' to run indefinitely.
        Device auto-resets after 20 consecutive days of continuous mode."""
        if isinstance(duration, str) and duration != "*":
            raise ValueError("duration must be a number or '*'")
        status, _ = self.query(f"DC,{ml_per_min:.2f},{duration}")
        return status == STATUS_OK

    def get_max_flow_rate(self) -> Optional[float]:
        """DC,? -- maximum achievable flow rate in mL/min after calibration.
        Response: ?maxrate,58.5"""
        status, data = self.query("DC,?")
        if status != STATUS_OK:
            return None
        try:
            return float(data.split(",")[-1])
        except ValueError:
            return None

    def get_dispense_status(self) -> Optional[DispenseStatus]:
        """D,? -- current dispense state (300 ms).
        Returns DispenseStatus(volume, pumping):
            volume  = last commanded volume string ('15.00') or '*'
            pumping = True if actively running
        Response: ?D,*,1  or  ?D,-40.50,0"""
        status, data = self.query("D,?")
        if status != STATUS_OK:
            return None
        parts = data.split(",")
        if len(parts) >= 3:
            return DispenseStatus(volume=parts[1].strip(), pumping=(parts[2].strip() == "1"))
        return None

    # ---- Stop / pause ------------------------------------------------------

    def stop(self) -> Optional[float]:
        """X -- stop dispensing immediately (300 ms).
        Returns volume dispensed in the stopped dose, or None on error.
        Response: *DONE,<volume>"""
        status, data = self.query("X")
        if status == STATUS_OK:
            parts = data.split(",")
            try:
                return float(parts[-1])
            except ValueError:
                return 0.0
        return None

    def pause(self) -> bool:
        """P -- pause dispensing; send again to resume (300 ms)."""
        status, _ = self.query("P")
        return status == STATUS_OK

    def get_pause_status(self) -> Optional[bool]:
        """P,? -- True if currently paused, False if running."""
        status, data = self.query("P,?")
        if status != STATUS_OK:
            return None
        return data.split(",")[-1].strip() == "1"

    # ---- Direction ---------------------------------------------------------

    def invert(self) -> bool:
        """Invert -- toggle dispensing direction (retained across power cycles).
        After inverting, D,* runs what was previously the reverse direction."""
        status, _ = self.query("Invert")
        return status == STATUS_OK

    def get_invert(self) -> Optional[bool]:
        """Invert,? -- True if direction is currently inverted."""
        status, data = self.query("Invert,?")
        if status != STATUS_OK:
            return None
        return data.split(",")[-1].strip() == "1"

    # ---- Startup dispense --------------------------------------------------

    def set_startup_dispense(self, volume_or_mode: "float | str") -> bool:
        """Dstart,[ml] / Dstart,* / Dstart,-* -- configure what runs on power-up.
        Pass a float for a fixed volume, '*' for continuous forward, '-*' for continuous reverse."""
        if isinstance(volume_or_mode, (int, float)):
            cmd = f"Dstart,{float(volume_or_mode):.2f}"
        else:
            cmd = f"Dstart,{volume_or_mode}"
        status, _ = self.query(cmd)
        return status == STATUS_OK

    def set_startup_dispense_over_time(self, ml: float, minutes: float) -> bool:
        """Dstart,[ml],[min] -- dose ml mL over minutes at startup."""
        if minutes <= 0:
            raise ValueError("minutes must be > 0")
        status, _ = self.query(f"Dstart,{ml:.2f},{minutes:.2f}")
        return status == STATUS_OK

    def disable_startup_dispense(self) -> bool:
        """Dstart,off -- disable automatic dispensing at startup."""
        status, _ = self.query("Dstart,off")
        return status == STATUS_OK

    def get_startup_dispense(self) -> Optional[str]:
        """Dstart,? -- query the configured startup dispense mode."""
        status, data = self.query("Dstart,?")
        if status != STATUS_OK:
            return None
        parts = data.split(",", 1)
        return parts[1].strip() if len(parts) >= 2 else "0"

    # ---- Volume tracking ---------------------------------------------------

    def get_total_volume(self) -> Optional[float]:
        """TV,? -- session volume dispensed since last clear_volume() (300 ms).
        Lost on power cycle. Negative = net reverse dispensing.
        Response: ?TV,623.00"""
        status, data = self.query("TV,?")
        if status != STATUS_OK:
            return None
        try:
            return float(data.split(",")[-1])
        except ValueError:
            return None

    def get_absolute_total_volume(self) -> Optional[float]:
        """ATV,? -- absolute cumulative volume (300 ms). Also lost on power cycle.
        Response: ?ATV,434.50"""
        status, data = self.query("ATV,?")
        if status != STATUS_OK:
            return None
        try:
            return float(data.split(",")[-1])
        except ValueError:
            return None

    def clear_volume(self) -> bool:
        """Clear -- reset the session (TV) volume counter to 0."""
        status, _ = self.query("Clear")
        return status == STATUS_OK

    # ---- Calibration -------------------------------------------------------

    def calibrate(self, actual_ml: float) -> bool:
        """Cal,v -- single-point volume calibration (300 ms).
        v = volume you measured from the pump output.
        Works for both D,[ml] and D,[ml],[min] modes independently.
        See class docstring for full calibration procedure."""
        status, _ = self.query(f"Cal,{actual_ml:.2f}")
        return status == STATUS_OK

    def get_calibration_status(self) -> Optional[int]:
        """Cal,? -- calibration state: 0=uncalibrated, 1=volume, 2=time, 3=both."""
        status, data = self.query("Cal,?")
        if status != STATUS_OK:
            return None
        try:
            return int(data.split(",")[-1])
        except ValueError:
            return None

    def clear_calibration(self) -> bool:
        """Cal,clear -- erase calibration data."""
        status, _ = self.query("Cal,clear")
        return status == STATUS_OK

    # ---- Output parameters -------------------------------------------------

    def set_output_param(self, param: str, enabled: bool) -> bool:
        """O,[param],[1/0] -- enable/disable a field in continuous output.
        param: 'V' (current volume), 'TV' (session total), 'ATV' (absolute total)."""
        status, _ = self.query(f"O,{param},{'1' if enabled else '0'}")
        return status == STATUS_OK

    def get_output_params(self) -> Optional[str]:
        """O,? -- which output parameters are enabled. e.g. '?,O,V,TV,ATV'"""
        status, data = self.query("O,?")
        if status != STATUS_OK:
            return None
        return data.strip()

    # ---- Pump voltage ------------------------------------------------------

    def get_pump_voltage(self) -> Optional[float]:
        """PV,? -- motor supply voltage in V (300 ms). Normal: 12-24V.
        Response: ?PV,13.86"""
        status, data = self.query("PV,?")
        if status != STATUS_OK:
            return None
        try:
            return float(data.split(",")[-1])
        except ValueError:
            return None

    # ---- Status polling ----------------------------------------------------

    def is_pumping(self) -> bool:
        """True while the pump is actively dispensing (uses D,?)."""
        ds = self.get_dispense_status()
        return ds.pumping if ds is not None else False

    def wait_until_done(
        self, timeout: float = 600.0, poll_interval: float = 1.0
    ) -> Optional[float]:
        """Block until dispensing finishes or timeout expires.
        Returns final session volume (TV,?) in mL, or None on timeout/error.
        timeout: max seconds to wait (default 10 min).
        poll_interval: seconds between D,? status checks (default 1 s)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ds = self.get_dispense_status()
            if ds is None:
                return None
            if not ds.pumping:
                return self.get_total_volume()
            time.sleep(poll_interval)
        return None


def scan_ezo_bus(
    bus: int = 1,
    start: int = 1,
    end: int = 127,
) -> list[tuple[int, DeviceInfo]]:
    """Probe I2C addresses [start, end] for EZO devices.
    Returns list of (address, DeviceInfo) for each responding module.

    Full scan (127 addresses) takes ~40 s at 300 ms per address.
    EZO default addresses cluster around 97-112 (0x61-0x70); scan that range for speed.

    Example:
        for addr, info in scan_ezo_bus(bus=1, start=97, end=112):
            print(f"  0x{addr:02X} ({addr:3d})  {info.device_type}  fw {info.firmware}")
    """
    found: list[tuple[int, DeviceInfo]] = []
    fd = io.open(f"/dev/i2c-{bus}", "r+b", buffering=0)
    try:
        for addr in range(start, end + 1):
            try:
                fcntl.ioctl(fd, _I2C_SLAVE, addr)
                fd.write(("i\x00").encode("latin-1"))
                time.sleep(_DELAY_DEFAULT)
                raw = fd.read(_READ_LEN)
                if raw and raw[0] == STATUS_OK:
                    data  = bytes(b & 0x7F for b in raw[1:])
                    text  = data.split(b"\x00", 1)[0].decode("latin-1").strip()
                    parts = text.split(",")
                    if len(parts) >= 3:
                        found.append((addr, DeviceInfo(
                            device_type=parts[1].strip(),
                            firmware=parts[2].strip(),
                        )))
            except OSError:
                pass
    finally:
        fd.close()
    return found


