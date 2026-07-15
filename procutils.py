"""
procutils.py — Cross-platform process helpers for the dashboard.

Historically this codebase shelled out to Windows-only tools (taskkill,
powershell Get-Process) and raw ctypes/NtSuspendProcess calls. Those silently
no-op on macOS/Linux. Every process operation now goes through this module,
which picks the right mechanism per platform.
"""
from __future__ import annotations

import logging
import os
import platform
import signal
import subprocess
import sys

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


# ── Suspend / resume a single process ─────────────────────────────────────────

def suspend_process(pid: int) -> tuple[bool, str]:
    """Suspend a process. SIGSTOP on POSIX, NtSuspendProcess on Windows."""
    if IS_WINDOWS:
        return _win_suspend_resume(pid, resume=False)
    try:
        os.kill(pid, signal.SIGSTOP)
        return True, "suspended"
    except Exception as e:
        return False, f"SIGSTOP failed: {e}"


def resume_process(pid: int) -> tuple[bool, str]:
    """Resume a suspended process. SIGCONT on POSIX, NtResumeProcess on Windows."""
    if IS_WINDOWS:
        return _win_suspend_resume(pid, resume=True)
    try:
        os.kill(pid, signal.SIGCONT)
        return True, "resumed"
    except Exception as e:
        return False, f"SIGCONT failed: {e}"


def _win_suspend_resume(pid: int, resume: bool) -> tuple[bool, str]:
    import ctypes  # Windows-only path
    PROCESS_SUSPEND_RESUME = 0x0800
    kernel32 = ctypes.windll.kernel32
    ntdll = ctypes.windll.ntdll
    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False, "Failed to open process handle."
    try:
        fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
        ret = fn(handle)
        if ret == 0:
            return True, "resumed" if resume else "suspended"
        return False, f"Nt{'Resume' if resume else 'Suspend'}Process failed with code {ret}."
    finally:
        kernel32.CloseHandle(handle)


# ── Kill helpers ──────────────────────────────────────────────────────────────

def kill_pid(pid: int, force: bool = True) -> bool:
    """Kill a single process by PID."""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except Exception:
        return False


def _child_pids(pid: int) -> list[int]:
    """Direct children of a process (POSIX)."""
    try:
        result = subprocess.run(["pgrep", "-P", str(pid)],
                                capture_output=True, text=True, timeout=5)
        return [int(t) for t in result.stdout.split() if t.strip().isdigit()]
    except Exception:
        return []


def kill_process_tree(pid: int) -> bool:
    """Kill a process and its descendants.

    POSIX walks the child tree explicitly — we must NOT killpg here, because
    a subprocess often shares the dashboard's own process group and killpg
    would take the whole app down with it.
    """
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        else:
            # Depth-first: collect descendants before killing the parent
            stack, ordered = [pid], []
            while stack:
                p = stack.pop()
                ordered.append(p)
                stack.extend(_child_pids(p))
            for p in reversed(ordered):  # children first
                try:
                    os.kill(p, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        return True
    except Exception:
        return False


def kill_processes_by_name(*names: str) -> int:
    """Force-kill all processes whose exact name matches.

    Returns the number of kill commands that ran without error.
    """
    killed = 0
    for name in names:
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/IM", f"{name}.exe", "/T"],
                               capture_output=True, timeout=5)
            else:
                subprocess.run(["pkill", "-9", "-x", name],
                               capture_output=True, timeout=5)
            killed += 1
        except Exception as e:
            log.warning(f"kill_processes_by_name({name}) failed: {e}")
    return killed


def kill_selenium_browser() -> None:
    """Kill ONLY Selenium's automation browser — never the user's own Chrome.

    Strategy: kill chromedriver (with its child tree on Windows via /T; on
    POSIX the spawned Chrome exits when its chromedriver dies or is cleaned
    up by _safe_quit_driver's tree-kill) plus the dedicated
    'Chrome for Testing' binary Selenium Manager downloads. The user's
    personal 'Google Chrome' / 'chrome' processes are deliberately untouched.
    """
    kill_processes_by_name("chromedriver")
    if not IS_WINDOWS:
        try:
            subprocess.run(["pkill", "-9", "-f", "Chrome for Testing"],
                           capture_output=True, timeout=5)
        except Exception:
            pass


def list_other_python_pids() -> list[int]:
    """PIDs of all other Python processes (excluding this one)."""
    my_pid = os.getpid()
    pids: list[int] = []
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Get-Process python* -ErrorAction SilentlyContinue | "
                 f"Where-Object {{ $_.Id -ne {my_pid} }} | "
                 f"Select-Object -ExpandProperty Id"],
                capture_output=True, text=True, timeout=5)
            raw = result.stdout.split()
        else:
            result = subprocess.run(["pgrep", "-i", "python"],
                                    capture_output=True, text=True, timeout=5)
            raw = result.stdout.split()
        for tok in raw:
            tok = tok.strip()
            if tok.isdigit() and int(tok) != my_pid:
                pids.append(int(tok))
    except Exception as e:
        log.warning(f"list_other_python_pids failed: {e}")
    return pids


def kill_other_python_processes() -> int:
    """Kill every Python process except the current one. Returns count killed."""
    killed = 0
    for pid in list_other_python_pids():
        if kill_pid(pid):
            killed += 1
    return killed


# ── Open a folder in the OS file manager ─────────────────────────────────────

def open_in_file_manager(path: str) -> tuple[bool, str]:
    """Reveal a folder in Explorer / Finder / the Linux file manager."""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", path], check=True, timeout=10)
        else:
            subprocess.run(["xdg-open", path], check=True, timeout=10)
        return True, f"Opened {path}"
    except Exception as e:
        return False, f"Failed to open folder: {e}"
