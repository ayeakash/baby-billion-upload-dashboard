#!/bin/bash
set -e

echo ""
echo "  ============================================================"
echo "   BabyBillion Upload Pipeline - One-Time Setup"
echo "  ============================================================"
echo ""

# ── Check Python ──────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python 3 not found."
    echo "          Install with: brew install python3"
    exit 1
fi
PYVER=$(python3 --version 2>&1)
echo "  [OK] $PYVER found"

# ── Create virtualenv ─────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "  [..] Creating virtual environment..."
    python3 -m venv .venv
    echo "  [OK] Virtual environment created"
else
    echo "  [OK] Virtual environment already exists"
fi

# ── Activate + install deps ───────────────────────────────────
echo "  [..] Installing Python dependencies..."
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  [OK] Dependencies installed"

# ── Check FFmpeg ──────────────────────────────────────────────
if ! command -v ffmpeg &> /dev/null; then
    echo ""
    echo "  [WARN] FFmpeg not found."
    echo "         The pipeline needs FFmpeg to compress videos."
    echo ""
    echo "         Install with:  brew install ffmpeg"
    echo ""
else
    echo "  [OK] FFmpeg found"
fi

# ── Check Chrome ──────────────────────────────────────────────
if [ -d "/Applications/Google Chrome.app" ]; then
    echo "  [OK] Google Chrome found"
else
    echo "  [WARN] Google Chrome not found in /Applications."
    echo "         Install from https://www.google.com/chrome/"
fi

# ── Check credentials.py ──────────────────────────────────────
if [ ! -f "credentials.py" ]; then
    echo ""
    echo "  [ACTION NEEDED] credentials.py not found!"
    echo "    1. Copy credentials.example.py to credentials.py"
    echo "    2. Fill in your Notion token, database ID, and admin login"
    echo ""
    cp credentials.example.py credentials.py
    echo "  [..] Created credentials.py from template — please edit it now."
    echo ""
    echo "  Run:  nano credentials.py"
    echo ""
else
    echo "  [OK] credentials.py found"
fi

echo ""
echo "  ============================================================"
echo "   Setup complete! Run the pipeline with:   ./run.sh"
echo "  ============================================================"
echo ""
