"""Create Windows Desktop and Start Menu shortcuts named Jonathan Ai."""

from __future__ import annotations

import os
import shutil
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
    dest = source_dir / "JonathanAi.exe"
    if dest.exists():
        return dest
    candidates = [
        source_dir / "packaging" / "windows" / "bin" / "JonathanAi.exe",
        source_dir / "desktop" / "JonathanAi.exe",
        source_dir / "start-desktop.bat",
    ]
    for path in candidates:
        if path.exists():
            return path
    return dest


def remove_parent_leftover_exes(source_dir: Path) -> list[str]:
    """Delete JonathanAi.exe left in %USERPROFILE%\\Jonathan (the parent folder)."""
    from .app_root import leftover_parent_exes

    removed: list[str] = []
    dest_exe = (Path(source_dir) / "JonathanAi.exe").resolve()
    for path in leftover_parent_exes(source_dir):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == dest_exe:
            continue
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def install_app_shortcuts(
    source_dir: Path,
    icon: Path | None = None,
    bundled_exe: Path | None = None,
) -> dict[str, str]:
    """Copy JonathanAi.exe into the app folder and rewrite Desktop/Start Menu links."""
    source_dir = Path(source_dir)
    dest_exe = source_dir / "JonathanAi.exe"
    sources: list[Path] = []
    if bundled_exe:
        sources.append(Path(bundled_exe))
    sources.extend(
        [
            source_dir / "packaging" / "windows" / "bin" / "JonathanAi.exe",
        ]
    )
    for src in sources:
        if src.exists() and src.resolve() != dest_exe.resolve():
            shutil.copy2(src, dest_exe)
            break
    remove_parent_leftover_exes(source_dir)
    result = create_windows_shortcuts(dest_exe, icon if icon and icon.exists() else None)
    result["target"] = str(dest_exe)
    result["workdir"] = str(source_dir)
    result["removed_leftovers"] = remove_parent_leftover_exes(source_dir)
    return result
