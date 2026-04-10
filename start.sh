#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[FoxEx] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install/upgrade dependencies
echo "[FoxEx] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Create required directories
mkdir -p data uploads/icons

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     FoxEx Network Monitor v1.0.0         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  URL:      http://0.0.0.0:8000           ║"
echo "║  Login:    admin / admin                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Start the application
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
