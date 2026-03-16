"""Configuration loader for TradRack-to-Bambu bridge."""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class BambuConfig:
    host: str = "192.168.1.100"
    access_code: str = ""
    serial: str = ""
    mqtt_port: int = 8883
    ftp_port: int = 990


@dataclass
class MoonrakerConfig:
    host: str = "http://127.0.0.1"
    port: int = 7125
    api_key: str = ""


@dataclass
class HappyHareConfig:
    num_gates: int = 8
    tool_change_timeout: int = 120
    retry_count: int = 2


@dataclass
class BridgeConfig:
    trigger_mode: str = "m600"
    poll_interval: float = 1.0
    auto_resume: bool = True
    resume_delay: float = 3.0
    bambu_command_timeout: float = 30.0


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "./logs/bridge.log"
    max_size_mb: int = 10
    backup_count: int = 3


@dataclass
class FilamentInfo:
    material: str = "PLA"
    color: str = "unknown"


def load_config(config_path: str = None) -> dict:
    """Load and validate the YAML configuration file.

    Returns the raw config dict so all consumers (main.py, bridge, etc.)
    work with the same structure that matches config.yaml.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"Error: Config file is empty: {config_path}")
        sys.exit(1)

    # Validate required sections
    required_sections = ["bambu", "moonraker", "happy_hare", "bridge"]
    for section in required_sections:
        if section not in config:
            print(f"Error: Missing '{section}' section in config")
            sys.exit(1)

    return config
