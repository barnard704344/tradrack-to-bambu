# TradRack-to-Bambu Bridge

> **Work in Progress** — This project is under active development. The hardware has not been fully tested yet. Use at your own risk and expect breaking changes.

Use a **TradRack MMU** with a **BambuLab P1S** over LAN mode.

This project bridges Bambu's proprietary firmware and the open-source TradRack filament changer by running **Klipper + Happy Hare** on a Raspberry Pi 4 with a **Fly-ECRF-V2** stepper driver board, and communicating with the P1S over **MQTT** (LAN mode).

## How It Works

```
┌─────────────┐     MQTT (LAN)     ┌─────────────────────┐     USB Serial      ┌──────────────┐
│  BambuLab   │◄──────────────────►│   Raspberry Pi 4    │◄────────────────────►│  Fly-ECRF-V2 │
│    P1S      │   status/commands  │                     │   Klipper MCU       │  + TradRack  │
│             │                    │  ┌───────────────┐  │                     │  (8 slots)   │
│  Prints     │  M600 detected ──►│  │ Bridge        │  │                     │              │
│  G-code     │                    │  │ (Python)      │  │  ┌──────────────┐   │  Selector ◄──┤
│             │  Resume print  ◄──│  │               │──┼─►│ Klipper +    │──►│  Gear     ◄──┤
│             │                    │  └───────────────┘  │  │ Happy Hare   │   │  Servo    ◄──┤
└─────────────┘                    └─────────────────────┘  └──────────────┘   └──────────────┘
```

**Print workflow:**
1. Configure Orca Slicer with custom tool-change G-code (see [docs/orca_slicer_setup.md](docs/orca_slicer_setup.md))
2. Slice multi-color model in Orca Slicer and send directly to P1S
3. The bridge service runs on the Pi and connects to the P1S via MQTT
4. When the print starts, the bridge auto-fetches the G-code from the P1S via FTPS
5. Bridge scans the G-code for the tool-change sequence
6. When P1S hits M600 and pauses:
   - Bridge tells Happy Hare to change filament on TradRack
   - Happy Hare unloads old filament, moves selector, loads new filament
   - Bridge resumes the P1S print
7. Repeat for each filament change until print completes

## Hardware

| Component | Purpose |
|-----------|---------|
| BambuLab P1S | 3D Printer (LAN mode enabled) |
| Raspberry Pi 4 | Runs Klipper, Happy Hare, Moonraker, and the bridge |
| Fly-ECRF-V2 | Stepper driver board (STM32F072, TMC2209, USB to Pi) |
| TradRack | Open-source filament changer (up to 8 slots) |

See [docs/hardware.md](docs/hardware.md) for full hardware reference and wiring.

## Project Structure

```
tradrack-to-bambu/
├── setup.sh                       # Main setup script (klipper-mcu, configs, venv, systemd service)
├── config/
│   └── config.yaml                # Bridge configuration (P1S IP, access code, etc.)
├── src/
│   ├── main.py                    # CLI entry point
│   ├── bambu_client.py            # P1S MQTT + FTPS client (LAN mode)
│   ├── happy_hare.py              # Happy Hare controller (Moonraker API)
│   ├── gcode_processor.py         # G-code scanner (extracts tool sequence)
│   ├── bridge.py                  # Orchestration coordinator
│   └── config.py                  # Configuration loader
├── klipper/
│   ├── printer.cfg                # Minimal Klipper config (TradRack-only, no real printer)
│   └── fly-ecrf-v2-tradrack.cfg   # Fly-ECRF-V2 pin reference for Happy Hare
├── scripts/
│   ├── flash-ecrf-v2.sh           # Automated firmware flash for Fly-ECRF-V2 (USB DFU)
│   └── tradrack-bridge.service    # Systemd service template
├── docs/
│   ├── setup_guide.md             # Full hardware/software setup guide
│   ├── hardware.md                # Hardware reference and wiring
│   └── orca_slicer_setup.md       # Orca Slicer configuration guide
└── requirements.txt
```

## Quick Start

### 1. Install Klipper + Moonraker via KIAUH

```bash
ssh admin@<pi-ip-address>
cd ~
git clone https://github.com/dw-0/kiauh.git && ./kiauh/kiauh.sh
```

From the KIAUH menu, install **Klipper**, **Moonraker**, and optionally **KlipperScreen**.

### 2. Install Happy Hare

```bash
cd ~
git clone https://github.com/moggieuk/Happy-Hare.git
cd Happy-Hare && ./install.sh
```

When prompted: select **Tradrack 1.0**, **8 gates**, board **"Not in list"** (option 15).

### 3. Clone This Repo and Run Setup

```bash
cd ~
git clone https://github.com/barnard704344/tradrack-to-bambu.git
cd tradrack-to-bambu
chmod +x setup.sh
./setup.sh
```

`setup.sh` handles everything automatically:
- Builds and installs `klipper-mcu` (Linux host MCU service)
- Copies `printer.cfg` and `fly-ecrf-v2-tradrack.cfg` to Klipper config
- Fixes Happy Hare config issues (servo_move_angle, pin aliases for Fly-ECRF-V2)
- Conditionally enables/disables MMU includes based on Fly-ECRF-V2 USB detection
- Creates Python virtual environment and installs dependencies
- Installs `tradrack-bridge` systemd service (auto-starts on boot)
- Restarts Klipper and verifies it reaches "ready" state

### 4. Flash Fly-ECRF-V2 Firmware (USB Mode)

See [Mellow wiring docs](https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring) for DIP switch configuration (set to USB, **not** CAN).

```bash
# Enter DFU mode: hold BOOT button, plug USB-C into Pi, release BOOT
cd ~/tradrack-to-bambu
chmod +x scripts/flash-ecrf-v2.sh
./scripts/flash-ecrf-v2.sh

# After flashing, unplug/replug USB, then re-run setup to auto-detect:
./setup.sh
```

The flash script automatically configures and builds Klipper firmware for STM32F072 with USB on PA11/PA12 (internal clock reference, no bootloader).

### 5. Configure the Bridge

```bash
nano config/config.yaml
```

Set your P1S IP address, LAN access code, and serial number.

### 6. Configure Orca Slicer

Follow [docs/orca_slicer_setup.md](docs/orca_slicer_setup.md) to set up Orca Slicer's custom tool-change G-code. This makes Orca Slicer insert `M600` + `TRADRACK_TOOL_CHANGE` comments at every filament swap.

### 7. Start the Bridge

```bash
# Start the service
sudo systemctl start tradrack-bridge
sudo systemctl status tradrack-bridge

# Watch logs
journalctl -u tradrack-bridge -f
```

Or run manually for debugging:
```bash
cd ~/tradrack-to-bambu
source venv/bin/activate
python -m src.main status    # check connectivity
python -m src.main bridge    # run in foreground
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `bridge` | Run real-time bridge (auto-fetches G-code, monitors P1S, handles tool changes) |
| `scan <file>` | Scan a G-code file to verify tool-change sequence |
| `status` | Check connectivity to P1S and Happy Hare |
| `test <tool>` | Test a tool change via Happy Hare (0-7) |

All commands accept `-c path/to/config.yaml` (default: `config/config.yaml`).

## Configuration

See [config/config.yaml](config/config.yaml) for all settings. Key items:

- **bambu.host** — P1S IP address
- **bambu.access_code** — LAN access code (from P1S LCD: Settings → LAN Mode)
- **bambu.serial** — Printer serial (from P1S LCD: Settings → Device Info)
- **happy_hare.num_gates** — Number of TradRack filament slots (1–8)
- **bridge.trigger_mode** — `"auto"` (default, listens for both M600 and pause events), `"m600"`, or `"pause"`
- **filament_map** — Maps Orca Slicer tool numbers to TradRack gate numbers

## Systemd Service

The bridge runs as a systemd service called `tradrack-bridge`:

```bash
sudo systemctl start tradrack-bridge     # start
sudo systemctl stop tradrack-bridge      # stop
sudo systemctl restart tradrack-bridge   # restart
sudo systemctl status tradrack-bridge    # check status
journalctl -u tradrack-bridge -f         # follow logs
```

The service starts after Klipper and Moonraker, and auto-restarts on failure.

## Requirements

- Python 3.10+
- Raspberry Pi 4 (or similar SBC)
- Fly-ECRF-V2 board with Klipper MCU firmware (USB mode)
- BambuLab P1S with LAN mode enabled
- TradRack MMU hardware
- Klipper + Happy Hare + Moonraker running on the Pi

## License

MIT
