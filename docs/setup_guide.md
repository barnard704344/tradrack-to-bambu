# Klipper / Fly-ECRF-V2 / Happy Hare Setup Guide

This guide covers the full setup of a Raspberry Pi 4 to run a TradRack MMU with a BambuLab P1S. Most steps are automated by `setup.sh` — this guide explains what happens and how to troubleshoot.

## Overview

The setup installs:
- **Klipper** — host software and Linux host MCU service (`klipper-mcu`)
- **Moonraker** — API server for Klipper
- **Happy Hare** — MMU firmware (manages TradRack selector, gear, servo)
- **Fly-ECRF-V2 firmware** — Klipper MCU on the RP2040 stepper driver board
- **tradrack-to-bambu bridge** — Python service that connects P1S ↔ TradRack

## 1. Prerequisites

- Raspberry Pi 4 (2GB+ RAM) running **Raspberry Pi OS Lite (Bookworm)**
- Fly-ECRF-V2 board (RP2040, TMC2209)
- TradRack hardware assembled and wired to the Fly-ECRF-V2
- Network connection to same LAN as the BambuLab P1S
- USB-C cable between Pi and Fly-ECRF-V2

**Fly-ECRF-V2 wiring reference:**
https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring

## 2. Install Klipper + Moonraker via KIAUH

```bash
ssh admin@<pi-ip-address>
cd ~
git clone https://github.com/dw-0/kiauh.git
./kiauh/kiauh.sh
```

From the KIAUH menu, install:
1. **Klipper** (the host software)
2. **Moonraker** (the API server)
3. **KlipperScreen** (optional — touchscreen UI for Happy Hare status)

Do NOT install Mainsail/Fluidd unless you want a web UI for debugging.

## 3. Install Happy Hare

```bash
cd ~
git clone https://github.com/moggieuk/Happy-Hare.git
cd Happy-Hare
./install.sh
```

When the interactive installer prompts you:
- **MMU Type**: Tradrack 1.0
- **Number of gates**: 8
- **Binky encoder**: Yes
- **Board**: "Not in list" (option 15)

Saying yes to Binky sets `mmu_version: 1.0e` (the "e" suffix), `encoder_resolution: 1.0` (12-tooth disc), and `gate_homing_endstop: encoder`.

The installer creates config files in `~/printer_data/config/mmu/`.

## 4. Clone This Repo and Run Setup

```bash
cd ~
git clone https://github.com/barnard704344/tradrack-to-bambu.git
cd tradrack-to-bambu
chmod +x setup.sh
./setup.sh
```

`setup.sh` does the following automatically:

1. **Checks prerequisites** — Python 3.10+, Klipper installed, printer_data exists
2. **Builds klipper-mcu** — compiles and installs the Linux host MCU service (provides `/tmp/klipper_host_mcu` for Klipper's `[mcu host]`)
3. **Installs Klipper configs** — copies `printer.cfg` and `fly-ecrf-v2-tradrack.cfg` to `~/printer_data/config/`
4. **Fixes Happy Hare config issues**:
   - Comments out `servo_move_angle: ''` (empty string crashes Klipper)
   - Auto-applies Fly-ECRF-V2 pin aliases to `mmu.cfg` (replaces `{placeholder}` values)
   - Enables/disables MMU includes based on Fly-ECRF-V2 USB detection
   - Enables/disables dummy extruder (required by Happy Hare when ECRF-V2 is connected)
5. **Restarts Klipper** — restarts `klipper-mcu` and `klipper`, verifies "ready" state
6. **Creates Python venv** — installs bridge dependencies in isolated virtual environment
7. **Installs systemd service** — `tradrack-bridge.service` (auto-starts on boot, restarts on failure)

**Safe to re-run** — `setup.sh` skips steps that are already done.

## 5. Flash Fly-ECRF-V2 Firmware (USB Mode)

The Fly-ECRF-V2 uses an **RP2040** MCU. The automated flash script handles everything via a two-stage process.

### Flash Overview

The flash script performs two stages:
1. **Stage 1**: Flashes the Katapult USB bootloader via UF2 (board in BOOTSEL mode)
2. **Stage 2**: Compiles Klipper firmware for RP2040 and flashes it via Katapult

### Enter BOOTSEL Mode

1. Disconnect the USB cable from the Fly-ECRF-V2
2. Hold the **BOOT** button on the board
3. Connect USB-C cable from Pi to the Fly-ECRF-V2
4. Release the BOOT button after ~1 second

Verify BOOTSEL mode:
```bash
lsusb | grep 2e8a:0003
# Should show: Raspberry Pi RP2 Boot
```

### Flash

```bash
cd ~/tradrack-to-bambu
chmod +x scripts/flash-ecrf-v2.sh
./scripts/flash-ecrf-v2.sh
```

The script automatically:
- Clones and builds Katapult bootloader for RP2040 USB
- Mounts the RPI-RP2 boot drive and copies the Katapult UF2 file
- Compiles Klipper firmware for RP2040 (16KiB bootloader, USBSERIAL, gpio17 startup pin)
- Flashes Klipper via Katapult's flashtool
- Restores the Linux host MCU `.config` afterward

### Firmware Configuration Details

For reference, these are the firmware settings (the flash script sets them automatically):

| Setting | Value |
|---------|-------|
| MCU Architecture | Raspberry Pi RP2040/RP235x |
| Processor model | rp2040 |
| Bootloader offset | 16KiB bootloader (Katapult) |
| Communication interface | USBSERIAL |
| GPIO pins at startup | gpio17 |

### After Flashing

The script waits for the board to appear automatically. Verify:
```bash
ls /dev/serial/by-id/usb-Klipper_rp2040*
# Should show: usb-Klipper_rp2040_XXXXX-if00
```

Then re-run setup to auto-detect and configure:
```bash
cd ~/tradrack-to-bambu && ./setup.sh
```

## 6. Fly-ECRF-V2 Pin Mapping

These pin assignments come from the official Fly-ECRF-V2 pinout diagram. The `setup.sh` script applies them to `mmu.cfg` automatically.

| Function | GPIO Pin |
|----------|----------|
| **Selector** | |
| Step | gpio4 |
| Direction | gpio3 |
| Enable | gpio5 |
| UART | gpio2 |
| Diag/Endstop | gpio20 |
| **Gear** | |
| Step | gpio7 |
| Direction | gpio8 |
| Enable | gpio6 |
| UART | gpio9 |
| Diag/Encoder (Binky) | gpio15 |
| **Other** | |
| Servo | gpio21 |
| Neopixel | gpio14 |

Pins are referenced as RP2040 GPIO numbers (`gpio0`–`gpio29`).

See `klipper/fly-ecrf-v2-tradrack.cfg` in this repo for the full pin reference file.

## 7. Configure Happy Hare

After `setup.sh` has applied the pin aliases, verify the key settings:

### mmu_parameters.cfg

```bash
nano ~/printer_data/config/mmu/base/mmu_parameters.cfg
```

Key settings:
```ini
mmu_vendor: TradRack
mmu_num_gates: 8
selector_homing_endstop: tmc
selector_touch_enable: 0
gear_homing_endstop: none
toolhead_sensor: none   # no sensor on P1S toolhead
gate_sensor: none       # unless you've added gate sensors
gate_homing_endstop: encoder          # Binky encoder for gate homing
```

### mmu_hardware.cfg (encoder & version)

Verify the Binky encoder settings:
```ini
mmu_version: 1.0e                    # "e" suffix = encoder fitted (Binky)

[mmu_encoder mmu_encoder]
encoder_pin: ^mmu:MMU_ENCODER        # gpio15 (Gear DIAG header)
encoder_resolution: 1.0              # Binky 12-tooth disc default (calibrate with MMU_CALIBRATE_ENCODER)
```

`setup.sh` verifies these automatically. After calibration, the actual resolution is stored in `mmu_vars.cfg` and overrides this default.

### mmu.cfg (MCU serial)

```bash
nano ~/printer_data/config/mmu/base/mmu.cfg
```

The serial path should match your board:
```ini
serial: /dev/serial/by-id/usb-Klipper_rp2040_XXXXX-if00
```

If `setup.sh` detected the board, this was set automatically.

## 8. Configure Moonraker

`~/printer_data/config/moonraker.conf` should already be configured by KIAUH. Verify:

```ini
[server]
host: 0.0.0.0
port: 7125
klippy_uds_address: ~/printer_data/comms/klippy.sock

[authorization]
trusted_clients:
    127.0.0.1
    10.0.0.0/8
    172.16.0.0/12
    192.168.0.0/16
```

## 9. Verify Services

```bash
# Check all services are running
sudo systemctl status klipper-mcu
sudo systemctl status klipper
sudo systemctl status moonraker

# Check Klipper state via Moonraker API
curl -s http://localhost:7125/printer/info | python3 -m json.tool

# Check Klipper logs for errors
tail -50 ~/printer_data/logs/klippy.log

# Check Happy Hare MMU status
curl -s http://localhost:7125/printer/objects/query?mmu
```

## 10. Configure the Bridge

```bash
nano ~/tradrack-to-bambu/config/config.yaml
```

Set your P1S details:
- **bambu.host** — P1S IP address
- **bambu.access_code** — from P1S LCD: Settings → LAN Mode
- **bambu.serial** — from P1S LCD: Settings → Device Info

The default `trigger_mode: "auto"` listens for both M600 and pause events — this works for most setups.

## 11. Start the Bridge Service

```bash
# Start it
sudo systemctl start tradrack-bridge

# Check status
sudo systemctl status tradrack-bridge

# Watch logs
journalctl -u tradrack-bridge -f
```

The service auto-starts on boot and restarts on failure (10-second delay).

## 12. Test

### Check connectivity
```bash
cd ~/tradrack-to-bambu
source venv/bin/activate
python -m src.main status
```

### Test a tool change
```bash
python -m src.main test 0
```

### Test TradRack via Moonraker API
```bash
# Home the MMU
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_HOME"}'

# Select gate 0
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_SELECT TOOL=0"}'
```

## Troubleshooting

### Klipper shows "error" state
```bash
# Check the error message
curl -s http://localhost:7125/printer/info | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['state_message'])"

# Check logs
tail -100 ~/printer_data/logs/klippy.log
```

Common causes:
- **servo_move_angle empty string**: `setup.sh` fixes this automatically
- **Missing extruder**: only needed if ECRF-V2 is connected. `setup.sh` handles this
- **Invalid pins on host MCU**: gpio pins only work on the RP2040 MMU MCU, not the Linux host MCU

### Board not detected after flashing
1. Check: `ls /dev/serial/by-id/usb-Klipper_rp2040*`
2. If nothing shows, hold BOOT, re-plug USB, and re-run `scripts/flash-ecrf-v2.sh`
3. If the board shows as `usb-katapult_rp2040*`, Katapult is running but Klipper wasn't flashed — re-run the flash script

### Bridge can't connect to P1S
1. Verify P1S is in LAN mode (Settings → LAN Mode on P1S LCD)
2. Check IP address, access code, and serial in `config/config.yaml`
3. Ensure Pi and P1S are on the same network
4. Test: `python -m src.main status`

## Notes

- The Fly-ECRF-V2 does NOT control the P1S extruder — it only controls the TradRack selector and gear motors
- The P1S extruder is controlled by the P1S firmware as normal
- Happy Hare's tip-forming works by controlling the TradRack gear motor to shape the filament tip before retraction
- If you have filament sensors on the TradRack gates, configure them in `mmu_hardware.cfg`

### Binky Encoder Calibration

After initial setup and homing, calibrate the encoder:
```bash
# Via Moonraker API:
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_CALIBRATE_ENCODER"}'
```

Or from KlipperScreen / console: `MMU_CALIBRATE_ENCODER`

This measures the actual encoder resolution (should be close to 1.0 for a 12-tooth Binky) and saves the calibrated value to `mmu_vars.cfg`.
