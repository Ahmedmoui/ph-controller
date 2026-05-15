"""
controller.py -- Dosing logic in a background thread.

The reader thread starts immediately on import and runs forever, so the
current pH is always shown on the dashboard -- even when the controller
is stopped and no dosing is happening.

Each session writes a CSV file to ph_controller/sessions/ and flushes
after every row, so a power loss loses at most one poll interval of data.

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
import threading
import time
from collections import deque

import pump
import sensors
from config import load as load_config

MAX_HISTORY  = 200
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


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

        # Thread starts immediately so pH is always read, even when stopped.
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ctrl-loop")
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        with self.lock:
            if self.status == "running":
                return
            if self.status == "stopped":
                self.cfg         = load_config()
                self.pump1_dosed = 0.0
                self.pump2_dosed = 0.0
                self.history.clear()
                self._open_session_csv()
                print(f"[{_ts()}] CTRL    fresh session started")
            self.status = "running"
            print(f"[{_ts()}] CTRL    status -> running")

    def pause(self):
        with self.lock:
            if self.status != "running":
                return
            self.status = "paused"
            self._stop_pumps()
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
                    "time":     e["time"],
                    "t_min":    round((e["ts"] - t0) / 60.0, 3),
                    "ph":       e["ph"],
                    "pump1_ml": e["pump1_ml"],
                    "pump2_ml": e["pump2_ml"],
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
                "history":      history_out,
                "session_file": os.path.basename(self._csv_file.name) if self._csv_file else None,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_session_csv(self):
        """Open a new timestamped CSV file. Call with self.lock held."""
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            ts_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path   = os.path.join(SESSIONS_DIR, f"session_{ts_str}.csv")
            self._csv_file      = open(path, "w", newline="")
            self._csv_writer    = csv.writer(self._csv_file)
            self._csv_writer.writerow(
                ["time", "elapsed_min", "ph", "pump1_acid_ml", "pump2_base_ml"])
            self._session_start = time.time()
            print(f"[{_ts()}] CTRL    session CSV -> {path}")
        except Exception as exc:
            print(f"[{_ts()}] CTRL    could not open session CSV: {exc}")
            self._csv_file   = None
            self._csv_writer = None

    def _close_session_csv(self):
        """Flush and close the CSV. Call with self.lock held."""
        if self._csv_file:
            try:
                self._csv_file.flush()
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file   = None
            self._csv_writer = None

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
                poll_sec = self.cfg["poll_sec"]
                ph_addr  = self.cfg["ph_addr"]
                p1_addr  = self.cfg["pump1_addr"]
                p2_addr  = self.cfg["pump2_addr"]
                bus      = self.cfg["i2c_bus"]

            # Sensor read outside lock (~900 ms on real hardware)
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

                if status == "running":
                    if ph < target - deadband:
                        try:
                            pump.dose(p2_addr, dose_ml, bus)
                            self.pump2_dosed += dose_ml
                            self.pump2_state = "dosing"
                            self.pump1_state = "idle"
                        except Exception as exc:
                            print(f"[{_ts()}] CTRL    pump 2 error: {exc}")
                    elif ph > target + deadband:
                        try:
                            pump.dose(p1_addr, dose_ml, bus)
                            self.pump1_dosed += dose_ml
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
                        "ts":       now,
                        "time":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "ph":       ph,
                        "pump1_ml": self.pump1_dosed,
                        "pump2_ml": self.pump2_dosed,
                    }
                    self.history.append(entry)

                    # Write to disk and flush immediately -- power loss loses at most one reading
                    if self._csv_writer:
                        try:
                            t_min = round((now - self._session_start) / 60.0, 3)
                            self._csv_writer.writerow([
                                entry["time"], t_min,
                                entry["ph"], entry["pump1_ml"], entry["pump2_ml"],
                            ])
                            self._csv_file.flush()
                        except Exception as exc:
                            print(f"[{_ts()}] CTRL    CSV write error: {exc}")

            time.sleep(poll_sec)


controller = Controller()
