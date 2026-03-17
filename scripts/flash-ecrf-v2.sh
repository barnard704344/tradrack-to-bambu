#!/bin/bash
# ============================================================
# Flash Klipper firmware to Fly-ECRF-V2 (RP2040) via USB
# ============================================================
#
# Docs & wiring:
#   https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/flash/usb
#   https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring
#
# Two-stage flash process:
#   Stage 1: Flash Katapult USB bootloader via UF2 (board in BOOTSEL mode)
#   Stage 2: Compile Klipper for RP2040 and flash via Katapult
#
# Before running this script:
#   1. Hold the BOOT button on the ECRF-V2 board
#   2. Connect the board to the Pi via USB-C
#   3. Release the BOOT button
#   4. Run this script
#
# After flashing, the board appears at:
#   ls /dev/serial/by-id/usb-Klipper_rp2040*
#
# Usage:
#   cd ~/tradrack-to-bambu
#   chmod +x scripts/flash-ecrf-v2.sh
#   ./scripts/flash-ecrf-v2.sh
# ============================================================

set -e

KLIPPER_DIR="$HOME/klipper"
KATAPULT_DIR="$HOME/katapult"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Fly-ECRF-V2 Klipper Firmware Flash (RP2040, USB mode) ==="
echo
echo "  Docs: https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/flash/usb"
echo

# Check Klipper source exists
if [ ! -d "$KLIPPER_DIR" ]; then
    echo "Error: Klipper not found at $KLIPPER_DIR"
    exit 1
fi

# ── Stage 1: Flash Katapult USB bootloader via UF2 ──────────

# Check if Katapult is installed; clone if not
if [ ! -d "$KATAPULT_DIR" ]; then
    echo "Katapult not found — cloning..."
    git clone https://github.com/Arksine/katapult.git "$KATAPULT_DIR"
fi

# Check if board already has Katapult running (skip UF2 stage)
KATAPULT_SERIAL=""
for dev in /dev/serial/by-id/usb-katapult_rp2040*; do
    if [ -e "$dev" ]; then
        KATAPULT_SERIAL="$dev"
        break
    fi
done

# Check if board already has Klipper running (needs Katapult re-entry)
KLIPPER_SERIAL=""
for dev in /dev/serial/by-id/usb-Klipper_rp2040*; do
    if [ -e "$dev" ]; then
        KLIPPER_SERIAL="$dev"
        break
    fi
done

if [ -n "$KATAPULT_SERIAL" ]; then
    echo "[OK] Katapult bootloader already running at: $KATAPULT_SERIAL"
    echo "     Skipping UF2 stage."
elif [ -n "$KLIPPER_SERIAL" ]; then
    echo "[OK] Klipper already running at: $KLIPPER_SERIAL"
    echo "     To re-flash, entering Katapult bootloader mode..."
    cd "$KLIPPER_DIR" && make flash FLASH_DEVICE="$KLIPPER_SERIAL" 2>&1 | tail -5 || true
    sleep 3
    for dev in /dev/serial/by-id/usb-katapult_rp2040*; do
        if [ -e "$dev" ]; then
            KATAPULT_SERIAL="$dev"
            break
        fi
    done
    if [ -z "$KATAPULT_SERIAL" ]; then
        echo "[WARN] Could not enter Katapult mode. Hold BOOT, re-plug USB, and try again."
        exit 1
    fi
else
    # Board should be in BOOTSEL mode (RP2 Boot) — flash Katapult via UF2
    echo "Checking for board in BOOTSEL mode (RP2 Boot)..."
    RP2_DEVICE=$(lsusb 2>/dev/null | grep -i "2e8a:0003" || true)

    if [ -z "$RP2_DEVICE" ]; then
        echo
        echo "ERROR: No RP2040 BOOTSEL device found!"
        echo
        echo "To enter BOOTSEL mode:"
        echo "  1. Hold the BOOT button on the ECRF-V2 board"
        echo "  2. Connect (or re-connect) USB-C to the Pi"
        echo "  3. Release the BOOT button"
        echo "  4. Run this script again"
        echo
        echo "Verify with: lsusb | grep 2e8a:0003"
        exit 1
    fi

    echo "[OK] RP2040 BOOTSEL device found: $RP2_DEVICE"

    # Wait for the RPI-RP2 drive to mount
    echo "Waiting for RPI-RP2 boot drive to mount..."
    RP2_MOUNT=""
    for i in $(seq 1 15); do
        # Check common mount points
        for mp in /media/*/RPI-RP2 /mnt/RPI-RP2 /run/media/*/RPI-RP2; do
            if [ -d "$mp" ] 2>/dev/null; then
                RP2_MOUNT="$mp"
                break 2
            fi
        done
        # Try to find it via lsblk
        PART=$(lsblk -rno NAME,LABEL 2>/dev/null | grep -i "RPI-RP2" | awk '{print $1}' | head -1)
        if [ -n "$PART" ]; then
            # Auto-mount if not mounted
            sudo mkdir -p /mnt/RPI-RP2
            sudo mount "/dev/$PART" /mnt/RPI-RP2 2>/dev/null || true
            if mountpoint -q /mnt/RPI-RP2 2>/dev/null; then
                RP2_MOUNT="/mnt/RPI-RP2"
                break
            fi
        fi
        sleep 1
    done

    if [ -z "$RP2_MOUNT" ]; then
        echo
        echo "ERROR: RPI-RP2 boot drive not found/mounted!"
        echo "       The board is in BOOTSEL mode but the drive didn't mount."
        echo "       Try manually: sudo mkdir -p /mnt/RPI-RP2 && sudo mount /dev/sda1 /mnt/RPI-RP2"
        exit 1
    fi

    echo "[OK] RPI-RP2 drive mounted at: $RP2_MOUNT"

    # Build Katapult for RP2040 USB
    echo "Building Katapult USB bootloader for RP2040..."
    cat > "$KATAPULT_DIR/.config" << 'KATAPULT_CFG'
CONFIG_LOW_LEVEL_OPTIONS=y
CONFIG_MACH_RPXXXX=y
CONFIG_MACH_RP2040=y
CONFIG_RP2040_FLASH_W25Q080=y
CONFIG_RPXXXX_FLASH_START_0100=y
CONFIG_RPXXXX_USB=y
CONFIG_INITIAL_PINS=""
KATAPULT_CFG
    make -C "$KATAPULT_DIR" olddefconfig 2>&1 | tail -3

    make -C "$KATAPULT_DIR" clean 2>/dev/null
    make -C "$KATAPULT_DIR" -j"$(nproc)" 2>&1 | tail -5
    echo "[OK] Katapult bootloader built"

    # Copy UF2 to the RP2 boot drive
    if [ ! -f "$KATAPULT_DIR/out/katapult.uf2" ]; then
        echo "ERROR: Katapult UF2 file not found at $KATAPULT_DIR/out/katapult.uf2"
        exit 1
    fi

    echo "Copying Katapult UF2 to RPI-RP2 drive..."
    sudo cp "$KATAPULT_DIR/out/katapult.uf2" "$RP2_MOUNT/"
    sync
    echo "[OK] Katapult UF2 copied — board should reboot automatically"

    # Wait for the board to reboot into Katapult
    echo "Waiting for Katapult USB serial device..."
    sleep 3
    for i in $(seq 1 20); do
        for dev in /dev/serial/by-id/usb-katapult_rp2040*; do
            if [ -e "$dev" ]; then
                KATAPULT_SERIAL="$dev"
                break 2
            fi
        done
        sleep 1
    done

    if [ -z "$KATAPULT_SERIAL" ]; then
        echo
        echo "ERROR: Katapult serial device not found after flashing bootloader."
        echo "       Check the board LED — it should be blinking."
        echo "       Try: ls /dev/serial/by-id/"
        exit 1
    fi

    echo "[OK] Katapult running at: $KATAPULT_SERIAL"
fi

# ── Stage 2: Build and flash Klipper via Katapult ───────────

# Save current klipper .config (if any)
SAVED_CONFIG=""
if [ -f "$KLIPPER_DIR/.config" ]; then
    SAVED_CONFIG=$(cat "$KLIPPER_DIR/.config")
fi

echo
echo "Building Klipper firmware for RP2040 (16KiB bootloader, USB)..."
cat > "$KLIPPER_DIR/.config" << 'ECRF_FW'
CONFIG_LOW_LEVEL_OPTIONS=y
CONFIG_MACH_RPXXXX=y
CONFIG_MACH_RP2040=y
CONFIG_RP2040_FLASH_W25Q080=y
CONFIG_RPXXXX_FLASH_START_4000=y
CONFIG_RPXXXX_USB=y
CONFIG_INITIAL_PINS="gpio17"
ECRF_FW
make -C "$KLIPPER_DIR" olddefconfig 2>&1 | tail -3

make -C "$KLIPPER_DIR" clean 2>/dev/null
make -C "$KLIPPER_DIR" -j"$(nproc)" 2>&1 | tail -5
echo "[OK] Klipper firmware built"

echo
echo "Flashing Klipper via Katapult..."
if [ -f "$HOME/klippy-env/bin/python" ]; then
    PYTHON="$HOME/klippy-env/bin/python"
else
    PYTHON="python3"
fi

"$PYTHON" "$KATAPULT_DIR/scripts/flashtool.py" -d "$KATAPULT_SERIAL" 2>&1 | tail -10

echo
echo "[OK] Klipper firmware flashed!"

# Restore Linux MCU config if we had one
if [ -n "$SAVED_CONFIG" ]; then
    echo "$SAVED_CONFIG" > "$KLIPPER_DIR/.config"
    echo "[OK] Restored previous .config (Linux host MCU)"
fi

# Wait for Klipper serial to appear
echo "Waiting for Klipper serial device..."
sleep 3
KLIPPER_SERIAL=""
for i in $(seq 1 15); do
    for dev in /dev/serial/by-id/usb-Klipper_rp2040*; do
        if [ -e "$dev" ]; then
            KLIPPER_SERIAL="$dev"
            break 2
        fi
    done
    sleep 1
done

if [ -n "$KLIPPER_SERIAL" ]; then
    echo "[OK] Klipper MCU detected at: $KLIPPER_SERIAL"
else
    echo "[WARN] Klipper serial device not found yet."
    echo "       Try: ls /dev/serial/by-id/"
fi

echo
echo "Next steps:"
echo "  1. Run setup.sh to auto-configure:"
echo "       cd ~/tradrack-to-bambu && ./setup.sh"
echo
