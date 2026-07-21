#!/bin/bash
# ============================================================
#  setup_cron.sh — Install/remove the nightly Slack summary cron job
#
#  Usage:
#    ./setup_cron.sh install    # Add the cron job (default: 8 PM IST)
#    ./setup_cron.sh remove     # Remove the cron job
#    ./setup_cron.sh status     # Check if the cron job exists
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH="${SCRIPT_DIR}/../.venv/bin/python"
SCRIPT_PATH="${SCRIPT_DIR}/slack_summary.py"
LOG_PATH="${SCRIPT_DIR}/logs/slack_summary.log"

# 8:00 PM IST = 2:30 PM UTC (14:30 UTC)
CRON_SCHEDULE="30 14 * * *"
CRON_COMMENT="# baby-billion-slack-summary"
CRON_LINE="${CRON_SCHEDULE} cd ${SCRIPT_DIR} && ${PYTHON_PATH} ${SCRIPT_PATH} >> ${LOG_PATH} 2>&1 ${CRON_COMMENT}"

case "${1:-install}" in
  install)
    # Create logs directory
    mkdir -p "${SCRIPT_DIR}/logs"

    # Check if Python exists in venv
    if [ ! -f "${PYTHON_PATH}" ]; then
      echo "⚠️  Virtual env Python not found at: ${PYTHON_PATH}"
      echo "   Falling back to system python3..."
      PYTHON_PATH="$(which python3)"
      CRON_LINE="${CRON_SCHEDULE} cd ${SCRIPT_DIR} && ${PYTHON_PATH} ${SCRIPT_PATH} >> ${LOG_PATH} 2>&1 ${CRON_COMMENT}"
    fi

    # Remove any existing entry, then add
    (crontab -l 2>/dev/null | grep -v "baby-billion-slack-summary" || true; echo "${CRON_LINE}") | crontab -

    echo "✅ Cron job installed!"
    echo ""
    echo "   Schedule : Every day at 8:00 PM IST (2:30 PM UTC)"
    echo "   Script   : ${SCRIPT_PATH}"
    echo "   Log file : ${LOG_PATH}"
    echo ""
    echo "   To verify: crontab -l"
    echo "   To remove: $0 remove"
    echo ""
    echo "   💡 To change the time, edit CRON_SCHEDULE in this script."
    echo "      Common schedules:"
    echo "        '0 18 * * *'   → 11:30 PM IST"
    echo "        '30 16 * * *'  → 10:00 PM IST"
    echo "        '0 14 * * *'   → 7:30 PM IST"
    ;;

  remove)
    (crontab -l 2>/dev/null | grep -v "baby-billion-slack-summary" || true) | crontab -
    echo "✅ Cron job removed."
    ;;

  status)
    if crontab -l 2>/dev/null | grep -q "baby-billion-slack-summary"; then
      echo "✅ Cron job is ACTIVE:"
      crontab -l | grep "baby-billion-slack-summary"
    else
      echo "❌ Cron job is NOT installed."
      echo "   Run: $0 install"
    fi
    ;;

  *)
    echo "Usage: $0 {install|remove|status}"
    exit 1
    ;;
esac
