"""Visible Windows install wizard: Next / Install / Finish, then launch the app."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.version import get_version

from .constants import CANONICAL_HTTPS, PRODUCT_NAME
from .launch import launch_jonathan_ai
from .source import default_source_dir
from .windows_shortcuts import create_windows_shortcuts, find_app_executable
from .wizard import InstallWizard


WIZARD_PAGES = ("Welcome", "Install location", "Installing", "Finish")
WIZARD_BUTTONS = ("Next", "Back", "Install", "Finish", "Cancel")


def robot_image_path() -> Path:
    return Path(__file__).resolve().parents[1] / "desktop" / "web" / "robot.png"


def run_windows_wizard(*, source_dir: str | None = None, from_local: str | None = None) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
    except Exception as exc:  # noqa: BLE001
        print(f"Tk is required for the Windows wizard: {exc}")
        return 1

    dest = Path(source_dir).expanduser() if source_dir else default_source_dir()
    local = Path(from_local) if from_local else Path(__file__).resolve().parents[2]
    page = {"i": 0}
    clone = {"v": False}

    root = tk.Tk()
    root.title(f"Install {PRODUCT_NAME} {get_version()}")
    root.geometry("620x460")
    root.configure(bg="#121214")
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(robot_image_path())))
    except Exception:
        pass

    header = tk.Frame(root, bg="#121214")
    header.pack(fill="x", padx=22, pady=16)
    try:
        photo = tk.PhotoImage(file=str(robot_image_path()))
        # subsample if huge
        if photo.width() > 96:
            factor = max(1, photo.width() // 88)
            photo = photo.subsample(factor, factor)
        img = tk.Label(header, image=photo, bg="#121214")
        img.image = photo
        img.pack(side="left", padx=(0, 14))
    except Exception:
        pass
    titles = tk.Frame(header, bg="#121214")
    titles.pack(side="left", fill="x")
    tk.Label(titles, text=PRODUCT_NAME, fg="#f4f7ff", bg="#121214", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(titles, text="Desktop installer", fg="#9aa0a6", bg="#121214", font=("Segoe UI", 11)).pack(anchor="w")

    body = tk.Frame(root, bg="#1a1b1e", highlightbackground="#2a2c31", highlightthickness=1)
    body.pack(fill="both", expand=True, padx=22, pady=(0, 12))

    welcome = tk.Frame(body, bg="#1a1b1e")
    tk.Label(
        welcome,
        text=f"This wizard installs {PRODUCT_NAME} {get_version()} on this computer.\n\n"
        "It copies GoDeskio/Clawd-Code into your Jonathan folder, creates the app, "
        "and puts Jonathan Ai on the Desktop and Start Menu.\n\n"
        "Tokens stay on this machine. Nothing is written into the installer artifact.",
        fg="#e8e8e8",
        bg="#1a1b1e",
        justify="left",
        wraplength=540,
        font=("Segoe UI", 11),
    ).pack(anchor="w", padx=18, pady=18)

    loc = tk.Frame(body, bg="#1a1b1e")
    tk.Label(loc, text="Install folder", fg="#f4f7ff", bg="#1a1b1e", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=18, pady=(18, 6))
    dest_var = tk.StringVar(value=str(dest))
    row = tk.Frame(loc, bg="#1a1b1e")
    row.pack(fill="x", padx=18)
    tk.Entry(row, textvariable=dest_var, bg="#121214", fg="#f4f7ff", insertbackground="#f4f7ff").pack(side="left", fill="x", expand=True)
    def browse() -> None:
        picked = filedialog.askdirectory(initialdir=str(Path(dest_var.get()).parent))
        if picked:
            dest_var.set(picked)
    tk.Button(row, text="Browse…", command=browse).pack(side="left", padx=8)
    clone_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        loc,
        text="Clone GoDeskio/Clawd-Code into the Jonathan folder if it is not already there",
        variable=clone_var,
        fg="#c8c8c8",
        bg="#1a1b1e",
        selectcolor="#121214",
        activebackground="#1a1b1e",
        wraplength=520,
        justify="left",
    ).pack(anchor="w", padx=18, pady=12)
    tk.Label(loc, text=f"Update channel: {CANONICAL_HTTPS}", fg="#9aa0a6", bg="#1a1b1e").pack(anchor="w", padx=18)

    progress = tk.Frame(body, bg="#1a1b1e")
    bar = ttk.Progressbar(progress, mode="indeterminate")
    bar.pack(fill="x", padx=18, pady=(18, 8))
    log = tk.Text(progress, height=12, bg="#121214", fg="#e8e8e8", insertbackground="#f4f7ff")
    log.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    finish = tk.Frame(body, bg="#1a1b1e")
    finish_msg = tk.Label(
        finish,
        text="Installation finished. Shortcuts named Jonathan Ai are on the Desktop and Start Menu.",
        fg="#e8e8e8",
        bg="#1a1b1e",
        wraplength=540,
        justify="left",
        font=("Segoe UI", 11),
    )
    finish_msg.pack(anchor="w", padx=18, pady=18)
    launch_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
        finish,
        text=f"Launch {PRODUCT_NAME} now",
        variable=launch_var,
        fg="#f4f7ff",
        bg="#1a1b1e",
        selectcolor="#121214",
        activebackground="#1a1b1e",
    ).pack(anchor="w", padx=18)

    frames = [welcome, loc, progress, finish]
    status: dict[str, Any] = {"result": None, "error": None}

    def show(index: int) -> None:
        page["i"] = index
        for frame in frames:
            frame.pack_forget()
        frames[index].pack(fill="both", expand=True)
        back_btn.configure(state=("normal" if index in {1} else "disabled"))
        next_btn.configure(state=("normal" if index in {0, 1} else "disabled"))
        install_btn.configure(state=("normal" if index == 1 else "disabled"))
        finish_btn.configure(state=("normal" if index == 3 else "disabled"))

    def append(message: str) -> None:
        log.insert("end", message + "\n")
        log.see("end")

    def do_install() -> None:
        clone["v"] = bool(clone_var.get())
        target = dest_var.get()
        show(2)
        bar.start(12)
        wizard = InstallWizard()

        def progress_cb(event: dict[str, Any]) -> None:
            root.after(0, append, str(event.get("message") or event.get("error") or event.get("type")))

        def work() -> None:
            try:
                result = wizard.run_sync(
                    source_dir=target,
                    from_local=None if clone["v"] else local,
                    clone=clone["v"],
                    progress=progress_cb,
                )
                icon = robot_image_path()
                if not icon.exists():
                    icon = Path(result["source_dir"]) / "src" / "desktop" / "web" / "robot.png"
                exe = find_app_executable(Path(result["source_dir"]))
                packaging_exe = Path(result["source_dir"]) / "packaging" / "windows" / "bin" / "JonathanAi.exe"
                if packaging_exe.exists() and not (Path(result["source_dir"]) / "JonathanAi.exe").exists():
                    import shutil

                    shutil.copy2(packaging_exe, Path(result["source_dir"]) / "JonathanAi.exe")
                    exe = Path(result["source_dir"]) / "JonathanAi.exe"
                create_windows_shortcuts(exe, icon if icon.exists() else None)
                status["result"] = result
            except Exception as exc:  # noqa: BLE001
                status["error"] = str(exc)
                root.after(0, append, f"ERROR: {exc}")
            def done() -> None:
                bar.stop()
                if status["error"]:
                    finish_msg.configure(text=f"Install failed: {status['error']}")
                else:
                    finish_msg.configure(
                        text="Installation finished. Shortcuts named Jonathan Ai are on the Desktop and Start Menu."
                    )
                show(3)
            root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def on_finish() -> None:
        result = status.get("result") or {}
        source = Path(result.get("source_dir") or dest_var.get())
        if launch_var.get():
            try:
                launch_jonathan_ai(source)
            except Exception as exc:  # noqa: BLE001
                append(str(exc))
        root.destroy()

    buttons = tk.Frame(root, bg="#121214")
    buttons.pack(fill="x", padx=22, pady=(0, 16))
    back_btn = tk.Button(buttons, text="Back", command=lambda: show(0), width=10)
    next_btn = tk.Button(buttons, text="Next", command=lambda: show(1), width=10)
    install_btn = tk.Button(buttons, text="Install", command=do_install, width=10)
    finish_btn = tk.Button(buttons, text="Finish", command=on_finish, width=10)
    cancel_btn = tk.Button(buttons, text="Cancel", command=root.destroy, width=10)
    cancel_btn.pack(side="right")
    finish_btn.pack(side="right", padx=6)
    install_btn.pack(side="right")
    next_btn.pack(side="right", padx=6)
    back_btn.pack(side="right")

    show(0)
    root.mainloop()
    return 0 if not status.get("error") else 1
