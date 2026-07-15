#!/bin/bash
# ── BabyBillion Pipeline Dashboard (macOS) ──────────────────────

set -e

# ── Ensure working directory is this script's folder ─────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PIPELINE_DIR="$SCRIPT_DIR/pipeline"

# ── Try venv first, fall back to global Python ──────────────
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
    echo "  [OK] Using virtual environment"
else
    echo "  [INFO] No .venv found, using system Python"
fi

# ── Check credentials ─────────────────────────────────────────
if [ ! -f "$PIPELINE_DIR/credentials.py" ]; then
    echo ""
    echo "  [ERROR] credentials.py not found in:"
    echo "          $PIPELINE_DIR"
    echo ""
    echo "  Create credentials.py with your Notion token!"
    echo ""
    exit 1
fi

# ── Verify Python + Flask are available ──────────────────────
if ! python3 -c "import flask" 2>/dev/null; then
    echo ""
    echo "  [ERROR] Flask is not installed."
    echo "  Run:  pip install flask requests selenium"
    echo ""
    exit 1
fi

echo ""
echo "  ============================================================"
echo "   BabyBillion Pipeline Dashboard"
echo "  ============================================================"
echo ""
echo "  Starting Dashboard server on http://127.0.0.1:5050..."
echo "  Press Ctrl+C in this window to stop the server."
echo ""

# ── Launch browser AFTER a short delay so Flask can start ────
(sleep 2 && open "http://127.0.0.1:5050") &

# ── Run the Flask app from this directory ────────────────────
python3 "$SCRIPT_DIR/app.py"

# ── If Flask exits (crash or Ctrl+C) ─────────────────────────
echo ""
echo "  [Dashboard stopped]"
echo ""
