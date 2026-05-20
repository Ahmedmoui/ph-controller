"""
sensors.py -- pH sensor using EZO-pH over I2C.
Creates a fresh EZOPH instance per call (thread-safe; overhead negligible vs 900 ms read).
Falls back to a sine-wave stub when ezo_i2c is unavailable (non-Pi dev machines).
"""

import datetime
import math
import threading
import time


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

try:
    from hardware.ezo_i2c import EZOPH
    _HW = True
    print(f"[{_ts()}] SENSOR  ezo_i2c loaded -- using real EZO-pH hardware")
except Exception as _e:
    _HW = False
    print(f"[{_ts()}] SENSOR  ezo_i2c not available ({_e}) -- using stub")

_i2c_lock = threading.Lock()


# ── Demo simulation ─────────────────────────────────────────────

def sim_ph(target: float) -> float:
    """Sine wave that oscillates ±2.0 pH around target, one full cycle per 40 s."""
    ph = round(target + 2.0 * math.sin(math.pi * time.time() / 20.0), 3)
    print(f"[{_ts()}] SENSOR  sim pH = {ph:.3f}  (target={target:.1f})")
    return ph


# ── Core read ────────────────────────────────────────────────────

def get_ph(address: int = 99, bus: int = 1) -> float:
    if not _HW:
        ph = round(6.5 + 0.4 * math.sin(time.time() / 20.0), 3)
        print(f"[{_ts()}] SENSOR  stub pH = {ph:.3f}")
        return ph
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            ph = s.read_ph()
    if ph is None:
        raise IOError(f"EZO-pH 0x{address:02X} returned no data")
    print(f"[{_ts()}] SENSOR  pH = {ph:.3f}  (I2C 0x{address:02X} bus {bus})")
    return ph


# ── Calibration ──────────────────────────────────────────────────

def calibrate_mid(value: float, address: int = 99, bus: int = 1) -> bool:
    if not _HW:
        print(f"[{_ts()}] SENSOR  stub Cal,mid,{value}")
        return True
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            ok = s.calibrate_mid(value)
    print(f"[{_ts()}] SENSOR  Cal,mid,{value} -> {ok}")
    return ok


def calibrate_low(value: float, address: int = 99, bus: int = 1) -> bool:
    if not _HW:
        print(f"[{_ts()}] SENSOR  stub Cal,low,{value}")
        return True
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            ok = s.calibrate_low(value)
    print(f"[{_ts()}] SENSOR  Cal,low,{value} -> {ok}")
    return ok


def calibrate_high(value: float, address: int = 99, bus: int = 1) -> bool:
    if not _HW:
        print(f"[{_ts()}] SENSOR  stub Cal,high,{value}")
        return True
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            ok = s.calibrate_high(value)
    print(f"[{_ts()}] SENSOR  Cal,high,{value} -> {ok}")
    return ok


def clear_calibration(address: int = 99, bus: int = 1) -> bool:
    if not _HW:
        print(f"[{_ts()}] SENSOR  stub Cal,clear")
        return True
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            ok = s.clear_calibration()
    print(f"[{_ts()}] SENSOR  Cal,clear -> {ok}")
    return ok


def get_calibration_info(address: int = 99, bus: int = 1) -> dict:
    if not _HW:
        return {"points": 0, "slope": None}
    with _i2c_lock:
        with EZOPH(address=address, bus=bus) as s:
            points = s.get_calibration_points()
            slope  = s.get_slope()
    return {
        "points": points,
        "slope": {
            "acid_pct": slope.acid_pct,
            "base_pct": slope.base_pct,
            "zero_mv":  slope.zero_mv,
        } if slope else None,
    }
