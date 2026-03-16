"""
G-code Processor for TradRack-to-Bambu Bridge.

Pre-processes G-code files from the slicer to:
1. Detect tool change commands (T0, T1, ... T7)
2. Replace/inject M600 (filament change) or M601 (pause) commands
3. Strip original tool-change commands (P1S has no MMU)
4. Generate a tool-change sequence map for the bridge to follow

This lets the P1S pause at each filament change point so the bridge
can trigger Happy Hare to swap filament on the TradRack.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Regex: match standalone tool change commands T0-T99
# Must be on its own line (possibly with comments after)
TOOL_CHANGE_RE = re.compile(r"^\s*(T(\d+))\s*(;.*)?$", re.MULTILINE)


@dataclass
class ToolChangeEvent:
    """A tool change detected in the G-code."""
    line_number: int
    original_line: str
    tool_number: int
    layer: Optional[int] = None


@dataclass
class ProcessingResult:
    """Result of G-code processing."""
    input_file: str
    output_file: str
    tool_changes: list  # list of ToolChangeEvent
    total_lines: int
    lines_modified: int


class GCodeProcessor:
    """
    Processes G-code to inject filament change commands at tool-change points.

    Usage:
        processor = GCodeProcessor(inject_command="m600", strip_toolchange=True)
        result = processor.process_file("input.gcode", "output.gcode")
        # result.tool_changes contains the ordered sequence of tool changes
    """

    def __init__(self, inject_command: str = "m600",
                 strip_toolchange: bool = True,
                 filament_map: Optional[dict] = None):
        """
        Args:
            inject_command: "m600" for M600 filament change, "pause" for M601 pause
            strip_toolchange: Whether to remove original Tx commands
            filament_map: Optional dict mapping "T0" -> gate_number
        """
        self.inject_command = inject_command.lower()
        self.strip_toolchange = strip_toolchange
        self.filament_map = filament_map or {}

        if self.inject_command == "m600":
            self._inject_gcode = "M600 ; Filament change - TradRack bridge"
        elif self.inject_command == "pause":
            self._inject_gcode = "M601 ; Pause for filament change - TradRack bridge"
        else:
            raise ValueError(f"Unknown inject_command: {inject_command}. Use 'm600' or 'pause'")

    def process_file(self, input_path: str, output_path: str = None) -> ProcessingResult:
        """
        Process a G-code file: detect tool changes, inject M600/pause, optionally strip Tx.

        Args:
            input_path: Path to input G-code file
            output_path: Path for processed output (default: auto-generate)

        Returns:
            ProcessingResult with tool change sequence and statistics
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"G-code file not found: {input_path}")

        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}_processed{input_path.suffix}"
        output_path = Path(output_path)

        logger.info(f"Processing G-code: {input_path}")

        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        tool_changes = []
        output_lines = []
        current_layer = None
        lines_modified = 0

        for i, line in enumerate(lines):
            # Track layer changes (common slicer comment format)
            layer_match = re.match(r";\s*(?:LAYER|layer_change|Z:)\s*(\d+)", line.strip())
            if layer_match:
                current_layer = int(layer_match.group(1))

            # Check for tool change command
            tc_match = TOOL_CHANGE_RE.match(line)
            if tc_match:
                tool_cmd = tc_match.group(1)  # e.g. "T1"
                tool_num = int(tc_match.group(2))

                event = ToolChangeEvent(
                    line_number=i + 1,
                    original_line=line.strip(),
                    tool_number=tool_num,
                    layer=current_layer,
                )
                tool_changes.append(event)

                gate = self.filament_map.get(f"T{tool_num}", tool_num)
                logger.debug(f"Line {i + 1}: {tool_cmd} -> gate {gate} (layer {current_layer})")

                # Inject the pause/M600 command
                comment = f"; === Tool change: T{tool_num} -> gate {gate} ==="
                output_lines.append(comment + "\n")
                output_lines.append(self._inject_gcode + "\n")
                lines_modified += 1

                if not self.strip_toolchange:
                    # Keep the original Tx command (commented out for reference)
                    output_lines.append(f"; {line.strip()} ; (original, kept for ref)\n")
                else:
                    # Strip it — add a comment showing what was removed
                    output_lines.append(f"; {line.strip()} ; (stripped by TradRack bridge)\n")
                    lines_modified += 1

                continue

            output_lines.append(line)

        # Write processed file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.writelines(output_lines)

        result = ProcessingResult(
            input_file=str(input_path),
            output_file=str(output_path),
            tool_changes=tool_changes,
            total_lines=len(lines),
            lines_modified=lines_modified,
        )

        logger.info(
            f"Processed {result.total_lines} lines, "
            f"found {len(tool_changes)} tool changes, "
            f"modified {lines_modified} lines"
        )
        logger.info(f"Output written to: {output_path}")

        return result

    def get_tool_sequence(self, input_path: str) -> list[int]:
        """
        Scan a G-code file and return the ordered sequence of tool numbers used.

        Returns list of tool numbers in order of appearance, e.g. [0, 1, 0, 2, 0]
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"G-code file not found: {input_path}")

        sequence = []
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                tc_match = TOOL_CHANGE_RE.match(line)
                if tc_match:
                    tool_num = int(tc_match.group(2))
                    sequence.append(tool_num)

        logger.info(f"Tool sequence ({len(sequence)} changes): {sequence}")
        return sequence

    def process_directory(self, input_dir: str, output_dir: str) -> list[ProcessingResult]:
        """Process all .gcode and .3mf G-code files in a directory."""
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        if not input_dir.exists():
            logger.warning(f"Input directory does not exist: {input_dir}")
            return []

        results = []
        for gcode_file in sorted(input_dir.glob("*.gcode")):
            output_file = output_dir / gcode_file.name
            try:
                result = self.process_file(str(gcode_file), str(output_file))
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {gcode_file}: {e}")

        return results

    def print_summary(self, result: ProcessingResult):
        """Print a human-readable summary of processing results."""
        print(f"\n{'=' * 60}")
        print(f"G-code Processing Summary")
        print(f"{'=' * 60}")
        print(f"Input:  {result.input_file}")
        print(f"Output: {result.output_file}")
        print(f"Total lines: {result.total_lines}")
        print(f"Lines modified: {result.lines_modified}")
        print(f"Tool changes found: {len(result.tool_changes)}")
        print()

        if result.tool_changes:
            print(f"Tool Change Sequence:")
            print(f"{'-' * 40}")
            for i, tc in enumerate(result.tool_changes, 1):
                gate = self.filament_map.get(f"T{tc.tool_number}", tc.tool_number)
                layer_str = f"layer {tc.layer}" if tc.layer is not None else "unknown layer"
                print(f"  {i:3d}. T{tc.tool_number} -> gate {gate}  "
                      f"(line {tc.line_number}, {layer_str})")

        print(f"{'=' * 60}\n")
