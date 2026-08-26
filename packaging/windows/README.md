# Jonathan Ai for Windows

**Version 0.4.6** — Jonathan Ai adds the audited ECC skills/agent catalog, lazy skill activation, Memory Vault interchange, evidence-backed Git-history skill drafts, native market forecasting, personal finance, code graph/memory, engineering-gate, editable-graphics and character engines, a tamper-evident runtime event ledger, and earned-autonomy evidence profiles to the standard upgrade-in-place wizard.

`JonathanAi.exe` looks for the app in this order: `CLAWD_SOURCE_DIR`, the exe folder, `%USERPROFILE%\Jonathan\Jonathan-Ai`, then the current working directory. A working `.venv` is enough to open the UI; Electron is optional. If a Desktop click still says it cannot find Electron or the venv, run `JonathanAi-Setup.exe` again — it upgrades that same `Jonathan-Ai` folder in place and rewrites shortcuts to `%USERPROFILE%\Jonathan\Jonathan-Ai\JonathanAi.exe`.

Desktop path:

**JonathanAi-Setup.exe → visible wizard (Next / Install / Finish) → Jonathan Ai window + Desktop icon**

## Double-click install

From a checkout:

1. Double-click `JonathanAi-Setup.exe` in this `bin/` folder, or `install.bat` / `JonathanAi-Setup.bat` at the repo root.
2. The wizard shows real windows. Click **Next**, choose the folder (default is the existing `%USERPROFILE%\Jonathan\Jonathan-Ai` or a previous `Clawd-Code` folder), click **Install**. A second run upgrades that same folder.
3. Click **Finish**. Jonathan Ai launches immediately.
4. A **Jonathan Ai** shortcut is on the Desktop and in the Start Menu. You do not hunt for `start-desktop.bat`.

`JonathanAi.exe` is the app. It opens the desktop UI window (Electron when present, otherwise the local host). It is not a hidden `.bat`.

The robot sketch is the app icon, installer icon, window icon, and sidebar logo.

## Build the exes (this repo already ships prebuilt PE files)

On Linux (mingw):

```bash
./packaging/windows/build.sh
```

On Windows (Electron plus a standard Inno Setup or NSIS wizard):

```powershell
powershell -File packaging\windows\build-windows.ps1
```

Inno Setup (`JonathanAi.iss`) or NSIS (`JonathanAi.nsi`) produces a standard Setup wizard that registers an uninstaller, writes Desktop/Start Menu shortcuts, upgrades the same folder, preserves `Skills`, installs runtime dependencies, initializes all native engines, optionally synchronizes the ECC catalog when online, and launches the app on Finish.

No API tokens are baked into these artifacts. Tokens stay in `%USERPROFILE%\.clawd\config.json`. There is no token paywall. The on-screen token count is informational only.

First chat: open **Jonathan Ai**, choose a provider (or a local model), send a message. You do not need another agent connected. Tool schemas are forced into the classic Anthropic shape (`input_schema.type=object`). If Anthropic still returns `tools.N.custom.input_schema.type: Field required`, the same request is retried without tools so the chat still replies (v0.2.1).
