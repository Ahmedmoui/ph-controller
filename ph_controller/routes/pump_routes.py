from flask import Blueprint, jsonify, render_template, request
from controller import controller
from hardware import pump as pump_hw
import config as cfg_mod

bp = Blueprint("pump_routes", __name__)


def _pump_addr(pump_id: int, cfg: dict):
    if pump_id == 1:
        return cfg["pump1_addr"]
    if pump_id == 2:
        return cfg["pump2_addr"]
    return None


def _locked() -> bool:
    """Returns True if the auto-controller is running (manual controls locked)."""
    return controller.status == "running"


@bp.route("/pumps")
def pumps_page():
    return render_template("pumps.html")


@bp.route("/api/pump/<int:pump_id>/status")
def api_pump_status(pump_id):
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        status = pump_hw.get_status(addr, cfg["i2c_bus"])
        status["locked"] = _locked()
        return jsonify(status)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/<int:pump_id>/run", methods=["POST"])
def api_pump_run(pump_id):
    if _locked():
        return jsonify({"error": "controller is running — stop it first"}), 409
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        data    = request.get_json(force=True) or {}
        reverse = bool(data.get("reverse", False))
        ok = pump_hw.run_continuous(addr, reverse, cfg["i2c_bus"])
        return jsonify({"ok": ok, "pump": pump_id, "reverse": reverse})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/<int:pump_id>/stop", methods=["POST"])
def api_pump_stop(pump_id):
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        pump_hw.stop(addr, cfg["i2c_bus"])
        return jsonify({"ok": True, "pump": pump_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/<int:pump_id>/invert", methods=["POST"])
def api_pump_invert(pump_id):
    if _locked():
        return jsonify({"error": "controller is running — stop it first"}), 409
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        ok = pump_hw.invert_direction(addr, cfg["i2c_bus"])
        return jsonify({"ok": ok, "pump": pump_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/<int:pump_id>/dispense", methods=["POST"])
def api_pump_dispense(pump_id):
    if _locked():
        return jsonify({"error": "controller is running — stop it first"}), 409
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        data = request.get_json(force=True) or {}
        ml   = float(data.get("ml", 10.0))
        if ml <= 0:
            return jsonify({"error": "ml must be > 0"}), 400
        ok = pump_hw.dispense_volume(addr, ml, cfg["i2c_bus"])
        return jsonify({"ok": ok, "pump": pump_id, "ml": ml})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/<int:pump_id>/calibrate", methods=["POST"])
def api_pump_calibrate(pump_id):
    if _locked():
        return jsonify({"error": "controller is running — stop it first"}), 409
    try:
        cfg  = cfg_mod.load()
        addr = _pump_addr(pump_id, cfg)
        if addr is None:
            return jsonify({"error": f"invalid pump id {pump_id}"}), 400
        data      = request.get_json(force=True) or {}
        actual_ml = float(data["actual_ml"])
        if actual_ml <= 0:
            return jsonify({"error": "actual_ml must be > 0"}), 400
        ok = pump_hw.calibrate_pump(addr, actual_ml, cfg["i2c_bus"])
        return jsonify({"ok": ok, "pump": pump_id, "actual_ml": actual_ml})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500