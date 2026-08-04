"""
video_inspector_manager.py
===========================
Clean, minimalistic backend manager for inspecting CMS Video Library details:
- Title
- Language
- Selected Age Groups ("0-3", "3-6", "6+")
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "pipeline")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)

import config as cfg
import uploader

_task_lock = threading.Lock()
_inspection_state: Dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "success_count": 0,
    "fail_count": 0,
    "current_video_id": "",
    "results": [],
    "log": [],
    "error": None
}

_stop_requested = threading.Event()


def get_inspector_status() -> Dict[str, Any]:
    with _task_lock:
        return dict(_inspection_state)


def reset_inspector_state():
    with _task_lock:
        global _inspection_state
        _inspection_state = {
            "running": False,
            "total": 0,
            "processed": 0,
            "success_count": 0,
            "fail_count": 0,
            "current_video_id": "",
            "results": [],
            "log": [],
            "error": None
        }


def stop_inspection():
    global _stop_requested
    _stop_requested.set()
    with _task_lock:
        _inspection_state["log"].append("⏹️ Inspection stopped by user.")


def inspect_single_video(driver, video_id: str) -> Dict[str, Any]:
    library_url = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-library"
    try:
        if "/dashboard/cms/video-library" not in driver.current_url:
            driver.get(library_url)
            time.sleep(2.5)

        # Close leftover modals if open
        driver.execute_script("""
            const cancels = document.querySelectorAll('.btn-cancel, [aria-label="Close"]');
            cancels.forEach(c => c.click());
        """)
        time.sleep(0.4)

        # Locate search input
        search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
        if not search_inputs:
            driver.get(library_url)
            time.sleep(2.5)
            search_inputs = driver.find_elements("css selector", "input.cms-filter-search, input[placeholder*='Search']")
            if not search_inputs:
                return {
                    "video_id": video_id,
                    "status": "ERROR",
                    "title": "N/A",
                    "language": "N/A",
                    "age_groups": [],
                    "message": "Search input not found"
                }

        search_inp = search_inputs[0]

        # Trigger React state filtering for Video ID
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, search_inp, video_id)
        time.sleep(2.0)

        # Find matching row and Edit button
        rows = driver.find_elements("css selector", "table tbody tr")
        edit_btn = None

        for row in rows:
            row_text = row.text.strip()
            if video_id.lower() in row_text.lower() or len(rows) == 1:
                buttons = row.find_elements("css selector", "button")
                for btn in buttons:
                    if btn.text.strip().lower() == "edit":
                        edit_btn = btn
                        break
            if edit_btn:
                break

        if not edit_btn:
            return {
                "video_id": video_id,
                "status": "NOT_FOUND",
                "title": "Not Found",
                "language": "N/A",
                "age_groups": [],
                "message": "Video ID not found in CMS search"
            }

        # Click Edit button to open modal
        driver.execute_script("arguments[0].click();", edit_btn)
        time.sleep(2.0)

        # Inspect title, language, and age groups inside modal
        modal_info = driver.execute_script("""
            const modal = document.querySelector('.bab-ref-edit-root.modal, [role="dialog"]');
            if (!modal) return null;

            // Title
            const titleInp = modal.querySelector('#vl-edit-title-inp');
            let title = titleInp ? titleInp.value.trim() : '';
            if (!title) {
                const ttlEl = modal.querySelector('.modal-ttl');
                if (ttlEl) {
                    title = ttlEl.innerText.replace(/^Edit:\\s*/i, '').trim();
                }
            }

            // Language
            const langSel = modal.querySelector('#vl-edit-language');
            let language = '';
            if (langSel && langSel.selectedIndex >= 0) {
                language = langSel.options[langSel.selectedIndex].text.trim();
            }

            // Selected Age Groups
            const chips = Array.from(modal.querySelectorAll('.chip-opt, button'));
            const selectedAgeGroups = chips
                .filter(c => ['0-3', '3-6', '6+'].includes(c.innerText.trim()) && c.className.includes('sel'))
                .map(c => c.innerText.trim());

            return {
                title: title,
                language: language,
                age_groups: selectedAgeGroups
            };
        """)

        # Close modal
        driver.execute_script("""
            const cancel = document.querySelector('.btn-cancel, [aria-label="Close"]');
            if (cancel) cancel.click();
        """)
        time.sleep(0.5)

        if not modal_info:
            return {
                "video_id": video_id,
                "status": "ERROR",
                "title": "N/A",
                "language": "N/A",
                "age_groups": [],
                "message": "Failed to open edit modal"
            }

        return {
            "video_id": video_id,
            "status": "SUCCESS",
            "title": modal_info["title"] or "Untitled",
            "language": modal_info["language"] or "Unknown",
            "age_groups": modal_info["age_groups"],
            "message": "Inspected successfully"
        }

    except Exception as e:
        return {
            "video_id": video_id,
            "status": "ERROR",
            "title": "N/A",
            "language": "N/A",
            "age_groups": [],
            "message": f"Exception: {str(e)}"
        }


def _run_inspection_thread(video_ids: List[str], headless: bool):
    global _inspection_state, _stop_requested
    _stop_requested.clear()

    with _task_lock:
        _inspection_state = {
            "running": True,
            "total": len(video_ids),
            "processed": 0,
            "success_count": 0,
            "fail_count": 0,
            "current_video_id": "",
            "results": [],
            "log": [f"🚀 Starting inspection for {len(video_ids)} videos..."],
            "error": None
        }

    driver = None
    try:
        driver = uploader.build_driver(headless=headless)
        with _task_lock:
            _inspection_state["log"].append("🔐 Logging into CMS Dashboard...")

        if not uploader.login(driver):
            with _task_lock:
                _inspection_state["running"] = False
                _inspection_state["error"] = "CMS Login failed. Check credentials."
            return

        with _task_lock:
            _inspection_state["log"].append("✅ Logged in! Inspecting videos...")

        for idx, vid in enumerate(video_ids, 1):
            if _stop_requested.is_set():
                break

            with _task_lock:
                _inspection_state["current_video_id"] = vid

            res = inspect_single_video(driver, vid)
            res["index"] = idx

            with _task_lock:
                _inspection_state["processed"] = idx
                if res["status"] == "SUCCESS":
                    _inspection_state["success_count"] += 1
                else:
                    _inspection_state["fail_count"] += 1
                _inspection_state["results"].append(res)

    except Exception as e:
        with _task_lock:
            _inspection_state["error"] = str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        with _task_lock:
            _inspection_state["running"] = False


def start_inspection(video_ids: List[str], headless: bool = True) -> Tuple[bool, str]:
    with _task_lock:
        if _inspection_state["running"]:
            return False, "An inspection task is already running."

    t = threading.Thread(
        target=_run_inspection_thread,
        args=(video_ids, headless),
        daemon=True
    )
    t.start()
    return True, f"Started inspecting {len(video_ids)} videos."
