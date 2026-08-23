# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-08-23

### Added
- Persistent desktop conversations: sessions restore on restart; sidebar lists all chats
- New Chat always creates a unique empty session (new id, empty messages, reset token meter)
- Shared agent memory under `~/.clawd/memory` (facts + compact conversation index) injected as a short brief each turn

## [0.2.1] - 2026-08-23

### Fixed
- Anthropic 400 `tools.17.custom.input_schema.type` still fired after 0.2.0: MCP resource tools were not omitted (real names are `ListMcpResourcesTool` / `ReadMcpResourceTool`), which shifted index 17 to AskUserQuestion
- Anthropic/OpenAI payloads now use only the classic tool shape `{name, description, input_schema:{type:object, properties, required?}}`; nested object schemas get `type`; anyOf/oneOf is flattened
- The same Anthropic request is retried with tools omitted on this exact 400 so the user still gets a reply; tool index 17 is logged

## [0.2.0] - 2026-08-23

### Added
- `VERSION` file (starts at 0.2.0), shown in the desktop header, Windows installer, and README
- Conversation rename in the left sidebar (inline double-click / context menu); title is persisted with the session
- Standalone desktop chat: Jonathan Ai is the agent. MCP / ExternalAgent / Cursor / Codex tools are omitted from the provider payload until something is connected
- Tool schema sanitizer: every tool sent to Anthropic/OpenAI has `input_schema.type: object` (repairs or drops invalid schemas)

### Fixed
- Anthropic 400 `tools.17.custom.input_schema.type: Field required` — SkillTool (default registry index 17) previously sent `anyOf` without a top-level `type`

### Added (earlier unreleased)
- Windows desktop path: JonathanAi-Setup.exe wizard (Next/Install/Finish), JonathanAi.exe app, Desktop and Start Menu shortcuts named Jonathan Ai, robot sketch branding, glassmorphism dashboard
- First-class GitHub and GitLab connectors: token or device/OAuth login, clone/pull/push, create repo/project, PR/MR, list remotes. Default GitHub owner is GoDeskio. Default branches are not pushed unless the operator names them.
- MCP server and OpenAI-compatible agent connectors (add/list/enable/test/invoke) plus Cursor/Codex/local hook files and inbound localhost hook
- Per-chat informational token usage (input, output, running total) persisted with the session — never a quota or paywall
- First-class Hugging Face (Hub + Inference) and Local LLM connectors in Jonathan Ai settings and the install wizard
- Local endpoint scan for Ollama, LM Studio, vLLM, llama.cpp, TGI, and custom loopback/LAN URLs
- Desktop app: localhost Python host + chat UI, optional Electron shell
- First-run install wizard (`./install.sh`, `install.ps1`, `python -m src.cli install`)
- Local source default `~/Jonathan/Jonathan-Ai` with configurable path
- User-facing product name **Jonathan Ai** (desktop, wizard, tray; repo remains GoDeskio/Clawd-Code)
- Self-update from GoDeskio/Clawd-Code only (launch + interval, UI status)
- Interactive permission prompts for gated desktop tools (Bash, Write, Edit, Web)
- Session listing, first-run login UI, workspace picker, file/clipboard attach
- Initial context injection pipeline for workspace snapshot, git status, and `CLAUDE.md`
- Tests covering the new context system integration and desktop host wiring

### Changed
- Skill frontmatter parsing now supports inline list syntax such as `arguments: [path]`
- README and contributor docs now prefer `uv`-based setup instructions
- Documentation now distinguishes provider-level streaming interfaces from the current turn-based CLI output

## [0.1.0] - 2026-04-01

### Added

#### Core Features
- Multi-provider support for Anthropic, OpenAI, and GLM (Zhipu AI)
- Interactive REPL with prompt-toolkit integration
- Rich interactive terminal output
- Session persistence and management
- Configuration management with basic API key obfuscation

#### CLI Commands
- `clawd` - Start the interactive REPL
- `clawd login` - Interactive API key configuration
- `clawd config` - View current configuration
- `clawd --version` - Show version information

#### Provider Implementations
- **Anthropic Provider**: Claude integration with chat + streaming interfaces
- **OpenAI Provider**: GPT integration with chat + streaming interfaces
- **GLM Provider**: GLM integration with chat + streaming interfaces

#### REPL Features
- Command history with persistent storage
- Auto-suggestions from history
- Slash commands: `/help`, `/exit`, `/clear`, `/save`, `/load`, `/multiline`
- Skill slash commands backed by `SKILL.md`
- Syntax highlighting with Rich library
- Tab completion and multi-line input support

#### Configuration System
- JSON-based configuration storage
- Base64-encoded API keys for basic obfuscation
- Provider-specific settings (API key, base URL, default model)
- Session auto-save option

#### Session Management
- Unique session ID generation
- Conversation history tracking
- Session save/load functionality
- Conversation clear operation

#### Code Quality
- Type hints for all public functions
- Abstract base class for provider implementations
- Data classes for structured data (ChatMessage, ChatResponse)
- Error handling and validation

#### Testing
- Unit tests for core components
- Integration tests for providers
- End-to-end tests for REPL functionality
- Test coverage for configuration management

### Technical Details

#### Architecture
- Modular provider system with base abstraction
- Conversation management with message history
- Configuration management layer
- REPL engine with prompt-toolkit

#### Dependencies
- `anthropic>=0.18.0` - Anthropic SDK
- `openai>=1.0.0` - OpenAI SDK
- `zhipuai>=2.0.0` - Zhipu AI SDK
- `prompt-toolkit>=3.0.0` - Interactive REPL
- `rich>=13.0.0` - Terminal formatting
- `python-dotenv>=1.0.0` - Environment variables

#### File Structure
```
src/
├── providers/          # LLM provider implementations
│   ├── base.py        # Abstract base class
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   └── glm_provider.py
├── repl/              # Interactive REPL
│   └── core.py
├── agent/             # Session management
│   ├── session.py
│   └── conversation.py
├── config.py          # Configuration management
└── cli.py             # CLI commands
```

### Known Limitations

- Context building is still in early MVP form and needs deeper project summarization
- Permission enforcement exists as a framework but is not fully integrated everywhere
- `/resume`, `/compact`, and `/doctor` are not implemented yet
- The current CLI uses turn-based output even though providers expose streaming interfaces

### Migration Notes

This is the initial MVP release. No migration needed.

### Future Roadmap

- [ ] Context enrichment and project-memory improvements
- [ ] Full permission integration
- [ ] `/resume`, `/compact`, `/doctor`
- [ ] Token usage and cost tracking
- [ ] MCP and plugin-system enhancements

---

## Release Notes

### v0.1.0 - MVP Release

This is the first public release of Clawd Codex, a complete reimplementation of Claude Code. This MVP includes:

- Full multi-provider support
- Interactive REPL
- Session management
- Configuration system
- Tool system and agent loop foundations
- Type-safe implementation

The focus was on building a solid foundation with clean architecture, comprehensive testing, and good developer experience. All core features are working and tested.

**Special Thanks**: This project is inspired by Claude Code and aims to provide an open-source alternative for learning and experimentation.

---

[0.2.2]: https://github.com/GoDeskio/Clawd-Code/releases/tag/v0.2.2
[0.2.1]: https://github.com/GoDeskio/Clawd-Code/releases/tag/v0.2.1
[0.2.0]: https://github.com/GoDeskio/Clawd-Code/releases/tag/v0.2.0
[0.1.0]: https://github.com/GPT-AGI/Clawd-Code/releases/tag/v0.1.0
