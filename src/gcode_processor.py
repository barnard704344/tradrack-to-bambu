"""
G-code Scanner for TradRack-to-Bambu Bridge.

Scans G-code (produced by Orca Slicer with TradRack custom tool-change G-code)
to extract the ordered tool-change sequence the bridge needs to follow.

Orca Slicer is configured to emit these comments at tool changes:
    ; TRADRACK_TOOL_CHANGE T=<n>
    M600

This module scans for those markers (and also plain Tx commands as fallback)
to build the list of tool numbers in order.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Orca Slicer custom comment: ; TRADRACK_TOOL_CHANGE T=2
TRADRACK_COMMENT_RE = re.compile(
    r";\s*TRADRACK_TOOL_CHANGE\s+T\s*=\s*(\d+)", re.IGNORECASE
)

# Orca Slicer initial tool: ; TRADRACK_INITIAL_TOOL T=0
TRADRACK_INITIAL_RE = re.compile(
    r";\s*TRADRACK_INITIAL_TOOL\s+T\s*=\s*(\d+)", re.IGNORECASE
)

# Fallback: standalone tool change commands T0-T99
TOOL_CHANGE_RE = re.compile(r"^\s*T(\d+)\s*(;.*)?$")

# Layer tracking (Orca Slicer format)
LAYER_RE = re.compile(r";\s*(?:CHANGE_LAYER|LAYER_CHANGE|LAYER)\s*[=:]?\s*(\d+)")


@dataclass
class ToolChangeEvent:
    """A tool change detected in the G-code."""
    line_number: int
    tool_number: int
    layer: Optional[int] = None
    is_initial: bool = False


class GCodeScanner:
    """
    Scans G-code to extract the tool-change sequence for the bridge.

    Works with G-code produced by Orca Slicer configured per docs/orca_slicer_setup.md.
    Can scan from a file path or from raw G-code text (fetched from P1S via FTP).
    """

    def __init__(self, filament_map: Optional[dict] = None):
        self.filament_map = filament_map or {}

    def scan_file(self, gcode_path: str) -> list[ToolChangeEvent]:
        """Scan a G-code file and return all tool change events in order."""
        path = Path(gcode_path)
        if not path.exists():
            raise FileNotFoundError(f"G-code file not found: {path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return self._scan_lines(f)

    def scan_text(self, gcode_text: str) -> list[ToolChangeEvent]:
        """Scan raw G-code text and return all tool change events in order."""
        return self._scan_lines(gcode_text.splitlines(keepends=True))

    def get_tool_sequence(self, gcode_path: str) -> list[int]:
        """
        Get the ordered tool number sequence from a G-code file.

        Returns: e.g. [0, 1, 0, 2, 0]
        """
        events = self.scan_file(gcode_path)
        return [e.tool_number for e in events]

    def get_tool_sequence_from_text(self, gcode_text: str) -> list[int]:
        """
        Get the ordered tool number sequence from raw G-code text.

        Returns: e.g. [0, 1, 0, 2, 0]
        """
        events = self.scan_text(gcode_text)
        return [e.tool_number for e in events]

    def get_gate_sequence(self, gcode_path: str) -> list[int]:
        """
        Get the ordered gate sequence (after filament_map remapping).

        Returns: e.g. [0, 1, 0, 2, 0] (gate numbers, not tool numbers)
        """
        tools = self.get_tool_sequence(gcode_path)
        return [self.filament_map.get(f"T{t}", t) for t in tools]

    def get_gate_sequence_from_text(self, gcode_text: str) -> list[int]:
        """Get ordered gate sequence from raw G-code text."""
        tools = self.get_tool_sequence_from_text(gcode_text)
        return [self.filament_map.get(f"T{t}", t) for t in tools]

    def _scan_lines(self, lines) -> list[ToolChangeEvent]:
        """Core scanning logic — works on any iterable of lines."""
        events = []
        current_layer = None
        # Track whether we've seen TRADRACK comments — if so, ignore plain Tx
        has_tradrack_comments = False

        # First pass: check if TRADRACK comments exist
        all_lines = list(lines)
        for line in all_lines:
            if TRADRACK_COMMENT_RE.search(line) or TRADRACK_INITIAL_RE.search(line):
                has_tradrack_comments = True
                break

        # Second pass: extract events
        for i, line in enumerate(all_lines):
            stripped = line.strip() if isinstance(line, str) else line

            # Track layers
            layer_match = LAYER_RE.match(stripped)
            if layer_match:
                current_layer = int(layer_match.group(1))

            # Check for TRADRACK_INITIAL_TOOL comment
            init_match = TRADRACK_INITIAL_RE.search(stripped)
            if init_match:
                events.append(ToolChangeEvent(
                    line_number=i + 1,
                    tool_number=int(init_match.group(1)),
                    layer=current_layer,
                    is_initial=True,
                ))
                continue

            # Check for TRADRACK_TOOL_CHANGE comment
            tc_match = TRADRACK_COMMENT_RE.search(stripped)
            if tc_match:
                events.append(ToolChangeEvent(
                    line_number=i + 1,
                    tool_number=int(tc_match.group(1)),
                    layer=current_layer,
                ))
                continue

            # Fallback: plain Tx commands (only if no TRADRACK comments found)
            if not has_tradrack_comments:
                plain_match = TOOL_CHANGE_RE.match(stripped)
                if plain_match:
                    events.append(ToolChangeEvent(
                        line_number=i + 1,
                        tool_number=int(plain_match.group(1)),
                        layer=current_layer,
                    ))

        logger.info(
            f"Scanned G-code: found {len(events)} tool changes "
            f"(tradrack_comments={'yes' if has_tradrack_comments else 'no/fallback'})"
        )
        if events:
            seq = [e.tool_number for e in events]
            logger.info(f"Tool sequence: {seq}")

        return events

    def print_summary(self, events: list[ToolChangeEvent]):
        """Print a human-readable summary of the tool-change sequence."""
        print(f"\n{'=' * 50}")
        print(f"G-code Tool Change Sequence")
        print(f"{'=' * 50}")
        print(f"Total tool changes: {len(events)}")

        if events:
            initial = [e for e in events if e.is_initial]
            changes = [e for e in events if not e.is_initial]

            if initial:
                e = initial[0]
                gate = self.filament_map.get(f"T{e.tool_number}", e.tool_number)
                print(f"Initial tool: T{e.tool_number} -> gate {gate}")

            print(f"\nTool changes ({len(changes)}):")
            print(f"{'-' * 40}")
            for i, e in enumerate(changes, 1):
                gate = self.filament_map.get(f"T{e.tool_number}", e.tool_number)
                layer_str = f"layer {e.layer}" if e.layer is not None else "?"
                print(f"  {i:3d}. T{e.tool_number} -> gate {gate}  "
                      f"(line {e.line_number}, {layer_str})")

        print(f"{'=' * 50}\n")
