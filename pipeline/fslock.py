"""
fslock.py — Minimal cross-process file lock (no third-party deps).

Why: state.json and batches.json are written by multiple PROCESSES at once
(the Flask dashboard, the pipeline subprocess it spawns, and CLI tools like
auto_upload.py). A `threading.Lock` only serialises threads inside one
process; without a real file lock, concurrent writers lose updates and
`next_batch_number` can hand out the same Batch_NN twice.

Usage:
    from fslock import FileLock
    with FileLock("/path/to/state.json.lock"):
        ...read-modify-write...

POSIX uses fcntl.flock (blocking, with timeout via polling); Windows uses
msvcrt.locking. Locks are advisory — every writer must go through this.
"""
from __future__ import annotations

import os
import time


class FileLock:
    def __init__(self, lock_path: str, timeout: float = 30.0, poll: float = 0.05):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll = poll
        self._fh = None

    def acquire(self):
        deadline = time.monotonic() + self.timeout
        # Keep the lock file open for the lifetime of the lock
        self._fh = open(self.lock_path, "a+")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > deadline:
                    self._fh.close()
                    self._fh = None
                    raise TimeoutError(
                        f"Could not acquire file lock {self.lock_path} "
                        f"within {self.timeout}s — another process is holding it."
                    )
                time.sleep(self.poll)

    def release(self):
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
