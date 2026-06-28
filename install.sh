#!/bin/bash
# install.sh — Set up MD Converter with a local virtual environment
#
# Usage:
#   cd md-converter
#   bash install.sh
#
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "ERROR: install.sh is for the macOS app setup."
    echo "For CLI usage, create a virtual environment and install requirements.txt manually."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "=== MD Converter — Setup ==="
echo ""

# -------------------------------------------------------------------
# Step 1: Check Python 3
# -------------------------------------------------------------------
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
    echo "[1/6] Python found: $PY ($(python3 --version 2>&1))"
else
    echo "[1/6] ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
echo ""

# -------------------------------------------------------------------
# Step 2: Create virtual environment
# -------------------------------------------------------------------
if [ -d "$VENV_DIR" ]; then
    echo "[2/6] Virtual environment already exists at .venv/"
else
    echo "[2/6] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "  Created .venv/"
fi
echo ""

# -------------------------------------------------------------------
# Step 3: Install Python dependencies
# -------------------------------------------------------------------
echo "[3/6] Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo ""

# -------------------------------------------------------------------
# Step 4: Install PyInstaller (needed for .app build)
# -------------------------------------------------------------------
echo "[4/6] Installing PyInstaller..."
"$VENV_DIR/bin/pip" install pyinstaller -q
echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 5: Check Tesseract (needed for scanned PDF OCR)
# -------------------------------------------------------------------
echo "[5/6] Checking Tesseract OCR..."
if command -v tesseract &>/dev/null; then
    echo "  Tesseract found: $(tesseract --version 2>&1 | head -1)"
else
    echo "  WARNING: Tesseract not found."
    echo "  OCR for scanned PDFs won't work without it."
    echo "  Install with: brew install tesseract"
fi
echo ""

# -------------------------------------------------------------------
# Create output directories
# -------------------------------------------------------------------
mkdir -p "$PROJECT_DIR/converted"
mkdir -p "$PROJECT_DIR/input"

# -------------------------------------------------------------------
# Step 6: Build .app and install to /Applications
# -------------------------------------------------------------------
echo "[6/6] Building MD Converter.app..."
bash "$PROJECT_DIR/scripts/build_app.sh"

APP_PATH="$PROJECT_DIR/src/dist/MD Converter.app"
if [ -d "$APP_PATH" ]; then
    echo ""
    echo "Installing to /Applications..."
    pkill -x "MD Converter" 2>/dev/null || true
    sleep 1
    rm -rf "/Applications/MD Converter.app"
    cp -R "$APP_PATH" "/Applications/MD Converter.app"
    echo "  Installed: /Applications/MD Converter.app"
fi
echo ""

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
echo "=== Setup Complete ==="
echo ""
echo "MD Converter is now in your Applications folder."
echo "Open it from Launchpad, Spotlight, or Finder > Applications."
echo ""
echo "You can also run from the command line:"
echo "  .venv/bin/python3 src/converter_app.py file1.pdf file2.docx"
