#!/bin/bash
set -e

# ── Activate venv ─────────────────────────────────────────────
if [ ! -f ".venv/bin/activate" ]; then
    echo "  [ERROR] Virtual environment not found. Run ./setup.sh first!"
    exit 1
fi
source .venv/bin/activate

# ── Check credentials ─────────────────────────────────────────
if [ ! -f "credentials.py" ]; then
    echo "  [ERROR] credentials.py not found. Run ./setup.sh first!"
    exit 1
fi

echo ""
echo "  ============================================================"
echo "   BabyBillion Upload Pipeline"
echo "  ============================================================"
echo ""

# ── Auto-sync: pull latest code from GitHub ───────────────────
echo "  [SYNC] Pulling latest code from GitHub..."
if git pull --ff-only origin master 2>/dev/null; then
    echo "  [SYNC] Code is up to date."
else
    echo "  [WARN] Git pull failed — running with local code."
fi
echo ""

echo "  Starting pipeline... (Chrome will open when first batch is ready)"
echo "  Press Ctrl+C to stop safely at any time."
echo ""

python3 pipeline.py "$@"
PIPELINE_EXIT=$?

echo ""
if [ $PIPELINE_EXIT -ne 0 ]; then
    echo "  [DONE] Pipeline finished with errors. Check logs/ for details."
else
    echo "  [DONE] Pipeline finished successfully!"
fi

# ── Auto-push: commit and push any code changes ─────────────
echo ""
echo "  [SYNC] Checking for code changes to push..."
git add -A 2>/dev/null
if ! git diff --cached --quiet 2>/dev/null; then
    HOSTNAME_VAL=$(hostname)
    git commit -m "Auto-sync from ${HOSTNAME_VAL} [$(date +%Y-%m-%d)]" >/dev/null 2>/dev/null
    if git push origin master 2>/dev/null; then
        echo "  [SYNC] Changes pushed to GitHub."
    else
        echo "  [WARN] Git push failed — push manually when online."
    fi
else
    echo "  [SYNC] No code changes to push."
fi
echo ""
