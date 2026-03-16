#!/bin/bash
# ============================================================
# TradRack-to-Bambu Bridge — Setup Script
# ============================================================
# Sets up a Python virtual environment and installs dependencies.
# Run this once after cloning the repo.
#
# Usage:
#   cd ~/tradrack-to-bambu
#   chmod +x setup.sh
#   ./setup.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "=== TradRack-to-Bambu Bridge Setup ==="
echo

# Check Python 3.10+
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

# Ensure python3-venv is installed (needed on Debian/Ubuntu/RPi OS)
if ! python3 -m venv --help &>/dev/null; then
    echo "Installing python3-venv..."
    sudo apt-get update -qq && sudo apt-get install -y python3-venv
fi

# Create virtual environment
if [ -d "$VENV_DIR" ]; then
    echo "[OK] Virtual environment already exists at $VENV_DIR"
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created"
fi

# Activate and install dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "[OK] Dependencies installed"

# Create log directory
mkdir -p "$SCRIPT_DIR/logs"
echo "[OK] Log directory ready"

# Verify the bridge loads
echo
echo "Verifying bridge..."
if python -m src.main --help &>/dev/null; then
    echo "[OK] Bridge CLI loads successfully"
else
    echo "[FAIL] Bridge CLI failed to load. Check Python errors above."
    exit 1
fi

echo
echo "=== Setup Complete ==="
echo
echo "Next steps:"
echo "  1. Edit config/config.yaml with your P1S details"
echo "  2. Activate the venv before running commands:"
echo "       cd $SCRIPT_DIR"
echo "       source venv/bin/activate"
echo "  3. Check connectivity:"
echo "       python -m src.main status"
echo "  4. Run the bridge:"
echo "       python -m src.main bridge"
echo
