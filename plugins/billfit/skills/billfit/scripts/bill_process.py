"""Shared bounded capture for owned local parsers; no input diagnostics escape."""
from __future__ import annotations
import os
import subprocess
import threading
import time
from bill_cancellation import check_cancelled
from billfit_errors import BillFitError


def run_bounded(command: list[str], *, timeout: float = 30,
                output_limit: int = 2_000_000, kind: str = "OCR") -> bytes:
    """Capture bounded stdout; concurrently discard stderr under one deadline.

    This limits wall time and captured output, not native decoder memory. The
    operator must configure a trusted local executable, not an input-supplied one.
    """
    check_cancelled()
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except OSError as exc:
        raise BillFitError(f"LOCAL_{kind}_FAILED", f"The configured local {kind} process could not run.") from exc
    lock = threading.Lock()
    failed = threading.Event()
    chunks, errors = [], []
    captured = 0

    def read_stream(stream, keep: bool):
        nonlocal captured
        try:
            read = getattr(stream, "read1", stream.read)
            while not failed.is_set():
                chunk = read(64 * 1024)
                if not chunk:
                    return
                with lock:
                    captured += len(chunk)
                    if captured > output_limit:
                        errors.append(f"{kind}_OUTPUT_LIMIT")
                        failed.set()
                        return
                    if keep:
                        chunks.append(chunk)
        except (OSError, ValueError):
            with lock:
                errors.append(f"LOCAL_{kind}_FAILED")
            failed.set()

    threads = [threading.Thread(target=read_stream, args=(process.stdout, True), daemon=True),
               threading.Thread(target=read_stream, args=(process.stderr, False), daemon=True)]
    for thread in threads:
        thread.start()
    try:
        while True:
            check_cancelled()
            if failed.is_set():
                code = errors[0]
                message = f"{kind} output exceeded the limit." if code == f"{kind}_OUTPUT_LIMIT" else f"The local {kind} process could not be read."
                raise BillFitError(code, message)
            if not any(thread.is_alive() for thread in threads) and process.poll() is not None:
                break
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise BillFitError(f"LOCAL_{kind}_TIMEOUT", f"Local {kind} parsing exceeded the time limit. Use a smaller, readable input.")
            failed.wait(min(0.01, remaining))
        if process.returncode != 0:
            raise BillFitError(f"LOCAL_{kind}_FAILED", f"Local {kind} parsing failed. Check the file and local parser installation.")
        check_cancelled()
        return b"".join(chunks)
    finally:
        # Only this invocation's child is controlled; no process-name scans.
        failed.set()
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        for thread, stream in zip(threads, (process.stdout, process.stderr)):
            thread.join(timeout=0.25)
            if not thread.is_alive():
                stream.close()
