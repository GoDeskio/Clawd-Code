"""Desktop agent runtime — wraps the existing loop, sessions, and skills."""

from __future__ import annotations

import os
import mimetypes
import re
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.agent import Session
from src.agent.conversation import AttachmentContentBlock, ImageContentBlock, TextContentBlock
from src.agent.session import empty_token_usage
from src.command_system import (
    CommandRegistry,
    create_command_context,
    execute_command_sync,
    register_builtin_commands,
)
from src.agent.memory import remember_turn
from src.agent.checkpoints import create_checkpoint, list_checkpoints, prepare_retry, restore_checkpoint, undo_last_turn
from src.agent.history_search import search_history
from src.agent.event_log import append_runtime_event, read_runtime_events
from src.agent.autonomy import autonomy_status, record_permission_evidence
from src.agent.roster import get_agent as get_roster_agent, list_agents as list_roster_agents, read_inbox, remove_agent as remove_roster_agent, save_agent as save_roster_agent, send_message as send_roster_message
from src.config import (
    get_default_provider,
    get_desktop_settings,
    get_finance_config,
    get_local_runtime_credential,
    get_provider_config,
    has_configured_provider,
    is_provider_ready,
    provider_requires_key,
    public_config,
    set_api_key,
    set_default_provider,
    set_alpaca_config,
    update_desktop_settings,
)
from src.providers.huggingface_connect import (
    cache_huggingface_model,
    list_huggingface_models,
    verify_huggingface_token,
)
from src.providers.local_endpoints import (
    assert_local_or_lan_url,
    discover_local_environment,
    list_local_models,
    normalize_openai_base,
    scan_local_endpoints,
)
from src.cost_tracker import CostTracker
from src.history import HistoryLog
from src.providers import PROVIDER_INFO, get_provider_class
from src.providers.resilient import ResilientProvider, resilient
from src.skills.loader import get_all_skills
from src.skills.frontmatter import parse_frontmatter
from src.skills.learning import analyze_git_history, learning_status, record_observation
from src.skills.library import (
    archive_user_skill,
    ensure_learning_skill,
    open_skill_library,
    render_skill,
    save_user_skill,
    user_skill_library,
    validate_skill_source,
)
from src.tool_system.agent_loop import ToolEvent, run_agent_loop, summarize_tool_result, summarize_tool_use
from src.tool_system.audit import audit_path, read_actions, record_action
from src.tool_system.context import ToolContext
from src.tool_system.permissions import ToolPermissionContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.tool_system.tools.terminal import discover_terminals
from src.tool_system.tools.three_d_studio import media_capabilities
from src.tool_system.tools.image_studio import ImageStudioTool
from src.tool_system.tools.system_admin import system_admin_capabilities
from src.connectors.agents import get_saved_agent, invoke_agent, list_agent_tools, test_agent_endpoint
from src.connectors.external import authorization_request, exchange_authorization_code, test_service
from src.connectors.git_common import workspace_git_status
from src.connectors.github import GitHubConnector, poll_github_device_login, start_github_device_login
from src.connectors.gitlab import GitLabConnector, poll_gitlab_device_login, start_gitlab_device_login
from src.connectors.hooks import load_hook_files
from src.connectors.mcp_client import enabled_mcp_clients, test_mcp_record
from src.connectors.publish import publish_workspace
from src.connectors.store import (
    DEFAULT_GITHUB_OWNER,
    public_connectors,
    read_connectors,
    save_agent,
    save_external_service,
    save_mcp_server,
    remove_external_service,
    set_agent_enabled,
    set_mcp_enabled,
)
from src.install.record import read_install_record, resolve_source_dir
from src.install.source import default_source_dir
from src.integrations.fooocus import FooocusManager
from src.integrations.kronos import KronosManager
from src.integrations.securo import SecuroManager
from src.integrations.claude_db import ClaudeDbManager
from src.integrations.procoder import ProcoderManager
from src.integrations.drawai import DrawAiManager
from src.integrations.character_studio import generate_character
from src.integrations.ecc import (
    catalog as ecc_catalog,
    import_catalog as ecc_import_catalog,
    memory_vault_export,
    memory_vault_import,
    security_scan as ecc_security_scan,
    set_enabled as ecc_set_enabled,
    status as ecc_status,
    sync as ecc_sync,
    ecc_cache_dir,
)
from src.update import Updater
from src.version import get_version
from src.doctor import run_doctor

from .attachments import Attachment, attach_path, attachments_from_payload, image_source, render_attachments


def provider_limit_hint(exc: Exception | str) -> str:
    """Explain a provider rate-limit/billing error without inventing a token store."""
    message = str(exc)
    lower = message.lower()
    markers = (
        "rate limit",
        "rate_limit",
        "too many requests",
        "429",
        "quota",
        "billing",
        "insufficient_quota",
        "credit",
        "payment required",
    )
    if not any(marker in lower for marker in markers):
        return ""
    return (
        " This is the connected provider's own limit, not a Jonathan Ai token store. "
        "Switch to Hugging Face, a local LLM, or another saved provider in settings. "
        "The on-screen token count is informational and never a paywall."
    )


_LOCAL_ACTION_RE = re.compile(
    r"(?ix)(?:"
    r"\b(?:fix|debug|build|install|uninstall|run|execute|test|deploy|package|download|upload|"
    r"delete|remove|rename|move|copy|clone|push|pull|commit|monitor|scan|connect|configure|"
    r"browse|search|fetch|render|convert|trade|schedule|automate)\b|"
    r"\b(?:file|folder|directory|workspace|project|repo|repository|github|gitlab|terminal|shell|"
    r"powershell|bash|command|cli|script|source\s+code|database|server|process|service|system|"
    r"image|photo|picture|fooocus|blender|3d|stl|obj|gltf|audio|voice|speech|transcribe|whisper|spreadsheet|workbook|pdf|document|"
    r"connector|oauth|api|website|webpage|portfolio|market|stock|crypto|skill|agent|tool|cron|"
    r"device|application|app|browser|chrome|edge|firefox|keyboard|mouse|click|screenshot|network)\b|"
    r"https?://|```|(?:[A-Za-z]:\\)|(?:\./|\.\\)|\.(?:py|js|ts|tsx|jsx|json|md|txt|csv|xlsx|"
    r"docx|pdf|png|jpe?g|webp|stl|obj|gltf|blend)\b)"
)

_DIRECT_IMAGE_NOUN_RE = re.compile(
    r"(?i)\b(?:images?|pictures?|photos?|illustrations?|artworks?|graphics?|logos?|posters?|wallpapers?|icons?|portraits?)\b"
)
_DIRECT_IMAGE_CREATE_RE = re.compile(
    r"(?i)\b(?:generate|create|make|draw|render|produce|design|paint)\b"
)
_DIRECT_IMAGE_EDIT_RE = re.compile(
    r"(?i)^\s*(?:(?:please|kindly)\s+|(?:can|could|would)\s+you\s+)?"
    r"(?:edit|modify|change|transform|restyle|recolor|retouch|enhance|remove|replace|add)\b"
)
_IMAGE_FEATURE_REQUEST_RE = re.compile(
    r"(?i)\b(?:fix|build|implement|integrate|support|debug|wire|add)\b.*"
    r"\b(?:image\s+(?:generator|generation|editor|editing)|image\s+(?:tool|feature|button|api)|codebase|application|app)\b"
)


def direct_image_request(text: str, attachments: list[Attachment] | None = None) -> tuple[str, str] | None:
    """Recognize an explicit prompt-level image request without asking an LLM to route it."""
    raw = str(text or "").strip()
    images = [item for item in attachments or [] if item.is_image and item.path and not item.omitted]
    if raw.lower() == "/image":
        return "generate", ""
    if raw.lower().startswith("/image "):
        prompt = raw[7:].strip()
        return ("ai_edit" if images else "generate", prompt) if prompt else None
    if _IMAGE_FEATURE_REQUEST_RE.search(raw):
        return None
    wants_creation = bool(_DIRECT_IMAGE_CREATE_RE.search(raw) and _DIRECT_IMAGE_NOUN_RE.search(raw))
    wants_edit = bool(images and _DIRECT_IMAGE_EDIT_RE.search(raw))
    if not wants_creation and not wants_edit:
        return None
    return ("ai_edit" if images else "generate", raw)


def local_chat_route(text: str, attachments: list[Attachment] | None = None) -> tuple[bool, set[str]]:
    """Return (lightweight, visible tools) for an OpenAI-compatible local model.

    Ordinary conversation skips tool schemas entirely. Actionable requests get
    a focused subset plus ToolSearch, which can expand the set on later turns.
    """
    raw = str(text or "")
    lower = raw.lower()
    attached = list(attachments or [])
    if not attached and not _LOCAL_ACTION_RE.search(raw):
        return True, set()

    selected = {"ToolSearch", "AskUserQuestion"}

    def has(*terms: str) -> bool:
        return any(term in lower for term in terms)

    if has("file", "folder", "directory", "workspace", "project", "code", "script", "repo", "github", "gitlab") or re.search(r"\.(?:py|js|ts|tsx|jsx|json|md|txt)\b", lower):
        selected.update({"Read", "Write", "Edit", "Glob", "Grep", "Bash", "Terminal", "PowerShell", "LSP", "Repository", "Artifact"})
    if has("terminal", "shell", "powershell", "bash", "command", "cli", "process", "service", "system", "install", "monitor", "scan"):
        selected.update({"Bash", "Terminal", "PowerShell", "SystemAdmin"})
    if has("device", "application", " app", "browser", "chrome", "edge", "firefox", "keyboard", "mouse", "click", "type text", "hotkey", "screenshot", "open file", "open url"):
        selected.update({"DeviceControl", "Terminal", "SystemAdmin"})
    if has("browse", "search", "fetch", "website", "webpage", "http://", "https://"):
        selected.update({"WebSearch", "WebFetch", "ContentReach"})
    if has("youtube", "caption", "subtitle", "rss", "atom", "feed"):
        selected.update({"ContentReach", "WebFetch", "Artifact"})
    if has("network", "lan", "wifi", "ethernet", "port", "firewall", "ip address"):
        selected.update({"WebSearch", "WebFetch", "Terminal", "PowerShell", "SystemAdmin", "DeviceControl"})
    if attached or has("image", "photo", "picture", "fooocus", "png", "jpg", "jpeg", "webp"):
        selected.update({"Read", "VisionAnalyze", "ImageStudio", "LocalImage", "Artifact"})
    if any(str(item.media_type).startswith("audio/") for item in attached) or has("audio", "voice", "speech", "transcribe", "whisper", "wav", "mp3", "webm"):
        selected.update({"Read", "SpeechStudio", "AudioStudio", "Artifact"})
    if has("blender", "3d", "stl", "obj", "gltf", "blend"):
        selected.update({"ThreeDStudio", "Artifact", "Terminal"})
    if has("spreadsheet", "workbook", "csv", "xlsx", "pdf", "document", "docx", "notebook"):
        selected.update({"Read", "Write", "Artifact", "NotebookEdit"})
    if has("trade", "portfolio", "market", "stock", "crypto", "business", "finance"):
        selected.update({"BusinessManager", "FinanceMarkets", "Trading", "KronosForecast", "PersonalFinanceVault"})
    if has("connector", "oauth", "external", "mcp", "api"):
        selected.update({"MCP", "ExternalAgent", "ListMcpResources", "ReadMcpResource"})
    if has("skill"):
        selected.update({"Skill", "SkillManager"})
    if has("agent", "worker", "task", "team"):
        selected.update({"SpawnWorkers", "AgentInstances", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskOutput", "TeamCreate", "TeamDelete"})
    if has("remember", "memory"):
        selected.add("SharedMemory")
    if has("schedule", "cron", "automate"):
        selected.update({"CronCreate", "CronList", "CronDelete"})
    if has("package", "download", "artifact", "zip", "publish"):
        selected.add("Artifact")
    return False, selected


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class PermissionRequest:
    request_id: str
    tool_name: str
    message: str
    suggestion: str | None = None
    session_id: str = ""
    event: threading.Event = field(default_factory=threading.Event)
    allowed: bool = False
    always: bool = False
    enable_docs: bool = False


@dataclass
class ChatJob:
    job_id: str
    session_id: str = ""
    mode: str = "chat"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    done: bool = False
    cancelled: bool = False


@dataclass
class AgentInstance:
    """All mutable agent state owned by one conversation."""

    session: Session
    workspace: Path
    tool_context: ToolContext
    command_context: Any
    cost_tracker: CostTracker
    history_log: HistoryLog
    run_lock: threading.Lock = field(default_factory=threading.Lock)
    active_jobs: set[str] = field(default_factory=set)


class DesktopRuntime:
    """In-process desktop controller around the existing agent brain."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        provider_name: str | None = None,
        *,
        stream: bool = True,
        permission_timeout_s: float = 300.0,
    ) -> None:
        settings = get_desktop_settings()
        self.full_device_access = bool(settings.get("full_device_access", False))
        raw_workspace = workspace or settings.get("workspace") or Path.cwd()
        self.workspace = Path(raw_workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        raw_projects = settings.get("projects_dir") or Path.home() / "Jonathan" / "Projects"
        self.projects_dir = Path(raw_projects).expanduser().resolve()
        self._artifact_dir_override: Path | None = None
        self._artifact_fallback_dir = (Path.home() / ".clawd" / "artifacts").resolve()
        ensure_learning_skill(source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        self.stream = stream
        self.permission_timeout_s = permission_timeout_s
        self.provider_name = provider_name or get_default_provider()
        self._device: dict[str, Any] = {}
        # A local runtime is the zero-configuration fallback. Existing healthy
        # cloud configuration remains the user's explicit preference. Once a
        # provider is configured, move device-wide filesystem/port discovery
        # off the startup path so the conversation window can open immediately.
        provider_configured = has_configured_provider()
        try:
            if provider_configured:
                self._device = {
                    "runtimes": [], "endpoints": [], "selected": None,
                    "scan_pending": True, "auto_started": False,
                }
            else:
                self._device = discover_local_environment(auto_start=True)
            selected = self._device.get("selected")
            if not provider_configured and isinstance(selected, dict):
                models = list(selected.get("models") or [])
                if models:
                    local_key = get_local_runtime_credential(str(selected["base_url"])).get("api_key") or "local"
                    set_api_key(
                        "local", local_key, base_url=str(selected["base_url"]),
                        default_model=str(models[0]),
                    )
                    set_default_provider("local")
                    self.provider_name = "local"
        except Exception as exc:
            self._device = {"runtimes": [], "endpoints": [], "selected": None, "error": str(exc)}
        self.provider = None
        self.session = Session.create(self.provider_name, "unconfigured", workspace=str(self.workspace))
        self.tool_registry = build_default_registry()
        self.tool_context = self._make_context()
        self.command_registry = CommandRegistry()
        register_builtin_commands(self.command_registry)
        self.cost_tracker = CostTracker()
        self.history_log = HistoryLog()
        self.command_context = create_command_context(
            workspace_root=self.workspace,
            conversation=self.session.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history_log,
        )
        self._instances: dict[str, AgentInstance] = {}
        self._jobs: dict[str, ChatJob] = {}
        self._permissions: dict[str, PermissionRequest] = {}
        self._lock = threading.Lock()
        self.install_record = read_install_record()
        self.updater = Updater(resolve_source_dir() or Path.cwd())
        self.fooocus = FooocusManager(self.updater.source_dir)
        self.kronos = KronosManager(self.updater.source_dir)
        self.personal_finance = SecuroManager(self.updater.source_dir)
        self.code_memory = ClaudeDbManager(self.updater.source_dir)
        self.procoder = ProcoderManager(self.updater.source_dir)
        self.drawai = DrawAiManager(self.updater.source_dir)
        self._external_oauth: dict[str, dict[str, str]] = {}
        try:
            load_hook_files()
        except Exception:
            pass
        self._try_init_provider()
        self._restore_session()
        if provider_configured:
            self._device_thread = threading.Thread(
                target=self._refresh_device_inventory,
                daemon=True,
                name="clawd-local-scan",
            )
            self._device_thread.start()
        if self.install_record:
            self._update_thread = threading.Thread(target=self._auto_update_on_launch, daemon=True, name="clawd-update")
            self._update_thread.start()

    def _refresh_device_inventory(self) -> None:
        try:
            self._device = discover_local_environment(auto_start=False)
        except Exception as exc:
            self._device = {
                "runtimes": [], "endpoints": [], "selected": None,
                "scan_pending": False, "error": str(exc),
            }

    def _make_context(self, workspace: Path | None = None, session_id: str | None = None) -> ToolContext:
        root = Path(workspace or self.workspace).resolve()
        sid = session_id or (getattr(self, "session", None).session_id if getattr(self, "session", None) else "")
        permission_context = ToolPermissionContext.from_iterables(
            workspace_root=root,
            allow_docs=self.full_device_access,
            full_system_access=self.full_device_access,
        )
        ctx = ToolContext(workspace_root=root, permission_context=permission_context)
        ctx.gate_destructive_tools = True
        if self.full_device_access:
            ctx.session_grants.add("*")
        ctx.permission_handler = lambda tool, message, suggestion: self._handle_permission_request(
            sid, ctx, tool, message, suggestion
        )
        ctx.ask_user = self._ask_user_questions
        ctx.mcp_clients = enabled_mcp_clients()
        ctx.session_id = sid or None
        ctx.instance_reader = lambda action, target: self._read_instance(sid, action, target)
        ctx.agent_roster = lambda action, payload: self._agent_roster_action(sid, action, payload)
        ctx.artifact_publisher = lambda source, name=None: self._publish_session_artifact(sid, source, name)
        ctx.audit_logger = record_action
        ctx.provider = getattr(self, "provider", None)
        return ctx

    def _create_instance(self, session: Session, workspace: Path | None = None) -> AgentInstance:
        root = Path(workspace or session.workspace or self.workspace).expanduser().resolve()
        if not root.is_dir():
            root = self.workspace
        cost_tracker = CostTracker()
        history_log = HistoryLog()
        context = self._make_context(root, session.session_id)
        command_context = create_command_context(
            workspace_root=root,
            conversation=session.conversation,
            cost_tracker=cost_tracker,
            history=history_log,
        )
        instance = AgentInstance(
            session=session,
            workspace=root,
            tool_context=context,
            command_context=command_context,
            cost_tracker=cost_tracker,
            history_log=history_log,
        )
        self._instances[session.session_id] = instance
        return instance

    def _agent_for_session(self, session_id: str | None = None) -> AgentInstance:
        target_id = str(session_id or self.session.session_id or "").strip()
        instance = self._instances.get(target_id)
        if instance is not None:
            return instance
        loaded = Session.load(target_id)
        if loaded is None:
            raise ValueError(f"session not found: {target_id}")
        return self._create_instance(loaded)

    def _bind_session(self, session: Session) -> None:
        if self.provider is not None:
            session.provider = self.provider_name
            session.model = self.provider.model
        session.workspace = session.workspace or str(self.workspace)
        instance = self._instances.get(session.session_id) or self._create_instance(session)
        instance.session = session
        instance.command_context.conversation = session.conversation
        self.session = session
        self.workspace = instance.workspace
        self.tool_context = instance.tool_context
        self.command_context = instance.command_context
        self.cost_tracker = instance.cost_tracker
        self.history_log = instance.history_log
        try:
            update_desktop_settings(current_session_id=self.session.session_id)
        except Exception:
            pass

    def _restore_session(self) -> None:
        settings = get_desktop_settings()
        candidates = [settings.get("current_session_id") or ""]
        listed = Session.list_sessions()
        if listed:
            candidates.append(listed[0].get("session_id") or "")
        seen: set[str] = set()
        for session_id in candidates:
            if not session_id or session_id in seen:
                continue
            seen.add(session_id)
            loaded = Session.load(session_id)
            if loaded is None:
                continue
            if loaded.workspace:
                try:
                    workspace = Path(loaded.workspace).expanduser().resolve()
                    if workspace.exists() and workspace.is_dir():
                        self.workspace = workspace
                        grants = set(self.tool_context.session_grants)
                        self.tool_context = self._make_context()
                        self.tool_context.session_grants = grants
                except Exception:
                    pass
            self._bind_session(loaded)
            return
        self.session.workspace = str(self.workspace)
        self.session.save()
        self._bind_session(self.session)

    def _refresh_mcp(self) -> None:
        clients = enabled_mcp_clients()
        self.tool_context.mcp_clients = clients
        for instance in self._instances.values():
            instance.tool_context.mcp_clients = clients

    def _try_init_provider(self) -> None:
        try:
            config = get_provider_config(self.provider_name)
        except ValueError:
            self.provider = None
            return
        if not is_provider_ready(self.provider_name, config):
            self.provider = None
            return
        provider_class = get_provider_class(self.provider_name)
        self.provider = provider_class(
            api_key=config.get("api_key") or "local",
            base_url=config.get("base_url"),
            model=config.get("default_model") or None,
        )
        self.provider = resilient(self.provider)
        if self.session.provider != self.provider_name or self.session.model == "unconfigured":
            self.session.provider = self.provider_name
            self.session.model = self.provider.model
        self.tool_context.provider = self.provider
        for instance in self._instances.values():
            instance.tool_context.provider = self.provider
            instance.session.provider = self.provider_name
            instance.session.model = self.provider.model

    def needs_setup(self) -> bool:
        return not has_configured_provider()

    def status(self) -> dict[str, Any]:
        cfg = public_config()
        return {
            "ready": not self.needs_setup(),
            "needs_setup": self.needs_setup(),
            "version": get_version(),
            "product": "Jonathan Ai",
            "standalone": True,
            "workspace": str(self.workspace),
            "projects_dir": str(self.projects_dir),
            "provider": self.provider_name,
            "model": getattr(self.provider, "model", None) or self.session.model,
            "provider_health": self.provider.health() if isinstance(self.provider, ResilientProvider) else {"state": "unknown"},
            "session": self.session.to_summary(),
            "config": cfg,
            "notify_on_complete": get_desktop_settings().get("notify_on_complete", True),
            "install": self.install_info(),
            "connectors": public_connectors(),
            "git": workspace_git_status(self.workspace),
            "preview": self.preview_info(),
            "artifacts": self.list_artifacts(),
            "terminals": discover_terminals(),
            "media": self.media_status(),
            "fooocus": self.fooocus.status(),
            "local_ai": self._device,
            "administrator": system_admin_capabilities(),
            "device_access": self.device_access_status(),
            "earned_autonomy": autonomy_status(self.session.session_id),
            "business_finance": self.business_finance_status(),
            "kronos": self.kronos.status(),
            "personal_finance": self.personal_finance.status(),
            "code_memory": self.code_memory.status(),
            "procoder": self.procoder.status(),
            "drawai": self.drawai.status(),
            "instances": self.instances_status(),
            "update": self.updater.last_check or {
                "source_dir": str(self.updater.source_dir),
                "local_sha": None,
                "update_available": False,
            },
        }

    def device_access_status(self) -> dict[str, Any]:
        settings = get_desktop_settings()
        enabled = bool(settings.get("full_device_access", False))
        admin = system_admin_capabilities().get("administrator", False)
        return {
            "enabled": enabled,
            "approved_at": settings.get("full_device_access_approved_at") or "",
            "operating_system_scope": "administrator" if admin else "signed-in user",
            "uac_required_for_elevation": bool(os.name == "nt" and not admin),
            "capabilities": [
                "read and write files across mounted drives",
                "run installed shells and command-line tools",
                "launch installed applications and browsers",
                "open local files and web URLs",
                "use network tools and connected services",
                "administer processes, services, packages, Git repositories, and system resources",
            ],
        }

    def configure_device_access(self, *, enabled: bool, confirmation: str = "") -> dict[str, Any]:
        if enabled and str(confirmation or "").strip() != "ENABLE FULL ACCESS":
            raise ValueError("Type ENABLE FULL ACCESS to approve persistent device and network access")
        approved_at = datetime.now(timezone.utc).isoformat() if enabled else ""
        update_desktop_settings(
            full_device_access=enabled,
            full_device_access_approved_at=approved_at,
        )
        self.full_device_access = enabled
        contexts: list[ToolContext] = [self.tool_context]
        contexts.extend(instance.tool_context for instance in self._instances.values())
        seen: set[int] = set()
        for context in contexts:
            if id(context) in seen:
                continue
            seen.add(id(context))
            current = context.permission_context
            context.permission_context = ToolPermissionContext.from_iterables(
                current.deny_names,
                current.deny_prefixes,
                workspace_root=context.workspace_root,
                additional_working_directories=current.additional_working_directories,
                allow_docs=enabled or current.allow_docs,
                full_system_access=enabled,
            )
            if enabled:
                context.session_grants.add("*")
            else:
                context.session_grants.discard("*")
        record_action({
            "session_id": self.session.session_id,
            "tool": "DeviceAccess",
            "input": {"enabled": enabled},
            "permission": "explicit persistent user approval" if enabled else "user revoked",
            "status": "enabled" if enabled else "revoked",
        })
        return self.device_access_status()

    def device_inventory(self, *, limit: int = 2000) -> dict[str, Any]:
        from src.device_control import discover_device_controls

        return discover_device_controls(limit=max(1, min(5000, int(limit))))

    def install_info(self) -> dict[str, Any]:
        record = self.install_record or read_install_record() or {}
        return {
            "source_dir": record.get("source_dir") or str(self.updater.source_dir),
            "default_source_dir": str(default_source_dir()),
            "repo": record.get("repo") or "https://github.com/GoDeskio/Clawd-Code.git",
            "commit": record.get("commit") or "",
        }

    def update_status(self, *, refresh: bool = False) -> dict[str, Any]:
        return self.updater.status(refresh=refresh)

    def audit_actions(self, limit: int = 100) -> dict[str, Any]:
        return {"path": str(audit_path()), "actions": read_actions(limit)}

    def media_status(self) -> dict[str, Any]:
        status = media_capabilities()
        image = status.setdefault("image", {})
        try:
            config = get_provider_config("openai")
            image["ai_configured"] = bool(str(config.get("api_key") or "").strip())
            image["ai_endpoint"] = config.get("base_url") or "https://api.openai.com/v1"
            image["ai_model"] = "gpt-image-1"
        except Exception:
            image["ai_configured"] = False
        try:
            image["fooocus"] = self.fooocus.status()
            image["local_generation_ready"] = bool(image["fooocus"].get("running"))
        except Exception as exc:
            image["fooocus"] = {"running": False, "error": str(exc)}
        return status

    def configure_image_provider(self, api_key: str, *, base_url: str = "", model: str = "") -> dict[str, Any]:
        if not str(api_key or "").strip():
            raise ValueError("Image API key is required")
        current = get_provider_config("openai")
        set_api_key(
            "openai",
            str(api_key).strip(),
            base_url=base_url.strip() or "https://api.openai.com/v1",
            default_model=str(current.get("default_model") or "gpt-5.4"),
        )
        return self.media_status()

    def run_image_action(self, payload: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
        agent = self._agent_for_session(session_id)
        tool_input = {key: value for key, value in payload.items() if key != "session_id" and value not in (None, "")}
        record_action({"session_id": agent.session.session_id, "tool": "ImageStudio", "input": tool_input,
                       "permission": "direct user action", "status": "requested"})
        result = ImageStudioTool().run(tool_input, agent.tool_context)
        if result.is_error:
            raise ValueError(str(result.output))
        agent.session.save()
        return result.output if isinstance(result.output, dict) else {"result": result.output}

    def fooocus_status(self) -> dict[str, Any]:
        return self.fooocus.status()

    def fooocus_action(self, payload: dict[str, Any] | str) -> dict[str, Any]:
        body = payload if isinstance(payload, dict) else {"action": payload}
        agent = self._agent_for_session(str(body.get("session_id") or "") or None)
        name = str(body.get("action") or "status").strip().lower()
        if name == "status":
            return self.fooocus.status()
        if name in {"install", "repair"}:
            return self.fooocus.install()
        if name == "start":
            return self.fooocus.start()
        if name == "stop":
            return self.fooocus.stop()
        if name == "generate":
            result = self.fooocus.generate(
                str(body.get("prompt") or ""),
                negative_prompt=str(body.get("negative_prompt") or ""),
                width=int(body.get("width") or 1024),
                height=int(body.get("height") or 1024),
                performance=str(body.get("performance") or "Speed"),
                seed=int(body["seed"]) if body.get("seed") is not None else None,
            )
            artifacts = [self._publish_artifact(item["path"], item["name"]) for item in result["outputs"]]
            for artifact in artifacts:
                agent.session.record_artifact(artifact, caption="Generated with Jonathan local diffusion")
            agent.session.save()
            return {**result, "artifact": artifacts[0], "artifacts": artifacts}
        if name == "outputs":
            return {"outputs": self.fooocus.latest_outputs(), **self.fooocus.status()}
        if name == "publish_latest":
            latest = self.fooocus.latest_outputs(1)
            if not latest:
                raise ValueError("Jonathan's local image engine has not produced an image yet")
            artifact = self._publish_artifact(latest[0]["path"], latest[0]["name"])
            agent.session.record_artifact(artifact, caption="Generated with Jonathan local diffusion")
            agent.session.save()
            return {"ok": True, "artifact": artifact, "artifacts": [artifact]}
        raise ValueError(f"unsupported local image action: {name}")

    def business_finance_status(self) -> dict[str, Any]:
        slot = get_finance_config().get("alpaca") or {}
        try:
            import importlib.util
            market_data = importlib.util.find_spec("yfinance") is not None
        except Exception:
            market_data = False
        return {
            "business_database": str(Path.home() / ".clawd" / "business" / "business.db"),
            "market_data": market_data,
            "broker": {"provider": "alpaca", "configured": bool(slot.get("api_key") and slot.get("secret_key")),
                       "paper": bool(slot.get("paper", True)), "mode": "paper" if slot.get("paper", True) else "live"},
        }

    def configure_alpaca(self, api_key: str, secret_key: str, *, paper: bool = True) -> dict[str, Any]:
        if not api_key.strip() or not secret_key.strip():
            raise ValueError("Alpaca API key and secret are required")
        set_alpaca_config(api_key, secret_key, paper=paper)
        return self.business_finance_status()

    def apply_update(self) -> dict[str, Any]:
        result = self.updater.apply()
        self.install_record = read_install_record()
        return result

    def _auto_update_on_launch(self) -> None:
        """Check for updates without mutating the checkout behind the app."""
        try:
            self.updater.status(refresh=True)
        except Exception:
            return

    def provider_catalog(self) -> dict[str, Any]:
        return {
            name: {
                "label": info["label"],
                "default_base_url": info["default_base_url"],
                "default_model": info["default_model"],
                "available_models": list(info.get("available_models") or []),
                "requires_key": bool(info.get("requires_key", True)),
                "kind": info.get("kind") or "cloud",
                "token_label": info.get("token_label") or "API key",
                "help": info.get("help") or "",
            }
            for name, info in PROVIDER_INFO.items()
        }

    def login(
        self,
        provider: str,
        api_key: str,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> dict[str, Any]:
        if provider not in PROVIDER_INFO:
            raise ValueError(f"Unknown provider: {provider}")
        info = PROVIDER_INFO[provider]
        key = str(api_key or "").strip()
        if provider_requires_key(provider) and not key:
            raise ValueError(f"{info.get('token_label') or 'API key'} cannot be empty")
        url = base_url or info["default_base_url"]
        if info.get("kind") == "local":
            url = normalize_openai_base(url)
            if not str(default_model or "").strip():
                raise ValueError("Pick a local model before connecting")
        set_api_key(
            provider,
            api_key=key,
            base_url=url,
            default_model=default_model or info["default_model"],
        )
        set_default_provider(provider)
        self.provider_name = provider
        self._try_init_provider()
        return self.status()

    def set_provider(self, provider: str, *, model: str | None = None) -> dict[str, Any]:
        if provider not in PROVIDER_INFO:
            raise ValueError(f"Unknown provider: {provider}")
        set_default_provider(provider)
        if model:
            cfg = get_provider_config(provider)
            set_api_key(
                provider,
                api_key=cfg.get("api_key") or "",
                base_url=cfg.get("base_url"),
                default_model=model,
            )
        self.provider_name = provider
        self._try_init_provider()
        if self.provider is not None:
            self.session.provider = provider
            self.session.model = self.provider.model
        return self.status()

    def test_huggingface(self, token: str) -> dict[str, Any]:
        return verify_huggingface_token(token)

    def list_huggingface(self, token: str, search: str = "") -> dict[str, Any]:
        models = list_huggingface_models(token, search=search)
        return {"models": models, "router": "https://router.huggingface.co/v1"}

    def cache_huggingface(self, repo_id: str, token: str) -> dict[str, Any]:
        return cache_huggingface_model(repo_id, token)

    def scan_local(self, extra_url: str | None = None, *, auto_start: bool = False) -> dict[str, Any]:
        extras = [extra_url] if extra_url else None
        if extra_url:
            assert_local_or_lan_url(extra_url)
        self._device = discover_local_environment(extras, auto_start=auto_start)
        selected = self._device.get("selected")
        if auto_start and isinstance(selected, dict) and selected.get("models"):
            local_key = get_local_runtime_credential(str(selected["base_url"])).get("api_key") or "local"
            set_api_key(
                "local", local_key, base_url=str(selected["base_url"]),
                default_model=str(selected["models"][0]),
            )
            set_default_provider("local")
            self.provider_name = "local"
            self._try_init_provider()
            self._device["connected"] = True
        return self._device

    def list_local(self, base_url: str, api_key: str | None = None) -> dict[str, Any]:
        url = normalize_openai_base(base_url)
        return {"base_url": url, "models": list_local_models(url, api_key)}

    def connectors_public(self) -> dict[str, Any]:
        return public_connectors()

    def save_external_connector(self, payload: dict[str, Any]) -> dict[str, Any]:
        return save_external_service(
            name=str(payload.get("name") or ""),
            base_url=str(payload.get("base_url") or ""),
            auth_type=str(payload.get("auth_type") or "none"),
            service_id=str(payload.get("id") or "") or None,
            **{key: payload.get(key) or "" for key in (
                "username", "password", "api_key", "api_key_header", "bearer_token",
                "authorization_url", "token_url", "client_id", "client_secret", "scopes",
            )},
        )

    def remove_external_connector(self, service_id: str) -> dict[str, Any]:
        return remove_external_service(service_id)

    def test_external_connector(self, service_id: str) -> dict[str, Any]:
        return test_service(service_id)

    def start_external_oauth(self, service_id: str) -> dict[str, Any]:
        result = authorization_request(service_id)
        self._external_oauth[service_id] = result
        return result

    def finish_external_oauth(self, service_id: str, code: str, state: str = "") -> dict[str, Any]:
        pending = self._external_oauth.get(service_id) or {}
        if state and pending.get("state") and state != pending["state"]:
            raise ValueError("OAuth state did not match the pending connection")
        result = exchange_authorization_code(service_id, code, redirect_uri=pending.get("redirect_uri") or "urn:ietf:wg:oauth:2.0:oob")
        self._external_oauth.pop(service_id, None)
        return {**result, "connectors": public_connectors()}

    def connect_github(self, token: str, owner: str | None = None) -> dict[str, Any]:
        result = GitHubConnector().login_with_token(token, owner=owner or DEFAULT_GITHUB_OWNER)
        return {"ok": True, **result, "connectors": public_connectors()}

    def connect_gitlab(self, token: str, owner: str | None = None, host: str | None = None) -> dict[str, Any]:
        result = GitLabConnector(host=host).login_with_token(token, owner=owner, host=host)
        return {"ok": True, **result, "connectors": public_connectors()}

    def start_device_login(self, host: str, client_id: str, forge_host: str | None = None) -> dict[str, Any]:
        if host == "gitlab":
            payload = start_gitlab_device_login(client_id, host=forge_host or "https://gitlab.com")
        else:
            payload = start_github_device_login(client_id)
        self._device = {"host": host, **payload}
        return {k: v for k, v in payload.items() if k != "device_code"} | {"started": True}

    def poll_device_login(self, host: str | None = None) -> dict[str, Any]:
        pending = self._device
        kind = host or pending.get("host") or "github"
        if not pending.get("device_code"):
            raise ValueError("Start device login first")
        if kind == "gitlab":
            result = poll_gitlab_device_login(pending["client_id"], pending["device_code"], host=pending.get("host"))
        else:
            result = poll_github_device_login(pending["client_id"], pending["device_code"])
        if result.get("pending"):
            return result
        self._device = {}
        return {**result, "connectors": public_connectors()}

    def github_repos(self) -> dict[str, Any]:
        return {"repos": GitHubConnector().list_repos()}

    def gitlab_projects(self) -> dict[str, Any]:
        return {"projects": GitLabConnector().list_projects()}

    def clone_repo(self, forge: str, repo: str, dest: str | None = None) -> dict[str, Any]:
        target = Path(dest).expanduser() if dest else self.projects_dir / Path(str(repo).rstrip("/").split("/")[-1].replace(".git", ""))
        if forge == "gitlab":
            result = GitLabConnector().clone(repo, target)
        else:
            result = GitHubConnector().clone(repo, target)
        return {**result, "opened": self.set_workspace(result["path"])}

    def pull_repo(self, dest: str | None = None) -> dict[str, Any]:
        path = Path(dest).expanduser() if dest else self.workspace
        connectors = read_connectors()
        if connectors["gitlab"].get("token") and "gitlab" in str(workspace_git_status(path).get("status") or ""):
            return GitLabConnector().pull(path)
        if connectors["github"].get("token"):
            return GitHubConnector().pull(path)
        return GitHubConnector().pull(path)

    def push_repo(self, branch: str, *, dest: str | None = None, forge: str = "github", operator_named: bool = False) -> dict[str, Any]:
        path = Path(dest).expanduser() if dest else self.workspace
        named = bool(operator_named or (branch or "").strip())
        if forge == "gitlab":
            return GitLabConnector().push_branch(path, branch, operator_named=named)
        return GitHubConnector().push_branch(path, branch, operator_named=named)

    def open_review(self, forge: str, repo: str, branch: str, title: str, body: str = "") -> dict[str, Any]:
        if forge == "gitlab":
            return GitLabConnector().create_merge_request(repo, title=title, source=branch, body=body)
        return GitHubConnector().create_pull_request(repo, title=title, head=branch, body=body)

    def publish_repo(self, *, forge: str = "github", name: str | None = None, owner: str | None = None, branch: str | None = None, title: str | None = None) -> dict[str, Any]:
        operator_named = bool(branch)
        return publish_workspace(
            self.workspace,
            forge=forge,
            name=name,
            owner=owner,
            branch=branch,
            title=title,
            operator_named_branch=operator_named,
        )

    def open_this_repo(self) -> dict[str, Any]:
        status = workspace_git_status(self.workspace)
        if status.get("is_repo"):
            return self.set_workspace(status["path"])
        raise ValueError("This workspace is not a git repository")

    def add_mcp(self, body: dict[str, Any]) -> dict[str, Any]:
        result = save_mcp_server(
            name=str(body.get("name") or ""),
            command=str(body.get("command") or ""),
            args=list(body.get("args") or []),
            url=str(body.get("url") or ""),
            token=str(body.get("token") or ""),
            enabled=bool(body.get("enabled", True)),
            server_id=body.get("id"),
        )
        self._refresh_mcp()
        return result

    def enable_mcp(self, server_id: str, enabled: bool) -> dict[str, Any]:
        result = set_mcp_enabled(server_id, enabled)
        self._refresh_mcp()
        return result

    def enable_agent(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        return set_agent_enabled(agent_id, enabled)

    def test_mcp(self, body: dict[str, Any]) -> dict[str, Any]:
        record = body
        if body.get("id") or body.get("name"):
            for item in read_connectors().get("mcp") or []:
                if item.get("id") == body.get("id") or item.get("name") == body.get("name"):
                    record = {**item, **{k: v for k, v in body.items() if v}}
                    break
        result = test_mcp_record(record)
        return result

    def add_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        return save_agent(
            name=str(body.get("name") or ""),
            base_url=str(body.get("base_url") or body.get("url") or ""),
            api_key=str(body.get("api_key") or body.get("token") or ""),
            kind=str(body.get("kind") or "openai-compatible"),
            enabled=bool(body.get("enabled", True)),
            agent_id=body.get("id"),
        )

    def test_saved_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        url = str(body.get("base_url") or "")
        key = str(body.get("api_key") or "")
        if body.get("id") or body.get("name"):
            saved = get_saved_agent(str(body.get("id") or body.get("name")))
            url = url or str(saved.get("base_url") or "")
            key = key or str(saved.get("api_key") or "")
        result = test_agent_endpoint(url, key)
        result["tools"] = list_agent_tools(url, key)
        return result

    def invoke_saved_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        saved = get_saved_agent(str(body.get("id") or body.get("name") or ""))
        return invoke_agent(
            str(saved.get("base_url") or ""),
            str(body.get("text") or body.get("prompt") or ""),
            api_key=str(saved.get("api_key") or ""),
            model=body.get("model"),
        )

    def inbound_hook(self, text: str) -> dict[str, Any]:
        if not str(text or "").strip():
            raise ValueError("inbound hook text is required")
        job_id = self.start_chat(text)
        return {"ok": True, "job_id": job_id}

    def set_workspace(self, path: str | Path) -> dict[str, Any]:
        workspace = Path(path).expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")
        current = self._agent_for_session()
        if current.active_jobs:
            raise ValueError("wait for this conversation agent to finish before changing its workspace")
        self.workspace = workspace
        update_desktop_settings(workspace=str(workspace))
        grants = set(self.tool_context.session_grants)
        self.tool_context = self._make_context()
        self.tool_context.session_grants = grants
        self.session.workspace = str(workspace)
        self.command_context = create_command_context(
            workspace_root=self.workspace,
            conversation=self.session.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history_log,
        )
        current.workspace = workspace
        current.tool_context = self.tool_context
        current.command_context = self.command_context
        current.session = self.session
        return self.status()

    def set_projects_dir(self, path: str | Path) -> dict[str, Any]:
        projects_dir = Path(path).expanduser().resolve()
        projects_dir.mkdir(parents=True, exist_ok=True)
        if not projects_dir.is_dir():
            raise ValueError(f"project download location is not a directory: {projects_dir}")
        self.projects_dir = projects_dir
        self._artifact_dir_override = None
        update_desktop_settings(projects_dir=str(projects_dir))
        return {"projects_dir": str(projects_dir), "artifacts": self.list_artifacts()}

    @property
    def artifacts_dir(self) -> Path:
        return self._artifact_dir_override or (self.projects_dir / "Jonathan Ai Downloads")

    def _fallback_artifacts_dir(self) -> Path:
        """Keep generated work downloadable if a selected drive becomes unavailable."""
        self._artifact_fallback_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_dir_override = self._artifact_fallback_dir
        return self._artifact_fallback_dir

    def list_artifacts(self) -> list[dict[str, Any]]:
        root = self.artifacts_dir
        if not root.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in root.iterdir():
            if not path.is_file():
                continue
            stat = path.stat()
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            is_image = media_type.startswith("image/")
            rows.append({
                "id": path.name,
                "name": path.name,
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "download_url": f"/api/artifacts/download?name={path.name}",
                "view_url": f"/api/artifacts/view?name={path.name}" if is_image else "",
                "media_type": media_type,
                "is_image": is_image,
            })
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return rows[:30]

    def resolve_artifact(self, name: str) -> Path:
        root = self.artifacts_dir.resolve()
        target = (root / Path(name).name).resolve()
        if target.parent != root or not target.is_file():
            raise ValueError("artifact not found")
        return target

    def _publish_artifact(self, source: str | Path, preferred_name: str | None = None) -> dict[str, Any]:
        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"generated file does not exist: {path}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        raw_name = preferred_name or path.name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-.") or "jonathan-artifact"
        if path.is_dir() and not safe_name.lower().endswith(".zip"):
            safe_name += ".zip"
        elif path.is_file():
            suffix = path.suffix
            if suffix and not safe_name.lower().endswith(suffix.lower()):
                safe_name += suffix

        def publish_into(root: Path) -> Path:
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"{stamp}-{safe_name}"
            if path.is_dir():
                with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for current, dirs, names in os.walk(path):
                        dirs[:] = [name for name in dirs if name not in {".git", ".venv", "node_modules", "__pycache__"}]
                        for name in names:
                            item = Path(current) / name
                            archive.write(item, item.relative_to(path).as_posix())
            else:
                shutil.copy2(path, target)
            return target

        try:
            target = publish_into(self.artifacts_dir)
        except PermissionError:
            # Removable/network folders and corporate-controlled Downloads can
            # become read-only after selection. The generation itself should
            # still succeed, so publish to Jonathan's private durable store.
            target = publish_into(self._fallback_artifacts_dir())
        return next(row for row in self.list_artifacts() if row["name"] == target.name)

    def _publish_session_artifact(
        self,
        session_id: str,
        source: str | Path,
        preferred_name: str | None = None,
    ) -> dict[str, Any]:
        artifact = self._publish_artifact(source, preferred_name)
        instance = self._instances.get(session_id)
        if instance is not None:
            instance.session.record_artifact(artifact)
        return artifact

    def package_workspace(self, session_id: str | None = None) -> dict[str, Any]:
        root = (self._agent_for_session(session_id).workspace if session_id else self.workspace).resolve()
        if not root.is_dir():
            raise ValueError("workspace is not available")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-.") or "jonathan-project"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Prefer a built, installable output when the project already produced one.
        distributable_suffixes = {".exe", ".msi", ".apk", ".dmg", ".deb", ".rpm", ".whl"}
        candidates: list[Path] = []
        for folder in ("dist", "build", "release", "packaging"):
            base = root / folder
            if base.is_dir():
                candidates.extend(
                    path for path in base.rglob("*")
                    if path.is_file() and path.suffix.lower() in distributable_suffixes
                )
        if candidates:
            source = max(candidates, key=lambda path: path.stat().st_mtime)
            target = self.artifacts_dir / f"{safe_name}-{stamp}{source.suffix.lower()}"
            shutil.copy2(source, target)
        else:
            target = self.artifacts_dir / f"{safe_name}-{stamp}.zip"
            ignored_dirs = {
                ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
                ".pytest_cache", ".mypy_cache", ".ruff_cache", "Jonathan Ai Downloads",
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for current, dirs, names in os.walk(root):
                    dirs[:] = [name for name in dirs if name not in ignored_dirs]
                    current_path = Path(current)
                    for name in names:
                        path = current_path / name
                        if path.stat().st_size <= 250 * 1024 * 1024:
                            archive.write(path, path.relative_to(root).as_posix())
        artifact = self.list_artifacts()[0]
        return {"ok": True, "artifact": artifact, "artifacts": self.list_artifacts()}

    def preview_info(self) -> dict[str, Any]:
        root = self.workspace.resolve()
        ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
        files: list[str] = []
        try:
            for current, dirs, names in os.walk(root):
                dirs[:] = [name for name in dirs if name not in ignored]
                current_path = Path(current)
                for name in names:
                    files.append((current_path / name).relative_to(root).as_posix())
                    if len(files) >= 250:
                        break
                if len(files) >= 250:
                    break
        except OSError:
            pass
        entry = next((name for name in ("dist/index.html", "build/index.html", "index.html", "public/index.html") if (root / name).is_file()), "")
        return {
            "workspace": str(root),
            "files": files,
            "entry": entry,
            "entry_url": f"/preview/{entry}" if entry else "",
        }

    def resolve_preview_path(self, relative: str) -> Path:
        root = self.workspace.resolve()
        target = (root / relative.lstrip("/\\")).resolve()
        if target != root and root not in target.parents:
            raise ValueError("preview path is outside the workspace")
        if not target.is_file():
            raise ValueError("preview file not found")
        return target

    def list_sessions(self) -> list[dict[str, Any]]:
        hidden = set(get_desktop_settings().get("hidden_session_ids") or [])
        active = {job.session_id for job in self._jobs.values() if not job.done}
        return [
            {**row, "agent_state": "working" if row.get("session_id") in active else "idle"}
            for row in Session.list_sessions()
            if row.get("session_id") not in hidden
        ]

    def search_conversations(self, query: str, limit: int = 30) -> dict[str, Any]:
        return search_history(query, limit=limit)

    def doctor(self, *, repair: bool = False) -> dict[str, Any]:
        return run_doctor(repair=repair)

    def list_agent_profiles(self) -> list[dict[str, Any]]:
        summaries = {row["session_id"]: row for row in Session.list_sessions()}
        active = {job.session_id for job in self._jobs.values() if not job.done}
        rows = []
        for agent in list_roster_agents():
            session_id = str(agent.get("canonical_session_id") or "")
            inbox = read_inbox(str(agent.get("id") or ""), limit=200)
            rows.append({
                **agent,
                "session": summaries.get(session_id),
                "state": "working" if session_id in active else "idle",
                "unread": sum(1 for item in inbox if not item.get("read_at")),
            })
        return rows

    def save_agent_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = get_roster_agent(str(payload.get("id") or "")) if payload.get("id") else None
        session_id = str((existing or {}).get("canonical_session_id") or "")
        session = Session.load(session_id) if session_id else None
        if session is None:
            session = Session.create(
                str(payload.get("provider") or self.provider_name),
                str(payload.get("model") or getattr(self.provider, "model", None) or self.session.model),
                workspace=str(payload.get("workspace") or self.workspace),
            )
            session.rename(str(payload.get("name") or "Agent"))
            session_id = session.session_id
        elif payload.get("name"):
            session.rename(str(payload["name"]))
        saved = save_roster_agent(payload, canonical_session_id=session_id)
        return {"agent": saved, "agents": self.list_agent_profiles()}

    def remove_agent_profile(self, agent_id: str) -> dict[str, Any]:
        result = remove_roster_agent(agent_id)
        return {**result, "agents": self.list_agent_profiles()}

    def open_agent_profile(self, agent_id: str) -> dict[str, Any]:
        agent = get_roster_agent(agent_id)
        if agent is None:
            raise ValueError("Agent profile not found.")
        loaded = self.load_session(str(agent.get("canonical_session_id") or ""))
        return {"agent": agent, **loaded}

    def run_agent_profile(self, agent_id: str, message: str, *, sender_session_id: str = "") -> dict[str, Any]:
        agent = get_roster_agent(agent_id)
        if agent is None:
            raise ValueError("Agent profile not found.")
        prompt = str(message or "").strip()
        if not prompt:
            raise ValueError("Message is empty.")
        sender = sender_session_id or self.session.session_id
        mail = send_roster_message(sender_session_id=sender, recipient_agent_id=agent_id, text=prompt)
        instructions = str(agent.get("instructions") or "").strip()
        framed = f"Your persistent role:\n{instructions}\n\nMessage from another Jonathan agent/session:\n{prompt}"
        job_id = self.start_chat(framed, session_id=str(agent.get("canonical_session_id") or ""))
        return {"job_id": job_id, "session_id": self._require_job(job_id).session_id, "message": mail}

    def agent_inbox(self, agent_id: str, *, mark_read: bool = False) -> dict[str, Any]:
        if get_roster_agent(agent_id) is None:
            raise ValueError("Agent profile not found.")
        return {"agent_id": agent_id, "messages": read_inbox(agent_id, mark_read=mark_read)}

    def _agent_roster_action(self, sender_session_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id") or "")
        if action == "list":
            return {"agents": self.list_agent_profiles()}
        if action == "inbox":
            return self.agent_inbox(agent_id, mark_read=bool(payload.get("mark_read")))
        if action == "send":
            return {"message": send_roster_message(sender_session_id=sender_session_id, recipient_agent_id=agent_id, text=str(payload.get("message") or ""))}
        if action == "run":
            return self.run_agent_profile(agent_id, str(payload.get("message") or ""), sender_session_id=sender_session_id)
        raise ValueError("Unsupported agent roster action.")

    def checkpoints(self, session_id: str | None = None) -> dict[str, Any]:
        target = str(session_id or self.session.session_id)
        return {"session_id": target, "checkpoints": list_checkpoints(target)}

    def restore_session_checkpoint(self, checkpoint_id: str = "", session_id: str | None = None) -> dict[str, Any]:
        agent = self._agent_for_session(session_id)
        result = restore_checkpoint(agent.session, checkpoint_id)
        if agent.session.session_id == self.session.session_id:
            self._bind_session(agent.session)
        return result

    def undo_session_turn(self, session_id: str | None = None) -> dict[str, Any]:
        agent = self._agent_for_session(session_id)
        result = undo_last_turn(agent.session)
        if agent.session.session_id == self.session.session_id:
            self._bind_session(agent.session)
        return result

    def retry_session_turn(self, session_id: str | None = None) -> dict[str, Any]:
        agent = self._agent_for_session(session_id)
        prompt = prepare_retry(agent.session)
        job_id = self.start_chat(prompt, session_id=agent.session.session_id)
        return {"job_id": job_id, "session_id": agent.session.session_id, "prompt": prompt}

    def instances_status(self) -> list[dict[str, Any]]:
        active_by_session: dict[str, list[ChatJob]] = {}
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if not job.done:
                active_by_session.setdefault(job.session_id, []).append(job)
        rows: list[dict[str, Any]] = []
        summaries = {row["session_id"]: row for row in Session.list_sessions()}
        for session_id, instance in self._instances.items():
            summary = summaries.get(session_id) or instance.session.to_summary()
            running = active_by_session.get(session_id, [])
            rows.append({
                "session_id": session_id,
                "title": summary.get("title") or session_id,
                "workspace": str(instance.workspace),
                "state": "working" if running else "idle",
                "jobs": [
                    {"job_id": job.job_id, "mode": job.mode, "started_at": job.started_at}
                    for job in running
                ],
                "message_count": summary.get("message_count", 0),
            })
        for session_id, summary in summaries.items():
            if session_id in self._instances:
                continue
            rows.append({
                "session_id": session_id,
                "title": summary.get("title") or session_id,
                "workspace": summary.get("workspace") or "",
                "state": "idle",
                "jobs": [],
                "message_count": summary.get("message_count", 0),
            })
        rows.sort(key=lambda row: (row["state"] != "working", row["title"].lower()))
        return rows

    def peek_session(self, session_id: str) -> dict[str, Any]:
        instance = self._agent_for_session(session_id)
        return {
            "session": instance.session.to_summary(),
            "messages": instance.session.export_messages(),
            "agent": next((row for row in self.instances_status() if row["session_id"] == session_id), {}),
        }

    def _read_instance(self, requester_id: str, action: str, target_id: str) -> dict[str, Any]:
        if action == "list":
            return {"requester_session_id": requester_id, "instances": self.instances_status()}
        snapshot = self.peek_session(target_id)
        messages = snapshot["messages"][-50:]
        for message in messages:
            content = str(message.get("content") or "")
            if len(content) > 12_000:
                message["content"] = content[:12_000] + "\n… [truncated]"
        return {
            "requester_session_id": requester_id,
            "session": snapshot["session"],
            "agent": snapshot["agent"],
            "messages": messages,
        }

    def new_session(self) -> dict[str, Any]:
        previous_id = self.session.session_id
        current = self._instances.get(previous_id)
        if current is None or not current.active_jobs:
            try:
                self.save_session()
            except Exception:
                pass
        model = getattr(self.provider, "model", None) or self.session.model
        created = Session.create(self.provider_name, model, workspace=str(self.workspace))
        created.save()
        self._bind_session(created)
        if created.session_id == previous_id:
            raise RuntimeError("New chat reused the previous session id")
        return {
            **created.to_summary(),
            "messages": [],
            "previous_session_id": previous_id,
        }

    def remove_session(self, session_id: str) -> dict[str, Any]:
        target_id = str(session_id or "").strip()
        if Session.load(target_id) is None:
            raise ValueError(f"session not found: {target_id}")
        settings = get_desktop_settings()
        hidden = list(settings.get("hidden_session_ids") or [])
        if target_id not in hidden:
            hidden.append(target_id)
        update_desktop_settings(hidden_session_ids=hidden)
        replacement = self.new_session() if target_id == self.session.session_id else None
        return {
            "removed": target_id,
            "retained_in_memory": True,
            "session": replacement or self.session.to_summary(),
            "messages": [] if replacement else self.session.export_messages(),
        }

    def load_session(self, session_id: str) -> dict[str, Any]:
        instance = self._agent_for_session(session_id)
        self._bind_session(instance.session)
        return {**instance.session.to_summary(), "messages": instance.session.export_messages()}

    def save_session(self) -> dict[str, Any]:
        self.session.workspace = str(self.workspace)
        self.session.save()
        self._bind_session(self.session)
        return self.session.to_summary()

    def export_current_messages(self) -> dict[str, Any]:
        return {
            "session": self.session.to_summary(),
            "messages": self.session.export_messages(),
        }

    def session_events(self, session_id: str | None = None, limit: int = 500) -> dict[str, Any]:
        target = str(session_id or self.session.session_id)
        if Session.load(target) is None and target != self.session.session_id:
            raise ValueError(f"session not found: {target}")
        return read_runtime_events(target, limit)

    def earned_autonomy_status(self, session_id: str | None = None) -> dict[str, Any]:
        target = str(session_id or self.session.session_id)
        if Session.load(target) is None and target != self.session.session_id:
            raise ValueError(f"session not found: {target}")
        return autonomy_status(target)

    def rename_session(self, session_id: str | None, title: str) -> dict[str, Any]:
        target_id = str(session_id or self.session.session_id or "").strip()
        if not target_id:
            raise ValueError("session_id is required")
        if target_id == self.session.session_id:
            self.session.workspace = str(self.workspace)
            self.session.rename(title)
            return self.session.to_summary()
        loaded = Session.load(target_id)
        if loaded is None:
            raise ValueError(f"session not found: {target_id}")
        loaded.rename(title)
        return loaded.to_summary()

    def list_skills(self) -> list[dict[str, Any]]:
        skills = list(get_all_skills(project_root=self.workspace))
        skills.sort(key=lambda s: s.name.lower())
        return [
            {
                "name": s.name,
                "description": s.description,
                "loaded_from": getattr(s, "loaded_from", ""),
                "user_invocable": getattr(s, "user_invocable", True),
            }
            for s in skills
        ]

    def skill_library_status(self) -> dict[str, Any]:
        ensure_learning_skill(source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        root = user_skill_library(source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        items: list[dict[str, Any]] = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            path = directory / "SKILL.md"
            if directory.name.startswith(".") or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            validation = validate_skill_source(directory.name, content)
            items.append({**validation, "path": str(path), "content": content})
        return {"path": str(root), "skills": items}

    def save_library_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip().lower().replace("_", "-").replace(" ", "-")
        content = str(payload.get("content") or "")
        if not content.strip():
            content = render_skill(
                name=name,
                description=str(payload.get("description") or "").strip(),
                instructions=str(payload.get("instructions") or "").strip(),
                version=str(payload.get("version") or "1.0.0"),
                when_to_use=str(payload.get("when_to_use") or ""),
                allowed_tools=[str(item) for item in payload.get("allowed_tools") or []],
                user_invocable=bool(payload.get("user_invocable", True)),
            )
        saved = save_user_skill(name, content, source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        record_action({
            "session_id": self.session.session_id,
            "tool": "SkillLibrary",
            "input": {"name": name},
            "permission": "direct user action",
            "status": "saved",
        })
        return {"saved": saved, **self.skill_library_status()}

    def archive_library_skill(self, name: str) -> dict[str, Any]:
        archived = archive_user_skill(name, source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        return {"archived": archived, **self.skill_library_status()}

    def open_library_folder(self) -> dict[str, Any]:
        path = open_skill_library(source_dir=resolve_source_dir() or Path(__file__).resolve().parents[2])
        return {"opened": True, "path": str(path)}

    def ecc_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Manage the audited ECC catalog without loading it all into prompts."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        source = resolve_source_dir() or Path(__file__).resolve().parents[2]
        if action == "status":
            return ecc_status(source)
        if action == "sync":
            return ecc_sync(source)
        if action == "scan":
            return ecc_security_scan(ecc_cache_dir(source))
        if action == "import":
            skills = body.get("skills")
            agents = body.get("agents")
            enable = body.get("enable")
            result = ecc_import_catalog(
                source,
                skill_names=[str(item) for item in skills] if isinstance(skills, list) else None,
                agent_names=[str(item) for item in agents] if isinstance(agents, list) else None,
                enable_names=[str(item) for item in enable] if isinstance(enable, list) else None,
                allow_unsafe=bool(body.get("allow_unsafe", False)),
            )
            record_action({
                "session_id": self.session.session_id,
                "tool": "ECCIntegration",
                "input": {"action": "import", "skill_count": len(result.get("imported_skills") or []), "agent_count": len(result.get("imported_agents") or [])},
                "permission": "direct user action",
                "status": "imported",
            })
            return result
        if action in {"enable", "disable"}:
            names = body.get("skills") or body.get("names") or []
            if not isinstance(names, list) or not names:
                raise ValueError("Select at least one imported ECC skill.")
            return ecc_set_enabled([str(item) for item in names], action == "enable", source)
        if action == "memory_export":
            return memory_vault_export()
        if action == "memory_import":
            return memory_vault_import(str(body.get("path") or ""))
        if action == "learning_status":
            return learning_status(self.workspace)
        if action == "analyze_git":
            return analyze_git_history(self.workspace, int(body.get("commits") or 200))
        if action == "activate_draft":
            draft = analyze_git_history(self.workspace, int(body.get("commits") or 200)) if not body.get("content") else {
                "name": str(body.get("name") or ""), "content": str(body.get("content") or "")
            }
            saved = save_user_skill(str(draft["name"]), str(draft["content"]), source_dir=source)
            return {"ok": True, "saved": saved, "learning": learning_status(self.workspace), **self.skill_library_status()}
        if action == "agent_profile":
            name = str(body.get("name") or "").strip().lower()
            available = {str(item.get("name")): item for item in ecc_catalog(source).get("agents") or []}
            item = available.get(name)
            if not item:
                raise ValueError("ECC agent template was not found. Synchronize the catalog first.")
            content = Path(str(item["path"])).read_text(encoding="utf-8")
            parsed = parse_frontmatter(content)
            title = name.replace("-", " ").title()
            return self.save_agent_profile({
                "name": title,
                "workspace": str(self.workspace),
                "instructions": parsed.body.strip(),
                "source": "ecc",
                "source_revision": ecc_status(source).get("revision") or "",
            })
        raise ValueError(f"Unsupported ECC action: {action}")

    def kronos_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Manage local, research-only Kronos OHLCV forecasting."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        if action == "status":
            return self.kronos.status()
        if action in {"install", "sync", "repair"}:
            result = self.kronos.install() if action != "sync" else self.kronos.sync()
            record_action({"session_id": self.session.session_id, "tool": "KronosForecast",
                           "input": {"action": action}, "permission": "direct user action", "status": "ready"})
            return result
        if action == "forecast":
            agent = self._agent_for_session(str(body.get("session_id") or "") or None)
            if not body.get("input_csv"):
                raise ValueError("Select an OHLCV CSV first.")
            source = agent.tool_context.ensure_allowed_path(str(body["input_csv"]))
            target = agent.tool_context.ensure_allowed_path(str(body.get("output_csv") or f"finance/kronos-{source.stem}-forecast.csv"))
            result = self.kronos.forecast(source, target, model=str(body.get("model") or "mini"),
                                          pred_len=int(body.get("pred_len") or 24), lookback=int(body.get("lookback") or 400),
                                          sample_count=int(body.get("sample_count") or 1),
                                          temperature=float(body.get("temperature") or 1.0), top_p=float(body.get("top_p") or 0.9),
                                          timeout=int(body.get("timeout") or 1800))
            artifact = self._publish_artifact(target, target.name)
            agent.session.record_artifact(artifact, caption="Kronos research forecast")
            agent.session.save()
            record_action({"session_id": agent.session.session_id, "tool": "KronosForecast",
                           "input": {"action": action, "model": body.get("model") or "mini", "pred_len": body.get("pred_len") or 24},
                           "permission": "direct user action", "status": "forecasted"})
            return {**result, "artifact": artifact, "artifacts": [artifact]}
        raise ValueError(f"Unsupported Kronos action: {action}")

    def personal_finance_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Control the isolated AGPL personal-finance application."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        if action == "status": result = self.personal_finance.status()
        elif action == "sync": result = self.personal_finance.sync()
        elif action in {"install", "repair"}: result = self.personal_finance.install()
        elif action == "start": result = self.personal_finance.start()
        elif action == "stop": result = self.personal_finance.stop()
        elif action == "logs": result = self.personal_finance.logs(int(body.get("limit") or 200))
        else: raise ValueError(f"Unsupported personal finance action: {action}")
        if action != "status":
            record_action({"session_id": self.session.session_id, "tool": "PersonalFinanceVault",
                           "input": {"action": action}, "permission": "direct user action", "status": "complete"})
        return result

    def code_memory_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the isolated local code graph without installing Claude hooks."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        agent = self._agent_for_session(str(body.get("session_id") or "") or None)
        result = self.code_memory.execute(
            action,
            workspace=agent.tool_context.workspace_root,
            query=str(body.get("query") or ""),
            target=str(body.get("target") or ""),
            mode=str(body.get("mode") or "text"),
            force=bool(body.get("force")),
            limit=int(body.get("limit") or 100),
        )
        if action not in {"status", "search", "usages", "explain", "path"}:
            record_action({"session_id": agent.session.session_id, "tool": "CodeMemory",
                           "input": {"action": action}, "permission": "direct user action", "status": "complete"})
        return result

    def procoder_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run an explicitly selected, report-first engineering quality controller."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        agent = self._agent_for_session(str(body.get("session_id") or "") or None)
        result = self.procoder.execute(action, workspace=agent.tool_context.workspace_root,
                                       argument=str(body.get("argument") or ""), deep=bool(body.get("deep")),
                                       coverage=bool(body.get("coverage")), timeout=int(body.get("timeout") or 1800))
        if action not in {"status", "doctor"}:
            record_action({"session_id": agent.session.session_id, "tool": "Procoder",
                           "input": {"action": action}, "permission": "direct user action", "status": "complete"})
        return result

    def drawai_integration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create editable SVG/PPTX assets from an uploaded raster image."""
        body = dict(payload or {})
        action = str(body.get("action") or "status").strip().lower()
        agent = self._agent_for_session(str(body.get("session_id") or "") or None)
        if action == "status": result = self.drawai.status()
        elif action == "sync": result = self.drawai.sync()
        elif action in {"install", "repair"}: result = self.drawai.install(models=True, device=str(body.get("device") or "cpu"))
        elif action == "convert":
            if not body.get("image"): raise ValueError("Select an uploaded raster image first.")
            source = agent.tool_context.ensure_allowed_path(str(body["image"]))
            target = agent.tool_context.ensure_allowed_path(str(body.get("output_dir") or f"media/editable-{source.stem}"))
            result = self.drawai.convert(source, target, device=str(body.get("device") or "cpu"), timeout=int(body.get("timeout") or 7200))
            published = [self._publish_artifact(Path(path), Path(path).name) for path in result["artifacts"]]
            for artifact in published: agent.session.record_artifact(artifact, caption="Editable graphics output")
            agent.session.save()
            result["artifacts"] = published
        else: raise ValueError(f"Unsupported DrawAI action: {action}")
        if action != "status":
            record_action({"session_id": agent.session.session_id, "tool": "EditableGraphics",
                           "input": {"action": action}, "permission": "direct user action", "status": "complete"})
        return result

    def character_studio(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body=dict(payload or {}); agent=self._agent_for_session(str(body.get("session_id") or "") or None)
        target=agent.tool_context.ensure_allowed_path(str(body.get("output_dir") or "media/characters"))
        result=generate_character(target,seed=str(body.get("seed") or "jonathan"),name=str(body.get("name") or ""),species=str(body.get("species") or "auto"),medium=str(body.get("medium") or "ink"))
        published=[self._publish_artifact(Path(path),Path(path).name) for path in result["artifacts"]]
        for artifact in published: agent.session.record_artifact(artifact,caption="Procedural character asset")
        agent.session.save(); result["artifacts"]=published
        record_action({"session_id":agent.session.session_id,"tool":"CharacterStudio","input":{"seed":body.get("seed"),"species":body.get("species")},"permission":"direct user action","status":"complete"})
        return result

    def list_commands(self) -> list[dict[str, Any]]:
        builtins = [
            {"name": "/", "description": "Show commands and skills"},
            {"name": "/help", "description": "Show help"},
            {"name": "/clear", "description": "Clear conversation"},
            {"name": "/new", "description": "Start a brand-new empty session"},
            {"name": "/save", "description": "Save current session"},
            {"name": "/load", "description": "Load a session by id"},
            {"name": "/tools", "description": "List available tools"},
            {"name": "/skills", "description": "List available skills"},
            {"name": "/image", "description": "Generate an image locally and show it in this conversation"},
        ]
        seen = {item["name"] for item in builtins}
        for cmd in self.command_registry.list_commands():
            name = f"/{cmd.name}"
            if name in seen:
                continue
            builtins.append({"name": name, "description": cmd.description})
            seen.add(name)
        for skill in self.list_skills():
            name = f"/{skill['name']}"
            if name in seen:
                continue
            builtins.append({"name": name, "description": skill["description"], "kind": "skill"})
            seen.add(name)
        return builtins

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "is_destructive": spec.is_destructive,
                "is_read_only": spec.is_read_only,
            }
            for spec in self.tool_registry.list_specs()
        ]

    def _stage_attachments(self, agent: AgentInstance, attachments: list[Attachment]) -> list[Attachment]:
        """Copy explicitly selected files into a per-session tool-readable staging folder."""
        if not attachments:
            return []
        target_dir = (Path.home() / ".clawd" / "attachments" / agent.session.session_id).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        roots = list(agent.tool_context.permission_context.additional_working_directories)
        if target_dir not in roots:
            roots.append(target_dir)
            current = agent.tool_context.permission_context
            agent.tool_context.permission_context = ToolPermissionContext.from_iterables(
                current.deny_names,
                current.deny_prefixes,
                workspace_root=agent.tool_context.workspace_root,
                additional_working_directories=roots,
                allow_docs=current.allow_docs,
                full_system_access=current.full_system_access,
            )
        staged: list[Attachment] = []
        for item in attachments:
            if item.data:
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", item.name).strip(".-") or "attachment"
                destination = target_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
                destination.write_bytes(item.data)
                parsed = attach_path(destination, kind="screenshot" if item.kind == "screenshot" else "file")
                staged.append(replace(
                    parsed,
                    name=item.name,
                    media_type=item.media_type or parsed.media_type,
                    is_image=item.is_image or parsed.is_image,
                ))
                continue
            if not item.path or item.omitted and not item.is_image:
                staged.append(item)
                continue
            source = Path(item.path).expanduser().resolve()
            try:
                source.relative_to(target_dir)
                staged.append(item)
                continue
            except ValueError:
                pass
            if not source.is_file():
                staged.append(replace(item, omitted=True, reason="file not found"))
                continue
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip(".-") or "attachment"
            destination = target_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
            shutil.copy2(source, destination)
            staged.append(replace(item, path=str(destination), name=source.name))
        return staged

    def attach_files(self, payload: list[dict[str, Any]] | None, session_id: str | None = None) -> list[dict[str, Any]]:
        agent = self._agent_for_session(session_id)
        rows: list[dict[str, Any]] = []
        for item in self._stage_attachments(agent, attachments_from_payload(payload)):
            row = item.to_dict()
            if item.path and Path(item.path).is_file():
                stored_name = Path(item.path).name
                query = f"session_id={agent.session.session_id}&name={stored_name}"
                row["download_url"] = f"/api/attachments/download?{query}"
                if item.is_image:
                    row["preview_url"] = f"/api/attachments/view?{query}"
            rows.append(row)
        return rows

    def resolve_attachment(self, session_id: str, name: str) -> Path:
        safe_session = re.sub(r"[^A-Za-z0-9_-]+", "", str(session_id or ""))
        if not safe_session:
            raise ValueError("attachment session is required")
        root = (Path.home() / ".clawd" / "attachments" / safe_session).resolve()
        target = (root / Path(name).name).resolve()
        if target.parent != root or not target.is_file():
            raise ValueError("attachment not found")
        return target

    def start_chat(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> str:
        agent = self._agent_for_session(session_id)
        job = ChatJob(job_id=uuid.uuid4().hex, session_id=agent.session.session_id, mode="chat")
        with self._lock:
            if agent.active_jobs:
                raise ValueError("this conversation agent is already working; open another conversation to run in parallel")
            self._jobs[job.job_id] = job
            agent.active_jobs.add(job.job_id)
        create_checkpoint(agent.session, reason="before-chat")
        parsed_attachments = self._stage_attachments(agent, attachments_from_payload(attachments))
        # Finish the deterministic setup error before returning. This avoids
        # leaving a pointless daemon thread racing shutdown/test cleanup when
        # no provider exists, while configured providers remain asynchronous.
        if self.provider is None and direct_image_request(text, parsed_attachments) is None:
            self._run_chat_job(job, agent, text, parsed_attachments)
            return job.job_id
        thread = threading.Thread(
            target=self._run_chat_job,
            args=(job, agent, text, parsed_attachments),
            daemon=True,
            name=f"clawd-chat-{job.job_id[:8]}",
        )
        thread.start()
        return job.job_id

    def start_multi_agent(self, text: str, *, session_id: str | None = None, mode: str = "balanced") -> str:
        agent = self._agent_for_session(session_id)
        job = ChatJob(job_id=uuid.uuid4().hex, session_id=agent.session.session_id, mode="workers")
        with self._lock:
            if agent.active_jobs:
                raise ValueError("this conversation agent is already working; open another conversation to run in parallel")
            self._jobs[job.job_id] = job
            agent.active_jobs.add(job.job_id)
        create_checkpoint(agent.session, reason="before-workers")
        thread = threading.Thread(
            target=self._run_multi_agent_job,
            args=(job, agent, text, mode),
            daemon=True,
            name=f"clawd-workers-{job.job_id[:8]}",
        )
        thread.start()
        return job.job_id

    def _run_multi_agent_job(self, job: ChatJob, agent: AgentInstance, text: str, mode: str = "balanced") -> None:
        from src.agent.multi_agent import run_internal_workers

        try:
            if self.provider is None:
                self._finish(job, {
                    "type": "error",
                    "error": "Connect a provider in settings (Hugging Face, Local LLM, or a cloud key).",
                    "needs_setup": self.needs_setup(),
                })
                return
            goal = (text or "").strip()
            if not goal:
                self._finish(job, {"type": "error", "error": "Message is empty."})
                return
            agent.session.conversation.add_user_message(goal)
            self._emit(job, {"type": "user", "text": goal})
            self._emit(job, {"type": "workers_started", "goal": goal, "mode": mode})
            result = run_internal_workers(
                provider=self.provider,
                goal=goal,
                parent_session_id=agent.session.session_id,
                mode=mode,
            )
            for worker in result.get("workers") or []:
                self._emit(job, {"type": "worker", **worker})
            answer = str(result.get("answer") or result.get("combined") or "")
            agent.session.conversation.add_assistant_message(answer)
            agent.session.record_usage(result.get("usage") or {})
            agent.session.save()
            self._finish(job, {
                "type": "done",
                "text": answer,
                "workers": result.get("workers") or [],
                "worker_mode": result.get("mode") or mode,
                "review": result.get("review") or "",
                "session": agent.session.to_summary(),
            })
        except Exception as exc:
            self._finish(job, {"type": "error", "error": str(exc)})

    def drain_events(self, job_id: str, after: int = 0) -> tuple[list[dict[str, Any]], bool]:
        job = self._require_job(job_id)
        with job.condition:
            events = list(job.events[after:])
            return events, job.done

    def wait_events(self, job_id: str, after: int = 0, timeout: float = 1.0) -> tuple[list[dict[str, Any]], bool]:
        job = self._require_job(job_id)
        with job.condition:
            if after >= len(job.events) and not job.done:
                job.condition.wait(timeout=timeout)
            return list(job.events[after:]), job.done

    def pending_permissions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "request_id": req.request_id,
                    "session_id": req.session_id,
                    "tool_name": req.tool_name,
                    "message": req.message,
                    "suggestion": req.suggestion,
                }
                for req in self._permissions.values()
                if not req.event.is_set()
            ]

    def resolve_permission(self, request_id: str, decision: str) -> dict[str, Any]:
        with self._lock:
            req = self._permissions.get(request_id)
        if req is None:
            raise ValueError(f"unknown permission request: {request_id}")
        choice = (decision or "").strip().lower()
        if choice in {"allow", "yes", "y", "once"}:
            req.allowed = True
        elif choice in {"always", "always_allow", "session"}:
            req.allowed = True
            req.always = True
        elif choice in {"allow_docs", "enable_docs"}:
            req.allowed = True
            req.enable_docs = True
        elif choice in {"deny", "no", "n"}:
            req.allowed = False
        else:
            raise ValueError(f"unknown permission decision: {decision}")
        req.event.set()
        try:
            append_runtime_event(req.session_id, "permission_decision", {
                "request_id": request_id, "tool_name": req.tool_name, "decision": choice, "allowed": req.allowed,
            }, workspace=str(self.workspace))
        except Exception:
            pass
        try:
            record_permission_evidence(req.session_id, req.tool_name, choice, request_id)
        except Exception:
            pass
        return {"request_id": request_id, "decision": choice, "allowed": req.allowed}

    def cancel_job(self, job_id: str) -> None:
        job = self._require_job(job_id)
        job.cancelled = True
        try:
            append_runtime_event(job.session_id, "job_cancelled", {"mode": job.mode}, job_id=job.job_id, workspace=str(self.workspace))
        except Exception:
            pass
        with self._lock:
            for req in self._permissions.values():
                if not req.event.is_set() and req.session_id == job.session_id:
                    req.allowed = False
                    req.event.set()

    def _require_job(self, job_id: str) -> ChatJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"unknown job: {job_id}")
        return job

    def _emit(self, job: ChatJob, event: dict[str, Any]) -> None:
        event.setdefault("job_id", job.job_id)
        event.setdefault("session_id", job.session_id)
        with job.condition:
            job.events.append(event)
            job.condition.notify_all()
        if event.get("type") != "token":
            try:
                append_runtime_event(job.session_id, str(event.get("type") or "event"),
                                     {key: value for key, value in event.items() if key not in {"job_id", "session_id"}},
                                     job_id=job.job_id, workspace=str(self._instances.get(job.session_id).workspace if self._instances.get(job.session_id) else self.workspace))
            except Exception:
                # The live turn remains authoritative if an OS/filesystem issue
                # temporarily prevents optional recovery evidence from writing.
                pass

    def _finish(self, job: ChatJob, event: dict[str, Any]) -> None:
        self._emit(job, event)
        with job.condition:
            job.done = True
            job.condition.notify_all()
        with self._lock:
            instance = self._instances.get(job.session_id)
            if instance is not None:
                instance.active_jobs.discard(job.job_id)

    def _handle_permission_request(
        self,
        session_id: str,
        tool_context: ToolContext,
        tool_name: str,
        message: str,
        suggestion: str | None,
    ) -> tuple[bool, bool]:
        req = PermissionRequest(
            request_id=uuid.uuid4().hex,
            tool_name=tool_name,
            message=message,
            suggestion=suggestion,
            session_id=session_id,
        )
        with self._lock:
            self._permissions[req.request_id] = req
            jobs = list(self._jobs.values())
        payload = {
            "type": "permission_request",
            "request_id": req.request_id,
            "tool_name": tool_name,
            "message": message,
            "suggestion": suggestion,
        }
        for job in jobs:
            if not job.done and job.session_id == session_id:
                self._emit(job, payload)
        if not req.event.wait(timeout=self.permission_timeout_s):
            return False, False
        if req.always:
            tool_context.session_grants.add(tool_name.lower())
        if req.enable_docs:
            tool_context.permission_context.allow_docs = True
        return req.allowed, False

    def _ask_user_questions(self, questions: list[dict]) -> dict[str, str]:
        # Desktop does not yet host a multi-question widget; return first option.
        answers: dict[str, str] = {}
        for q in questions:
            question_text = str(q.get("question", "")).strip()
            options = q.get("options") or []
            if not question_text or not isinstance(options, list) or not options:
                continue
            label = str((options[0] or {}).get("label", "")).strip()
            answers[question_text] = label
        return answers

    @staticmethod
    def _record_user_turn(agent: AgentInstance, visible_text: str, provider_text: str,
                          attachments: list[Attachment]) -> None:
        image_blocks = []
        attachment_blocks = []
        for attachment in attachments:
            if attachment.is_image and not attachment.omitted:
                image_blocks.append(ImageContentBlock(source=image_source(attachment)))
            elif attachment.path and Path(attachment.path).is_file():
                stored_name = Path(attachment.path).name
                query = f"session_id={agent.session.session_id}&name={stored_name}"
                attachment_blocks.append(AttachmentContentBlock(
                    name=attachment.name,
                    download_url=f"/api/attachments/download?{query}",
                    media_type=attachment.media_type or "application/octet-stream",
                    size=attachment.size,
                ))
        if attachments:
            agent.session.conversation.add_user_message([
                TextContentBlock(text=provider_text, display_text=visible_text.strip()),
                *image_blocks,
                *attachment_blocks,
            ])
        else:
            agent.session.conversation.add_user_message(provider_text)

    def _run_direct_image_job(
        self,
        job: ChatJob,
        agent: AgentInstance,
        text: str,
        attachments: list[Attachment],
        action: str,
        prompt: str,
    ) -> None:
        """Execute an explicit image prompt locally without provider routing or credentials."""
        rendered = render_attachments(attachments)
        provider_text = f"{text.strip()}\n\n{rendered}" if rendered else text.strip()
        self._record_user_turn(agent, text, provider_text, attachments)
        self._emit(job, {"type": "user", "text": text.strip(), "attachments": [a.to_dict() for a in attachments]})

        lower = prompt.lower()
        if any(word in lower for word in ("landscape", "wide", "widescreen", "banner")):
            width, height = 768, 512
        elif any(word in lower for word in ("portrait", "vertical", "phone wallpaper")):
            width, height = 512, 768
        else:
            width = height = 512
        tool_input: dict[str, Any] = {
            "action": action,
            "engine": "local",
            "prompt": prompt,
            "performance": "Speed" if action == "ai_edit" else "Extreme Speed",
            "width": width,
            "height": height,
            "output": f"media/jonathan-image-{job.job_id[:12]}.png",
        }
        if action == "ai_edit":
            source = next((item.path for item in attachments if item.is_image and item.path and not item.omitted), "")
            if not source:
                raise ValueError("Attach an image before asking Jonathan to edit it.")
            tool_input["source"] = source

        tool_use_id = f"direct-image-{job.job_id}"
        self._emit(job, {
            "type": "tool_use",
            "tool_name": "ImageStudio",
            "tool_input": tool_input,
            "tool_use_id": tool_use_id,
            "summary": "Generating image locally" if action == "generate" else "Editing uploaded image locally",
        })
        record_action({
            "session_id": agent.session.session_id,
            "tool": "ImageStudio",
            "input": tool_input,
            "permission": "explicit prompt image request",
            "status": "started",
        })
        try:
            result = ImageStudioTool().run(tool_input, agent.tool_context)
        except Exception:
            record_action({
                "session_id": agent.session.session_id,
                "tool": "ImageStudio",
                "input": {"action": action},
                "permission": "explicit prompt image request",
                "status": "failed",
            })
            agent.session.save()
            raise

        output = result.output if isinstance(result.output, dict) else {"result": result.output}
        artifacts = output.get("artifacts") or ([output["artifact"]] if output.get("artifact") else [])
        for artifact in artifacts:
            agent.session.record_artifact(artifact, caption="Generated image" if action == "generate" else "Edited image")
        response = (
            "Generated the image locally. It is shown below and ready to download."
            if action == "generate"
            else "Edited the uploaded image locally. The result is shown below and ready to download."
        )
        agent.session.conversation.add_assistant_message(response)
        agent.session.save()
        record_action({
            "session_id": agent.session.session_id,
            "tool": "ImageStudio",
            "input": {"action": action},
            "permission": "explicit prompt image request",
            "status": "complete",
        })
        self._emit(job, {
            "type": "tool_result",
            "tool_name": "ImageStudio",
            "tool_output": output,
            "tool_use_id": tool_use_id,
            "is_error": bool(result.is_error),
            "summary": "Image ready to preview and download",
        })
        self._finish(job, {
            "type": "done",
            "text": response,
            "usage": dict(agent.session.token_usage),
            "turn_usage": empty_token_usage(),
            "num_turns": 1,
            "session": agent.session.to_summary(),
        })

    def _run_chat_job(self, job: ChatJob, agent: AgentInstance, text: str, attachments: list[Attachment]) -> None:
        try:
            self._emit(job, {"type": "job_started", "text": text})
            image_request = direct_image_request(text, attachments)
            if image_request is not None:
                self._run_direct_image_job(job, agent, text, attachments, *image_request)
                return
            if self.provider is None:
                self._finish(job, {
                    "type": "error",
                    "error": "Connect a provider in settings (Hugging Face, Local LLM, or a cloud key).",
                    "needs_setup": self.needs_setup(),
                })
                return

            combined = text.strip()
            rendered = render_attachments(attachments)
            if rendered:
                combined = f"{combined}\n\n{rendered}" if combined else rendered
                image_briefs: list[str] = []
                wants_ocr = bool(re.search(r"(?i)\b(?:ocr|read|scan|text|word|letter|caption|sign)\b", text or ""))
                for attachment in attachments:
                    if not attachment.is_image or not attachment.path or attachment.omitted:
                        continue
                    self._emit(job, {"type": "attachment_scan", "name": attachment.name, "ocr": wants_ocr})
                    try:
                        from src.image_vision import compact_image_brief, inspect_image

                        scan = inspect_image(attachment.path, run_ocr=wants_ocr)
                        image_briefs.append(f"{attachment.name}: {compact_image_brief(scan)}")
                    except Exception as exc:
                        image_briefs.append(f"{attachment.name}: local pixel scan unavailable ({exc})")
                if image_briefs:
                    combined += "\n\n[Fast local image scan]\n" + "\n".join(image_briefs)
                combined += (
                    "\n\n[Attachment handling instruction]\n"
                    "Focus on the user's attached files and request. Inspect the supplied image pixels or extracted "
                    "document content directly. Use VisionAnalyze for detailed color, shape, object, QR, or OCR evidence. "
                    "Do not claim an attachment is unavailable. For an image change, use "
                    "ImageStudio with the exact staged source path above; use add_text/remove_text for precise pixel-"
                    "preserving changes and ai_edit for prompt-driven variations. For attached audio or a voice recording, "
                    "use SpeechStudio transcribe with the exact staged path. Return generated files as artifacts."
                )
            if not combined.strip():
                self._finish(job, {"type": "error", "error": "Message is empty."})
                return

            if combined.lstrip().startswith("/"):
                handled = self._handle_slash(job, agent, combined.strip())
                if handled:
                    return

            self._record_user_turn(agent, text, combined, attachments)
            self._emit(job, {"type": "user", "text": combined, "attachments": [a.to_dict() for a in attachments]})

            def on_event(ev: ToolEvent) -> None:
                if ev.kind == "tool_use":
                    self._emit(job, {
                        "type": "tool_use",
                        "tool_name": ev.tool_name,
                        "tool_input": ev.tool_input,
                        "tool_use_id": ev.tool_use_id,
                        "summary": summarize_tool_use(ev.tool_name, ev.tool_input or {}),
                    })
                elif ev.kind == "tool_result":
                    self._emit(job, {
                        "type": "tool_result",
                        "tool_name": ev.tool_name,
                        "tool_output": ev.tool_output,
                        "tool_use_id": ev.tool_use_id,
                        "is_error": ev.is_error,
                        "summary": summarize_tool_result(ev.tool_name, ev.tool_output),
                    })
                elif ev.kind == "tool_error":
                    self._emit(job, {
                        "type": "tool_error",
                        "tool_name": ev.tool_name,
                        "error": ev.error,
                        "tool_use_id": ev.tool_use_id,
                    })

            def on_text_chunk(chunk: str) -> None:
                if chunk:
                    self._emit(job, {"type": "token", "text": chunk})

            try:
                lightweight = False
                selected_tool_names = None
                if self.provider_name == "local":
                    lightweight, routed_tools = local_chat_route(combined, attachments)
                    selected_tool_names = None if lightweight else routed_tools
                result = run_agent_loop(
                    conversation=agent.session.conversation,
                    provider=self.provider,
                    tool_registry=self.tool_registry,
                    tool_context=agent.tool_context,
                    max_turns=1 if lightweight else (12 if self.provider_name == "local" else 20),
                    stream=self.stream,
                    verbose=False,
                    on_event=on_event,
                    on_text_chunk=on_text_chunk,
                    lightweight=lightweight,
                    selected_tool_names=selected_tool_names,
                )
            except Exception as loop_exc:
                from src.tool_system.schema_sanitize import is_input_schema_type_error

                if not is_input_schema_type_error(loop_exc):
                    raise
                result = run_agent_loop(
                    conversation=agent.session.conversation,
                    provider=self.provider,
                    tool_registry=self.tool_registry,
                    tool_context=agent.tool_context,
                    max_turns=20,
                    stream=self.stream,
                    verbose=False,
                    on_event=on_event,
                    on_text_chunk=on_text_chunk,
                    omit_tools=True,
                )
            usage = agent.session.record_usage(result.usage)
            if agent.session.conversation.messages:
                agent.session.save()
            try:
                remember_turn(
                    session_id=agent.session.session_id,
                    title=agent.session.display_title(),
                    user_text=combined,
                    assistant_text=result.response_text or "",
                )
            except Exception:
                pass
            try:
                record_observation(
                    agent.workspace,
                    session_id=agent.session.session_id,
                    request=text,
                    response=result.response_text or "",
                    tool_events=[dict(event) for event in job.events if event.get("type") in {"tool_use", "tool_result", "tool_error"}],
                    successful=True,
                )
            except Exception:
                # Learning is optional evidence capture and must never delay or
                # break the first visible answer in a conversation.
                pass
            self._finish(job, {
                "type": "done",
                "text": result.response_text,
                "usage": usage,
                "turn_usage": result.usage,
                "num_turns": result.num_turns,
                "session": agent.session.to_summary(),
            })
        except Exception as exc:
            hint = provider_limit_hint(exc)
            self._finish(job, {
                "type": "error",
                "error": f"{exc}{hint}",
                "provider_limit": bool(hint),
            })

    def _handle_slash(self, job: ChatJob, agent: AgentInstance, raw: str) -> bool:
        if raw == "/":
            self._finish(job, {
                "type": "done",
                "text": self._format_palette(),
                "kind": "command",
            })
            return True

        parts = raw[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in {"help"}:
            self._finish(job, {"type": "done", "text": _HELP_TEXT, "kind": "command"})
            return True
        if cmd in {"new"}:
            if self.session.session_id == agent.session.session_id:
                created = self.new_session()
            else:
                model = getattr(self.provider, "model", None) or agent.session.model
                fresh = Session.create(self.provider_name, model, workspace=str(agent.workspace))
                fresh.save()
                self._create_instance(fresh, agent.workspace)
                created = {**fresh.to_summary(), "messages": [], "previous_session_id": agent.session.session_id}
            self._finish(job, {
                "type": "done",
                "text": "Started a new chat.",
                "kind": "command",
                "session": created,
                "messages": [],
            })
            return True
        if cmd in {"clear", "reset"}:
            agent.session.conversation.clear()
            agent.session.token_usage = empty_token_usage()
            if not agent.session.custom_title:
                agent.session.title = "New chat"
            agent.session.workspace = str(agent.workspace)
            agent.session.save()
            self._finish(job, {
                "type": "done",
                "text": "Conversation cleared.",
                "kind": "command",
                "session": agent.session.to_summary(),
                "messages": [],
            })
            return True
        if cmd == "save":
            agent.session.workspace = str(agent.workspace)
            agent.session.save()
            summary = agent.session.to_summary()
            self._finish(job, {"type": "done", "text": f"Session saved: {summary['session_id']}", "kind": "command"})
            return True
        if cmd == "load":
            if not args:
                self._finish(job, {"type": "error", "error": "Usage: /load <session-id>"})
                return True
            snapshot = self.peek_session(args.strip())
            summary = {**snapshot["session"], "messages": snapshot["messages"]}
            self._finish(job, {"type": "done", "text": f"Session loaded: {summary['session_id']}", "kind": "command", "session": summary})
            return True
        if cmd == "tools":
            names = ", ".join(spec["name"] for spec in self.list_tools())
            self._finish(job, {"type": "done", "text": f"Tools: {names}", "kind": "command"})
            return True
        if cmd == "skills":
            skills = self.list_skills()
            if not skills:
                text = "No skills found."
            else:
                text = "\n".join(f"/{s['name']} — {s['description']}" for s in skills)
            self._finish(job, {"type": "done", "text": text, "kind": "command"})
            return True
        if cmd == "tool":
            tool_parts = args.split(maxsplit=1)
            if not tool_parts:
                self._finish(job, {"type": "error", "error": "Usage: /tool <name> <json>"})
                return True
            import json
            payload: dict[str, Any] = {}
            if len(tool_parts) == 2:
                payload = json.loads(tool_parts[1])
            result = self.tool_registry.dispatch(ToolCall(name=tool_parts[0], input=payload), agent.tool_context)
            self._finish(job, {"type": "done", "text": json.dumps(result.output, indent=2, ensure_ascii=False), "kind": "command"})
            return True

        try:
            success, result_text, error = execute_command_sync(cmd, args, agent.command_context)
            if success:
                self._finish(job, {"type": "done", "text": result_text or "", "kind": "command"})
                return True
            if error and "unknown command" not in error.lower():
                self._finish(job, {"type": "error", "error": error})
                return True
        except Exception:
            pass

        if self._try_run_skill(job, agent, cmd, args):
            return True
        return False

    def _try_run_skill(self, job: ChatJob, agent: AgentInstance, skill_name: str, args: str) -> bool:
        try:
            result = self.tool_registry.dispatch(
                ToolCall(name="Skill", input={"skill": skill_name, "args": args}),
                agent.tool_context,
            )
        except Exception:
            return False
        payload = result.output if isinstance(result.output, dict) else {}
        if result.is_error or not payload.get("success"):
            return False
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return False
        self._emit(job, {"type": "skill", "name": payload.get("commandName", skill_name)})
        # Recurse into the normal agent path with the skill prompt.
        agent.session.conversation.add_user_message(prompt)
        result_loop = run_agent_loop(
            conversation=agent.session.conversation,
            provider=self.provider,
            tool_registry=self.tool_registry,
            tool_context=agent.tool_context,
            max_turns=20,
            stream=self.stream,
            verbose=False,
            on_event=lambda ev: self._emit(job, {
                "type": ev.kind,
                "tool_name": ev.tool_name,
                "tool_input": ev.tool_input,
                "tool_output": ev.tool_output,
                "tool_use_id": ev.tool_use_id,
                "is_error": ev.is_error,
                "error": ev.error,
            }),
            on_text_chunk=lambda chunk: self._emit(job, {"type": "token", "text": chunk}) if chunk else None,
        )
        usage = agent.session.record_usage(result_loop.usage)
        agent.session.save()
        self._finish(job, {
            "type": "done",
            "text": result_loop.response_text,
            "usage": usage,
            "turn_usage": result_loop.usage,
            "num_turns": result_loop.num_turns,
            "session": agent.session.to_summary(),
        })
        return True

    def _format_palette(self) -> str:
        lines = ["**Commands and skills**", ""]
        for item in self.list_commands():
            desc = item.get("description") or ""
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- `{item['name']}`{suffix}")
        return "\n".join(lines)


_HELP_TEXT = """**Jonathan Ai**

- `/` — list commands and skills
- `/help` — this help
- `/clear` — clear the current conversation (same session, saved empty)
- `/new` — start a brand-new empty session
- `/save` — persist this session to `~/.clawd/sessions`
- `/load <id>` — restore a saved session
- `/tools` — list tools
- `/skills` — list SKILL.md slash commands

Type a message to run the existing agent loop. Destructive and network tools
prompt for approval before they run.
"""
