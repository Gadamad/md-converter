#!/bin/bash
# build_app.sh — Package MD Converter as a macOS .app bundle
#
# Usage:
#   bash scripts/build_app.sh
#
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "ERROR: build_app.sh is macOS-only."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="$PROJECT_DIR/scripts"
SRC_DIR="$PROJECT_DIR/src"
VENV="$PROJECT_DIR/.venv"
PYTHON="$VENV/bin/python3"
PYINSTALLER="$VENV/bin/pyinstaller"

echo "=== MD Converter — macOS App Build ==="
echo "Project : $PROJECT_DIR"
echo "Source  : $SRC_DIR"
echo "Venv    : $VENV"
echo ""

# -------------------------------------------------------------------
# Step 1: Generate app icon if not already present
# -------------------------------------------------------------------
if [ ! -f "$SCRIPTS_DIR/icon.icns" ]; then
    echo "[1/3] Generating app icon..."
    "$PYTHON" "$SCRIPTS_DIR/generate_icon.py"
else
    echo "[1/3] App icon already exists — skipping generation."
fi
echo ""

# -------------------------------------------------------------------
# Step 2: Clean previous build artifacts
# -------------------------------------------------------------------
echo "[2/3] Cleaning previous build artifacts..."
rm -rf "$SRC_DIR/build" "$SRC_DIR/dist" "$SRC_DIR/MD Converter.spec"
find "$SRC_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 3: Run PyInstaller
# -------------------------------------------------------------------
echo "[3/3] Running PyInstaller..."
cd "$SRC_DIR"

"$PYINSTALLER" \
    --name "MD Converter" \
    --windowed \
    --icon "$SCRIPTS_DIR/icon.icns" \
    --add-data "converters.py:." \
    --hidden-import=webview \
    --hidden-import=webview.platforms.cocoa \
    --hidden-import=objc \
    --hidden-import=AppKit \
    --hidden-import=Foundation \
    --hidden-import=native_drop \
    --noconfirm \
    converter_app.py

echo ""

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
APP_PATH="$SRC_DIR/dist/MD Converter.app"
if [ -d "$APP_PATH" ]; then
    echo "=== BUILD SUCCEEDED ==="
    echo "App bundle: $APP_PATH"
    echo ""
    echo "To run:  open \"$APP_PATH\""
    echo "To move: cp -R \"$APP_PATH\" /Applications/"
    echo ""
    # Show bundle size
    du -sh "$APP_PATH"
else
    echo "=== BUILD FAILED ==="
    echo "No .app bundle found in $SRC_DIR/dist/"
    exit 1
fi
