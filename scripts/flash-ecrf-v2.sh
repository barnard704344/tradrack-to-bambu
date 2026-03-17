#!/bin/bash
# ============================================================
# Flash Klipper firmware to Fly-ECRF-V2 (STM32F072) via USB
# ============================================================
#
# Wiring & DIP switch documentation:
#   https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring
#
# Before running this script:
#   1. Set DIP switches to USB mode (NOT CAN) — see wiring link above
#   2. Hold the BOOT button on the ECRF-V2 board
#   3. Connect the board to the Pi via USB-C
#   4. Release the BOOT button
#   5. Run this script
#
# After flashing, unplug and re-plug USB, then run:
#   ls /dev/serial/by-id/usb-Klipper_stm32f072*
# to find the serial path for mmu.cfg.
#
# Usage:
#   cd ~/tradrack-to-bambu
#   chmod +x scripts/flash-ecrf-v2.sh
#   ./scripts/flash-ecrf-v2.sh
# ============================================================

set -e

KLIPPER_DIR="$HOME/klipper"

echo "=== Fly-ECRF-V2 Klipper Firmware Flash (USB mode) ==="
echo
echo "  Docs: https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring"
echo

# Check Klipper source exists
if [ ! -d "$KLIPPER_DIR" ]; then
    echo "Error: Klipper not found at $KLIPPER_DIR"
    exit 1
fi

# Check dfu-util is installed
if ! command -v dfu-util &>/dev/null; then
    echo "Installing dfu-util..."
    sudo apt-get update -qq && sudo apt-get install -y dfu-util
fi

# Check board is in DFU mode
echo "Checking for board in DFU mode..."
DFU_DEVICE=$(lsusb 2>/dev/null | grep -i "0483:df11" || true)

if [ -z "$DFU_DEVICE" ]; then
    echo
    echo "ERROR: No STM32 DFU device found!"
    echo
    echo "To enter DFU mode:"
    echo "  1. Set DIP switches to USB mode (see docs link above)"
    echo "  2. Hold the BOOT button on the ECRF-V2 board"
    echo "  3. Connect (or re-connect) USB-C to the Pi"
    echo "  4. Release the BOOT button"
    echo "  5. Run this script again"
    echo
    echo "Verify with: lsusb | grep 0483:df11"
    exit 1
fi

echo "[OK] DFU device found: $DFU_DEVICE"

# Save current klipper .config (if any) and write ECRF-V2 config
SAVED_CONFIG=""
if [ -f "$KLIPPER_DIR/.config" ]; then
    SAVED_CONFIG=$(cat "$KLIPPER_DIR/.config")
fi

echo "Writing Fly-ECRF-V2 firmware config (STM32F072, USB on PA11/PA12)..."
cat > "$KLIPPER_DIR/.config" << 'ECRF_FW'
CONFIG_LOW_LEVEL_OPTIONS=y
CONFIG_MACH_STM32=y
CONFIG_BOARD_DIRECTORY="stm32"
CONFIG_MCU="stm32f072xb"
CONFIG_CLOCK_FREQ=48000000
CONFIG_FLASH_SIZE=0x20000
CONFIG_FLASH_BOOT_ADDRESS=0x8000000
CONFIG_RAM_START=0x20000000
CONFIG_RAM_SIZE=0x4000
CONFIG_STACK_SIZE=512
CONFIG_FLASH_APPLICATION_ADDRESS=0x8000000
CONFIG_STM32_SELECT=y
CONFIG_MACH_STM32F072=y
CONFIG_STM32_CLOCK_REF_INTERNAL=y
CONFIG_STM32_USB_PA11_PA12=y
CONFIG_USB_VENDOR_ID=0x1d50
CONFIG_USB_DEVICE_ID=0x614e
CONFIG_USB_SERIAL_NUMBER_CHIPID=y
CONFIG_CANBUS_FREQUENCY=1000000
CONFIG_INITIAL_PINS=""
CONFIG_HAVE_GPIO=y
CONFIG_HAVE_GPIO_ADC=y
CONFIG_HAVE_GPIO_SPI=y
CONFIG_HAVE_GPIO_I2C=y
CONFIG_HAVE_GPIO_HARD_PWM=y
CONFIG_HAVE_STRICT_TIMING=y
CONFIG_HAVE_CHIPID=y
CONFIG_HAVE_STEPPER_BOTH_EDGE=y
CONFIG_STEPPER_STEP_BOTH_EDGE=y
CONFIG_HAVE_BOOTLOADER_REQUEST=y
CONFIG_HAVE_LCD_MENU=y
ECRF_FW

echo "Building firmware..."
make -C "$KLIPPER_DIR" clean 2>/dev/null
make -C "$KLIPPER_DIR" -j"$(nproc)" 2>&1 | tail -5
echo "[OK] Firmware built"

echo
echo "Flashing via DFU..."
sudo dfu-util -a 0 -D "$KLIPPER_DIR/out/klipper.bin" \
    -s 0x08000000:leave 2>&1 | tail -3

echo
echo "[OK] Firmware flashed!"

# Restore Linux MCU config if we had one
if [ -n "$SAVED_CONFIG" ]; then
    echo "$SAVED_CONFIG" > "$KLIPPER_DIR/.config"
    echo "[OK] Restored previous .config (Linux host MCU)"
fi

echo
echo "Now:"
echo "  1. Disconnect and reconnect the USB cable"
echo "  2. Wait 5 seconds, then run:"
echo "       ls /dev/serial/by-id/usb-Klipper_stm32f072*"
echo "  3. Copy that path and re-run setup.sh to auto-configure:"
echo "       cd ~/tradrack-to-bambu && ./setup.sh"
echo
