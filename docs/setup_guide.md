# ==============================================================
# Klipper / Fly-ECRF-V2 / Happy Hare Setup Guide
# ==============================================================
# This guide covers setting up the Raspberry Pi 4 with:
#   - Klipper MCU firmware on the Fly-ECRF-V2 board
#   - Klipper host software on the Pi
#   - Moonraker API server
#   - Happy Hare MMU firmware for TradRack
# ==============================================================

## 1. Prerequisites

- Raspberry Pi 4 (2GB+ RAM) running Raspberry Pi OS Lite (Bookworm)
- Fly-ECRF-V2 board connected to Pi via USB
- TradRack hardware assembled and wired to the Fly-ECRF-V2
- Network connection to same LAN as the BambuLab P1S

## 2. Install Klipper + Moonraker via KIAUH

KIAUH (Klipper Installation And Update Helper) is the easiest way
to install the full Klipper ecosystem.

```bash
# SSH into your Pi
ssh pi@<pi-ip-address>

# Install KIAUH
cd ~
git clone https://github.com/dw-0/kiauh.git
./kiauh/kiauh.sh
```

From the KIAUH menu, install:
1. **Klipper** (the host software)
2. **Moonraker** (the API server)

Do NOT install Mainsail/Fluidd — we don't need a web UI for this
(though you can install one for debugging if you want).

## 3. Flash Klipper MCU Firmware on Fly-ECRF-V2

The Fly-ECRF-V2 uses an STM32F072 MCU. We need to compile and flash
Klipper firmware for it.

```bash
cd ~/klipper

# Configure firmware for STM32F072
make menuconfig
```

In menuconfig, set:
- Micro-controller Architecture: **STMicroelectronics STM32**
- Processor model: **STM32F072**
- Bootloader offset: **No bootloader** (or 8KiB if using DFU bootloader)
- Clock Reference: **8 MHz crystal**
- Communication interface: **USB (on PA11/PA12)**

```bash
# Build firmware
make clean
make

# Find the ECRF-V2 USB device
ls /dev/serial/by-id/

# Flash via DFU (hold BOOT0 button while plugging in USB, then release)
# Enter DFU mode first:
#   1. Disconnect USB
#   2. Hold the BOOT button on the ECRF-V2
#   3. Reconnect USB while holding BOOT
#   4. Release BOOT after 1 second

# Flash
make flash FLASH_DEVICE=/dev/serial/by-id/usb-Klipper_stm32f072_XXXXXXXXXX-if00

# Or via DFU:
sudo dfu-util -a 0 -D out/klipper.bin -s 0x08000000:leave
```

After flashing, the board should enumerate as a Klipper USB device:
```bash
ls /dev/serial/by-id/
# Should show: usb-Klipper_stm32f072_XXXXX-if00
```

## 4. Install Happy Hare

Happy Hare is the MMU firmware for Klipper that manages TradRack.

```bash
cd ~
git clone https://github.com/moggieuk/Happy-Hare.git
cd Happy-Hare

# Run the installer
# Select "TradRack" when prompted for MMU type
# Set number of gates to 8
./install.sh
```

The installer will:
- Install Happy Hare Klipper modules
- Create config files in ~/printer_data/config/mmu/
- Add [include] directives to printer.cfg

## 5. Configure Klipper for Fly-ECRF-V2

Copy the TradRack Klipper config to your printer data directory:

```bash
cp klipper/fly-ecrf-v2-tradrack.cfg ~/printer_data/config/
```

Edit ~/printer_data/config/printer.cfg to include it:

```ini
[include fly-ecrf-v2-tradrack.cfg]
[include mmu/base/*.cfg]
[include mmu/optional/client_macros.cfg]
```

See the `klipper/fly-ecrf-v2-tradrack.cfg` file in this project for
the pin mappings and motor configuration.

## 6. Configure Happy Hare for TradRack

After the Happy Hare installer runs, edit the main MMU config:

```bash
nano ~/printer_data/config/mmu/mmu_parameters.cfg
```

Key settings to verify:
```ini
# MMU type
mmu_vendor: TradRack
mmu_num_gates: 8

# Selector (the carriage that moves between gates)
selector_homing_endstop: tmc
selector_touch_enable: 0

# Gear stepper (feeds filament)
gear_homing_endstop: none

# Filament sensor
toolhead_sensor: none  # We don't have a toolhead sensor on the P1S
gate_sensor: none       # Unless you've added gate sensors
```

Edit the hardware config:
```bash
nano ~/printer_data/config/mmu/mmu_hardware.cfg
```

Make sure the MCU serial path matches your Fly-ECRF-V2:
```ini
[mmu_machine]
serial: /dev/serial/by-id/usb-Klipper_stm32f072_XXXXX-if00
```

## 7. Configure Moonraker

Edit ~/printer_data/config/moonraker.conf:

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

cors_domains:
    *
```

## 8. Start Services

```bash
# Start Klipper
sudo systemctl enable klipper
sudo systemctl start klipper

# Start Moonraker
sudo systemctl enable moonraker
sudo systemctl start moonraker

# Check status
sudo systemctl status klipper
sudo systemctl status moonraker
```

## 9. Verify Happy Hare

```bash
# Check Klipper logs for errors
tail -f ~/printer_data/logs/klippy.log

# From the bridge Pi (or same Pi), test the API:
curl http://localhost:7125/printer/info
# Should return: {"result": {"state": "ready", ...}}

curl http://localhost:7125/printer/objects/query?mmu
# Should return MMU status data
```

## 10. Test TradRack

Once everything is running, test via Moonraker:

```bash
# Home the MMU
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_HOME"}'

# Select gate 0
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_SELECT TOOL=0"}'

# Load filament from gate 0
curl -X POST http://localhost:7125/printer/gcode/script \
  -H "Content-Type: application/json" \
  -d '{"script": "MMU_CHANGE_TOOL TOOL=0"}'
```

Or use the bridge's test command:
```bash
cd ~/tradrack-to-bambu
python -m src.main -c config/config.yaml test 0
```

## 11. Notes

- The Fly-ECRF-V2 does NOT control the P1S extruder — it only
  controls the TradRack selector and gear motors
- The P1S extruder is controlled by the P1S firmware as normal
- Happy Hare's tip-forming works by controlling the TradRack gear
  motor to shape the filament tip before retraction
- If you have filament sensors on the TradRack gates, configure
  them in mmu_hardware.cfg for better reliability
