# Jonathan Ai for Windows

**Version 0.2.5** — Jonathan Ai is itself the AI agent. After install, chat works with one API key or a local LLM. Conversations persist across restarts; New Chat is always empty. Shared memory stays in `%USERPROFILE%\.clawd\memory`. MCP, Cursor, and Codex are optional. Rename conversations from the left sidebar (double-click or right-click). The version appears in the installer title and the app header.

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

On Windows (optional Electron + Inno Setup polish):

```powershell
powershell -File packaging\windows\build-windows.ps1
```

Inno Setup (`JonathanAi.iss`) produces a classic Setup wizard that also writes Desktop/Start Menu shortcuts and launches the app on Finish.

No API tokens are baked into these artifacts. Tokens stay in `%USERPROFILE%\.clawd\config.json`. There is no token paywall. The on-screen token count is informational only.

First chat: open **Jonathan Ai**, choose a provider (or a local model), send a message. You do not need another agent connected. Tool schemas are forced into the classic Anthropic shape (`input_schema.type=object`). If Anthropic still returns `tools.N.custom.input_schema.type: Field required`, the same request is retried without tools so the chat still replies (v0.2.1).
