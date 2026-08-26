<div align="center">

**English** | [中文](#中文版) | [Français](docs/i18n/README_FR.md) | [Русский](docs/i18n/README_RU.md) | [हिन्दी](docs/i18n/README_HI.md) | [العربية](docs/i18n/README_AR.md) | [Português](docs/i18n/README_PT.md)

# Jonathan Ai

**A local desktop and CLI agent, built as a Python reimplementation of Claude Code**

**Version 0.4.7** — Jonathan Ai adds native durable control for long-running work. `LongHorizonControl` keeps objectives, workspace scope, bounded turns, dependency-aware todos, agent claims/leases, human gates, evidence receipts, and handoffs in atomic UTF-8 state shared across conversations. Its continuation and closure decisions fail closed when judgment, evidence, prerequisites, or budget are missing.

Local-model discovery now also reports on-disk model size, live runtime RAM, available system RAM, and conservative fit guidance before a large model is selected. The measurements are local and informational; Jonathan does not silently stop another runtime or send hardware details to a service.

Every conversation also writes a redacted, tamper-evident append-only runtime ledger under `~/.clawd/events`. Provider context can stay bounded for speed without deleting job, tool, permission, completion, usage, or artifact evidence. Token counts remain persisted per conversation and agent and are informational only—there is no quota, payment, or purchase path.

When a project contains `DESIGN.md`, Jonathan loads its UTF-8 visual system into a separate bounded context section for every conversation agent. This keeps project colors, typography, components, layout, responsive rules, and design constraints persistent without copying a third-party brand catalog into the application.

The Device & System card also shows an earned-autonomy profile for each conversation and gated tool. It counts only distinct human decisions, uses a conservative Wilson confidence bound, and caps terminal, write, device, repository, and trading actions at approval-required. Recommendations are visible evidence—not authority—and can never enable a tool or full-device access without the user's explicit grant.

Tool execution is audit-gated: after policy and user approval, Jonathan writes a secret-redacted `started` record before invoking the tool and a second record with success, refusal, or failure. If the preflight audit cannot be persisted, the side effect does not run.

The 0.4.7 shell uses a quiet, neutral desktop system: compact native typography, solid surfaces, low-decoration hierarchy, consistent radii, clear focus rings, semantic state colors, and reduced-motion support. It keeps the dense operational layout instead of applying oversized website spacing.

Pydantic AI was evaluated for typed outputs, broad model adapters, durable execution, evaluations, and telemetry. Jonathan keeps its existing single runtime for this release; adding a second agent loop would duplicate session, permission, provider, and tool state. Its strongest capabilities remain candidates for narrow future adapters rather than a wholesale dependency.

The Workers control now offers **Fast**, **Balanced**, and **Verified** modes. Verified uses an additional independent model pass to challenge the worker outputs against the original goal and synthesize the final response; Fast avoids that latency for small jobs. These modes are explicit because deeper orchestration costs more time and provider tokens, and every worker/reviewer token is added to the owning conversation's informational total.

### Media, 3D, and administrator tools

- `ImageStudio`: create and convert PNG/JPEG/WebP/BMP/GIF/TIFF/PDF, add/remove text, inpaint, composite, crop, resize, rotate, flip, or call a configured OpenAI-compatible image endpoint.
- `ThreeDStudio`: make colored GLB/GLTF/OBJ/STL/PLY assets locally; use Blender for textures, BLEND/FBX/USD, advanced conversion, and high-definition Eevee/Cycles renders. The common `MLB` typo is accepted and corrected to `.glb`.
- `Artifact`: publish any file to the conversation download shelf, or safely ZIP a directory.
- `SystemAdmin`: inventory, monitor, evaluate, report, control approved processes/services, and install approved packages. Every tool action is written to a secret-redacted audit ledger at `~/.clawd/audit/actions.jsonl`.
- `Repository`: inspect, clone, fetch, pull, and push GitHub/GitLab repositories without merging; protected branches require explicit authorization.
- `AudioStudio`: generate deterministic original instrumental WAV beds and trim, normalize, or mix local PCM WAV files into conversation downloads without an account or cloud service.
- `SkillManager` and `SharedMemory`: create/validate/package reusable `SKILL.md` files and search/export durable cross-conversation memory.
- `LongHorizonControl`: coordinate durable goals across separate conversation agents with bounded turns, dependency-aware work, leases, judgment gates, evidence receipts, handoffs, and explicit continuation checks.
- `ECCIntegration`: synchronize, audit, import, update, enable/disable, and search ECC skills/agent templates; exchange unreviewed Memory Vault documents; and create reviewable skills from measured Git history.
- `BusinessManager`: durable local customers, projects, tasks, invoices, income/expense ledger, dashboard, and downloadable JSON/CSV/HTML business reports.
- `KronosForecast`: create built-in Mini/Small/Base probabilistic EWMA/Monte Carlo OHLCV research forecasts as downloadable CSV files; never places an order.
- `PersonalFinanceVault`: manage built-in SQLite accounts, transactions, categories, recurring items, budgets, goals, assets, reports, and currencies; no container, subscription, or payment is required.
- `CodeMemory`: build an incremental local code graph, search durable notes, find symbol usages, explain dependencies, and trace paths through the project using a Jonathan-owned SQLite database with no cloud account or Claude hooks.
- `Procoder`: run Jonathan's built-in fail-closed changed-file gate, detected project tests, secret/conflict hygiene, release readiness, and related engineering reports; it never installs hooks or edits the project.
- `EditableGraphics`: vectorize an uploaded raster diagram into editable SVG, native PowerPoint shapes, OCR text, a review PNG, and a JSON package with no separate model pack.
- `CharacterStudio`: generate deterministic animated SVG character rigs and editable JSON recipes from a seed without a model or API.
- `FinanceMarkets`: current/delayed quotes, price history, RSI/moving averages, multi-symbol screens, portfolio valuation, and timed watchlist reports.
- `Trading`: optional Alpaca paper/live brokerage connection. Credentials are entered directly in Connect Tools; paper is the default, and every order submission or cancellation requires a fresh approval.
- `PublicApiCatalog`: search Jonathan's audited offline starter index by category, authentication, HTTPS, or CORS, inspect the provider's documentation, and—with approval—create a persistent connector card. Provider terms, credentials, quotas, and data policies still apply.
- `writing-polish` skill: opt-in two-pass editing for surface clarity and document structure, calibrated to supplied voice samples while preserving facts, citations, uncertainty, and honest authorship.
- `interface-art-direction` skill: set deliberate layout-variance, motion-intensity, and information-density controls for new interfaces or evidence-based redesigns, with accessibility and responsive verification built in.
- `react-performance-review` skill: diagnose request waterfalls, client bundle cost, rendering boundaries, rerenders, expensive hot paths, and loading behavior using reproducible before/after evidence.
- `screenshot-to-interface` skill: turn an uploaded screenshot or mockup into maintainable code in the project's existing stack, then render and compare desktop/narrow previews before packaging the result.
- `SpeechStudio`: record only when the user clicks Voice, transcribe/translate locally with a Whisper-family model, and synthesize responses to downloadable WAV with the device voice engine.
- `ContentReach`: check public channel readiness, read RSS/Atom feeds, and retrieve public YouTube metadata/captions without silently reusing browser cookies.

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

<a href="https://www.star-history.com/?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left" />
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
providers = ["Anthropic Claude", "OpenAI GPT", "Zhipu GLM"]  # + easy to extend
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
| Multi-Provider | ✅ | Anthropic, OpenAI, GLM, Minimax, Hugging Face, Local LLM |
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

**Chat on first run with only a local model or one API key.** After install, Jonathan first discovers installed local runtimes and connects a reachable model automatically when no working provider exists. The installer prepares the built-in code memory, forecasting, engineering-gate, finance, editable-graphics, and long-horizon control engines; only the audited ECC catalog needs an optional online source sync. You can pick Anthropic / OpenAI / GLM / Hugging Face / Local LLM and send a message. MCP servers, Cursor, Codex, and other agents are optional — they are omitted from provider requests until connected. Tokens stay on this machine. The product version is **0.4.7**.

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

The wizard only clones **https://github.com/GoDeskio/Clawd-Code**. It will refuse any other remote, including upstream GPT-AGI/Clawd-Code. The graphical wizard has an optional checkbox to clone that repo into the Jonathan folder if it is not already there.

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

On first run and in settings, **Scan local ports** also inventories installed runtimes and common model stores, starts a known Ollama/LM Studio service when needed, lists available models, and connects the first reachable model. Custom URLs that resolve to the public internet are rejected. Local endpoints are never bound or advertised on the WAN by Jonathan Ai. Credentials are scoped to their endpoint, so an Ollama credential is not sent to LM Studio.

#### Jonathan local image generation

Open **Connect tools → Local diffusion** to verify Jonathan's built-in Diffusers engine, generate or edit an image from an uploaded source, and publish outputs directly into the conversation. The installer supplies its Python packages; the first generation downloads the configured model (`stabilityai/sdxl-turbo` by default) into Jonathan's private cache. It uses CUDA when available and otherwise runs on CPU. Fooocus informed the product requirements, but Jonathan does not clone, launch, or depend on Fooocus, Gradio, or an upstream service.

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

The dashboard is a compact prompt UI: conversations on the left (title + last activity; **double-click or right-click to rename**), clear chat cards, and a monochrome + eye-glow palette matching the robot sketch. The header shows **v0.4.7** and the token meter (informational only). Conversations persist in the sidebar; New Chat is always empty. Shared memory is local only (`~/.clawd/memory`), while durable goal governance is stored under `~/.clawd/goals`. User-authored skills are visible under `Jonathan-Ai/Skills`; managed ECC content is stored below `Skills/.managed/ecc` and only enabled entries are loaded. Jonathan Ai is the agent — no second AI connection is required.

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
- Anthropic 400 fix (0.2.7): `tool_result.content` dicts and ordinary lists are JSON-encoded before `chat`, `chat_stream`, and `chat_stream_response`, including old persisted sessions. Valid content-block lists are preserved. Unrelated 400/401/429 errors are not hidden by the tool-schema fallback.
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

#### ECC catalog and automatic skill learning

Open **Skills library → ECC catalog** to synchronize the official `affaan-m/ECC` repository, run a full security scan, import the complete skills/agent-template catalog, and enable or disable individual skills. Jonathan records the exact upstream revision and MIT provenance. The complete catalog remains on disk, but only enabled entries are parsed into agent context; this avoids duplicate hooks and large prompt/startup costs.

#### Native local market forecasting

Open **Connect tools → Market forecasts** or use `KronosForecast` with a timestamped CSV containing a close column (OHLCV columns are accepted). Jonathan's built-in engine estimates recency-weighted log-return drift and volatility, generates bounded Monte Carlo paths, and exports median/P10/P90 forecast CSVs. It requires no cloned repository or model download. Results are research artifacts, not investment advice or automatic trading signals; validate them with walk-forward tests, transaction costs, slippage, portfolio constraints, and independent risk controls.

#### Private personal finance vault

Open **Connect tools → Personal finance vault** or use `PersonalFinanceVault`. Jonathan stores accounts, transactions, categories, recurring flags, budgets, savings goals, assets, and currency-separated totals in `~/.clawd/finance/personal-finance.sqlite`. It is an embedded UTF-8/WAL SQLite engine: no Docker, remote service, bank credential, subscription, or cloned finance application is required.

#### Local code graph and durable code memory

Open **Connect tools → Code memory** or use `CodeMemory`. Jonathan's built-in Python/SQLite engine incrementally scans supported source files, indexes symbols/calls/imports, performs live text search, and stores only explicitly requested notes in `~/.clawd/code_memory/jonathan-code-memory.sqlite`. No Node helper, Claude installer, hook, cloned repository, remote database, or account is used. Existing UTF-8 chat/session and shared-memory systems remain authoritative.

Benjamin Plus was evaluated and adopted as a compact native workflow discipline in Jonathan's system prompt. Fullstack Agent was evaluated but not embedded because it is a setup script for a separate Claude/Obsidian stack. Procoder, DrawAI, Kindergrimm, and Scroll Craft were used only as licensed design references: their useful capabilities were rewritten as Jonathan's built-in engineering gate, editable-graphics engine, procedural character studio, and scroll-storytelling skill.

OmniRoute informed Jonathan's in-process transient retry/circuit-breaker layer, but no gateway or cross-provider auto-fallback is installed: changing providers remains explicit so prompts, credentials, privacy boundaries, and possible charges cannot move unexpectedly. Task Observer informed the correction/failure/repeated-workflow review queue in automated skill learning; observations are sanitized, confidence scored, and never silently activated. Anthropic's Claude plugin catalog was evaluated, but its Claude-specific marketplace and hooks duplicate Jonathan's audited `SKILL.md`, MCP, connector, and agent systems and are not bundled.

Headroom's provider-cache analysis informed a native Anthropic prompt-cache marker on Jonathan's system prefix. Jonathan does not install Headroom, route traffic through a proxy, compress user intent, discard turns, or add a retrieval service; the persistent UTF-8 transcript remains authoritative.

Anthropic's community plugin marketplace was also evaluated. It is a directory of third-party sources rather than an application engine, and its entries have independent licenses, credentials, hooks, and runtime requirements. Jonathan does not bulk-install it; users connect MCP/external tools explicitly and enable reviewed skills individually.

YuE and ACE-Step UI were evaluated for full-song generation. Both are valuable optional GPU systems, but their multi-gigabyte model stacks and hardware/runtime requirements would make a standard desktop install slower and less reliable. Jonathan therefore ships an always-available native `AudioStudio` baseline for original procedural WAV generation and editing. Users with a separately approved local music server can connect it through Jonathan's existing external/MCP connector; no cloned music UI is required.

**Learn from project** analyzes up to 200 local Git commits. It measures commit prefixes, frequently changed areas, file types, co-change pairs, and test placement. Repository text and commit messages are sanitized as untrusted evidence, possible secrets are redacted, and the result is saved as a confidence-scored draft. Review the draft in the editor and click **Validate & save** before it becomes active. Jonathan never silently overwrites a user skill or automatically turns a draft into executable policy.

Memory Vault export writes inspectable `ecc.memory.v1` Markdown under `~/.clawd/memory/vault`. Imported vault entries remain `unreviewed` context, reject credential/instruction-override patterns, and do not grant tools or permissions.



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

# 中文版

<div align="center">

[English](#-clawd-codex) | **中文** | [Français](docs/i18n/README_FR.md) | [Русский](docs/i18n/README_RU.md) | [हिन्दी](docs/i18n/README_HI.md) | [العربية](docs/i18n/README_AR.md) | [Português](docs/i18n/README_PT.md)

# Jonathan Ai

**本地桌面与 CLI Agent，基于真实 Claude Code 源码的 Python 重实现**

**版本 0.3.0** — Jonathan Ai 本身就是 AI Agent。会话会持久化；New Chat 总是空线程。跨会话记忆只存在本机 `~/.clawd/memory`。MCP / Cursor / Codex 均为可选。新增图像、Blender 3D、系统管理、审计、仓库和技能工具。Windows 会话使用原子 UTF-8 持久化。启动器会在 `%USERPROFILE%\Jonathan\Jonathan-Ai` 找到 venv。

*从 TypeScript 源码 → 用 Python 重建 ❤️*

***

[![GitHub stars](https://img.shields.io/github/stars/GoDeskio/Clawd-Code?style=for-the-badge&logo=github&color=yellow)](https://github.com/GoDeskio/Clawd-Code/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/GoDeskio/Clawd-Code?style=for-the-badge&logo=github&color=blue)](https://github.com/GoDeskio/Clawd-Code/network/members)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)

**🔥 活跃开发中 • 每周更新新功能 🔥**

## FLEXIBLE SKILL SYSTEMS

**基于 Markdown 的斜杠技能系统，支持参数替换、工具限制，以及项目级 / 用户级技能加载。**

</div>

***

## 🎯 为什么是 Jonathan Ai？

**Jonathan Ai** 是一个面向真实使用的 **Claude Code Python 重构版**：它基于**真实 TypeScript 架构**移植而来，并且交付的是一个**可运行的桌面与 CLI Agent**，而不只是源码镜像。

- **真实 Agent Runtime** — 具备工具调用循环、流式 REPL、会话历史与多轮执行能力
- **高保真移植** — 尽可能保留 Claude Code 的原始架构，同时做符合 Python 风格的实现
- **适合继续开发** — 代码可读、测试完善，并支持基于 Markdown 的技能扩展

<div align="center">

**Token Streaming + Tool-Aware Agent Loop**

![流式 Agent 演示](assets/clawd-stream.gif)

**可编程 Skill Runtime 与工具沙箱**

![Skills（斜杠命令）](assets/clawd-code-skill.png)

**Instant Web Fetch for External Context**

![网页获取](assets/claude-code-webfetch.png)

**真实的 CLI • 真实的使用 • 真实的社区**

</div>

**这是一个真正可跑的 Claude Code 风格 Python 终端工作流：能流式回答、调工具、抓外部上下文，并通过 skills 扩展行为。**

**🚀 立即试用！Fork 它、修改它、让它成为你的！欢迎提交 Pull Request！**

***

## ⭐ Star 历史

<a href="https://www.star-history.com/?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=GPT-AGI%2FClawd-Code&type=date&legend=top-left" />
 </picture>
</a>

## ✨ 特性

### Streaming Agent Experience

```text
>>> /stream on
>>> 解释 tests/test_agent_loop.py
[流式回答中...]
• Read (tests/test_agent_loop.py) running...
  ↳ lines 1-180
>>> /render-last
```

- 直接回答支持真实 API 流式输出，带工具的 agent loop 也具备更完整的流式体验
- 内置 `/stream` 开关用于实时输出，`/render-last` 可按需把上一条回答重新渲染为 Markdown
- 专门为终端演示优化：一边看回答流出，一边看到工具调用，并保留稳定回退路径

### 可编程 Skill Runtime

```md
---
description: 用类比 + 图示解释代码
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

请解释 $path 的实现：先给一个类比，再画一个结构示意图。
```

- 基于 `SKILL.md` 的 Markdown 斜杠命令
- 支持项目级技能、用户级技能、命名参数替换与工具限制

### 多提供商支持

```python
providers = ["Anthropic Claude", "OpenAI GPT", "Zhipu GLM"]  # + 易于扩展
```

### 交互式 REPL

```text
>>> 你好！
Assistant: 嗨！我是 Clawd Codex，一个 Python 重实现...

>>> /help         # 显示命令
>>> /             # 显示命令与技能
>>> /save         # 保存会话
>>> /multiline    # 多行输入模式
>>> Tab           # 自动补全
>>> /explain-code qsort.py   # 运行一个技能
```

### 完整的 CLI

```bash
clawd              # 启动 REPL
clawd login        # 配置 API
clawd --version    # 检查版本
clawd config       # 查看设置
clawd desktop      # 启动桌面 host
```

***

## 📊 状态

| 组件    | 状态     | 数量     |
| ----- | ------ | ------ |
| REPL 命令 | ✅ 完成   | 6+ 内置命令 |
| 工具系统 | ✅ 完成   | 30+ 工具 |
| 自动化测试 | ✅ 已覆盖  | Skills、providers、REPL、tools、context |
| 文档    | ✅ 完成   | 10+ 文档 |

### 核心系统

| 系统 | 状态 | 描述 |
|------|------|------|
| CLI 入口 | ✅ | `clawd`、`login`、`config`、`--version` |
| 交互式 REPL | ✅ | 丰富的交互输出、历史记录、Tab 补全、多行输入 |
| 多提供商支持 | ✅ | 支持 Anthropic、OpenAI、GLM、Minimax、Hugging Face、本地 LLM |
| 会话持久化 | ✅ | 本地保存/加载会话 |
| Token 用量 | ✅ | 每个聊天窗口显示 input/output/合计，仅信息展示，不是配额 |
| 会话重命名 | ✅ | 左侧会话列表双击或右键重命名，标题随会话持久化 |
| 独立首启 | ✅ | 只需 provider key 或本地 LLM；未连接的其他 Agent 不会进入 API 请求 |
| 工具 schema 清洗 | ✅ | 发给 Anthropic/OpenAI 的每个工具都带 `input_schema.type`（修复 400） |
| Agent Loop | ✅ | 工具调用循环实现 |
| Skill 系统 | ✅ | 基于 SKILL.md 的 /skill 技能：参数替换 + 工具限制 |
| 上下文构建 | 🟡 | 已接入 workspace、git、CLAUDE.md 的基础上下文注入，桌面端工作区选择器复用同一套 builder |
| 权限系统 | ✅ | 路径沙箱 + 破坏性/网络工具的交互批准 |
| 桌面应用 | ✅ | Electron/浏览器壳，复用现有 Python agent loop |
| GitHub / GitLab | ✅ | 本机登录后可 clone/pull/push、建仓、开 PR/MR |
| MCP / 其他 Agent | ✅ | 设置中接入 MCP 与 OpenAI 兼容 agent；Cursor/Codex hook |

### 工具系统（已实现 30+ 工具）

| 类别 | 工具 | 状态 |
|------|------|------|
| 文件操作 | Read, Write, Edit, Glob, Grep | ✅ 完成 |
| 系统 | Bash 执行 | ✅ 完成 |
| 网络 | WebFetch, WebSearch | ✅ 完成 |
| 交互 | AskUserQuestion, SendMessage | ✅ 完成 |
| 任务管理 | TodoWrite, TaskManager, TaskStop | ✅ 完成 |
| Agent 工具 | Agent, Brief, Team | ✅ 完成 |
| 配置 | Config, PlanMode, Cron | ✅ 完成 |
| MCP | MCP 工具和资源 | ✅ 完成 |
| 其他 | LSP, Worktree, Skill（SKILL.md）, ToolSearch | ✅ 完成 |

### 路线图进度

- ✅ **阶段 0**：可安装、可运行的 CLI
- ✅ **阶段 1**：Claude Code 核心 MVP 体验
- ✅ **阶段 2**：真实工具调用闭环
- 🟡 **阶段 3**：上下文、权限、恢复能力（进行中）
- ⏳ **阶段 4**：MCP、插件、扩展性
- ⏳ **阶段 5**：Python 原生差异化特性

**详细功能状态和 PR 指南请查看 [FEATURE_LIST.md](FEATURE_LIST.md)。**

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/GoDeskio/Clawd-Code.git
cd Clawd-Code

# 创建虚拟环境（推荐使用 uv）
uv venv --python 3.11
source .venv/bin/activate

# 安装
uv pip install -r requirements.txt
```

### 配置

#### 方式 1：交互式（推荐）

```bash
python -m src.cli login
```

这个流程会：

1. 让你选择 provider：anthropic / openai / glm / minimax / **huggingface** / **local**
2. 让你输入 API key 或 Hugging Face token（本地 LLM 的 key 可选）
3. 可选：保存自定义 base URL
4. 可选：保存默认 model
5. 将该 provider 设为默认（切换 provider 无需重装）

Hugging Face：在 https://huggingface.co/settings/tokens 创建 token，于桌面设置中点 **Test Hugging Face** 验证，再选择 Hub 模型。Token 只保存在 `~/.clawd/config.json`。

本地 LLM：扫描 Ollama (`http://127.0.0.1:11434`)、LM Studio、vLLM、llama.cpp、TGI 或自定义局域网地址，仅允许回环/局域网，不会暴露到公网。

GitHub / GitLab：在桌面 **Git & agents** 或安装向导中粘贴 token（或用你自己的 OAuth/Application ID 做设备登录）。默认可在 GoDeskio 下建仓；不会推送默认分支，除非你明确写出分支名。凭证只保存在 `~/.clawd/config.json`。

MCP / 其他 Agent：在设置中添加真实的 MCP 命令/URL 或 OpenAI 兼容地址（Cursor / Codex / 本地），可测试连接并列出工具。也可放置 `~/.clawd/hooks/cursor.json`，或向 `http://127.0.0.1:8765/api/hooks/inbound` POST。

每个聊天窗口会显示该会话的 token 用量（输入/输出/合计），只做展示，不是付费墙。

配置文件会保存在 `~/.clawd/config.json`。示例结构：

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
    }
  }
}
```

### 安装桌面端（一条命令）

Windows：双击 `packaging/windows/bin/JonathanAi-Setup.exe`，向导点 Next / Install / Finish 后应用会打开，桌面和开始菜单出现 **Jonathan Ai** 图标。

```bash
./install.sh --yes
# 默认源码目录：~/Jonathan/Jonathan-Ai
# 只从 https://github.com/GoDeskio/Clawd-Code 安装与更新
# 版本 0.3.0：图像与 Blender 3D、系统管理与审计、仓库自动化、自建技能、持久共享记忆；Setup 原地升级且不合并 main
# 安装后可在向导或桌面设置中连接 Hugging Face / 本地 LLM / GitHub / GitLab / MCP，无需重装
# Token 只保存在 ~/.clawd/config.json，不会写入安装包或 git
# 聊天窗口的 token 计数只做展示，不是付费墙
# 左侧会话可重命名；工具 schema 会补上 type，避免 Anthropic 400
```

### 运行 CLI

```bash
python -m src.cli          # 启动 REPL
python -m src.cli --help   # 显示帮助
python -m src.cli login    # 配置 API（密钥只保存在 ~/.clawd/config.json）
```

### 运行桌面应用

```bash
python -m src.cli desktop          # Python host + 浏览器 UI
cd desktop && npm install && npm start   # Electron 壳
```

密钥不会写入 Git。桌面端复用现有 agent loop、工具、skills 与会话。Jonathan Ai 本身就是 Agent：发送消息、流式回复、显示工具、新建/重命名会话、信息性 token 计数、provider 设置。不需要第二个 AI 连接。头部显示版本 **0.3.0**。内部 Workers 可并行拆任务，不需要其它 Agent。会话会留在侧栏，New Chat 总是新的空对话。

***

## 💡 使用

### REPL 命令

| 命令           | 描述      |
| ------------ | ------- |
| `/`          | 显示命令与技能 |
| `/help`      | 显示所有命令  |
| `/save`      | 保存会话    |
| `/load <id>` | 加载会话    |
| `/multiline` | 切换多行模式  |
| `/clear`     | 清空历史    |
| `/exit`      | 退出 REPL |

### Skills（技能 / 斜杠命令）教程

技能是存放在 `.clawd/skills` 下的 Markdown 斜杠命令。每个技能对应一个目录，并且文件名固定为 `SKILL.md`。

**1）创建项目技能**

创建：

```text
<project-root>/.clawd/skills/<skill-name>/SKILL.md
```

示例：

```md
---
description: 用类比 + 图示解释代码
when_to_use: 当用户问“这段代码怎么工作？”时使用
allowed-tools:
  - Read
  - Grep
  - Glob
arguments: [path]
---

请解释 $path 的实现：先给一个类比，再画一个结构示意图。
```

**2）在 REPL 中使用**

```text
❯ /
❯ /<skill-name> <args>
```

示例：

```text
❯ /explain-code qsort.py
```

**补充说明**

- 用户级技能：`~/.clawd/skills/<skill-name>/SKILL.md`
- 工具限制：`allowed-tools` 用于限制技能允许调用的工具集合
- 参数替换：支持 `$ARGUMENTS`、`$0`、`$1`、以及命名参数（例如 `$path`，来自 `arguments`）
- 占位符写法：请使用 `$path`，不要写成 `${path}`


***

## 🎓 为什么选择 Jonathan Ai？

### 基于真实源码

- **不是克隆** — 从真实的 TypeScript 实现移植而来
- **架构保真** — 保持经过验证的设计模式
- **持续改进** — 更好的错误处理、更多测试、更清晰的代码

### 原生 Python

- **类型提示** — 完整的类型注解
- **现代 Python** — 使用 3.10+ 特性
- **符合习惯** — 干净的 Python 风格代码

### 以用户为中心

- **3 步设置** — 克隆、配置、运行
- **交互式配置** — `clawd login` 引导你完成设置
- **丰富的 REPL** — Tab 补全、语法高亮
- **会话持久化** — 永不丢失你的工作

***

## 📦 项目结构

```text
Clawd-Code/
├── src/
│   ├── cli.py           # CLI 入口
│   ├── desktop/         # 桌面 host 与 Web UI
│   ├── providers/       # LLM 提供商
│   ├── repl/            # 交互式 REPL
│   ├── skills/          # SKILL.md 加载与创建
│   └── tool_system/     # 工具注册、循环与校验
├── desktop/             # Electron 壳
├── tests/               # 核心测试套件
├── .clawd/
│   └── skills/          # 项目级自定义技能
└── FEATURE_LIST.md      # 当前功能状态
```

***

## 🤝 贡献

**我们欢迎贡献！**

```bash
# 快速开发设置
pip install -e .[dev]
python -m pytest tests/ -v
```

查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

***

## 📖 文档

- **[SETUP_GUIDE.md](docs/guide/SETUP_GUIDE.md)** — 详细安装说明
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — 开发指南
- **[TESTING.md](docs/guide/TESTING.md)** — 测试指南
- **[CHANGELOG.md](CHANGELOG.md)** — 版本历史

***

## ⚡ 性能

- **启动时间**：< 1 秒
- **内存占用**：< 50MB
- **响应**：回合式输出，支持 Rich Markdown 渲染

***

## 🔒 安全

✅ **基础本地安全实践**

- Git 中无敏感数据
- API 密钥在配置中做了基础混淆
- `.env` 文件被忽略
- 适合本地开发工作流

***

## 📄 许可证

MIT 许可证 — 查看 [LICENSE](LICENSE)

***

## 🙏 致谢

- 基于 Claude Code TypeScript 源码
- 独立的教育项目
- 未隶属于 Anthropic

***

<div align="center">

### 🌟 支持我们

如果你觉得这个项目有用，请给个 **star** ⭐！

**用 ❤️ 制作 by Jonathan Ai**

[⬆ 回到顶部](#中文版)

</div>
