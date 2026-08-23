# Jonathan Ai for Windows

**Version 0.2.0** — Jonathan Ai is itself the AI agent. After install, chat works with one API key or a local LLM. MCP, Cursor, and Codex are optional and not required. Rename conversations from the left sidebar (double-click or right-click). The version appears in the installer title and the app header.

Desktop path:

**JonathanAi-Setup.exe → visible wizard (Next / Install / Finish) → Jonathan Ai window + Desktop icon**

## Double-click install

From a checkout:

1. Double-click `JonathanAi-Setup.exe` in this `bin/` folder, or `install.bat` / `JonathanAi-Setup.bat` at the repo root.
2. The wizard shows real windows. Click **Next**, choose the folder (default `%USERPROFILE%\Jonathan\Jonathan-Ai`), click **Install**.
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

First chat: open **Jonathan Ai**, choose a provider (or a local model), send a message. You do not need another agent connected. Tool schemas are sanitized so Anthropic/OpenAI requests always include `input_schema.type` (v0.2.0 fix for `tools.N.custom.input_schema.type`).
