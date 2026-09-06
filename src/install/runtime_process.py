"""Track and stop only the Jonathan Ai processes owned by an install tree."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROCESS_RECORD_NAME = ".jonathan-ai-processes.json"


def process_record_path(source_dir: str | Path) -> Path:
    return Path(source_dir).expanduser().resolve() / PROCESS_RECORD_NAME


def write_process_record(
    source_dir: str | Path,
    *,
    owner_pid: int | None = None,
    backend_pid: int | None = None,
    kind: str = "python",
    owner_executable: str | None = None,
) -> Path:
    """Atomically record the process tree an in-place upgrade may stop."""
    root = Path(source_dir).expanduser().resolve()
    path = process_record_path(root)
    payload = {
        "source_dir": str(root),
        "owner_pid": int(owner_pid or os.getpid()),
        "backend_pid": int(backend_pid) if backend_pid else None,
        "kind": kind,
        "owner_executable": owner_executable or (sys.executable if owner_pid in (None, os.getpid()) else ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def read_process_record(source_dir: str | Path) -> dict[str, Any] | None:
    root = Path(source_dir).expanduser().resolve()
    path = process_record_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        recorded_root = Path(str(payload.get("source_dir") or "")).expanduser().resolve()
        owner_pid = int(payload.get("owner_pid") or 0)
    except (OSError, TypeError, ValueError):
        return None
    if recorded_root != root or owner_pid <= 4:
        return None
    return payload


def remove_process_record(source_dir: str | Path, *, owner_pid: int | None = None) -> None:
    path = process_record_path(source_dir)
    if owner_pid is not None:
        record = read_process_record(source_dir)
        if record and int(record.get("owner_pid") or 0) != int(owner_pid):
            return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _windows_process_info(pid: int) -> tuple[bool, str]:
    """Return process liveness/image via read-only Win32 handles."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False, ""
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False, ""
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        image = ""
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            image = buffer.value
        return exit_code.value == still_active, image
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_running(pid: int) -> tuple[bool, str]:
    if pid <= 4 or pid == os.getpid():
        return False, ""
    if os.name == "nt":
        return _windows_process_info(pid)
    proc_entry = Path("/proc") / str(pid)
    if Path("/proc").is_dir():
        return proc_entry.exists(), ""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return result.returncode == 0 and bool(result.stdout.strip()), ""


def _is_expected_process(record: dict[str, Any], image: str, source_dir: Path) -> bool:
    name = Path(image).name.lower()
    kind = str(record.get("kind") or "").lower()
    allowed = {"jonathanai.exe", "electron.exe", "python.exe", "pythonw.exe"}
    if kind == "electron":
        allowed = {"jonathanai.exe", "electron.exe"}
    elif kind == "python":
        allowed = {"python.exe", "pythonw.exe"}
    if name not in allowed:
        return False
    recorded = Path(str(record.get("owner_executable") or "")).name.lower()
    if recorded and recorded != name:
        return False
    try:
        image_path = Path(image).resolve()
        root = source_dir.resolve()
        if image_path != root and root not in image_path.parents:
            return False
        recorded_path = str(record.get("owner_executable") or "").strip()
        if recorded_path and image_path != Path(recorded_path).resolve():
            return False
    except OSError:
        return False
    return True


def stop_running_app(source_dir: str | Path, *, timeout_s: float = 10.0) -> dict[str, Any]:
    """Stop the recorded Jonathan Ai process tree before an in-place upgrade."""
    root = Path(source_dir).expanduser().resolve()
    record = read_process_record(root)
    if not record:
        return {"was_running": False, "stopped": False}
    owner_pid = int(record["owner_pid"])
    running, image = _pid_is_running(owner_pid)
    if not running:
        remove_process_record(root)
        return {"was_running": False, "stopped": False, "owner_pid": owner_pid}
    if os.name == "nt" and not _is_expected_process(record, image, root):
        return {
            "was_running": False,
            "stopped": False,
            "owner_pid": owner_pid,
            "error": f"recorded PID belongs to an unexpected executable: {image or '(unknown)'}",
        }

    if os.name == "nt":
        taskkill = shutil.which("taskkill") or str(
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        )
        result = subprocess.run(
            [taskkill, "/PID", str(owner_pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_s),
        )
        stopped = result.returncode == 0
    else:
        stopped = True
        try:
            os.kill(owner_pid, signal.SIGTERM)
        except OSError:
            stopped = False
        deadline = time.monotonic() + max(0.1, timeout_s)
        while stopped and _pid_is_running(owner_pid)[0] and time.monotonic() < deadline:
            time.sleep(0.05)
        if stopped and _pid_is_running(owner_pid)[0]:
            try:
                os.kill(owner_pid, signal.SIGKILL)
            except OSError:
                stopped = False

    if stopped:
        remove_process_record(root)
    return {"was_running": True, "stopped": stopped, "owner_pid": owner_pid}
