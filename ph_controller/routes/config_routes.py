from flask import Blueprint, jsonify, render_template, request
from controller import controller
import config as cfg_mod
import sensors

bp = Blueprint("config_routes", __name__)


@bp.route("/config")
def config_page():
    return render_template("config.html")


@bp.route("/api/config", methods=["GET"])
def api_config_get():
    try:
        return jsonify(cfg_mod.load())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/config", methods=["POST"])
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


@bp.route("/api/calibrate/reading")
def api_cal_reading():
    try:
        cfg  = cfg_mod.load()
        ph   = controller.current_ph
        info = sensors.get_calibration_info(cfg["ph_addr"], cfg["i2c_bus"])
        return jsonify({"current_ph": ph, **info})
    except Exception as exc:
        return jsonify({"error": str(exc), "current_ph": None,
                        "points": None, "slope": None})


@bp.route("/api/calibrate/<point>", methods=["POST"])
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