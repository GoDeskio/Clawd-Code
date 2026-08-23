"""Desktop agent runtime — wraps the existing loop, sessions, and skills."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.agent import Session
from src.command_system import (
    CommandRegistry,
    create_command_context,
    execute_command_sync,
    register_builtin_commands,
)
from src.agent.memory import remember_turn
from src.config import (
    get_default_provider,
    get_desktop_settings,
    get_provider_config,
    has_configured_provider,
    is_provider_ready,
    provider_requires_key,
    public_config,
    set_api_key,
    set_default_provider,
    update_desktop_settings,
)
from src.providers.huggingface_connect import (
    cache_huggingface_model,
    list_huggingface_models,
    verify_huggingface_token,
)
from src.providers.local_endpoints import (
    assert_local_or_lan_url,
    list_local_models,
    normalize_openai_base,
    scan_local_endpoints,
)
from src.cost_tracker import CostTracker
from src.history import HistoryLog
from src.providers import PROVIDER_INFO, get_provider_class
from src.skills.loader import get_all_skills
from src.tool_system.agent_loop import ToolEvent, run_agent_loop, summarize_tool_result, summarize_tool_use
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.protocol import ToolCall
from src.connectors.agents import get_saved_agent, invoke_agent, list_agent_tools, test_agent_endpoint
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
    save_mcp_server,
    set_agent_enabled,
    set_mcp_enabled,
)
from src.install.record import read_install_record, resolve_source_dir
from src.install.source import default_source_dir
from src.update import Updater
from src.version import get_version

from .attachments import Attachment, attachments_from_payload, render_attachments


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


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class PermissionRequest:
    request_id: str
    tool_name: str
    message: str
    suggestion: str | None = None
    event: threading.Event = field(default_factory=threading.Event)
    allowed: bool = False
    always: bool = False
    enable_docs: bool = False


@dataclass
class ChatJob:
    job_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    done: bool = False
    cancelled: bool = False


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
        raw_workspace = workspace or settings.get("workspace") or Path.cwd()
        self.workspace = Path(raw_workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.stream = stream
        self.permission_timeout_s = permission_timeout_s
        self.provider_name = provider_name or get_default_provider()
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
        self._jobs: dict[str, ChatJob] = {}
        self._permissions: dict[str, PermissionRequest] = {}
        self._lock = threading.Lock()
        self.install_record = read_install_record()
        self.updater = Updater(resolve_source_dir() or Path.cwd())
        self._device: dict[str, Any] = {}
        try:
            load_hook_files()
        except Exception:
            pass
        self._try_init_provider()
        self._restore_session()
        if self.install_record:
            self._update_thread = threading.Thread(target=self._auto_update_on_launch, daemon=True, name="clawd-update")
            self._update_thread.start()

    def _make_context(self) -> ToolContext:
        ctx = ToolContext(workspace_root=self.workspace)
        ctx.gate_destructive_tools = True
        ctx.permission_handler = self._handle_permission_request
        ctx.ask_user = self._ask_user_questions
        ctx.mcp_clients = enabled_mcp_clients()
        ctx.session_id = getattr(self, "session", None).session_id if getattr(self, "session", None) else None
        return ctx

    def _bind_session(self, session: Session) -> None:
        self.session = session
        self.session.workspace = self.session.workspace or str(self.workspace)
        self.command_context.conversation = self.session.conversation
        self.tool_context.session_id = self.session.session_id
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
        self.tool_context.mcp_clients = enabled_mcp_clients()

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
        if self.session.provider != self.provider_name or self.session.model == "unconfigured":
            self.session.provider = self.provider_name
            self.session.model = self.provider.model

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
            "provider": self.provider_name,
            "model": getattr(self.provider, "model", None) or self.session.model,
            "session": self.session.to_summary(),
            "config": cfg,
            "notify_on_complete": get_desktop_settings().get("notify_on_complete", True),
            "install": self.install_info(),
            "connectors": public_connectors(),
            "git": workspace_git_status(self.workspace),
            "update": self.updater.last_check or {
                "source_dir": str(self.updater.source_dir),
                "local_sha": None,
                "update_available": False,
            },
        }

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

    def apply_update(self) -> dict[str, Any]:
        result = self.updater.apply()
        self.install_record = read_install_record()
        return result

    def _auto_update_on_launch(self) -> None:
        record = self.install_record or read_install_record()
        if not record:
            try:
                self.updater.status(refresh=True)
            except Exception:
                return
            return
        try:
            status = self.updater.status(refresh=True)
            if status.get("update_available") and not status.get("dirty") and not status.get("error"):
                self.updater.apply()
                self.install_record = read_install_record()
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

    def scan_local(self, extra_url: str | None = None) -> dict[str, Any]:
        extras = [extra_url] if extra_url else None
        if extra_url:
            assert_local_or_lan_url(extra_url)
        return {"endpoints": scan_local_endpoints(extras)}

    def list_local(self, base_url: str, api_key: str | None = None) -> dict[str, Any]:
        url = normalize_openai_base(base_url)
        return {"base_url": url, "models": list_local_models(url, api_key)}

    def connectors_public(self) -> dict[str, Any]:
        return public_connectors()

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
        target = Path(dest).expanduser() if dest else Path.home() / "Jonathan" / Path(str(repo).rstrip("/").split("/")[-1].replace(".git", ""))
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
        return self.status()

    def list_sessions(self) -> list[dict[str, Any]]:
        return Session.list_sessions()

    def new_session(self) -> dict[str, Any]:
        previous_id = self.session.session_id
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

    def load_session(self, session_id: str) -> dict[str, Any]:
        loaded = Session.load(session_id)
        if loaded is None:
            raise ValueError(f"session not found: {session_id}")
        if loaded.workspace:
            try:
                self.set_workspace(loaded.workspace)
            except ValueError:
                pass
        self._bind_session(loaded)
        return {**loaded.to_summary(), "messages": loaded.export_messages()}

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

    def list_commands(self) -> list[dict[str, Any]]:
        builtins = [
            {"name": "/", "description": "Show commands and skills"},
            {"name": "/help", "description": "Show help"},
            {"name": "/clear", "description": "Clear conversation"},
            {"name": "/save", "description": "Save current session"},
            {"name": "/load", "description": "Load a session by id"},
            {"name": "/tools", "description": "List available tools"},
            {"name": "/skills", "description": "List available skills"},
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

    def attach_files(self, payload: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in attachments_from_payload(payload)]

    def start_chat(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        job = ChatJob(job_id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run_chat_job,
            args=(job, text, attachments_from_payload(attachments)),
            daemon=True,
            name=f"clawd-chat-{job.job_id[:8]}",
        )
        thread.start()
        return job.job_id

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
        return {"request_id": request_id, "decision": choice, "allowed": req.allowed}

    def cancel_job(self, job_id: str) -> None:
        job = self._require_job(job_id)
        job.cancelled = True
        with self._lock:
            for req in self._permissions.values():
                if not req.event.is_set():
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
        with job.condition:
            job.events.append(event)
            job.condition.notify_all()

    def _finish(self, job: ChatJob, event: dict[str, Any]) -> None:
        self._emit(job, event)
        with job.condition:
            job.done = True
            job.condition.notify_all()

    def _handle_permission_request(
        self,
        tool_name: str,
        message: str,
        suggestion: str | None,
    ) -> tuple[bool, bool]:
        req = PermissionRequest(
            request_id=uuid.uuid4().hex,
            tool_name=tool_name,
            message=message,
            suggestion=suggestion,
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
            if not job.done:
                self._emit(job, payload)
        if not req.event.wait(timeout=self.permission_timeout_s):
            return False, False
        if req.always:
            self.tool_context.session_grants.add(tool_name.lower())
        if req.enable_docs:
            self.tool_context.permission_context.allow_docs = True
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

    def _run_chat_job(self, job: ChatJob, text: str, attachments: list[Attachment]) -> None:
        try:
            self._emit(job, {"type": "job_started", "text": text})
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
            if not combined.strip():
                self._finish(job, {"type": "error", "error": "Message is empty."})
                return

            if combined.lstrip().startswith("/"):
                handled = self._handle_slash(job, combined.strip())
                if handled:
                    return

            self.session.conversation.add_user_message(combined)
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

            result = run_agent_loop(
                conversation=self.session.conversation,
                provider=self.provider,
                tool_registry=self.tool_registry,
                tool_context=self.tool_context,
                max_turns=20,
                stream=self.stream,
                verbose=False,
                on_event=on_event,
                on_text_chunk=on_text_chunk,
            )
            usage = self.session.record_usage(result.usage)
            if self.session.conversation.messages:
                self.session.save()
            try:
                remember_turn(
                    session_id=self.session.session_id,
                    title=self.session.display_title(),
                    user_text=combined,
                    assistant_text=result.response_text or "",
                )
            except Exception:
                pass
            self._finish(job, {
                "type": "done",
                "text": result.response_text,
                "usage": usage,
                "turn_usage": result.usage,
                "num_turns": result.num_turns,
                "session": self.session.to_summary(),
            })
        except Exception as exc:
            hint = provider_limit_hint(exc)
            self._finish(job, {
                "type": "error",
                "error": f"{exc}{hint}",
                "provider_limit": bool(hint),
            })

    def _handle_slash(self, job: ChatJob, raw: str) -> bool:
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
        if cmd in {"clear", "reset", "new"}:
            self.session.conversation.clear()
            self._finish(job, {"type": "done", "text": "Conversation cleared.", "kind": "command"})
            return True
        if cmd == "save":
            summary = self.save_session()
            self._finish(job, {"type": "done", "text": f"Session saved: {summary['session_id']}", "kind": "command"})
            return True
        if cmd == "load":
            if not args:
                self._finish(job, {"type": "error", "error": "Usage: /load <session-id>"})
                return True
            summary = self.load_session(args.strip())
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
            result = self.tool_registry.dispatch(ToolCall(name=tool_parts[0], input=payload), self.tool_context)
            self._finish(job, {"type": "done", "text": json.dumps(result.output, indent=2, ensure_ascii=False), "kind": "command"})
            return True

        try:
            success, result_text, error = execute_command_sync(cmd, args, self.command_context)
            if success:
                self._finish(job, {"type": "done", "text": result_text or "", "kind": "command"})
                return True
            if error and "unknown command" not in error.lower():
                self._finish(job, {"type": "error", "error": error})
                return True
        except Exception:
            pass

        if self._try_run_skill(job, cmd, args):
            return True
        return False

    def _try_run_skill(self, job: ChatJob, skill_name: str, args: str) -> bool:
        try:
            result = self.tool_registry.dispatch(
                ToolCall(name="Skill", input={"skill": skill_name, "args": args}),
                self.tool_context,
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
        self.session.conversation.add_user_message(prompt)
        result_loop = run_agent_loop(
            conversation=self.session.conversation,
            provider=self.provider,
            tool_registry=self.tool_registry,
            tool_context=self.tool_context,
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
        usage = self.session.record_usage(result_loop.usage)
        self.session.save()
        self._finish(job, {
            "type": "done",
            "text": result_loop.response_text,
            "usage": usage,
            "turn_usage": result_loop.usage,
            "num_turns": result_loop.num_turns,
            "session": self.session.to_summary(),
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
- `/clear` — clear the current conversation
- `/save` — persist this session to `~/.clawd/sessions`
- `/load <id>` — restore a saved session
- `/tools` — list tools
- `/skills` — list SKILL.md slash commands

Type a message to run the existing agent loop. Destructive and network tools
prompt for approval before they run.
"""
