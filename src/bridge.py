"""
Bridge Coordinator — the core orchestration logic.

Ties together the Bambu MQTT client and Happy Hare controller to:
1. Monitor the P1S print in real-time via MQTT
2. Auto-fetch G-code from P1S via FTPS when a print starts
3. Scan the G-code for tool-change sequence (TRADRACK_TOOL_CHANGE comments)
4. Detect M600/pause events (filament change requests)
5. Trigger Happy Hare tool changes on the TradRack
6. Resume the P1S print after successful filament swap

Orca Slicer is configured to insert M600 + TRADRACK_TOOL_CHANGE comments
at each tool change, so no manual G-code processing is needed.
"""

import logging
import threading
import time
from enum import Enum
from typing import Optional

from .bambu_client import BambuMQTTClient, PrintStatus
from .gcode_processor import GCodeScanner
from .happy_hare import HappyHareController, MMUState

logger = logging.getLogger(__name__)


class BridgeState(Enum):
    """Bridge coordinator states."""
    IDLE = "idle"
    MONITORING = "monitoring"
    TOOL_CHANGING = "tool_changing"
    WAITING_RESUME = "waiting_resume"
    ERROR = "error"
    STOPPED = "stopped"


class Bridge:
    """
    Orchestrates filament changes between the BambuLab P1S and TradRack/Happy Hare.

    Workflow per tool change:
    1. P1S hits M600 in G-code -> pauses print
    2. Bridge detects PAUSE_FILAMENT status via MQTT
    3. Bridge tells Happy Hare to change to next tool (MMU_CHANGE_TOOL)
    4. Happy Hare: unloads old filament, moves selector, loads new filament
    5. Bridge waits for Happy Hare to report success
    6. Bridge resumes print on the P1S via MQTT
    """

    def __init__(self, bambu: BambuMQTTClient, happy_hare: HappyHareController,
                 filament_map: dict, trigger_mode: str = "m600",
                 auto_resume: bool = True, resume_delay: float = 3.0,
                 bambu_command_timeout: float = 30.0):
        self.bambu = bambu
        self.happy_hare = happy_hare
        self.filament_map = filament_map  # {"T0": 0, "T1": 1, ...}
        self.trigger_mode = trigger_mode
        self.auto_resume = auto_resume
        self.resume_delay = resume_delay
        self.bambu_command_timeout = bambu_command_timeout

        self._state = BridgeState.IDLE
        self._tool_sequence: list[int] = []  # ordered tool changes from G-code
        self._tool_index: int = 0  # current position in sequence
        self._current_tool: Optional[int] = None
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._scanner = GCodeScanner(filament_map=filament_map)
        self._sequence_loaded = False

        # Stats
        self._tool_changes_completed = 0
        self._tool_changes_failed = 0

    @property
    def state(self) -> BridgeState:
        with self._state_lock:
            return self._state

    def set_tool_sequence(self, sequence: list[int]):
        """
        Set the expected tool change sequence.

        Normally auto-loaded from the P1S G-code via FTP, but can also
        be set manually for testing.

        Args:
            sequence: Ordered list of tool numbers, e.g. [0, 1, 0, 2, 0]
        """
        self._tool_sequence = sequence
        self._tool_index = 0
        self._sequence_loaded = True
        logger.info(f"Tool sequence set: {sequence} ({len(sequence)} changes)")

    def start(self):
        """Start monitoring the P1S and handling tool changes."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("Bridge is already running")
            return

        if not self.bambu.is_connected():
            logger.error("Cannot start bridge: not connected to P1S")
            return

        if not self.happy_hare.check_connection():
            logger.error("Cannot start bridge: Happy Hare/Moonraker not reachable")
            return

        # Auto-fetch and scan G-code from P1S if no sequence loaded yet
        if not self._sequence_loaded:
            self._auto_load_sequence()

        logger.info("Starting bridge coordinator")
        self._stop_event.clear()
        self._set_state(BridgeState.MONITORING)

        # Register MQTT callbacks based on trigger mode
        if self.trigger_mode == "m600":
            self.bambu.on_m600(self._handle_filament_change)
        elif self.trigger_mode == "pause":
            self.bambu.on_pause(self._handle_filament_change)
        else:
            # Both modes — react to either
            self.bambu.on_m600(self._handle_filament_change)
            self.bambu.on_pause(self._handle_filament_change)

        self.bambu.on_state_change(self._on_state_change)

        # Start monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="bridge-monitor"
        )
        self._monitor_thread.start()

        logger.info(f"Bridge running | mode={self.trigger_mode} | "
                    f"auto_resume={self.auto_resume} | "
                    f"sequence={len(self._tool_sequence)} changes queued")

    def stop(self):
        """Stop the bridge coordinator."""
        logger.info("Stopping bridge coordinator")
        self._stop_event.set()
        self._set_state(BridgeState.STOPPED)
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def get_stats(self) -> dict:
        """Return bridge statistics."""
        return {
            "state": self.state.value,
            "tool_changes_completed": self._tool_changes_completed,
            "tool_changes_failed": self._tool_changes_failed,
            "current_tool": self._current_tool,
            "sequence_position": f"{self._tool_index}/{len(self._tool_sequence)}",
            "remaining_changes": max(0, len(self._tool_sequence) - self._tool_index),
        }

    def _set_state(self, state: BridgeState):
        with self._state_lock:
            if self._state != state:
                logger.info(f"Bridge state: {self._state.value} -> {state.value}")
                self._state = state

    def _handle_filament_change(self):
        """
        Called when M600/pause is detected on the P1S.
        Triggers the next tool change in the sequence.
        """
        if self.state == BridgeState.TOOL_CHANGING:
            logger.warning("Already handling a tool change, ignoring duplicate trigger")
            return

        self._set_state(BridgeState.TOOL_CHANGING)

        # Determine next tool
        next_tool = self._get_next_tool()
        if next_tool is None:
            logger.error("No more tool changes in sequence! Cannot determine next tool.")
            self._set_state(BridgeState.ERROR)
            return

        gate = self.filament_map.get(f"T{next_tool}", next_tool)
        logger.info(f"Filament change #{self._tool_index}: T{next_tool} -> gate {gate}")

        # Execute tool change via Happy Hare
        success = self.happy_hare.change_tool(gate)

        if success:
            self._current_tool = next_tool
            self._tool_changes_completed += 1
            logger.info(f"Tool change to T{next_tool} (gate {gate}) successful")

            if self.auto_resume:
                self._resume_print()
            else:
                logger.info("Auto-resume disabled. Waiting for manual resume.")
                self._set_state(BridgeState.WAITING_RESUME)
        else:
            self._tool_changes_failed += 1
            logger.error(f"Tool change to T{next_tool} (gate {gate}) FAILED!")
            self._set_state(BridgeState.ERROR)

    def _get_next_tool(self) -> Optional[int]:
        """Get the next tool number from the sequence."""
        if self._tool_index < len(self._tool_sequence):
            tool = self._tool_sequence[self._tool_index]
            self._tool_index += 1
            return tool
        return None

    def _resume_print(self):
        """Resume the P1S print after a successful tool change."""
        self._set_state(BridgeState.WAITING_RESUME)

        if self.resume_delay > 0:
            logger.info(f"Waiting {self.resume_delay}s before resuming print...")
            time.sleep(self.resume_delay)

        logger.info("Resuming P1S print...")
        success = self.bambu.resume_print()

        if success:
            # Wait for P1S to confirm it's running again
            if self.bambu.wait_for_status(PrintStatus.RUNNING, timeout=self.bambu_command_timeout):
                logger.info("P1S print resumed successfully")
                self._set_state(BridgeState.MONITORING)
            else:
                logger.warning("P1S did not confirm resume within timeout")
                self._set_state(BridgeState.MONITORING)  # continue monitoring anyway
        else:
            logger.error("Failed to send resume command to P1S!")
            self._set_state(BridgeState.ERROR)

    def _monitor_loop(self):
        """Background monitoring loop — keeps connection alive and logs status."""
        while not self._stop_event.is_set():
            try:
                # Check P1S connection
                if not self.bambu.is_connected():
                    logger.warning("Lost connection to P1S, waiting for reconnect...")

                # Periodic status request to keep MQTT alive
                if self.bambu.is_connected():
                    self.bambu.push_status_request()

                # Auto-fetch G-code if a print started and we don't have a sequence
                bambu_state = self.bambu.state
                if (bambu_state.status == PrintStatus.RUNNING
                        and not self._sequence_loaded
                        and bambu_state.gcode_file):
                    logger.info("Print detected, auto-fetching G-code for tool sequence...")
                    self._auto_load_sequence()

                # Check print completion
                if bambu_state.status == PrintStatus.FINISH:
                    logger.info("Print finished!")
                    self._print_final_stats()
                    self._set_state(BridgeState.IDLE)
                    break
                elif bambu_state.status == PrintStatus.FAILED:
                    logger.error("Print failed!")
                    self._set_state(BridgeState.ERROR)
                    break

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            self._stop_event.wait(timeout=5.0)

    def _auto_load_sequence(self):
        """Fetch G-code from P1S via FTP and scan for tool-change sequence."""
        gcode_text = self.bambu.fetch_gcode()
        if gcode_text is None:
            logger.warning("Could not fetch G-code from P1S. "
                          "Tool sequence must be set manually or will be empty.")
            return

        sequence = self._scanner.get_tool_sequence_from_text(gcode_text)
        if sequence:
            self.set_tool_sequence(sequence)
            self._sequence_loaded = True
            logger.info(f"Auto-loaded tool sequence from P1S: {sequence}")
        else:
            logger.warning("No tool changes found in fetched G-code")

    def _on_state_change(self, state):
        """Handle P1S state changes — auto-fetch on print start + diagnostics."""
        logger.debug(
            f"P1S: {state.status.value} | "
            f"{state.mc_percent}% | layer {state.layer_num}/{state.total_layers} | "
            f"ETA {state.mc_remaining_time}min"
        )

    def _print_final_stats(self):
        """Log final bridge statistics."""
        stats = self.get_stats()
        logger.info(f"=== Bridge Session Complete ===")
        logger.info(f"Tool changes completed: {stats['tool_changes_completed']}")
        logger.info(f"Tool changes failed: {stats['tool_changes_failed']}")
        logger.info(f"Sequence position: {stats['sequence_position']}")
