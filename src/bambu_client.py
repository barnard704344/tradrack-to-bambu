"""
BambuLab P1S MQTT Client for LAN Mode.

Connects to the P1S via MQTT over TLS (port 8883) to monitor print status,
detect M600/pause events, and send pause/resume commands.

Also provides FTPS access to fetch G-code files from the P1S SD card
so the bridge can auto-scan the tool-change sequence.

Protocol reference:
- Topic: device/{serial}/report  (printer -> client)
- Topic: device/{serial}/request (client -> printer)
- Messages are JSON payloads
"""

import ftplib
import io
import json
import logging
import ssl
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class PrintStatus(Enum):
    """P1S print status codes from MQTT."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PAUSE_FILAMENT = "PAUSE_FILAMENT"  # M600 triggered
    FINISH = "FINISH"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class PrintState:
    """Current state of the P1S print job."""
    status: PrintStatus = PrintStatus.IDLE
    gcode_state: str = ""
    mc_percent: int = 0  # print progress 0-100
    mc_remaining_time: int = 0  # remaining time in minutes
    layer_num: int = 0
    total_layers: int = 0
    subtask_name: str = ""  # current G-code filename
    gcode_file: str = ""
    hw_switch_state: int = 0  # filament sensor
    mc_print_error_code: str = "0"
    mc_print_sub_stage: int = 0
    # Temperatures
    bed_temper: float = 0.0
    bed_target_temper: float = 0.0
    nozzle_temper: float = 0.0
    nozzle_target_temper: float = 0.0
    chamber_temper: float = 0.0
    # Fans (speed as string like "15" meaning 100*15/15 or percentage)
    cooling_fan_speed: str = "0"
    heatbreak_fan_speed: str = "0"
    big_fan1_speed: str = "0"
    big_fan2_speed: str = "0"
    # Speed
    spd_lvl: int = 1  # speed level (1=silent,2=standard,3=sport,4=ludicrous)
    spd_mag: int = 100  # speed magnitude percentage
    # Nozzle
    nozzle_diameter: str = ""
    nozzle_type: str = ""
    # Network
    wifi_signal: str = ""
    # Errors
    print_error: int = 0
    hms: list = None  # health management system alerts
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.hms is None:
            self.hms = []


class BambuMQTTClient:
    """
    MQTT client for BambuLab P1S in LAN mode.

    Subscribes to printer reports, tracks print state, and provides
    methods to send commands (pause, resume, stop).
    """

    def __init__(self, host: str, access_code: str, serial: str,
                 port: int = 8883, ftp_port: int = 990):
        self.host = host
        self.access_code = access_code
        self.serial = serial
        self.port = port
        self.ftp_port = ftp_port

        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._state = PrintState()
        self._state_lock = threading.Lock()

        # Callback hooks
        self._on_m600: Optional[Callable[[], None]] = None
        self._on_pause: Optional[Callable[[], None]] = None
        self._on_state_change: Optional[Callable[[PrintState], None]] = None

        # Topics
        self._report_topic = f"device/{self.serial}/report"
        self._request_topic = f"device/{self.serial}/request"

        # When True, print raw MQTT payloads to console
        self.mqtt_log = False

    @property
    def state(self) -> PrintState:
        with self._state_lock:
            return self._state

    def on_m600(self, callback: Callable[[], None]):
        """Register callback for M600 filament change detection."""
        self._on_m600 = callback

    def on_pause(self, callback: Callable[[], None]):
        """Register callback for print pause detection."""
        self._on_pause = callback

    def on_state_change(self, callback: Callable[[PrintState], None]):
        """Register callback for any print state change."""
        self._on_state_change = callback

    def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect to the P1S MQTT broker over TLS.

        Returns True if connection succeeds within timeout.
        """
        self._client = mqtt.Client(
            client_id=f"tradrack_bridge_{int(time.time())}",
            protocol=mqtt.MQTTv311,
        )

        # P1S LAN mode auth: username "bblp", password is access code
        self._client.username_pw_set("bblp", self.access_code)

        # TLS setup — P1S uses self-signed cert, so we skip verification
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        self._client.tls_set_context(ssl_ctx)

        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message
        self._client.on_disconnect = self._handle_disconnect

        logger.info(f"Connecting to P1S at {self.host}:{self.port}...")
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to P1S: {e}")
            return False

        if not self._connected.wait(timeout=timeout):
            logger.error("Connection to P1S timed out")
            return False

        logger.info("Connected to P1S successfully")
        return True

    def disconnect(self):
        """Disconnect from the P1S."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected.clear()
            logger.info("Disconnected from P1S")

    def pause_print(self) -> bool:
        """Send pause command to P1S."""
        return self._send_command({
            "print": {
                "command": "pause",
                "sequence_id": str(int(time.time())),
            }
        })

    def resume_print(self) -> bool:
        """Send resume command to P1S."""
        return self._send_command({
            "print": {
                "command": "resume",
                "sequence_id": str(int(time.time())),
            }
        })

    def stop_print(self) -> bool:
        """Send stop command to P1S."""
        return self._send_command({
            "print": {
                "command": "stop",
                "sequence_id": str(int(time.time())),
            }
        })

    def push_status_request(self) -> bool:
        """Request a full status update from the P1S."""
        return self._send_command({
            "pushing": {
                "command": "pushall",
                "sequence_id": str(int(time.time())),
            }
        })

    def _send_command(self, payload: dict) -> bool:
        """Publish a command to the P1S request topic."""
        if not self._client or not self._connected.is_set():
            logger.error("Cannot send command: not connected")
            return False

        try:
            msg = json.dumps(payload)
            result = self._client.publish(self._request_topic, msg)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Sent command: {payload}")
                return True
            else:
                logger.error(f"Failed to publish command: rc={result.rc}")
                return False
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return False

    def _handle_connect(self, client, userdata, flags, rc):
        """MQTT on_connect callback."""
        if rc == 0:
            logger.info("MQTT connected, subscribing to report topic")
            client.subscribe(self._report_topic)
            self._connected.set()
            # Request initial full status
            self.push_status_request()
        else:
            logger.error(f"MQTT connection failed with code: {rc}")

    def _handle_disconnect(self, client, userdata, rc):
        """MQTT on_disconnect callback."""
        self._connected.clear()
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnect (rc={rc}), will auto-reconnect")
        else:
            logger.info("MQTT disconnected cleanly")

    def _handle_message(self, client, userdata, msg):
        """Process incoming MQTT messages from the P1S."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to decode MQTT message: {e}")
            return

        if self.mqtt_log:
            print(json.dumps(payload, indent=2))

        # The P1S sends various message types; we care about "print" reports
        if "print" not in payload:
            return

        print_data = payload["print"]
        self._update_state(print_data)

    def _update_state(self, data: dict):
        """Update internal print state from MQTT report data."""
        prev_status = self._state.status

        with self._state_lock:
            self._state.raw_data = data

            gcode_state = data.get("gcode_state", "")
            if gcode_state:
                self._state.gcode_state = gcode_state
                self._state.status = self._parse_status(gcode_state, data)

            if "mc_percent" in data:
                self._state.mc_percent = data["mc_percent"]
            if "mc_remaining_time" in data:
                self._state.mc_remaining_time = data["mc_remaining_time"]
            if "layer_num" in data:
                self._state.layer_num = data["layer_num"]
            if "total_layer_num" in data:
                self._state.total_layers = data["total_layer_num"]
            if "subtask_name" in data:
                self._state.subtask_name = data["subtask_name"]
            if "gcode_file" in data:
                self._state.gcode_file = data["gcode_file"]
            if "hw_switch_state" in data:
                self._state.hw_switch_state = data["hw_switch_state"]
            if "mc_print_error_code" in data:
                self._state.mc_print_error_code = str(data["mc_print_error_code"])
            if "mc_print_sub_stage" in data:
                self._state.mc_print_sub_stage = data["mc_print_sub_stage"]
            # Temperatures
            if "bed_temper" in data:
                self._state.bed_temper = data["bed_temper"]
            if "bed_target_temper" in data:
                self._state.bed_target_temper = data["bed_target_temper"]
            if "nozzle_temper" in data:
                self._state.nozzle_temper = data["nozzle_temper"]
            if "nozzle_target_temper" in data:
                self._state.nozzle_target_temper = data["nozzle_target_temper"]
            if "chamber_temper" in data:
                self._state.chamber_temper = data["chamber_temper"]
            # Fans
            if "cooling_fan_speed" in data:
                self._state.cooling_fan_speed = str(data["cooling_fan_speed"])
            if "heatbreak_fan_speed" in data:
                self._state.heatbreak_fan_speed = str(data["heatbreak_fan_speed"])
            if "big_fan1_speed" in data:
                self._state.big_fan1_speed = str(data["big_fan1_speed"])
            if "big_fan2_speed" in data:
                self._state.big_fan2_speed = str(data["big_fan2_speed"])
            # Speed
            if "spd_lvl" in data:
                self._state.spd_lvl = data["spd_lvl"]
            if "spd_mag" in data:
                self._state.spd_mag = data["spd_mag"]
            # Nozzle
            if "nozzle_diameter" in data:
                self._state.nozzle_diameter = str(data["nozzle_diameter"])
            if "nozzle_type" in data:
                self._state.nozzle_type = str(data["nozzle_type"])
            # Network
            if "wifi_signal" in data:
                self._state.wifi_signal = str(data["wifi_signal"])
            # Errors
            if "print_error" in data:
                self._state.print_error = data["print_error"]
            if "hms" in data:
                self._state.hms = data["hms"]

        new_status = self._state.status

        # Fire callbacks on state transitions
        if new_status != prev_status:
            logger.info(f"Print status changed: {prev_status.value} -> {new_status.value}")

            if self._on_state_change:
                self._on_state_change(self._state)

            # Detect M600 (filament change pause)
            if new_status == PrintStatus.PAUSE_FILAMENT:
                logger.info("M600 filament change detected!")
                if self._on_m600:
                    self._on_m600()

            # Detect general pause
            elif new_status == PrintStatus.PAUSED:
                logger.info("Print paused detected")
                if self._on_pause:
                    self._on_pause()

    def _parse_status(self, gcode_state: str, data: dict) -> PrintStatus:
        """Parse the gcode_state string + context into a PrintStatus enum."""
        state_upper = gcode_state.upper()

        if state_upper == "RUNNING":
            return PrintStatus.RUNNING
        elif state_upper == "PAUSE":
            # Distinguish between M600 pause and manual/other pause
            # mc_print_sub_stage == 1 typically means M600 filament change
            sub_stage = data.get("mc_print_sub_stage", 0)
            error_code = str(data.get("mc_print_error_code", "0"))

            if sub_stage == 1 or error_code in ("50348", "50349"):
                return PrintStatus.PAUSE_FILAMENT
            return PrintStatus.PAUSED
        elif state_upper == "FINISH":
            return PrintStatus.FINISH
        elif state_upper == "FAILED":
            return PrintStatus.FAILED
        elif state_upper == "IDLE":
            return PrintStatus.IDLE
        else:
            logger.debug(f"Unknown gcode_state: {gcode_state}")
            return PrintStatus.UNKNOWN

    def is_connected(self) -> bool:
        """Check if MQTT connection is active."""
        return self._connected.is_set()

    def wait_for_status(self, target: PrintStatus, timeout: float = 30.0) -> bool:
        """
        Block until the print reaches the target status or timeout.

        Returns True if target status was reached.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._state.status == target:
                return True
            time.sleep(0.5)
        logger.warning(f"Timed out waiting for status {target.value}")
        return False

    def fetch_gcode(self, filename: str = None) -> Optional[str]:
        """
        Fetch G-code file content from the P1S via FTPS.

        If filename is None, uses the current print job's gcode_file.
        The P1S stores G-code in /cache/ on its internal storage.

        Returns the G-code as a string, or None on failure.
        """
        if filename is None:
            filename = self._state.gcode_file
            if not filename:
                logger.error("No G-code filename available (is a print running?)")
                return None

        # P1S FTPS: implicit TLS on port 990, user "bblp", password is access code
        logger.info(f"Fetching G-code from P1S via FTPS: {filename}")
        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            ftp = ftplib.FTP_TLS(context=ssl_ctx)
            ftp.connect(self.host, self.ftp_port, timeout=15)
            ftp.login("bblp", self.access_code)
            ftp.prot_p()  # switch to secure data connection

            # P1S G-code is stored under /cache/
            remote_path = f"/cache/{filename}" if not filename.startswith("/") else filename

            buffer = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_path}", buffer.write)
            ftp.quit()

            gcode_text = buffer.getvalue().decode("utf-8", errors="replace")
            logger.info(f"Fetched G-code: {len(gcode_text)} bytes")
            return gcode_text

        except ftplib.all_errors as e:
            logger.error(f"FTP error fetching G-code: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching G-code: {e}")
            return None
