"""
pump.py -- EZO-PMP pump control.
Creates a fresh EZOPump instance per call (thread-safe).
Falls back to console-only stub when ezo_i2c is unavailable.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

try:
    from ezo_i2c import EZOPump
    _HW = True
    print(f"[{_ts()}] PUMP    ezo_i2c loaded -- using real EZO-PMP hardware")
except Exception as _e:
    _HW = False
    print(f"[{_ts()}] PUMP    ezo_i2c not available ({_e}) -- using stub")


def dose(address: int, ml: float, bus: int = 1) -> None:
    """Dispense ml mL from the pump at the given I2C address."""
    print(f"[{_ts()}] PUMP    0x{address:02X} dose {ml:.2f} mL")
    if _HW:
        with EZOPump(address=address, bus=bus) as p:
            p.dispense(ml)


def stop(address: int, bus: int = 1) -> None:
    """Stop the pump at the given I2C address."""
    print(f"[{_ts()}] PUMP    0x{address:02X} stop")
    if _HW:
        with EZOPump(address=address, bus=bus) as p:
            p.stop()
