# TradRack-to-Bambu Bridge

Use a **TradRack MMU** with a **BambuLab P1S** over LAN mode.

This project bridges the gap between Bambu's proprietary firmware and the open-source TradRack filament changer by running **Klipper + Happy Hare** on a Raspberry Pi 4 with a **Fly-ECRF-V2** stepper driver board, and communicating with the P1S over **MQTT** (LAN mode).

## How It Works

```
┌─────────────┐     MQTT (LAN)     ┌─────────────────────┐     USB Serial      ┌──────────────┐
│  BambuLab   │◄──────────────────►│   Raspberry Pi 4    │◄───────────────────►│  Fly-ECRF-V2 │
│    P1S      │   status/commands  │                     │   Klipper MCU       │  + TradRack  │
│             │                    │  ┌───────────────┐  │                     │  (8 slots)   │
│  Prints     │  M600 detected ──►│  │ Bridge        │  │                     │              │
│  G-code     │                    │  │ (Python)      │  │  ┌──────────────┐   │  Selector ◄──┤
│             │  Resume print  ◄──│  │               │──┼─►│ Klipper +    │──►│  Gear     ◄──┤
│             │                    │  └───────────────┘  │  │ Happy Hare   │   │  Servo    ◄──┤
└─────────────┘                    └─────────────────────┘  └──────────────┘   └──────────────┘
```

**Print workflow:**
1. Slice multi-color model in Bambu Slicer (or any slicer)
2. Run G-code through the bridge processor to inject M600 at tool changes
3. Upload processed G-code to P1S and start print
4. Bridge monitors P1S via MQTT — when M600 triggers a pause:
   - Bridge tells Happy Hare to change filament on TradRack
   - Happy Hare unloads old filament, moves selector, loads new filament
   - Bridge resumes the P1S print
5. Repeat for each filament change until print completes

## Hardware

| Component | Purpose |
|-----------|---------|
| BambuLab P1S | 3D Printer (LAN mode enabled) |
| Raspberry Pi 4 | Runs Klipper, Happy Hare, Moonraker, and the bridge |
| Fly-ECRF-V2 | Stepper driver board (STM32F072, TMC2209, USB to Pi) |
| TradRack | Open-source filament changer (up to 8 slots) |

## Project Structure

```
tradrack-to-bambu/
├── config/
│   └── config.yaml          # Bridge configuration
├── src/
│   ├── main.py              # CLI entry point
│   ├── bambu_client.py      # P1S MQTT client (LAN mode)
│   ├── happy_hare.py        # Happy Hare controller (Moonraker API)
│   ├── gcode_processor.py   # G-code tool-change processor
│   └── bridge.py            # Orchestration coordinator
├── klipper/
│   ├── printer.cfg           # Minimal Klipper config (TradRack-only)
│   └── fly-ecrf-v2-tradrack.cfg  # ECRF-V2 pin reference for Happy Hare
├── docs/
│   └── setup_guide.md       # Full hardware/software setup guide
└── requirements.txt
```

## Quick Start

### 1. Set Up the Pi (Klipper + Happy Hare)

See [docs/setup_guide.md](docs/setup_guide.md) for the full guide. Summary:

```bash
# Install Klipper + Moonraker via KIAUH
git clone https://github.com/dw-0/kiauh.git && ./kiauh/kiauh.sh

# Flash Klipper firmware on Fly-ECRF-V2
cd ~/klipper && make menuconfig  # STM32F072, USB
make && make flash FLASH_DEVICE=/dev/serial/by-id/usb-Klipper_stm32f072_XXXXX-if00

# Install Happy Hare
git clone https://github.com/moggieuk/Happy-Hare.git
cd Happy-Hare && ./install.sh  # Select TradRack, 8 gates
```

### 2. Configure the Bridge

```bash
# Clone this repo on the Pi
git clone https://github.com/yourusername/tradrack-to-bambu.git
cd tradrack-to-bambu

# Install Python dependencies
pip install -r requirements.txt

# Edit config with your P1S details
nano config/config.yaml
```

Set your P1S IP address, LAN access code, and serial number in `config/config.yaml`.

### 3. Check Connectivity

```bash
python -m src.main status
```

This verifies the bridge can reach both the P1S (MQTT) and Happy Hare (Moonraker).

### 4. Process G-code

```bash
# Process a single file — injects M600 at every tool change
python -m src.main process -f my_multicolor_print.gcode -o ready_to_print.gcode
```

Upload the processed G-code to the P1S (via Bambu Studio, SD card, or FTP).

### 5. Run the Bridge

```bash
# Start monitoring — pass the original G-code so it knows the tool sequence
python -m src.main bridge -g my_multicolor_print.gcode
```

Start the print on the P1S. The bridge handles the rest.

### 6. Test a Tool Change

```bash
# Test Happy Hare tool change to gate 0
python -m src.main test 0
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `bridge [-g gcode]` | Run real-time bridge (monitor P1S + handle tool changes) |
| `process -f file [-o output]` | Process G-code to inject M600 at tool changes |
| `process -d dir [-o outdir]` | Process all G-code files in a directory |
| `status` | Check connectivity to P1S and Happy Hare |
| `test <tool>` | Test a tool change via Happy Hare (0-7) |

All commands accept `-c path/to/config.yaml` (default: `config/config.yaml`).

## Configuration

See [config/config.yaml](config/config.yaml) for all settings. Key items:

- **bambu.host** — P1S IP address
- **bambu.access_code** — LAN access code (from P1S LCD: Settings > LAN Mode)
- **bambu.serial** — Printer serial (from P1S LCD: Settings > Device Info)
- **happy_hare.num_gates** — Number of TradRack filament slots (1-8)
- **bridge.trigger_mode** — `"m600"` or `"pause"` detection mode
- **filament_map** — Maps slicer tool numbers to TradRack gate numbers

## Requirements

- Python 3.10+
- Raspberry Pi 4 (or similar SBC)
- Fly-ECRF-V2 board with Klipper MCU firmware
- BambuLab P1S with LAN mode enabled
- TradRack MMU hardware
- Klipper + Happy Hare + Moonraker running on the Pi

## License

MIT
