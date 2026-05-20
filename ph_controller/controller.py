"""
controller.py -- Dosing logic in a background thread.

The reader thread starts immediately on import and runs forever, so the
current pH is always shown on the dashboard -- even when the controller
is stopped and no dosing is happening.

Each session writes a CSV file to ph_controller/sessions/. Readings are
buffered in memory and flushed to disk in batches (BATCH_SIZE rows), with
os.fsync() after each flush to force the kernel to commit to the SD card.
The buffer is also flushed on pause and stop, so a clean shutdown loses
no data. Worst-case power-loss window = BATCH_SIZE * poll_sec seconds.

Status transitions:
  stopped  --start()--> running   (new session CSV opened; thread already running)
  running  --pause()--> paused
  paused   --start()--> running   (resumes; same CSV, no reset)
  any      --stop() --> stopped   (pumps halted; CSV closed)

Pump convention:
  pump 1 = acid  (lowers pH)
  pump 2 = base  (raises pH)
"""

import csv
import datetime
import os
import re
import threading
import time
from collections import deque

from hardware import pump
import sensors
from config import load as load_config

MAX_HISTORY  = 200
BATCH_SIZE   = 10    # rows buffered before flushing to disk
PUMP_MIN_ML  = 0.5   # EZO-PMP hardware minimum dispense volume (datasheet V3.0)
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _proportional_dose(error: float, deadband: float, p_gain: float, max_dose: float) -> float:
    """Return P-controller dose volume in mL.

    error    -- |pH - target|, always > deadband when this is called
    deadband -- no-dose zone half-width (pH units)
    p_gain   -- mL per pH unit of excess error; 0 disables P-control (always max_dose)
    max_dose -- upper cap (dose_ml config setting)

    Result is clamped to [PUMP_MIN_ML, max_dose] so the hardware minimum is
    always respected and the configured maximum is never exceeded.
    """
    if p_gain <= 0:
        return max_dose                           # P-control disabled: always full dose
    effective_error = error - deadband            # excess error beyond the deadband edge
    vol = p_gain * effective_error
    return max(PUMP_MIN_ML, min(max_dose, vol))


class Controller:
    def __init__(self):
        self.lock           = threading.Lock()
        self.cfg            = load_config()
        self.target_ph      = 7.0
        self.current_ph     = None
        self.status         = "stopped"
        self.pump1_state    = "idle"
        self.pump2_state    = "idle"
        self.pump1_dosed    = 0.0
        self.pump2_dosed    = 0.0
        self.history        = deque(maxlen=MAX_HISTORY)
        self._csv_file      = None   # open file handle for the current session
        self._csv_writer    = None
        self._session_start = 0.0
        self._write_buffer  = []     # pending rows awaiting batch flush

        # Thread starts immediately so pH is always read, even when stopped.
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ctrl-loop")
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, name: str = None):
        with self.lock:
            if self.status == "running":
                return
            if self.status == "stopped":
                self.cfg         = load_config()
                self.pump1_dosed = 0.0
                self.pump2_dosed = 0.0
                self.history.clear()
                self._open_session_csv(name)
                print(f"[{_ts()}] CTRL    fresh session started")
            self.status = "running"
            print(f"[{_ts()}] CTRL    status -> running")

    def pause(self):
        with self.lock:
            if self.status != "running":
                return
            self.status = "paused"
            self._stop_pumps()
            self._flush_buffer()   # checkpoint: commit buffered data before pausing
            print(f"[{_ts()}] CTRL    status -> paused")

    def stop(self):
        with self.lock:
            self.status = "stopped"
            self._stop_pumps()
            self._close_session_csv()
            print(f"[{_ts()}] CTRL    status -> stopped")

    def set_target(self, ph: float):
        with self.lock:
            self.target_ph = ph
            print(f"[{_ts()}] CTRL    target pH -> {ph:.1f}")

    def reload_config(self):
        with self.lock:
            self.cfg = load_config()
            print(f"[{_ts()}] CTRL    config reloaded")

    def get_state(self) -> dict:
        with self.lock:
            t0 = self.history[0]["ts"] if self.history else 0
            history_out = [
                {
                    "time":      e["time"],
                    "t_min":     round((e["ts"] - t0) / 60.0, 3),
                    "ph":        e["ph"],
                    "target_ph": e["target_ph"],
                    "pump1_ml":  e["pump1_ml"],
                    "pump2_ml":  e["pump2_ml"],
                }
                for e in self.history
            ]
            return {
                "target_ph":    self.target_ph,
                "current_ph":   self.current_ph,
                "status":       self.status,
                "pump1_state":  self.pump1_state,
                "pump2_state":  self.pump2_state,
                "pump1_dosed":  self.pump1_dosed,
                "pump2_dosed":  self.pump2_dosed,
                "history":        history_out,
                "session_file":   os.path.basename(self._csv_file.name) if self._csv_file else None,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_session_csv(self, name: str = None):
        """Open a new timestamped CSV file. Call with self.lock held."""
        self._write_buffer = []   # discard any stale buffer from a prior session
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            ts_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            if name:
                safe = re.sub(r"[^\w\-]", "_", name.strip())[:40].strip("_")
                filename = f"{safe}_{ts_str}.csv"
            else:
                filename = f"session_{ts_str}.csv"
            path   = os.path.join(SESSIONS_DIR, filename)
            self._csv_file      = open(path, "w", newline="")
            self._csv_writer    = csv.writer(self._csv_file)
            self._csv_writer.writerow(
                ["time", "elapsed_min", "ph", "target_ph", "pump1_acid_ml", "pump2_base_ml"])
            self._session_start = time.time()
            print(f"[{_ts()}] CTRL    session CSV -> {path}")
        except Exception as exc:
            print(f"[{_ts()}] CTRL    could not open session CSV: {exc}")
            self._csv_file   = None
            self._csv_writer = None

    def _close_session_csv(self):
        """Flush write buffer then close the CSV. Call with self.lock held."""
        self._flush_buffer()   # commit any remaining buffered rows
        if self._csv_file:
            try:
                self._csv_file.flush()
                os.fsync(self._csv_file.fileno())
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file   = None
            self._csv_writer = None

    def _flush_buffer(self):
        """Write all buffered rows to disk and fsync. Call with self.lock held.
        On failure the buffer is kept intact so the next flush can retry."""
        if not self._write_buffer:
            return
        if not self._csv_writer:
            self._write_buffer = []   # no writer open; discard stale buffer
            return
        n = len(self._write_buffer)
        try:
            for row in self._write_buffer:
                self._csv_writer.writerow(row)
            self._csv_file.flush()
            os.fsync(self._csv_file.fileno())
            self._write_buffer = []
            print(f"[{_ts()}] CTRL    flushed {n} rows to disk")
        except Exception as exc:
            print(f"[{_ts()}] CTRL    CSV flush error ({n} rows pending): {exc}")
            # Buffer intentionally kept -- will retry on next trigger

    def _stop_pumps(self):
        """Must be called with self.lock held."""
        try:
            pump.stop(self.cfg["pump1_addr"], self.cfg["i2c_bus"])
            pump.stop(self.cfg["pump2_addr"], self.cfg["i2c_bus"])
        except Exception as exc:
            print(f"[{_ts()}] CTRL    stop_pumps error: {exc}")
        self.pump1_state = "idle"
        self.pump2_state = "idle"

    # ------------------------------------------------------------------
    # Background loop -- runs forever (daemon thread)
    # ------------------------------------------------------------------

    def _loop(self):
        print(f"[{_ts()}] CTRL    reader thread started")
        while True:
            with self.lock:
                status   = self.status
                target   = self.target_ph
                deadband = self.cfg["deadband"]
                dose_ml  = self.cfg["dose_ml"]
                p_gain   = self.cfg.get("dose_p_gain", 2.0)
                poll_sec = self.cfg["poll_sec"]
                ph_addr  = self.cfg["ph_addr"]
                p1_addr  = self.cfg["pump1_addr"]
                p2_addr  = self.cfg["pump2_addr"]
                bus      = self.cfg["i2c_bus"]
                simulate = self.cfg.get("simulate_ph", False)

            # Sensor read outside lock (~900 ms on real hardware)
            if simulate:
                ph = sensors.sim_ph(target)
            else:
                try:
                    ph = sensors.get_ph(ph_addr, bus)
                except Exception as exc:
                    print(f"[{_ts()}] CTRL    sensor error: {exc}")
                    time.sleep(poll_sec)
                    continue

            with self.lock:
                self.current_ph = ph
                status   = self.status
                target   = self.target_ph
                deadband = self.cfg["deadband"]
                dose_ml  = self.cfg["dose_ml"]
                p_gain   = self.cfg.get("dose_p_gain", 2.0)

                if status == "running":
                    if ph < target - deadband:
                        try:
                            vol = _proportional_dose(abs(ph - target), deadband, p_gain, dose_ml)
                            pump.dose(p2_addr, vol, bus)
                            self.pump2_dosed += vol
                            self.pump2_state = "dosing"
                            self.pump1_state = "idle"
                        except Exception as exc:
                            print(f"[{_ts()}] CTRL    pump 2 error: {exc}")
                    elif ph > target + deadband:
                        try:
                            vol = _proportional_dose(abs(ph - target), deadband, p_gain, dose_ml)
                            pump.dose(p1_addr, vol, bus)
                            self.pump1_dosed += vol
                            self.pump1_state = "dosing"
                            self.pump2_state = "idle"
                        except Exception as exc:
                            print(f"[{_ts()}] CTRL    pump 1 error: {exc}")
                    else:
                        self.pump1_state = "idle"
                        self.pump2_state = "idle"

                # Record history only during active sessions (not when stopped)
                if status in ("running", "paused"):
                    now   = time.time()
                    entry = {
                        "ts":        now,
                        "time":      datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "ph":        ph,
                        "target_ph": target,
                        "pump1_ml":  self.pump1_dosed,
                        "pump2_ml":  self.pump2_dosed,
                    }
                    self.history.append(entry)

                    # Buffer the row; flush to disk once BATCH_SIZE rows accumulate
                    if self._csv_writer:
                        try:
                            t_min = round((now - self._session_start) / 60.0, 3)
                            self._write_buffer.append([
                                entry["time"], t_min,
                                entry["ph"], entry["target_ph"],
                                entry["pump1_ml"], entry["pump2_ml"],
                            ])
                            if len(self._write_buffer) >= BATCH_SIZE:
                                self._flush_buffer()
                        except Exception as exc:
                            print(f"[{_ts()}] CTRL    CSV buffer error: {exc}")

            time.sleep(poll_sec)


controller = Controller()

