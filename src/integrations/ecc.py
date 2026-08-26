"""Audited Everything Claude Code (ECC) integration.

ECC remains an independently updatable upstream cache. Jonathan indexes the
whole catalog but only loads explicitly enabled managed skills into prompts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.agent.memory import add_fact, list_facts, sanitize_memory_text
from src.skills.frontmatter import parse_frontmatter
from src.skills.library import user_skill_library, validate_skill_source

ECC_REPOSITORY = "https://github.com/affaan-m/ECC.git"
ECC_LICENSE = "MIT"
DEFAULT_ENABLED_SKILLS = (
    "plan-orchestrate",
    "tdd-workflow",
    "verification-loop",
    "security-review",
    "git-workflow",
    "codebase-onboarding",
    "context-budget",
    "error-handling",
    "production-audit",
    "agent-architecture-audit",
    "team-agent-orchestration",
    "architecture-decision-records",
    "api-design",
    "frontend-patterns",
    "backend-patterns",
    "python-patterns",
    "python-testing",
    "react-patterns",
    "react-testing",
    "e2e-testing",
    "deployment-patterns",
    "database-migrations",
    "mcp-server-patterns",
    "cost-tracking",
    "unified-memory",
)

_LOCK = threading.RLock()
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SECRET_PATTERNS = (
    ("github-token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
_INJECTION = re.compile(
    r"(?i)(?:ignore (?:all |any )?(?:previous|prior|system) instructions|"
    r"reveal (?:the )?(?:system prompt|secrets?)|disable (?:safety|permission)|"
    r"bypass (?:approval|permission)|grant (?:full|root|administrator) access)"
)
_DANGEROUS = re.compile(
    r"(?i)(?:rm\s+-rf\s+(?:/|~|\$HOME)|Remove-Item\s+[^\n]*-Recurse[^\n]*-Force|"
    r"Invoke-Expression|\biex\s*\(|curl[^\n|]*\|\s*(?:sh|bash)|wget[^\n|]*\|\s*(?:sh|bash))"
)


def _source_dir(source_dir: str | Path | None = None) -> Path:
    if source_dir:
        return Path(source_dir).expanduser().resolve()
    try:
        from src.install.record import resolve_source_dir

        resolved = resolve_source_dir()
        if resolved:
            return Path(resolved).resolve()
    except Exception:
        pass
    return Path(__file__).resolve().parents[2]


def ecc_cache_dir(source_dir: str | Path | None = None) -> Path:
    return _source_dir(source_dir) / "Integrations" / "ECC"


def ecc_managed_dir(source_dir: str | Path | None = None) -> Path:
    return user_skill_library(source_dir=_source_dir(source_dir)) / ".managed" / "ecc"


def _state_path(source_dir: str | Path | None = None) -> Path:
    return ecc_managed_dir(source_dir) / "state.json"


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "repository": ECC_REPOSITORY,
        "revision": "",
        "synced_at": "",
        "imported_at": "",
        "installed_skills": [],
        "enabled_skills": [],
        "installed_agents": [],
        "last_scan": {},
    }


def read_state(source_dir: str | Path | None = None) -> dict[str, Any]:
    path = _state_path(source_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    return {**_default_state(), **(data if isinstance(data, dict) else {})}


def _save_state(state: dict[str, Any], source_dir: str | Path | None = None) -> None:
    path = _state_path(source_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def enabled_skill_names(source_dir: str | Path | None = None) -> set[str]:
    state = read_state(source_dir)
    installed = set(str(item) for item in state.get("installed_skills") or [])
    return installed & set(str(item) for item in state.get("enabled_skills") or [])


def _run_git(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    command = ["git", "-c", "http.sslBackend=openssl", *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ValueError("Git is required to synchronize ECC.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("ECC synchronization timed out.") from exc


def sync(source_dir: str | Path | None = None) -> dict[str, Any]:
    """Clone or fast-refresh the dedicated managed upstream cache."""
    cache = ecc_cache_dir(source_dir)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if (cache / ".git").is_dir():
        result = _run_git(["-C", str(cache), "fetch", "--depth", "1", "origin", "main"])
        if result.returncode == 0:
            result = _run_git(["-C", str(cache), "checkout", "--detach", "--force", "FETCH_HEAD"])
    elif cache.exists() and any(cache.iterdir()):
        raise ValueError(f"ECC cache exists but is not a managed Git checkout: {cache}")
    else:
        result = _run_git(["clone", "--depth", "1", ECC_REPOSITORY, str(cache)])
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or "ECC synchronization failed.")
    revision_result = _run_git(["-C", str(cache), "rev-parse", "HEAD"], timeout=15)
    revision = revision_result.stdout.strip() if revision_result.returncode == 0 else ""
    state = read_state(source_dir)
    state.update({"repository": ECC_REPOSITORY, "revision": revision, "synced_at": datetime.now(timezone.utc).isoformat()})
    _save_state(state, source_dir)
    return {"ok": True, "path": str(cache), "revision": revision, "catalog": catalog(source_dir)}


def _frontmatter_summary(path: Path, fallback_name: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"name": fallback_name, "description": "Unreadable UTF-8 entry", "valid": False}
    parsed = parse_frontmatter(content)
    name = str(parsed.frontmatter.get("name") or fallback_name).strip().lower()
    description = str(parsed.frontmatter.get("description") or "").strip()
    return {
        "name": name,
        "description": description[:500],
        "version": str(parsed.frontmatter.get("version") or parsed.frontmatter.get("metadata.version") or ""),
        "path": str(path),
        "valid": bool(_NAME.fullmatch(name) and description and parsed.body.strip()),
    }


def catalog(source_dir: str | Path | None = None) -> dict[str, Any]:
    cache = ecc_cache_dir(source_dir)
    state = read_state(source_dir)
    skills: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    skills_root = cache / "skills"
    if skills_root.is_dir():
        for directory in sorted(skills_root.iterdir(), key=lambda item: item.name.lower()):
            path = directory / "SKILL.md"
            if directory.is_dir() and path.is_file():
                summary = _frontmatter_summary(path, directory.name)
                summary.update({"installed": summary["name"] in set(state.get("installed_skills") or []), "enabled": summary["name"] in set(state.get("enabled_skills") or [])})
                skills.append(summary)
    agents_root = cache / "agents"
    if agents_root.is_dir():
        for path in sorted(agents_root.glob("*.md"), key=lambda item: item.name.lower()):
            summary = _frontmatter_summary(path, path.stem)
            summary["installed"] = summary["name"] in set(state.get("installed_agents") or [])
            agents.append(summary)
    return {
        "available": cache.is_dir(),
        "path": str(cache),
        "repository": ECC_REPOSITORY,
        "license": ECC_LICENSE,
        "revision": state.get("revision") or "",
        "synced_at": state.get("synced_at") or "",
        "skills": skills,
        "agents": agents,
        "counts": {
            "skills": len(skills),
            "agents": len(agents),
            "installed": len(state.get("installed_skills") or []),
            "enabled": len(enabled_skill_names(source_dir)),
        },
    }


def security_scan(root: str | Path, *, max_files: int = 20000) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        return {"ok": False, "root": str(base), "files_scanned": 0, "findings": [{"severity": "critical", "kind": "missing-source", "path": str(base), "message": "Source directory is missing."}]}
    findings: list[dict[str, str]] = []
    scanned = 0
    ignored = {".git", "node_modules", ".venv", "__pycache__"}
    text_suffixes = {".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".py", ".js", ".mjs", ".cjs", ".sh", ".ps1", ".bat", ".cmd"}
    for current, dirs, files in os.walk(base):
        dirs[:] = [name for name in dirs if name not in ignored]
        for name in files:
            if scanned >= max_files:
                findings.append({"severity": "medium", "kind": "scan-limit", "path": str(base), "message": f"Stopped after {max_files} files."})
                break
            path = Path(current) / name
            scanned += 1
            try:
                resolved = path.resolve()
                if base != resolved and base not in resolved.parents:
                    findings.append({"severity": "critical", "kind": "path-escape", "path": str(path), "message": "Resolved path escapes the integration root."})
                    continue
                if path.is_symlink():
                    findings.append({"severity": "high", "kind": "symlink", "path": str(path), "message": "Symbolic links are not imported."})
                    continue
                if path.suffix.lower() not in text_suffixes or path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            relative = path.relative_to(base).as_posix()
            for kind, pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append({"severity": "critical", "kind": kind, "path": relative, "message": "Possible embedded credential; import is blocked by default."})
            if _INJECTION.search(text):
                findings.append({"severity": "high", "kind": "prompt-injection", "path": relative, "message": "Contains an instruction-override pattern; review before enabling."})
            if _DANGEROUS.search(text):
                findings.append({"severity": "high", "kind": "dangerous-command", "path": relative, "message": "Contains a destructive or pipe-to-shell command; approval remains required."})
        if scanned >= max_files:
            break
    critical = sum(1 for item in findings if item["severity"] == "critical")
    high = sum(1 for item in findings if item["severity"] == "high")
    return {"ok": critical == 0, "root": str(base), "files_scanned": scanned, "critical": critical, "high": high, "findings": findings[:500], "truncated": len(findings) > 500}


def _copy_managed(source: Path, destination: Path) -> None:
    root = destination.parent.resolve()
    target = destination.resolve()
    if target.parent != root:
        raise ValueError("Managed integration target escaped its approved root.")
    temp = destination.with_name(f".{destination.name}.incoming-{os.getpid()}-{threading.get_ident()}")
    if temp.exists():
        shutil.rmtree(temp)
    shutil.copytree(source, temp, symlinks=False, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    if destination.exists():
        archive_root = destination.parent.parent / ".archive" / "ecc"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive = archive_root / f"{destination.name}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        os.replace(destination, archive)
    os.replace(temp, destination)


def import_catalog(
    source_dir: str | Path | None = None,
    *,
    skill_names: Iterable[str] | None = None,
    agent_names: Iterable[str] | None = None,
    enable_names: Iterable[str] | None = None,
    allow_unsafe: bool = False,
) -> dict[str, Any]:
    """Import all requested content while keeping prompt activation lazy."""
    cache = ecc_cache_dir(source_dir)
    if not (cache / "skills").is_dir():
        raise ValueError("Synchronize ECC before importing its catalog.")
    # Only skills and agent templates are copied. Test fixtures intentionally
    # contain fake secrets and must remain visible in a full-repository scan,
    # but they are not part of the import decision.
    skill_scan = security_scan(cache / "skills")
    agent_scan = security_scan(cache / "agents")
    scan = {
        "ok": bool(skill_scan["ok"] and agent_scan["ok"]),
        "root": str(cache),
        "files_scanned": int(skill_scan["files_scanned"]) + int(agent_scan["files_scanned"]),
        "critical": int(skill_scan["critical"]) + int(agent_scan["critical"]),
        "high": int(skill_scan["high"]) + int(agent_scan["high"]),
        "findings": [*skill_scan["findings"], *agent_scan["findings"]][:500],
        "scope": ["skills", "agents"],
    }
    if scan["critical"] and not allow_unsafe:
        raise ValueError(f"ECC import blocked by {scan['critical']} critical finding(s) in importable content. Review the scan first.")
    info = catalog(source_dir)
    available_skills = {str(item["name"]): item for item in info["skills"] if item.get("valid")}
    available_agents = {str(item["name"]): item for item in info["agents"] if item.get("valid")}
    requested_skills = sorted(set(skill_names if skill_names is not None else available_skills))
    requested_agents = sorted(set(agent_names if agent_names is not None else available_agents))
    unknown = [name for name in requested_skills if name not in available_skills]
    if unknown:
        raise ValueError("Unknown or invalid ECC skills: " + ", ".join(unknown[:20]))
    managed = ecc_managed_dir(source_dir)
    skills_target = managed / "skills"
    agents_target = managed / "agents"
    skills_target.mkdir(parents=True, exist_ok=True)
    agents_target.mkdir(parents=True, exist_ok=True)
    imported_skills: list[str] = []
    imported_agents: list[str] = []
    with _LOCK:
        for name in requested_skills:
            source = Path(str(available_skills[name]["path"])).parent
            validation = validate_skill_source(name, (source / "SKILL.md").read_text(encoding="utf-8"))
            if not validation["valid"]:
                continue
            _copy_managed(source, skills_target / name)
            imported_skills.append(name)
        for name in requested_agents:
            item = available_agents.get(name)
            if not item:
                continue
            source = Path(str(item["path"]))
            shutil.copy2(source, agents_target / f"{name}.md")
            imported_agents.append(name)
        state = read_state(source_dir)
        installed = set(str(item) for item in state.get("installed_skills") or []) | set(imported_skills)
        installed_agents = set(str(item) for item in state.get("installed_agents") or []) | set(imported_agents)
        requested_enabled = set(enable_names if enable_names is not None else DEFAULT_ENABLED_SKILLS)
        enabled = (set(str(item) for item in state.get("enabled_skills") or []) | requested_enabled) & installed
        state.update({
            "installed_skills": sorted(installed),
            "enabled_skills": sorted(enabled),
            "installed_agents": sorted(installed_agents),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "last_scan": {key: scan[key] for key in ("ok", "files_scanned", "critical", "high")},
        })
        _save_state(state, source_dir)
    return {"ok": True, "imported_skills": imported_skills, "imported_agents": imported_agents, "enabled_skills": sorted(enabled), "scan": scan, "catalog": catalog(source_dir)}


def set_enabled(names: Iterable[str], enabled: bool, source_dir: str | Path | None = None) -> dict[str, Any]:
    requested = {str(name).strip().lower() for name in names if _NAME.fullmatch(str(name).strip().lower())}
    state = read_state(source_dir)
    installed = set(str(item) for item in state.get("installed_skills") or [])
    missing = requested - installed
    if missing:
        raise ValueError("Import these skills before enabling them: " + ", ".join(sorted(missing)))
    active = set(str(item) for item in state.get("enabled_skills") or [])
    active = (active | requested) if enabled else (active - requested)
    state["enabled_skills"] = sorted(active & installed)
    _save_state(state, source_dir)
    return {"ok": True, "enabled_skills": state["enabled_skills"], "catalog": catalog(source_dir)}


def memory_vault_export() -> dict[str, Any]:
    """Export Jonathan facts as inspectable ECC-compatible Markdown documents."""
    root = Path.home() / ".clawd" / "memory" / "vault"
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for fact in list_facts():
        fact_id = re.sub(r"[^a-z0-9_-]", "-", str(fact.get("id") or "fact").lower())
        memory_id = f"mem_jonathan_{fact_id}"
        timestamp = str(fact.get("created_at") or datetime.now(timezone.utc).isoformat()).replace("+00:00", "Z")
        body = sanitize_memory_text(str(fact.get("text") or ""), limit=4096)
        if not body:
            continue
        content = (
            "---\n"
            "schema: ecc.memory.v1\n"
            f"id: {memory_id}\n"
            f"title: Jonathan fact {fact_id}\n"
            "kind: fact\n"
            "scope: user\n"
            "trust: unreviewed\n"
            "status: active\n"
            "sourceHarness: jonathan-ai\n"
            "targetHarnesses: [jonathan-ai, codex, claude-code]\n"
            "tags: [jonathan-memory]\n"
            "links: []\n"
            f"createdAt: {timestamp}\n"
            f"updatedAt: {timestamp}\n"
            "---\n\n"
            f"{body}\n"
        )
        path = root / f"{memory_id}.md"
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(str(path))
    return {"ok": True, "path": str(root), "count": len(written), "files": written}


def memory_vault_import(path: str | Path) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    candidates = list(root.glob("*.md")) if root.is_dir() else [root]
    imported = []
    rejected = []
    for candidate in candidates[:5000]:
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            rejected.append({"path": str(candidate), "reason": "not readable UTF-8"})
            continue
        parsed = parse_frontmatter(text)
        if parsed.frontmatter.get("schema") != "ecc.memory.v1" or parsed.frontmatter.get("trust") != "unreviewed":
            rejected.append({"path": str(candidate), "reason": "not an unreviewed ecc.memory.v1 document"})
            continue
        if _INJECTION.search(parsed.body) or any(pattern.search(parsed.body) for _, pattern in _SECRET_PATTERNS):
            rejected.append({"path": str(candidate), "reason": "contains unsafe instruction or possible secret"})
            continue
        fact = add_fact(parsed.body, source_session=f"memory-vault:{candidate.name}")
        if fact:
            imported.append(fact)
    return {"ok": True, "imported": imported, "rejected": rejected}


def status(source_dir: str | Path | None = None) -> dict[str, Any]:
    info = catalog(source_dir)
    info["managed_path"] = str(ecc_managed_dir(source_dir))
    info["state"] = read_state(source_dir)
    info["default_enabled"] = list(DEFAULT_ENABLED_SKILLS)
    return info
