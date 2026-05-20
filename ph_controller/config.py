"""config.py -- Load/save settings from config.json next to this file."""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULTS = {
    "ph_addr":    99,    # EZO-pH  I2C address  (0x63)
    "pump1_addr": 103,   # EZO-PMP acid pump    (0x67)
    "pump2_addr": 114,   # EZO-PMP base pump    (0x72)
    "i2c_bus":    1,
    "deadband":   0.1,
    "dose_ml":    0.5,
    "poll_sec":   2.0,
    "simulate_ph": False,
}


def load() -> dict:
    if os.path.exists(_PATH):
        with open(_PATH) as f:
            saved = json.load(f)
        return {**DEFAULTS, **saved}
    return dict(DEFAULTS)


def save(data: dict) -> None:
    current = load()
    current.update(data)
    with open(_PATH, "w") as f:
        json.dump(current, f, indent=2)
