"""Configuration loader for TradRack-to-Bambu bridge."""

import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BambuConfig:
    ip: str = "192.168.1.100"
    access_code: str = ""
    serial_number: str = ""
    port: int = 8883


@dataclass
class MoonrakerConfig:
    host: str = "127.0.0.1"
    port: int = 7125


@dataclass
class LaneInfo:
    material: str = "PLA"
    color: str = "unknown"


@dataclass
class TradRackConfig:
    num_lanes: int = 8
    tool_to_lane: dict = field(default_factory=lambda: {i: i for i in range(8)})
    lanes: dict = field(default_factory=dict)


@dataclass
class BridgeConfig:
    trigger_mode: str = "m600"
    post_load_delay: float = 2.0
    filament_feed_timeout: float = 30.0
    log_level: str = "INFO"


@dataclass
class AppConfig:
    bambu: BambuConfig = field(default_factory=BambuConfig)
    moonraker: MoonrakerConfig = field(default_factory=MoonrakerConfig)
    tradrack: TradRackConfig = field(default_factory=TradRackConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)


def load_config(config_path: str = None) -> AppConfig:
    """Load config from YAML file, falling back to defaults."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    else:
        config_path = Path(config_path)

    config = AppConfig()

    if not config_path.exists():
        logger.warning("Config file not found at %s, using defaults", config_path)
        return config

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    if not raw:
        return config

    # Bambu settings
    if "bambu" in raw:
        b = raw["bambu"]
        config.bambu = BambuConfig(
            ip=b.get("ip", config.bambu.ip),
            access_code=b.get("access_code", config.bambu.access_code),
            serial_number=b.get("serial_number", config.bambu.serial_number),
            port=b.get("port", config.bambu.port),
        )

    # Moonraker settings
    if "moonraker" in raw:
        m = raw["moonraker"]
        config.moonraker = MoonrakerConfig(
            host=m.get("host", config.moonraker.host),
            port=m.get("port", config.moonraker.port),
        )

    # TradRack settings
    if "tradrack" in raw:
        t = raw["tradrack"]
        tool_to_lane = {}
        if "tool_to_lane" in t:
            for k, v in t["tool_to_lane"].items():
                tool_to_lane[int(k)] = int(v)
        else:
            tool_to_lane = {i: i for i in range(8)}

        lanes = {}
        if "lanes" in t:
            for k, v in t["lanes"].items():
                lanes[int(k)] = LaneInfo(
                    material=v.get("material", "PLA"),
                    color=v.get("color", "unknown"),
                )

        config.tradrack = TradRackConfig(
            num_lanes=t.get("num_lanes", config.tradrack.num_lanes),
            tool_to_lane=tool_to_lane,
            lanes=lanes,
        )

    # Bridge settings
    if "bridge" in raw:
        br = raw["bridge"]
        config.bridge = BridgeConfig(
            trigger_mode=br.get("trigger_mode", config.bridge.trigger_mode),
            post_load_delay=br.get("post_load_delay", config.bridge.post_load_delay),
            filament_feed_timeout=br.get(
                "filament_feed_timeout", config.bridge.filament_feed_timeout
            ),
            log_level=br.get("log_level", config.bridge.log_level),
        )

    return config
