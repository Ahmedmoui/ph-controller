"""
hardware/pump.py -- EZO-PMP pump control.
Creates a fresh EZOPump instance per call (thread-safe via _pump_lock).
Falls back to a stub when ezo_i2c is unavailable.
"""

import datetime
import threading

_pump_lock = threading.Lock()

def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

try:
    from hardware.ezo_i2c import EZOPump
    _HW = True
    print(f"[{_ts()}] PUMP    ezo_i2c loaded -- using real EZO-PMP hardware")
except Exception as _e:
    _HW = False
    print(f"[{_ts()}] PUMP    ezo_i2c not available ({_e}) -- using stub")


# ── Auto-dosing (called by controller) ───────────────────────────

def dose(address: int, ml: float, bus: int = 1) -> None:
    """Dispense ml mL. Used by the auto-dosing controller."""
    print(f"[{_ts()}] PUMP    0x{address:02X} dose {ml:.2f} mL")
    if _HW:
        with _pump_lock:
            with EZOPump(address=address, bus=bus) as p:
                p.dispense(ml)


def stop(address: int, bus: int = 1) -> None:
    """Stop the pump immediately."""
    print(f"[{_ts()}] PUMP    0x{address:02X} stop")
    if _HW:
        with _pump_lock:
            with EZOPump(address=address, bus=bus) as p:
                p.stop()


# ── Manual control (called by pump routes) ────────────────────────

def run_continuous(address: int, reverse: bool = False, bus: int = 1) -> bool:
    """Run continuously until stop() is called. Used for priming."""
    direction = "reverse" if reverse else "forward"
    print(f"[{_ts()}] PUMP    0x{address:02X} run continuous {direction}")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.dispense_continuous(reverse=reverse)


def invert_direction(address: int, bus: int = 1) -> bool:
    """Toggle dispensing direction (retained across power cycles)."""
    print(f"[{_ts()}] PUMP    0x{address:02X} invert direction")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.invert()


def dispense_volume(address: int, ml: float, bus: int = 1) -> bool:
    """Dispense a specific volume. Used in calibration step 2."""
    print(f"[{_ts()}] PUMP    0x{address:02X} dispense {ml:.2f} mL")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.dispense(ml)


def calibrate_pump(address: int, actual_ml: float, bus: int = 1) -> bool:
    """Store single-point volume calibration with measured actual_ml."""
    print(f"[{_ts()}] PUMP    0x{address:02X} calibrate actual={actual_ml:.2f} mL")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.calibrate(actual_ml)


def get_status(address: int, bus: int = 1) -> dict:
    """Return pump state: pumping, inverted, cal_status (0-3), voltage."""
    if not _HW:
        return {"pumping": False, "inverted": False, "cal_status": 0, "voltage": None}
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            ds      = p.get_dispense_status()
            inv     = p.get_invert()
            cal     = p.get_calibration_status()
            voltage = p.get_pump_voltage()
    return {
        "pumping":    ds.pumping if ds else False,
        "inverted":   bool(inv),
        "cal_status": cal if cal is not None else 0,
        "voltage":    voltage,
    }