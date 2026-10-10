# Jonathan Ai feature list

Capability list and roadmap for contributors.

Jonathan Ai is a Python rebuild of the Claude Code architecture: a local desktop and CLI agent with a tool loop, permissions, and on-machine memory.

## Status key

| Status | Meaning |
|--------|---------|
| Done | Verified in this repository |
| Partial | Skeleton or incomplete path |
| Planned | Direction is set |
| Not started | No implementation yet |

## Highlights

- Python rebuild of the agent loop, not a UI mock.
- Providers shown in the UI: Anthropic, OpenAI, Hugging Face, and a local LLM.
- REPL with history, tab completion, and multiline input.
- Tool registry, agent loop, and approval prompts. Dangerous shell commands stay blocked until the user approves that exact command.
- Per-user SQLite memory and schedules on this machine. Secrets are masked before they are stored.

## Core systems

| Capability | Status | Notes |
|------------|--------|-------|
| CLI entry | Done | `clawd`, `login`, `config`, `desktop`, `memory`, `cron`, `--version` |
| Interactive REPL | Done | Rich header, history, tab completion, multiline |
| Slash commands | Done | `/help`, `/clear`, `/new`, `/save`, `/load`, `/memory`, `/cron`, `/exit` |
| Providers in the UI | Done | Anthropic, OpenAI, Hugging Face, Local LLM |
| Provider config | Done | Default provider, base URL, default model in `~/.clawd/config.json` |
| Session persistence | Done | Sidebar survives restart. New Chat is an empty thread. Rename from the sidebar |
| Desktop agent | Done | UTF-8 session JSON, stringified Anthropic tool results, local memory, internal workers, schema retry, first-launch dependency repair |
| Tool schemas | Done | Each tool sent to Anthropic or OpenAI has `input_schema.type` |
| Token meter | Done | Per-chat input, output, and total. Informational only |
| GitHub / GitLab | Done | Token or device login. Clone, pull, push, create repo, PR/MR. Default branches are not pushed unless named |
| MCP / other agents | Done | User-supplied MCP stdio/HTTP servers and OpenAI-compatible agent URLs |
| Context | Done | Workspace, git, `CLAUDE.md`, and a memory brief. Other chats contribute titles, not full text |
| Agent loop | Done | `agent_loop.py` |
| Permissions | Done | Path sandbox plus desktop approval for Bash, Write, Edit, and web tools. Shell guard holds dangerous commands |
| Memory | Done | Per-user SQLite facts. `/memory` lists, recalls, and deletes |
| Schedules | Done | Per-user SQLite cron. America/Phoenix. Text or agent tasks. `/cron` lists, runs, enables, disables, deletes |
| Desktop app | Done | Browser UI plus local Python host. Windows ships `JonathanAi.exe` |
| Installer | Done | Windows setup wizard (Next / Install / Finish) into `~/Jonathan/Jonathan-Ai` |
| Self-update | Done | Fast-forward from GoDeskio/Clawd-Code only |
| `/resume` | Not started | No separate resume screen |
| `/compact` | Not started | No conversation compaction |
| `/doctor` | Not started | No diagnostic command |
| Hooks | Partial | Cursor/Codex/local inbound hook. Not a general pre/post tool hook |

## Tools

The registry includes read, write, edit, glob, grep, bash, web fetch, web search, questions, todos, tasks, agents, config, plan mode, cron, MCP, skills, LSP, worktree, and sleep. See `src/tool_system/tools/`.

## Runtime

| Module | Status | Notes |
|--------|--------|-------|
| Provider runtime | Done | Chat and streaming |
| REPL | Done | Commands, transcript |
| Agent loop | Done | Tool calls and results |
| Sessions | Done | Save and load |
| Context | Partial | Workspace, git, `CLAUDE.md` |
| Permissions | Done | Dispatch asks the desktop or REPL |
| Desktop host | Done | Localhost HTTP and SSE |
| Compaction | Not started | |
| MCP | Done | User-added servers only |
| Scheduler | Done | SQLite, per user, shell guard still applies to agent tasks |

## Tests

| Area | File |
|------|------|
| Tools | `test_tool_system_tools.py` |
| Agent loop | `test_agent_loop.py` |
| Providers | `test_providers.py` |
| Desktop | `test_desktop_runtime.py` |
| Install and update | `test_install_update.py` |
| Git, MCP, agents | `test_git_connectors.py` |
| Shell guard | `test_shell_guard.py` |
| Memory | `test_long_term_memory.py` |
| Scheduler | `test_scheduler.py` |
| UI routes | `tests/ui/audit.mjs` |

## Roadmap

### Phase 0 — installable

- [x] CLI help and version without a provider SDK
- [x] Lazy provider imports
- [x] Python 3.10+
- [x] Install notes and a minimal run path

### Phase 1 — core agent

- [x] REPL, slash commands, session store
- [x] Tool framework and agent loop
- [x] Transcript persistence

### Phase 2 — real tool calls

- [x] Read, write, edit, bash, web, todos, questions
- [x] Schema checks and result handoff

### Phase 3 — context, permissions, recovery

- [x] Git status, file tree, `CLAUDE.md`
- [x] Local memory
- [x] Desktop approvals and the shell guard
- [ ] Richer workspace summary
- [ ] `/resume`, `/compact`, `/doctor`
- [ ] General pre/post tool hooks

### Phase 4 — extensions

- [x] MCP client for servers the user already runs
- [ ] Python plugin loader
- [ ] Custom commands, tools, and hooks
- [ ] Broader observability

### Phase 5 — Python-specific tools

- [ ] Notebook helpers
- [ ] Data and ETL helpers
- [ ] pytest, ruff, mypy, and uv integration

## Pull requests

Prefer a working path over a longer command list. Keep each PR to one module, and add a test or a run example. Python 3.10 stays the minimum. Shell approvals and the shell guard stay on.

Suggested areas: CLI and desktop UX, tools, context, permissions, providers, MCP, tests, and performance.
