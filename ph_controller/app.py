"""
app.py -- Flask app and API routes.
Run: python3 app.py   then open http://<pi-ip>:8080
"""

from flask import Flask, jsonify, render_template, request

import config as cfg_mod
import sensors
from controller import controller

app = Flask(__name__)


# ── Pages ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/config")
def config_page():
    return render_template("config.html")


# ── Dashboard API ─────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    try:
        return jsonify(controller.get_state())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/target", methods=["POST"])
def api_target():
    try:
        data = request.get_json(force=True)
        ph = round(float(data["target_ph"]), 2)
        if not 0.0 <= ph <= 14.0:
            return jsonify({"error": "pH must be 0-14"}), 400
        controller.set_target(ph)
        return jsonify({"target_ph": ph})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/pump/start", methods=["POST"])
def api_start():
    try:
        controller.start()
        return jsonify({"status": "running"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pump/pause", methods=["POST"])
def api_pause():
    try:
        controller.pause()
        return jsonify({"status": "paused"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pump/stop", methods=["POST"])
def api_stop():
    try:
        controller.stop()
        return jsonify({"status": "stopped"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/debug")
def api_debug():
    try:
        state = controller.get_state()
        state["thread_alive"] = (
            controller._thread is not None and controller._thread.is_alive()
        )
        state["config"] = cfg_mod.load()
        return jsonify(state)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Config API ────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_config_get():
    try:
        return jsonify(cfg_mod.load())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/config", methods=["POST"])
def api_config_post():
    try:
        data = request.get_json(force=True)
        cfg  = cfg_mod.load()
        for k in ("ph_addr", "pump1_addr", "pump2_addr", "i2c_bus"):
            if k in data:
                v = int(data[k])
                if k != "i2c_bus" and not (1 <= v <= 127):
                    return jsonify({"error": f"{k} must be 1-127"}), 400
                cfg[k] = v
        for k in ("deadband", "dose_ml", "poll_sec"):
            if k in data:
                cfg[k] = float(data[k])
        cfg_mod.save(cfg)
        controller.reload_config()
        return jsonify(cfg)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── Calibration API ───────────────────────────────────────────────

@app.route("/api/calibrate/reading")
def api_cal_reading():
    """Calibration info for the config page.
    pH comes from the controller's always-running background thread
    (controller.current_ph) -- no extra I2C read, no bus conflict."""
    try:
        cfg  = cfg_mod.load()
        ph   = controller.current_ph          # already read by background thread
        info = sensors.get_calibration_info(cfg["ph_addr"], cfg["i2c_bus"])
        return jsonify({"current_ph": ph, **info})
    except Exception as exc:
        return jsonify({"error": str(exc), "current_ph": None,
                        "points": None, "slope": None})


@app.route("/api/calibrate/<point>", methods=["POST"])
def api_calibrate(point):
    try:
        cfg  = cfg_mod.load()
        addr = cfg["ph_addr"]
        bus  = cfg["i2c_bus"]

        if point == "clear":
            ok = sensors.clear_calibration(addr, bus)
            return jsonify({"ok": ok})

        defaults = {"mid": 7.0, "low": 4.0, "high": 10.0}
        if point not in defaults:
            return jsonify({"error": f"unknown point '{point}'"}), 400

        data  = request.get_json(force=True) or {}
        value = float(data.get("value", defaults[point]))
        fns   = {
            "mid":  sensors.calibrate_mid,
            "low":  sensors.calibrate_low,
            "high": sensors.calibrate_high,
        }
        ok = fns[point](value, addr, bus)
        return jsonify({"ok": ok, "point": point, "value": value})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)

