<div align="center">

**English** | [Français](docs/i18n/README_FR.md) | [Русский](docs/i18n/README_RU.md) | [हिन्दी](docs/i18n/README_HI.md) | [العربية](docs/i18n/README_AR.md) | [Português](docs/i18n/README_PT.md)

# Jonathan Ai

**A local desktop and CLI agent, built as a Python reimplementation of Claude Code**

**Version 0.2.8** — Jonathan Ai is itself the AI agent. Chats persist on disk and survive restart. New Chat starts a blank thread. Shared memory (`~/.clawd/memory`) lets facts from one chat inform another. Internal workers can plan a goal in parallel without Cursor, Codex, or MCP. Session JSON is always UTF-8 (Windows no longer decodes as cp1252). Anthropic tool results that are objects are stringified so resumed chats do not 400. A first Anthropic chat — including desktop streaming — retries without tools if a schema 400 still appears. First launch repairs the venv and pip packages automatically. The Windows launcher finds `%USERPROFILE%\Jonathan\Jonathan-Ai`.

*From TypeScript Source → Rebuilt in Python with ❤️*

***

[![GitHub stars](https://img.shields.io/github/stars/GoDeskio/Clawd-Code?style=for-the-badge&logo=github&color=yellow)](https://github.com/GoDeskio/Clawd-Code/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/GoDeskio/Clawd-Code?style=for-the-badge&logo=github&color=blue)](https://github.com/GoDeskio/Clawd-Code/network/members)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)


**🔥 Active Development • New Features Weekly 🔥**

</div>

***

## 🎯 Why Jonathan Ai?

**Jonathan Ai** is a **production-oriented Python rebuild of Claude Code**, ported from the **real TypeScript architecture** and shipped as a **working desktop and CLI agent**, not just a source dump.

- **Real Agent Runtime** — tool-calling loop, streaming REPL, session history, and multi-turn execution
- **High-Fidelity Port** — keeps the original Claude Code architecture while adapting it to idiomatic Python
- **Built to Hack On** — readable Python codebase, rich tests, and markdown-driven skill extensibility

<div align="center">

**Token Streaming + Tool-Aware Agent Loop**

![Streaming Agent Experience](assets/clawd-stream.gif)

**Programmable Skill Runtime with Tool Sandboxing**

![Skills (Slash Commands)](assets/clawd-code-skill.png)

**Instant Web Fetch for External Context**

![Web Fetch](assets/claude-code-webfetch.png)

**Real CLI • Real Usage • Real Community**

</div>

**A real Claude Code-style terminal workflow in Python: stream replies, call tools, fetch context, and extend behavior with skills.**

**🚀 Try it now! Fork it, modify it, make it yours! Pull requests welcome!**

***

## ⭐ Star History

<a href="https://www.star-history.com/?repos=GoDeskio%2FClawd-Code&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=GoDeskio%2FClawd-Code&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=GoDeskio%2FClawd-Code&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=GoDeskio%2FClawd-Code&type=date&legend=top-left" />
 </picture>
</a>

## ✨ Features

### Streaming Agent Experience

```text
>>> /stream on
>>> Explain tests/test_agent_loop.py
[streaming answer...]
• Read (tests/test_agent_loop.py) running...
  ↳ lines 1-180
>>> /render-last
```

- True API streaming for direct replies plus richer streaming during tool-driven agent loops
- Built-in `/stream` toggle for live output and `/render-last` for clean Markdown re-rendering on demand
- Designed for real terminal demos: streaming text, visible tool activity, and stable fallback behavior

### Programmable Skill Runtime

```md
---
description: Explain code with diagrams and analogies
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

Explain the code in $path. Start with an analogy, then draw a diagram.
```

- Markdown-based `SKILL.md` slash commands
- Supports project skills, user skills, named arguments, and tool limits

### Multi-Provider Support

```python
providers = ["Anthropic Claude", "OpenAI GPT", "Hugging Face", "Local LLM"]  # + easy to extend
```

### Interactive REPL

```text
>>> Hello!
Assistant: Hi! I'm Clawd Codex, a Python reimplementation...

>>> /help         # Show commands
>>> /             # Show all commands & skills
>>> /save         # Save session
>>> /multiline    # Multi-paragraph input
>>> Tab           # Auto-complete
>>> /explain-code qsort.py   # Run a skill
```

### Complete CLI

```bash
clawd              # Start REPL
clawd login        # Configure API
clawd --version    # Check version
clawd config       # View settings
clawd desktop      # Start the desktop host
```

***

## 📊 Status

| Component     | Status     | Count     |
| ------------- | ---------- | --------- |
| REPL Commands | ✅ Complete | 6+ built-ins |
| Tool System   | ✅ Complete | 30+ tools |
| Automated Tests | ✅ Present | Core suites for skills, providers, REPL, tools, context |
| Documentation | ✅ Complete | 10+ docs  |

### Core Systems

| System | Status | Description |
|--------|--------|-------------|
| CLI Entry | ✅ | `clawd`, `login`, `config`, `--version` |
| Interactive REPL | ✅ | Rich interactive output, history, tab completion, multiline |
| Multi-Provider | ✅ | Anthropic, OpenAI, Hugging Face, Local LLM in the UI |
| Session Persistence | ✅ | Save/load sessions locally |
| Token usage meter | ✅ | Per-chat input/output/total in the desktop header — informational only, never a gate |
| Conversation rename | ✅ | Double-click or right-click a chat in the left sidebar; the title is saved with the session |
| Standalone first-run | ✅ | Provider key or local LLM is enough. Other agents are omitted from the API payload until connected |
| Tool schema sanitizer | ✅ | Every tool sent to Anthropic/OpenAI has `input_schema.type` (fixes Anthropic 400 `tools.N.custom.input_schema.type`) |
| Agent Loop | ✅ | Tool calling loop implementation |
| Skill System | ✅ | SKILL.md-based slash-command skills with args + tool limits |
| Context Building | 🟡 | Initial prompt injection for workspace, git, and CLAUDE.md; desktop workspace picker feeds the same builder |
| Permission System | ✅ | Path sandbox plus interactive approve/deny for destructive and network tools |
| Desktop App | ✅ | Electron/browser shell over the existing Python agent loop |
| GitHub / GitLab | ✅ | Token or device login, clone/pull/push, create repo, PR/MR from the desktop UI |
| MCP / other agents | ✅ | Add/list/enable MCP servers and OpenAI-compatible agent URLs; Cursor/Codex/local hooks |

### Tool System (30+ Tools Implemented)

| Category | Tools | Status |
|----------|-------|--------|
| File Operations | Read, Write, Edit, Glob, Grep | ✅ Complete |
| System | Bash execution | ✅ Complete |
| Web | WebFetch, WebSearch | ✅ Complete |
| Interaction | AskUserQuestion, SendMessage | ✅ Complete |
| Task Management | TodoWrite, TaskManager, TaskStop | ✅ Complete |
| Agent Tools | Agent, Brief, Team | ✅ Complete |
| Configuration | Config, PlanMode, Cron | ✅ Complete |
| MCP | MCP tools and resources | ✅ Complete |
| Others | LSP, Worktree, Skill, ToolSearch | ✅ Complete |

### Roadmap Progress

- ✅ **Phase 0**: Installable, runnable CLI
- ✅ **Phase 1**: Core Claude Code MVP experience
- ✅ **Phase 2**: Real tool calling loop
- 🟡 **Phase 3**: Context, permissions, recovery (permissions + desktop host landed; deeper context still in progress)
- 🟡 **Phase 4**: MCP, plugins, extensibility (MCP + other-agent connectors landed)
- ⏳ **Phase 5**: Python-native differentiators

**See [FEATURE_LIST.md](FEATURE_LIST.md) for detailed feature status and PR guidelines.**

## 🚀 Quick Start

### Install the desktop agent (one command)

The first-run wizard installs everything needed to run the desktop agent: it detects the OS, saves the full source tree under a **Jonathan** folder, creates a Python venv, installs backend and desktop-shell dependencies, writes provider config placeholders (no API keys), and verifies the agent can start a session.

**Chat on first run with only a local model or one API key.** After install, open Jonathan Ai, pick Anthropic / OpenAI / Hugging Face / Local LLM, and send a message. MCP servers, Cursor, Codex, and other agents are optional — they are not required and are omitted from the provider request until you connect one. Tokens stay on this machine. The product version is **0.2.8** (see the `VERSION` file, UI header, and Windows installer).

**Windows (real desktop app):**

1. Double-click `packaging/windows/bin/JonathanAi-Setup.exe` (or `install.bat` / `JonathanAi-Setup.bat`).
2. A visible wizard runs: **Next → Install → Finish**. First run and later runs upgrade the same `%USERPROFILE%\Jonathan\Jonathan-Ai` folder (or an existing `Clawd-Code` folder). They do not create a second parallel install.
3. On Finish, **Jonathan Ai** opens. A **Jonathan Ai** icon is on the Desktop and in the Start Menu, targeting `Jonathan-Ai\JonathanAi.exe`.
4. Later launches use `JonathanAi.exe`. Electron is optional: if only the Python venv is present, the UI still opens.

If a Desktop click shows **Could not find Electron or the local Python venv**, re-run **JonathanAi-Setup.exe**. Setup replaces the leftover parent-folder shortcut/exe and upgrades the existing app in place.

Rebuild the Setup/app exes with `packaging/windows/build.sh` (Linux/mingw) or `packaging/windows/build-windows.ps1` (Windows). Details: [packaging/windows/README.md](packaging/windows/README.md).

**Other entry points:**

```bash
# Linux / macOS (from a checkout, or after downloading install.sh)
./install.sh --yes

# macOS Finder: double-click "Install Jonathan Ai.command"

# Windows fallback if the Setup exe is missing
powershell -File install.ps1

# Already have Python 3.10+ and this repo:
python -m src.cli install --yes
python -m src.install --ui          # graphical wizard
```

Default local source: `~/Jonathan/Jonathan-Ai`  
Windows: `%USERPROFILE%\Jonathan\Jonathan-Ai`

Override the folder in the wizard or with:

```bash
CLAWD_INSTALL_DIR=/path/to/Jonathan/Jonathan-Ai ./install.sh --yes
python -m src.cli install --source-dir ~/Jonathan/Jonathan-Ai --yes
```

The wizard only clones **https://github.com/GoDeskio/Clawd-Code**. It will refuse any other remote. The graphical wizard has an optional checkbox to clone that repo into the Jonathan folder if it is not already there.

After install, launch:

```bash
# Windows: Desktop / Start Menu shortcut "Jonathan Ai", or JonathanAi.exe
# Linux / macOS:
~/Jonathan/Jonathan-Ai/start-desktop.sh
python -m src.cli desktop
```

The app checks GoDeskio/Clawd-Code on launch (and about every 6 hours) and can apply fast-forward updates. Status is shown in the desktop UI. Dirty working trees are not overwritten.

### Developer CLI install (optional)

```bash
git clone https://github.com/GoDeskio/Clawd-Code.git
cd Clawd-Code

# Create venv (uv recommended)
uv venv --python 3.11
source .venv/bin/activate

# Install
uv pip install -r requirements.txt
```

### Configure

#### Option 1: Interactive (Recommended)

```bash
python -m src.cli login
```

This flow will:

1. ask you to choose a provider: anthropic / openai / glm / minimax / **huggingface** / **local**
2. ask for that provider's API key or Hugging Face token (Local LLM keys are optional)
3. optionally save a custom base URL
4. optionally save a default model
5. set the selected provider as default

Switching providers later does **not** require a reinstall — use Jonathan Ai settings or `python -m src.cli login` again.

The configuration file is saved in `~/.clawd/config.json` (mode `0600`). Tokens never go into git or the installer artifact. Example structure:

```json
{
  "default_provider": "glm",
  "providers": {
    "anthropic": {
      "api_key": "base64-encoded-key",
      "base_url": "https://api.anthropic.com",
      "default_model": "claude-sonnet-4-20250514"
    },
    "openai": {
      "api_key": "base64-encoded-key",
      "base_url": "https://api.openai.com/v1",
      "default_model": "gpt-4"
    },
    "glm": {
      "api_key": "base64-encoded-key",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "default_model": "glm-4.5"
    },
    "huggingface": {
      "api_key": "base64-encoded-hf-token",
      "base_url": "https://router.huggingface.co/v1",
      "default_model": "Qwen/Qwen2.5-7B-Instruct"
    },
    "local": {
      "api_key": "",
      "base_url": "http://127.0.0.1:11434/v1",
      "default_model": "llama3.2"
    }
  }
}
```

#### Hugging Face (Hub + Inference)

1. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (read access is enough for most inference models).
2. In Jonathan Ai first-run setup or **Provider & model**, choose **Hugging Face**.
3. Paste the token. It is stored only in `~/.clawd/config.json`.
4. Click **Test Hugging Face** — Jonathan Ai calls `whoami` and reports the account name.
5. Click **Load Hub models** to list inference-ready text-generation models, or type an `org/name` id (for example `Qwen/Qwen2.5-7B-Instruct`).
6. Optional: **Download / cache** writes the Hub repo to `~/.clawd/hf-cache` on this machine (no upload).
7. Save. Chat uses the HF Inference router (`https://router.huggingface.co/v1`). Jonathan Ai does **not** call Hugging Face unless you selected this provider or clicked test / list / download.

The install wizard has the same token field after the tree is installed. Unattended `./install.sh --yes` still writes empty placeholders only.

#### Local / self-hosted LLMs

Treat any OpenAI-compatible server as the **Local LLM** provider:

| Server | Default URL |
| --- | --- |
| Ollama | `http://127.0.0.1:11434/v1` |
| LM Studio | `http://127.0.0.1:1234/v1` |
| vLLM | `http://127.0.0.1:8000/v1` |
| llama.cpp server | `http://127.0.0.1:8080/v1` |
| Hugging Face TGI (self-hosted) | `http://127.0.0.1:3000/v1` |
| Custom | loopback or LAN URL + optional API key |

On first run and in settings, **Scan local ports** probes those addresses, lists available models, and lets you pick a default. Custom URLs that resolve to the public internet are rejected. Local endpoints are never bound or advertised on the WAN by Jonathan Ai.

#### GitHub and GitLab

From **Git & agents** in the desktop app (or the install wizard after the tree is installed):

1. Paste a personal access token, or start device/OAuth login with **your** GitHub OAuth App client ID / GitLab application ID. Jonathan Ai does not ship a client secret.
2. Credentials are stored only in `~/.clawd/config.json` (mode `0600`). They never enter git, `install.json`, or the installer artifact.
3. You can list repos/projects, clone (click a repo to open it), pull, push a branch, create a repo, and open a pull request or merge request — no terminal required.
4. **Branch-then-PR, not main.** Jonathan Ai will not push `main`/`master` (or the remote default) unless you explicitly name that branch. **Create repo and push** uses a `jonathan/<name>` feature branch and opens a PR/MR.
5. New GitHub repos default to the **GoDeskio** owner/org unless you pick another.

#### Other agents (MCP, Cursor, Codex, local)

Jonathan Ai is meant to call and be called by tools you already run. It does not invent fake agents.

- **MCP:** add a stdio command or HTTP URL in settings, test it (lists tools), enable/disable it. Enabled servers are available in the next turn.
- **OpenAI-compatible agents:** add a base URL (loopback/LAN preferred; user-pasted HTTPS is allowed). Test connection, list tools, and invoke from a turn via the `ExternalAgent` tool.
- **Cursor / Codex / local hook:** drop `~/.clawd/hooks/cursor.json` (or `codex.json`) with `{ "name": "Cursor", "base_url": "http://127.0.0.1:PORT/v1", "api_key": "" }`. Other local tools can `POST http://127.0.0.1:8765/api/hooks/inbound` with header `X-Clawd-Token` and `{ "text": "..." }`.

Tokens for MCP/agents are collected only in the wizard or settings.

#### Token usage (informational)

Every chat window shows input, output, and running total tokens for that conversation (header). The count is saved with the session. It is **never a quota**: there is no paywall, no “out of tokens” stop, no upgrade prompt, and no Jonathan Ai token store. If a provider API itself returns a rate-limit or billing error, the app says so and you can switch to Hugging Face, a local LLM, or another connected provider. Local/self-hosted models have no purchase path.

### Run the original CLI

```bash
python -m src.cli          # Start REPL
python -m src.cli --help   # Show help
python -m src.cli login    # First-run API setup (keys stay in ~/.clawd/config.json)
```

**That's it!** Start chatting from the terminal in 3 steps.

### Run the desktop app

The desktop app is a native/cross-platform shell around **this repo's existing agent runtime**. It does not rewrite the tool loop, skills, providers, or sessions.

**Option A — Python host + browser UI (Linux CI/dev, no Node required)**

```bash
python -m src.cli desktop
# or:
python -m src.desktop --port 8765
```

This binds `http://127.0.0.1:8765/` only, serves the chat UI, and opens a browser. Use `--no-browser` in CI.

The dashboard is a glassmorphism prompt UI: conversations on the left (title + last activity; **double-click or right-click to rename**), frosted chat cards, and a monochrome + eye-glow palette matching the robot sketch. The header shows **v0.2.8** and the token meter (informational only). Conversations persist in the sidebar; New Chat is always empty. Shared memory is local only (`~/.clawd/memory`). Jonathan Ai is the agent — no second AI connection is required.

**Option B — Electron desktop shell (tray, notifications, folder picker)**

```bash
cd desktop
npm install
npm start
```

Electron starts the Python sidecar (`python -m src.cli desktop --no-browser`) and opens a window. Linux, macOS, and Windows are supported; Linux is the CI/dev path.

First launch shows a login/config flow. API keys are written only to `~/.clawd/config.json` with mode `0600`. They are never committed.

The running desktop host uses the Jonathan install tree when `~/.clawd/install.json` is present. Updates are fetched only from `https://github.com/GoDeskio/Clawd-Code`.

```bash
python -m src.cli update          # check
python -m src.cli update --apply  # fetch + apply + restart if you relaunch
```

Desktop extras on top of the CLI:

- Chat with streaming tokens, visible tool activity, slash commands/skills, **persistent session list**, **rename chats**, provider/model settings
- **New Chat** always opens a brand-new empty conversation (new id, empty transcript, reset token meter). Previous chats stay in the sidebar and survive restart.
- Shared agent memory in `~/.clawd/memory` (facts + compact titles/summaries of other chats). Threads stay isolated; the model only sees a short brief, not full dumps.
- Standalone agent: send message → stream reply → show tools → new chat → rename chat → informational token meter. **Workers** plans a goal into isolated internal workers (shared memory only). No required Cursor/Codex/MCP connection.
- Windows session JSON (0.2.8): `Session.load` / `save` always use `encoding='utf-8'` so a UTF-8 byte such as `0x8F` no longer crashes desktop start under cp1252.
- Anthropic 400 fix (0.2.7): `tool_result.content` that is a dict/object/list is `json.dumps`'d before `chat`, `chat_stream`, and `chat_stream_response`, including resumed sessions that already stored object-shaped tool results. Schema 400s (`tools.N.custom.input_schema.type`) still retry the same turn without tools.
- Anthropic 400 fix (0.2.6): desktop streaming (`chat_stream_response`) and `chat()` send only `{name, description, input_schema:{type:object, properties}}`, including MCP/dynamic and custom-wrapped tools. If Anthropic still returns `tools.N.custom.input_schema.type: Field required`, the same turn retries with tools omitted so the first message still answers. First launch auto-installs missing venv/pip/Electron when possible. `/new` always opens a new empty session. Setup never merges `main` into this branch.
- Workspace/folder picker (Electron dialog, or a path prompt in the browser)
- Approve / deny / always-allow-this-session permission prompts
- System tray + notifications for long jobs (Electron)
- Attach / drop files, user-clicked clipboard attach, optional user-clicked screenshot
- Copy-friendly rendered markdown

Clipboard and screen access are **user-initiated only**. There is no background capture, keylogging, or secret scraping.

***

## 💡 Usage

### REPL Commands

| Command      | Description           |
| ------------ | --------------------- |
| `/`          | Show commands & skills |
| `/help`      | Show all commands     |
| `/save`      | Save session          |
| `/load <id>` | Load session          |
| `/multiline` | Toggle multiline mode |
| `/clear`     | Clear history         |
| `/exit`      | Exit REPL             |

### Skills (Slash Commands)

Skills are markdown-based slash commands stored under `.clawd/skills`. Each skill lives in its own directory and must be named `SKILL.md`.

**1) Create a project skill**

Create:

```text
<project-root>/.clawd/skills/<skill-name>/SKILL.md
```

Example:

```md
---
description: Explains code with diagrams and analogies
when_to_use: Use when explaining how code works
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

Explain the code in $path. Start with an analogy, then draw a diagram.
```

**2) Use it in the REPL**

```text
❯ /
❯ /<skill-name> <args>
```

Example:

```text
❯ /explain-code qsort.py
```

**Notes**

- User-level skills: `~/.clawd/skills/<skill-name>/SKILL.md`
- Tool limits: `allowed-tools` controls which tools the skill can use.
- Arguments: use `$ARGUMENTS`, `$0`, `$1`, or named args like `$path` (from `arguments`).
- Placeholder syntax: use `$path`, not `${path}`.



***

## 🎓 Why Jonathan Ai?

### Based on Real Source Code

- **Not a clone** — Ported from actual TypeScript implementation
- **Architectural fidelity** — Maintains proven design patterns
- **Improvements** — Better error handling, more tests, cleaner code

### Python Native

- **Type hints** — Full type annotations
- **Modern Python** — Uses 3.10+ features
- **Idiomatic** — Clean, Pythonic code

### User Focused

- **3-step setup** — Clone, configure, run
- **Interactive config** — `clawd login` guides you
- **Rich REPL** — Tab completion, syntax highlighting
- **Session persistence** — Never lose your work

***

## 📦 Project Structure

```text
Clawd-Code/
├── install.sh / install.ps1 / install.bat / Install Jonathan Ai.command
├── src/
│   ├── cli.py           # CLI entry (`clawd`, `login`, `config`, `desktop`, `install`, `update`)
│   ├── desktop/         # Localhost host, runtime, and web UI
│   ├── install/         # First-run wizard
│   ├── update/          # GoDeskio/Clawd-Code self-update
│   ├── providers/       # LLM providers
│   ├── repl/            # Interactive REPL
│   ├── skills/          # SKILL.md loading and creation
│   └── tool_system/     # Tool registry, loop, validation
├── desktop/             # Electron shell (tray, dialogs, notifications)
├── tests/               # Core test suite
├── .clawd/
│   └── skills/          # Project-local custom skills
└── FEATURE_LIST.md      # Current feature status
```

***


## 🤝 Contributing

**We welcome contributions!**

```bash
# Quick dev setup
pip install -e .[dev]
python -m pytest tests/ -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

***

## 📖 Documentation

- **[SETUP_GUIDE.md](docs/guide/SETUP_GUIDE.md)** — Detailed installation
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Development guide
- **[TESTING.md](docs/guide/TESTING.md)** — Testing guide
- **[CHANGELOG.md](CHANGELOG.md)** — Version history

***

## ⚡ Performance

- **Startup**: < 1 second
- **Memory**: < 50MB
- **Response**: Turn-based assistant output with Rich markdown rendering

***

## 🔒 Security

✅ **Basic Local Safety Practices**

- No sensitive data in Git
- API keys obfuscated in config
- `.env` files ignored
- Safe for local development workflows

***

## 📄 License

MIT License — See [LICENSE](LICENSE)

***

## 🙏 Acknowledgments

- Based on Claude Code TypeScript source
- Independent educational project
- Not affiliated with Anthropic

***

<div align="center">

### 🌟 Show Your Support

If you find this useful, please **star** ⭐ the repo!

**Made with ❤️ by Jonathan Ai**

[⬆ Back to Top](#jonathan-ai)

</div>

***

***
