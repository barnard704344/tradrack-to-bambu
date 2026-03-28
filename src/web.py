"""
Flask Web UI for the TradRack-to-Bambu Bridge.

Provides a live dashboard showing P1S printer status, temperatures,
fans, print progress, and bridge/Happy Hare state. Auto-refreshes
via JSON polling.
"""

import logging
import threading
import time
from typing import Optional

from flask import Flask, Response, jsonify, render_template, request

logger = logging.getLogger(__name__)


def create_app(bambu_client, happy_hare, bridge=None, camera=None):
    """
    Create the Flask app with references to live bridge objects.

    Args:
        bambu_client: BambuMQTTClient instance (for P1S state)
        happy_hare: HappyHareController instance (for MMU state)
        bridge: Bridge instance (for bridge stats), optional
        camera: BambuCamera instance (for video feed), optional
    """
    app = Flask(__name__, template_folder="../templates")

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html", camera_enabled=camera is not None)

    @app.route("/api/camera/snapshot")
    def camera_snapshot():
        """Return the latest JPEG frame."""
        if camera is None:
            return "Camera not enabled", 404
        frame = camera.latest_frame
        if frame is None:
            return "No frame available", 503
        return Response(frame, mimetype="image/jpeg")

    @app.route("/api/camera/stream")
    def camera_stream():
        """MJPEG stream — continuously sends JPEG frames."""
        if camera is None:
            return "Camera not enabled", 404

        def generate():
            last_frame = None
            while True:
                frame = camera.latest_frame
                if frame is not None and frame is not last_frame:
                    last_frame = frame
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" +
                           frame + b"\r\n")
                time.sleep(0.5)

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.route("/api/status")
    def api_status():
        """Return full system status as JSON."""
        # P1S state
        p1s = bambu_client.state
        p1s_data = {
            "connected": bambu_client.is_connected(),
            "status": p1s.status.value,
            "gcode_state": p1s.gcode_state,
            "mc_percent": p1s.mc_percent,
            "mc_remaining_time": p1s.mc_remaining_time,
            "layer_num": p1s.layer_num,
            "total_layers": p1s.total_layers,
            "subtask_name": p1s.subtask_name,
            "bed_temper": p1s.bed_temper,
            "bed_target_temper": p1s.bed_target_temper,
            "nozzle_temper": p1s.nozzle_temper,
            "nozzle_target_temper": p1s.nozzle_target_temper,
            "chamber_temper": p1s.chamber_temper,
            "cooling_fan_speed": p1s.cooling_fan_speed,
            "heatbreak_fan_speed": p1s.heatbreak_fan_speed,
            "big_fan1_speed": p1s.big_fan1_speed,
            "big_fan2_speed": p1s.big_fan2_speed,
            "spd_lvl": p1s.spd_lvl,
            "spd_mag": p1s.spd_mag,
            "nozzle_diameter": p1s.nozzle_diameter,
            "nozzle_type": p1s.nozzle_type,
            "wifi_signal": p1s.wifi_signal,
            "print_error": p1s.print_error,
            "hms": p1s.hms or [],
            "chamber_light": p1s.chamber_light,
        }

        # Happy Hare / Klipper state
        hh_data = {"connected": False}
        try:
            if happy_hare.check_connection():
                mmu_status = happy_hare.get_status()
                hh_data = {
                    "connected": True,
                    "state": mmu_status.state.value,
                    "current_tool": mmu_status.current_tool,
                    "filament_loaded": mmu_status.filament_loaded,
                    "is_homed": mmu_status.is_homed,
                    "gate_status": mmu_status.gate_status,
                    "message": mmu_status.message,
                }
        except Exception:
            pass

        # Bridge state
        bridge_data = {}
        if bridge:
            bridge_data = bridge.get_stats()

        return jsonify({
            "p1s": p1s_data,
            "happy_hare": hh_data,
            "bridge": bridge_data,
        })

    @app.route("/api/light/toggle", methods=["POST"])
    def toggle_light():
        """Toggle the P1S chamber light."""
        current = bambu_client.state.chamber_light
        ok = bambu_client.set_chamber_light(not current)
        return jsonify({"ok": ok, "light": not current})

    # --- MMU Page ---

    @app.route("/mmu")
    def mmu_page():
        return render_template("mmu.html")

    @app.route("/api/mmu/status")
    def mmu_status():
        """Full MMU status for the MMU dashboard."""
        try:
            data = happy_hare.get_extended_status()
        except Exception:
            data = {"connected": False}
        return jsonify(data)

    @app.route("/api/mmu/home", methods=["POST"])
    def mmu_home():
        ok = happy_hare.home()
        return jsonify({"ok": ok})

    @app.route("/api/mmu/select", methods=["POST"])
    def mmu_select():
        gate = request.json.get("gate")
        if gate is None:
            return jsonify({"ok": False, "error": "gate required"}), 400
        ok = happy_hare.select_gate(int(gate))
        return jsonify({"ok": ok})

    @app.route("/api/mmu/change_tool", methods=["POST"])
    def mmu_change_tool():
        tool = request.json.get("tool")
        if tool is None:
            return jsonify({"ok": False, "error": "tool required"}), 400
        ok = happy_hare.change_tool(int(tool))
        return jsonify({"ok": ok})

    @app.route("/api/mmu/load", methods=["POST"])
    def mmu_load():
        ok = happy_hare.load_filament()
        return jsonify({"ok": ok})

    @app.route("/api/mmu/unload", methods=["POST"])
    def mmu_unload():
        ok = happy_hare.unload_filament()
        return jsonify({"ok": ok})

    @app.route("/api/mmu/eject", methods=["POST"])
    def mmu_eject():
        ok = happy_hare.eject_filament()
        return jsonify({"ok": ok})

    @app.route("/api/mmu/servo", methods=["POST"])
    def mmu_servo():
        pos = request.json.get("pos")
        if pos == "up":
            ok = happy_hare.servo_up()
        elif pos == "down":
            ok = happy_hare.servo_down()
        else:
            return jsonify({"ok": False, "error": "pos must be 'up' or 'down'"}), 400
        return jsonify({"ok": ok})

    @app.route("/api/mmu/recover", methods=["POST"])
    def mmu_recover():
        ok = happy_hare.recover()
        return jsonify({"ok": ok})

    return app


def start_web_server(app, host="0.0.0.0", port=5000):
    """Start Flask in a background daemon thread."""
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
        name="web-ui",
    )
    thread.start()
    logger.info(f"Web UI started at http://{host}:{port}")
    return thread
