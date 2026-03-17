#!/bin/bash
# ============================================================
# TradRack-to-Bambu Bridge — Setup Script
# ============================================================
# Sets up:
#   1. Klipper host MCU (klipper-mcu service)
#   2. printer.cfg and Fly-ECRF-V2 reference config
#   3. Python venv and bridge dependencies
#
# Safe to re-run — skips steps that are already done.
#
# Usage:
#   cd ~/tradrack-to-bambu
#   chmod +x setup.sh
#   ./setup.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
KLIPPER_DIR="$HOME/klipper"
PRINTER_DATA="$HOME/printer_data"
PRINTER_CFG="$PRINTER_DATA/config/printer.cfg"
ECRF_SERIAL=""

echo "=== TradRack-to-Bambu Bridge Setup ==="
echo

# ── 1. Check prerequisites ──────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.10+ first."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "Error: Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi
echo "[OK] Python $PY_VERSION"

if [ ! -d "$KLIPPER_DIR" ]; then
    echo "Error: Klipper not found at $KLIPPER_DIR"
    echo "       Install Klipper first via KIAUH: https://github.com/dw-0/kiauh"
    exit 1
fi
echo "[OK] Klipper found at $KLIPPER_DIR"

if [ ! -d "$PRINTER_DATA/config" ]; then
    echo "Error: Printer data directory not found at $PRINTER_DATA"
    echo "       Install Klipper + Moonraker first via KIAUH."
    exit 1
fi
echo "[OK] Printer data directory exists"

# ── 2. Build and install klipper-mcu (host MCU) ─────────────

echo
echo "--- Klipper Host MCU (klipper-mcu) ---"

if systemctl is-active --quiet klipper-mcu 2>/dev/null && [ -x /usr/local/bin/klipper_mcu ]; then
    echo "[OK] klipper-mcu service already running"
else
    echo "Building klipper_mcu for Linux host MCU..."

    # Write the Linux MCU build config
    cat > "$KLIPPER_DIR/.config" << 'MCUCONF'
CONFIG_LOW_LEVEL_OPTIONS=y
CONFIG_MACH_LINUX=y
CONFIG_BOARD_DIRECTORY="linux"
CONFIG_CLOCK_FREQ=50000000
CONFIG_LINUX_SELECT=y
CONFIG_USB_VENDOR_ID=0x1d50
CONFIG_USB_DEVICE_ID=0x614e
CONFIG_USB_SERIAL_NUMBER="klipper_host_mcu"
CONFIG_HAVE_GPIO=y
CONFIG_HAVE_GPIO_ADC=y
CONFIG_HAVE_GPIO_SPI=y
CONFIG_HAVE_GPIO_I2C=y
CONFIG_HAVE_GPIO_HARD_PWM=y
MCUCONF

    make -C "$KLIPPER_DIR" clean 2>/dev/null
    make -C "$KLIPPER_DIR" -j"$(nproc)" 2>&1 | tail -3
    sudo cp "$KLIPPER_DIR/out/klipper.elf" /usr/local/bin/klipper_mcu
    echo "[OK] klipper_mcu binary installed"

    # Install and start the systemd service
    sudo cp "$KLIPPER_DIR/scripts/klipper-mcu.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable klipper-mcu
    sudo systemctl start klipper-mcu
    sleep 2

    if systemctl is-active --quiet klipper-mcu; then
        echo "[OK] klipper-mcu service started"
    else
        echo "[WARN] klipper-mcu service failed to start. Check: systemctl status klipper-mcu"
    fi
fi

# ── 3. Install Klipper configs ──────────────────────────────

echo
echo "--- Klipper Configuration ---"

# Copy printer.cfg if not present (never overwrite existing)
if [ -f "$PRINTER_CFG" ]; then
    echo "[OK] printer.cfg already exists (not overwriting)"
else
    cp "$SCRIPT_DIR/klipper/printer.cfg" "$PRINTER_CFG"
    echo "[OK] printer.cfg installed"
fi

# Copy Fly-ECRF-V2 pin reference
ECRF_CFG="$PRINTER_DATA/config/fly-ecrf-v2-tradrack.cfg"
if [ -f "$ECRF_CFG" ]; then
    echo "[OK] fly-ecrf-v2-tradrack.cfg already exists"
else
    cp "$SCRIPT_DIR/klipper/fly-ecrf-v2-tradrack.cfg" "$ECRF_CFG"
    echo "[OK] fly-ecrf-v2-tradrack.cfg installed"
fi

# Create gcodes directory (required by virtual_sdcard)
mkdir -p "$PRINTER_DATA/gcodes"

# ── 3b. Happy Hare config fixups ────────────────────────────

MMU_PARAMS="$PRINTER_DATA/config/mmu/base/mmu_parameters.cfg"
MMU_HW="$PRINTER_DATA/config/mmu/base/mmu_hardware.cfg"
MMU_MCU="$PRINTER_DATA/config/mmu/base/mmu.cfg"

if [ -d "$PRINTER_DATA/config/mmu/base" ]; then
    echo
    echo "--- Happy Hare Config Fixups ---"

    # Fix servo_move_angle: '' (empty string crashes Klipper parser)
    if grep -q "^servo_move_angle:.*''" "$MMU_PARAMS" 2>/dev/null; then
        sed -i "s|^servo_move_angle:.*|#servo_move_angle:|" "$MMU_PARAMS"
        echo "[OK] Fixed servo_move_angle empty string"
    fi

    # Detect Fly-ECRF-V2 board (or any Klipper USB device)
    ECRF_SERIAL=""
    for dev in /dev/serial/by-id/usb-Klipper_stm32f072*; do
        if [ -e "$dev" ]; then
            ECRF_SERIAL="$dev"
            break
        fi
    done

    if [ -n "$ECRF_SERIAL" ]; then
        echo "Fly-ECRF-V2 detected at: $ECRF_SERIAL"
        # Update MMU MCU serial in mmu.cfg
        if grep -q "serial:.*XXX" "$MMU_MCU" 2>/dev/null; then
            sed -i "s|serial:.*|serial: ${ECRF_SERIAL}|" "$MMU_MCU"
            echo "[OK] Updated MMU MCU serial to $ECRF_SERIAL"
        fi
        # Enable Happy Hare includes
        sed -i 's|^# \[include mmu/base/\*\.cfg\]|\[include mmu/base/*.cfg\]|' "$PRINTER_CFG"
        sed -i 's|^# \[include mmu/optional/client_macros\.cfg\]|\[include mmu/optional/client_macros.cfg\]|' "$PRINTER_CFG"
        echo "[OK] Happy Hare includes enabled"

        # Uncomment dummy extruder (required by Happy Hare for filament loading logic)
        # Uses host MCU GPIO pins — no real hardware attached
        if grep -q '^# \[extruder\]' "$PRINTER_CFG" 2>/dev/null; then
            sed -i '/^# \[extruder\]/,/^# min_extrude_temp/{s/^# //}' "$PRINTER_CFG"
            echo "[OK] Dummy extruder enabled"
        fi
    else
        echo "[INFO] Fly-ECRF-V2 board not detected on USB"
        echo "       MMU includes will stay commented out until the board is connected."
        echo "       After connecting, update serial in: $MMU_MCU"
        echo "       Then re-run this script or uncomment the includes in printer.cfg"
        # Make sure includes are commented out (safe state)
        sed -i 's|^\[include mmu/base/\*\.cfg\]|# [include mmu/base/*.cfg]|' "$PRINTER_CFG"
        sed -i 's|^\[include mmu/optional/client_macros\.cfg\]|# [include mmu/optional/client_macros.cfg]|' "$PRINTER_CFG"

        # Make sure dummy extruder is commented out (no use without MMU)
        if grep -q '^\[extruder\]' "$PRINTER_CFG" 2>/dev/null; then
            sed -i '/^\[extruder\]/,/^min_extrude_temp/{s/^/# /}' "$PRINTER_CFG"
            echo "[OK] Dummy extruder commented out (no ECRF-V2 connected)"
        fi
    fi
else
    echo "[INFO] Happy Hare not installed yet — MMU includes remain commented out"
fi

# Restart Klipper to pick up new config
echo "Restarting Klipper..."
sudo systemctl restart klipper-mcu 2>/dev/null || true
sleep 2
sudo systemctl restart klipper
sleep 5

KLIPPER_STATE=$(curl -s http://127.0.0.1:7125/printer/info 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['state'])" 2>/dev/null \
    || echo "unreachable")

if [ "$KLIPPER_STATE" = "ready" ]; then
    echo "[OK] Klipper is ready"
elif [ "$KLIPPER_STATE" = "error" ]; then
    KLIPPER_MSG=$(curl -s http://127.0.0.1:7125/printer/info 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['state_message'])" 2>/dev/null)
    echo "[WARN] Klipper started but has an error:"
    echo "       $KLIPPER_MSG"
elif [ "$KLIPPER_STATE" = "startup" ]; then
    echo "[WARN] Klipper is still starting up. Give it a few more seconds."
else
    echo "[WARN] Could not reach Moonraker. Is it running?"
fi

# ── 4. Python bridge setup ──────────────────────────────────

echo
echo "--- Bridge Python Environment ---"

# Ensure python3-venv is available
if ! python3 -m venv --help &>/dev/null; then
    echo "Installing python3-venv..."
    sudo apt-get update -qq && sudo apt-get install -y python3-venv
fi

# Create virtual environment
if [ -d "$VENV_DIR" ]; then
    echo "[OK] Virtual environment already exists"
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created"
fi

# Install dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "[OK] Dependencies installed"

# Create log directory
mkdir -p "$SCRIPT_DIR/logs"

# Verify the bridge loads
echo
echo "Verifying bridge CLI..."
if python -m src.main --help &>/dev/null; then
    echo "[OK] Bridge CLI loads successfully"
else
    echo "[FAIL] Bridge CLI failed to load. Check errors above."
    exit 1
fi

# ── 5. Summary ──────────────────────────────────────────────

echo
echo "========================================="
echo "  Setup Complete!"
echo "========================================="
echo
echo "  Klipper state: $KLIPPER_STATE"
echo
echo "  Installed:"
echo "    - klipper-mcu host service"
echo "    - printer.cfg (TradRack-only)"
echo "    - fly-ecrf-v2-tradrack.cfg (pin reference)"
echo "    - Python venv + bridge dependencies"
echo
echo "  Next steps:"

if [ ! -d "$PRINTER_DATA/config/mmu/base" ]; then
    echo "    1. Install Happy Hare:"
    echo "         cd ~ && git clone https://github.com/moggieuk/Happy-Hare.git"
    echo "         cd Happy-Hare && ./install.sh -i"
    echo "       Select: Tradrack 1.0, 8 gates, board 'Not in list'"
    echo "       Then re-run this setup script."
    echo
fi

if [ -z "$ECRF_SERIAL" ]; then
    echo "    2. Connect and flash Fly-ECRF-V2:"
    echo "         cd ~/klipper && make menuconfig  # STM32F072, USB"
    echo "         make && make flash FLASH_DEVICE=/dev/serial/by-id/usb-Klipper_..."
    echo "       Then re-run this setup script to auto-detect the board."
    echo
fi

echo "    3. Edit config/config.yaml with your P1S details:"
echo "         nano $SCRIPT_DIR/config/config.yaml"
echo
echo "    4. Run the bridge:"
echo "         cd $SCRIPT_DIR"
echo "         source venv/bin/activate"
echo "         python -m src.main status    # check connectivity"
echo "         python -m src.main bridge    # start the bridge"
echo
