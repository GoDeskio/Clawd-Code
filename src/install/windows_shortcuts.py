"""Create Windows Desktop and Start Menu shortcuts named Jonathan Ai."""

from __future__ import annotations

import os
from pathlib import Path


SHORTCUT_NAME = "Jonathan Ai.lnk"


def desktop_dir() -> Path:
    override = os.environ.get("CLAWD_DESKTOP_DIR")
    if override:
        return Path(override)
    return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    override = os.environ.get("CLAWD_START_MENU_DIR")
    if override:
        return Path(override)
    programs = os.environ.get("PROGRAMDATA")
    user_programs = os.environ.get("APPDATA")
    if user_programs:
        return Path(user_programs) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if programs:
        return Path(programs) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_script(target: Path, icon: Path | None, dest: Path) -> str:
    icon_line = f'$s.IconLocation = "{icon};0"' if icon else ""
    return (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(\""
        + str(dest).replace('"', "")
        + "\")\n"
        + f'$s.TargetPath = "{target}"\n'
        + f'$s.WorkingDirectory = "{target.parent}"\n'
        + f'$s.Description = "Jonathan Ai"\n'
        + (icon_line + "\n" if icon_line else "")
        + "$s.Save()\n"
    )


def create_windows_shortcuts(target: Path, icon: Path | None = None) -> dict[str, str]:
    """Write Desktop + Start Menu .lnk files. Safe to call on non-Windows via env overrides."""
    target = Path(target)
    desktop = desktop_dir()
    start = start_menu_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    start.mkdir(parents=True, exist_ok=True)
    desk_lnk = desktop / SHORTCUT_NAME
    start_lnk = start / SHORTCUT_NAME
    if os.name == "nt":
        import subprocess

        for dest in (desk_lnk, start_lnk):
            script = shortcut_script(target, icon, dest)
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
            )
    else:
        for dest in (desk_lnk, start_lnk):
            dest.write_text(f"Jonathan Ai -> {target}\n", encoding="utf-8")
    return {"desktop": str(desk_lnk), "start_menu": str(start_lnk), "name": "Jonathan Ai"}


def find_app_executable(source_dir: Path) -> Path:
    source_dir = Path(source_dir)
    candidates = [
        source_dir / "JonathanAi.exe",
        source_dir / "packaging" / "windows" / "bin" / "JonathanAi.exe",
        source_dir / "desktop" / "JonathanAi.exe",
        source_dir / "start-desktop.bat",
    ]
    for path in candidates:
        if path.exists():
            return path
    return source_dir / "JonathanAi.exe"
