"""
Happy Hare / Moonraker Controller.

Communicates with Happy Hare (MMU firmware for Klipper) via the Moonraker
HTTP/WebSocket API to perform tool changes, query filament status, and
manage the TradRack.

Happy Hare Klipper macros used:
  - MMU_CHANGE_TOOL TOOL=<n>  — full tool change (unload + load)
  - MMU_EJECT                  — unload current filament
  - MMU_SELECT TOOL=<n>       — select gate without loading
  - MMU_HOME                   — home the MMU selector
  - MMU_STATUS                 — query current MMU state
  - MMU_SERVO POS=<up|down>   — control servo
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class MMUState(Enum):
    """Happy Hare MMU states."""
    READY = "ready"
    CHANGING_TOOL = "changing_tool"
    LOADING = "loading"
    UNLOADING = "unloading"
    PAUSED_USER = "paused_user"  # waiting for user input
    ERROR = "error"
    HOMING = "homing"
    UNKNOWN = "unknown"


@dataclass
class MMUStatus:
    """Current status of the Happy Hare MMU."""
    state: MMUState = MMUState.UNKNOWN
    current_tool: int = -1  # -1 = no tool loaded
    filament_loaded: bool = False
    is_homed: bool = False
    num_gates: int = 8
    gate_status: list = None  # per-gate status
    message: str = ""

    def __post_init__(self):
        if self.gate_status is None:
            self.gate_status = []


class HappyHareController:
    """
    Controls TradRack via Happy Hare through the Moonraker API.

    All tool change commands are executed by calling Happy Hare's
    Klipper macros through Moonraker's gcode endpoint.
    """

    def __init__(self, host: str = "http://127.0.0.1", port: int = 7125,
                 api_key: str = "", num_gates: int = 8,
                 tool_change_timeout: int = 120, retry_count: int = 2):
        self.base_url = f"{host}:{port}"
        self.api_key = api_key
        self.num_gates = num_gates
        self.tool_change_timeout = tool_change_timeout
        self.retry_count = retry_count

        self._session = requests.Session()
        if api_key:
            self._session.headers["X-Api-Key"] = api_key

    def check_connection(self) -> bool:
        """Verify Moonraker is reachable and Klipper is ready."""
        try:
            resp = self._get("/printer/info")
            state = resp.get("result", {}).get("state", "")
            if state == "ready":
                logger.info("Klipper is ready")
                return True
            else:
                logger.warning(f"Klipper state: {state}")
                return state == "ready"
        except Exception as e:
            logger.error(f"Cannot reach Moonraker: {e}")
            return False

    def get_status(self) -> MMUStatus:
        """Query Happy Hare MMU status from Klipper."""
        status = MMUStatus(num_gates=self.num_gates)
        try:
            # Query the mmu object status from Klipper
            resp = self._get(
                "/printer/objects/query",
                params={"mmu": ""}
            )
            mmu_data = resp.get("result", {}).get("status", {}).get("mmu", {})

            if mmu_data:
                status.current_tool = mmu_data.get("tool", -1)
                status.filament_loaded = mmu_data.get("filament", "") == "Loaded"
                status.is_homed = mmu_data.get("is_homed", False)
                status.gate_status = mmu_data.get("gate_status", [])
                status.message = mmu_data.get("message", "")

                action = mmu_data.get("action", "idle")
                status.state = self._parse_mmu_state(action)

            logger.debug(f"MMU status: tool={status.current_tool}, "
                        f"loaded={status.filament_loaded}, state={status.state.value}")
        except Exception as e:
            logger.error(f"Failed to query MMU status: {e}")
            status.state = MMUState.ERROR

        return status

    def change_tool(self, tool: int) -> bool:
        """
        Perform a full tool change via Happy Hare.

        This calls MMU_CHANGE_TOOL which handles:
        1. Unload current filament (with tip forming)
        2. Move selector to new gate
        3. Load new filament to nozzle

        Args:
            tool: Target tool/gate number (0-based)

        Returns:
            True if tool change completed successfully
        """
        if tool < 0 or tool >= self.num_gates:
            logger.error(f"Invalid tool number: {tool} (must be 0-{self.num_gates - 1})")
            return False

        current_status = self.get_status()
        if current_status.current_tool == tool and current_status.filament_loaded:
            logger.info(f"Tool T{tool} already loaded, skipping change")
            return True

        for attempt in range(1, self.retry_count + 1):
            logger.info(f"Tool change to T{tool} (attempt {attempt}/{self.retry_count})")

            success = self._run_gcode(f"MMU_CHANGE_TOOL TOOL={tool}")
            if not success:
                logger.error(f"Failed to send tool change command (attempt {attempt})")
                continue

            # Wait for tool change to complete
            if self._wait_for_tool_ready(tool, self.tool_change_timeout):
                logger.info(f"Tool change to T{tool} completed successfully")
                return True
            else:
                logger.warning(f"Tool change to T{tool} timed out or failed (attempt {attempt})")

                # Check if Happy Hare is paused waiting for user input
                status = self.get_status()
                if status.state == MMUState.PAUSED_USER:
                    logger.error("MMU paused waiting for user intervention!")
                    return False

        logger.error(f"Tool change to T{tool} failed after {self.retry_count} attempts")
        return False

    def eject_filament(self) -> bool:
        """Eject/unload the currently loaded filament."""
        logger.info("Ejecting filament")
        success = self._run_gcode("MMU_EJECT")
        if success:
            return self._wait_for_idle(timeout=60)
        return False

    def home(self) -> bool:
        """Home the MMU selector."""
        logger.info("Homing MMU")
        success = self._run_gcode("MMU_HOME")
        if success:
            return self._wait_for_idle(timeout=30)
        return False

    def select_gate(self, gate: int) -> bool:
        """Select a gate without loading filament."""
        logger.info(f"Selecting gate {gate}")
        return self._run_gcode(f"MMU_SELECT TOOL={gate}")

    def servo_up(self) -> bool:
        """Raise the servo (release filament)."""
        return self._run_gcode("MMU_SERVO POS=up")

    def servo_down(self) -> bool:
        """Lower the servo (grip filament)."""
        return self._run_gcode("MMU_SERVO POS=down")

    def get_gate_filament_info(self, gate: int) -> dict:
        """Get filament info for a specific gate from Happy Hare."""
        try:
            resp = self._get(
                "/printer/objects/query",
                params={"mmu": ""}
            )
            mmu_data = resp.get("result", {}).get("status", {}).get("mmu", {})
            gate_material = mmu_data.get("gate_material", [])
            gate_color = mmu_data.get("gate_color", [])

            info = {}
            if gate < len(gate_material):
                info["material"] = gate_material[gate]
            if gate < len(gate_color):
                info["color"] = gate_color[gate]
            return info
        except Exception:
            return {}

    def _run_gcode(self, gcode: str) -> bool:
        """Execute a G-code command/macro via Moonraker."""
        try:
            resp = self._post(
                "/printer/gcode/script",
                json_data={"script": gcode}
            )
            if resp is not None:
                logger.debug(f"Executed G-code: {gcode}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to execute G-code '{gcode}': {e}")
            return False

    def _wait_for_tool_ready(self, expected_tool: int, timeout: float) -> bool:
        """Wait until Happy Hare reports the expected tool is loaded."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_status()
            if (status.current_tool == expected_tool
                    and status.filament_loaded
                    and status.state == MMUState.READY):
                return True
            if status.state == MMUState.ERROR:
                logger.error(f"MMU error during tool change: {status.message}")
                return False
            if status.state == MMUState.PAUSED_USER:
                logger.warning(f"MMU waiting for user: {status.message}")
                return False
            time.sleep(1.0)
        return False

    def _wait_for_idle(self, timeout: float = 30) -> bool:
        """Wait for MMU to return to idle/ready state."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.get_status()
            if status.state == MMUState.READY:
                return True
            if status.state == MMUState.ERROR:
                return False
            time.sleep(1.0)
        return False

    def _parse_mmu_state(self, action: str) -> MMUState:
        """Parse Happy Hare action string into MMUState."""
        action_lower = action.lower()
        if action_lower in ("idle", "ready"):
            return MMUState.READY
        elif "load" in action_lower:
            return MMUState.LOADING
        elif "unload" in action_lower:
            return MMUState.UNLOADING
        elif "change" in action_lower or "select" in action_lower:
            return MMUState.CHANGING_TOOL
        elif "home" in action_lower:
            return MMUState.HOMING
        elif "pause" in action_lower:
            return MMUState.PAUSED_USER
        else:
            return MMUState.UNKNOWN

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """HTTP GET to Moonraker."""
        url = f"{self.base_url}{endpoint}"
        resp = self._session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, json_data: dict = None) -> Optional[dict]:
        """HTTP POST to Moonraker."""
        url = f"{self.base_url}{endpoint}"
        resp = self._session.post(url, json=json_data, timeout=30)
        resp.raise_for_status()
        return resp.json()
