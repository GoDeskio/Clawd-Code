"""Installed application, browser, and command discovery for device control."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any


def _clean_executable(value: str) -> Path | None:
    text = os.path.expandvars(str(value or "").strip()).strip('"')
    if not text:
        return None
    # Registry DisplayIcon values may end with an icon index.
    if "," in text:
        possible, suffix = text.rsplit(",", 1)
        if suffix.strip().lstrip("-").isdigit():
            text = possible.strip('" ')
    path = Path(text).expanduser()
    return path.resolve() if path.is_file() else None


def discover_browsers() -> list[dict[str, str]]:
    candidates: dict[str, list[Path]] = {}
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        local = Path(os.environ.get("LocalAppData", ""))
        candidates = {
            "Microsoft Edge": [program_files_x86 / "Microsoft/Edge/Application/msedge.exe", program_files / "Microsoft/Edge/Application/msedge.exe"],
            "Google Chrome": [program_files / "Google/Chrome/Application/chrome.exe", program_files_x86 / "Google/Chrome/Application/chrome.exe", local / "Google/Chrome/Application/chrome.exe"],
            "Mozilla Firefox": [program_files / "Mozilla Firefox/firefox.exe", program_files_x86 / "Mozilla Firefox/firefox.exe"],
            "Brave": [program_files / "BraveSoftware/Brave-Browser/Application/brave.exe", local / "BraveSoftware/Brave-Browser/Application/brave.exe"],
            "Vivaldi": [local / "Vivaldi/Application/vivaldi.exe", program_files / "Vivaldi/Application/vivaldi.exe"],
            "Opera": [local / "Programs/Opera/opera.exe"],
        }
    elif sys.platform == "darwin":
        candidates = {
            "Safari": [Path("/Applications/Safari.app/Contents/MacOS/Safari")],
            "Google Chrome": [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")],
            "Mozilla Firefox": [Path("/Applications/Firefox.app/Contents/MacOS/firefox")],
        }
    else:
        candidates = {
            "Google Chrome": [Path(shutil.which("google-chrome") or "")],
            "Chromium": [Path(shutil.which("chromium") or shutil.which("chromium-browser") or "")],
            "Mozilla Firefox": [Path(shutil.which("firefox") or "")],
            "Microsoft Edge": [Path(shutil.which("microsoft-edge") or "")],
        }
    rows: list[dict[str, str]] = []
    seen: set[Path] = set()
    for name, paths in candidates.items():
        match = next((path.resolve() for path in paths if str(path) not in {"", "."} and path.is_file()), None)
        if match and match not in seen:
            seen.add(match)
            rows.append({"name": name, "path": str(match)})
    return rows


def _windows_registered_apps() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    rows: dict[str, dict[str, str]] = {}
    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for root, key_name in keys:
        try:
            with winreg.OpenKey(root, key_name) as key:
                count = winreg.QueryInfoKey(key)[0]
                for index in range(count):
                    sub_name = winreg.EnumKey(key, index)
                    try:
                        with winreg.OpenKey(key, sub_name) as sub:
                            value = winreg.QueryValue(sub, None)
                    except OSError:
                        continue
                    path = _clean_executable(value)
                    if path:
                        rows[str(path).lower()] = {"name": path.stem, "path": str(path), "source": "Windows App Paths"}
        except OSError:
            continue
    return sorted(rows.values(), key=lambda item: item["name"].lower())


def discover_path_tools(*, limit: int = 2000) -> list[dict[str, str]]:
    extensions = {item.lower() for item in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT;.COM").split(";") if item}
    rows: dict[str, dict[str, str]] = {}
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(raw.strip('" ')).expanduser()
        try:
            is_directory = folder.is_dir()
        except OSError:
            is_directory = False
        if not is_directory:
            continue
        try:
            for path in folder.iterdir():
                if not path.is_file():
                    continue
                if os.name == "nt" and path.suffix.lower() not in extensions and path.suffix.lower() != ".ps1":
                    continue
                if os.name != "nt" and not os.access(path, os.X_OK):
                    continue
                rows.setdefault(path.name.lower(), {"name": path.stem, "path": str(path.resolve()), "source": "PATH"})
                if len(rows) >= limit:
                    break
        except OSError:
            continue
        if len(rows) >= limit:
            break
    return sorted(rows.values(), key=lambda item: item["name"].lower())


def discover_device_controls(*, limit: int = 2000) -> dict[str, Any]:
    browsers = discover_browsers()
    applications = _windows_registered_apps()
    known = {item["path"].lower() for item in applications}
    for browser in browsers:
        if browser["path"].lower() not in known:
            applications.append({**browser, "source": "browser"})
    tools = discover_path_tools(limit=limit)
    return {
        "platform": sys.platform,
        "applications": sorted(applications, key=lambda item: item["name"].lower()),
        "browsers": browsers,
        "command_line_tools": tools,
        "counts": {"applications": len(applications), "browsers": len(browsers), "command_line_tools": len(tools)},
    }


def resolve_application(identifier: str) -> Path:
    value = str(identifier or "").strip()
    if not value:
        raise ValueError("application or executable is required")
    direct = _clean_executable(value)
    if direct:
        return direct
    on_path = shutil.which(value)
    if on_path:
        return Path(on_path).resolve()
    wanted = value.lower()
    inventory = discover_device_controls()
    candidates = [*inventory["applications"], *inventory["command_line_tools"]]
    for item in candidates:
        name = str(item["name"]).lower()
        path = Path(str(item["path"]))
        if wanted in {name, path.name.lower(), path.stem.lower()}:
            return path.resolve()
    raise ValueError(f"installed application or executable was not found: {identifier}")
