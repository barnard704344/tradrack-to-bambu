"""
Main entry point & CLI for the TradRack-to-Bambu Bridge.

Commands:
  bridge  - Run the real-time bridge (monitor P1S + handle tool changes)
  scan    - Scan a G-code file to verify tool-change sequence
  status  - Check connection to P1S and Happy Hare
  test    - Test tool change (dry run or real)
"""

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import time
from pathlib import Path

import yaml

from .bambu_client import BambuMQTTClient
from .bridge import Bridge
from .gcode_processor import GCodeScanner
from .happy_hare import HappyHareController

logger = logging.getLogger("tradrack_bridge")


def load_config(config_path: str) -> dict:
    """Load and validate the YAML configuration file."""
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Basic validation
    required_sections = ["bambu", "moonraker", "happy_hare", "bridge"]
    for section in required_sections:
        if section not in config:
            print(f"Error: Missing '{section}' section in config")
            sys.exit(1)

    return config


def setup_logging(config: dict):
    """Configure logging from config settings."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "./logs/bridge.log")

    # Create log directory
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_config.get("max_size_mb", 10) * 1024 * 1024,
        backupCount=log_config.get("backup_count", 3),
    )
    file_handler.setLevel(logging.DEBUG)  # always log debug to file
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)


def create_bambu_client(config: dict) -> BambuMQTTClient:
    """Create and configure the Bambu MQTT client from config."""
    bambu_cfg = config["bambu"]
    return BambuMQTTClient(
        host=bambu_cfg["host"],
        access_code=bambu_cfg["access_code"],
        serial=bambu_cfg["serial"],
        port=bambu_cfg.get("mqtt_port", 8883),
        ftp_port=bambu_cfg.get("ftp_port", 990),
    )


def create_happy_hare(config: dict) -> HappyHareController:
    """Create and configure the Happy Hare controller from config."""
    moon_cfg = config["moonraker"]
    hh_cfg = config["happy_hare"]
    return HappyHareController(
        host=moon_cfg.get("host", "http://127.0.0.1"),
        port=moon_cfg.get("port", 7125),
        api_key=moon_cfg.get("api_key", ""),
        num_gates=hh_cfg.get("num_gates", 8),
        tool_change_timeout=hh_cfg.get("tool_change_timeout", 120),
        retry_count=hh_cfg.get("retry_count", 2),
    )


def get_filament_map(config: dict) -> dict:
    """Extract filament map from config."""
    return config.get("filament_map", {f"T{i}": i for i in range(8)})


# ── Commands ────────────────────────────────────────────────────────

def cmd_bridge(args, config: dict):
    """Run the real-time bridge: monitor P1S, auto-handle tool changes via Happy Hare."""
    bambu = create_bambu_client(config)
    happy_hare = create_happy_hare(config)
    filament_map = get_filament_map(config)
    bridge_cfg = config["bridge"]

    bridge = Bridge(
        bambu=bambu,
        happy_hare=happy_hare,
        filament_map=filament_map,
        trigger_mode=bridge_cfg.get("trigger_mode", "m600"),
        auto_resume=bridge_cfg.get("auto_resume", True),
        resume_delay=bridge_cfg.get("resume_delay", 3.0),
        bambu_command_timeout=bridge_cfg.get("bambu_command_timeout", 30),
    )

    # Connect to P1S
    print(f"Connecting to P1S at {config['bambu']['host']}...")
    if not bambu.connect():
        print("Failed to connect to P1S. Check IP, access code, and network.")
        sys.exit(1)
    print("Connected to P1S!")

    # Verify Happy Hare
    print("Checking Happy Hare / Moonraker...")
    if not happy_hare.check_connection():
        print("Cannot reach Happy Hare/Moonraker. Is Klipper running?")
        bambu.disconnect()
        sys.exit(1)

    mmu_status = happy_hare.get_status()
    print(f"Happy Hare ready! Current tool: T{mmu_status.current_tool}, "
          f"Filament loaded: {mmu_status.filament_loaded}")

    # Start bridge — it will auto-fetch G-code from P1S when a print starts
    bridge.start()
    print("\n=== Bridge is running ===")
    print("Waiting for print to start on P1S...")
    print("G-code will be auto-fetched from the printer to determine tool sequence.")
    print("Press Ctrl+C to stop\n")

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        bridge.stop()
        bambu.disconnect()
        stats = bridge.get_stats()
        print(f"\nSession stats: {stats['tool_changes_completed']} changes completed, "
              f"{stats['tool_changes_failed']} failed")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)


def cmd_scan(args, config: dict):
    """Scan a G-code file to verify tool-change sequence (for debugging)."""
    filament_map = get_filament_map(config)
    scanner = GCodeScanner(filament_map=filament_map)

    print(f"Scanning: {args.file}\n")
    events = scanner.scan_file(args.file)
    scanner.print_summary(events)

    if not events:
        print("No tool changes found! Make sure Orca Slicer is configured")
        print("with TRADRACK_TOOL_CHANGE comments. See docs/orca_slicer_setup.md")


def cmd_status(args, config: dict):
    """Check connectivity to P1S and Happy Hare."""
    print("=== TradRack-to-Bambu Status Check ===\n")

    # Check P1S
    print(f"[P1S] Connecting to {config['bambu']['host']}:{config['bambu'].get('mqtt_port', 8883)}...")
    bambu = create_bambu_client(config)
    if bambu.connect(timeout=5):
        state = bambu.state
        print(f"[P1S] Connected! Status: {state.status.value}")
        if state.subtask_name:
            print(f"[P1S] Current job: {state.subtask_name} ({state.mc_percent}%)")
        bambu.disconnect()
    else:
        print("[P1S] Connection FAILED. Check IP and access code.")

    print()

    # Check Moonraker / Happy Hare
    moon_cfg = config["moonraker"]
    print(f"[Happy Hare] Connecting to Moonraker at "
          f"{moon_cfg.get('host', '127.0.0.1')}:{moon_cfg.get('port', 7125)}...")
    happy_hare = create_happy_hare(config)
    if happy_hare.check_connection():
        status = happy_hare.get_status()
        print(f"[Happy Hare] Connected! State: {status.state.value}")
        print(f"[Happy Hare] Current tool: T{status.current_tool}, "
              f"Loaded: {status.filament_loaded}, Homed: {status.is_homed}")
    else:
        print("[Happy Hare] Connection FAILED. Is Klipper/Moonraker running?")


def cmd_test(args, config: dict):
    """Test a tool change via Happy Hare."""
    tool = args.tool
    print(f"=== Test Tool Change to T{tool} ===\n")

    happy_hare = create_happy_hare(config)
    if not happy_hare.check_connection():
        print("Cannot reach Happy Hare/Moonraker. Is Klipper running?")
        sys.exit(1)

    status = happy_hare.get_status()
    print(f"Current state: tool=T{status.current_tool}, loaded={status.filament_loaded}")

    filament_map = get_filament_map(config)
    gate = filament_map.get(f"T{tool}", tool)
    print(f"Requesting change to T{tool} (gate {gate})...")

    success = happy_hare.change_tool(gate)
    if success:
        print(f"Tool change to T{tool} SUCCESSFUL!")
    else:
        print(f"Tool change to T{tool} FAILED!")
        sys.exit(1)


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="tradrack-bridge",
        description="TradRack-to-Bambu Bridge: Use TradRack MMU with BambuLab P1S via LAN mode",
    )
    parser.add_argument(
        "-c", "--config",
        default="config/config.yaml",
        help="Path to config file (default: config/config.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # bridge command
    subparsers.add_parser("bridge", help="Run the real-time bridge (auto-fetches G-code from P1S)")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a G-code file to verify tool-change sequence")
    scan_parser.add_argument("file", help="G-code file to scan")

    # status command
    subparsers.add_parser("status", help="Check P1S and Happy Hare connectivity")

    # test command
    test_parser = subparsers.add_parser("test", help="Test a tool change via Happy Hare")
    test_parser.add_argument("tool", type=int, help="Tool number to change to (0-7)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Load config
    config = load_config(args.config)
    setup_logging(config)

    # Dispatch command
    commands = {
        "bridge": cmd_bridge,
        "scan": cmd_scan,
        "status": cmd_status,
        "test": cmd_test,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args, config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
