import glob
import os

from flask import Blueprint, jsonify, render_template, request, send_from_directory
from controller import controller
import config as cfg_mod

bp = Blueprint("dashboard", __name__)

_SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "sessions")


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/status")
def api_status():
    try:
        return jsonify(controller.get_state())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/target", methods=["POST"])
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


@bp.route("/api/pump/start", methods=["POST"])
def api_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name", "").strip() or None
        controller.start(name)
        return jsonify({"status": "running"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/pause", methods=["POST"])
def api_pause():
    try:
        controller.pause()
        return jsonify({"status": "paused"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/pump/stop", methods=["POST"])
def api_stop():
    try:
        controller.stop()
        return jsonify({"status": "stopped"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/debug")
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


@bp.route("/api/sessions")
def api_sessions():
    try:
        files = []
        for path in sorted(
            glob.glob(os.path.join(_SESSIONS_DIR, "*.csv")), reverse=True
        ):
            stat = os.stat(path)
            files.append({
                "name":     os.path.basename(path),
                "size_kb":  round(stat.st_size / 1024, 1),
                "modified": stat.st_mtime,
            })
        return jsonify(files)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/sessions/<filename>")
def api_session_download(filename):
    if not filename.endswith(".csv") or "/" in filename or ".." in filename:
        return jsonify({"error": "invalid filename"}), 400
    return send_from_directory(
        os.path.abspath(_SESSIONS_DIR), filename, as_attachment=True
    )