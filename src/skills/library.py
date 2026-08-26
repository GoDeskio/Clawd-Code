"""Visible, shared library for user-authored Jonathan Ai skills."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .frontmatter import parse_frontmatter

_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_LOCK = threading.RLock()


def user_skill_library(*, source_dir: str | Path | None = None, home: Path | None = None, create: bool = True) -> Path:
    """Return the one visible skill directory shared by every conversation agent."""
    override = os.environ.get("CLAWD_SKILLS_DIR")
    if override:
        root = Path(override).expanduser().resolve()
    else:
        root_source: Path | None = Path(source_dir).expanduser().resolve() if source_dir else None
        if root_source is None:
            try:
                from src.install.record import resolve_source_dir

                root_source = resolve_source_dir(home=home)
            except Exception:
                root_source = None
        base_home = Path(home) if home is not None else Path.home()
        root = (root_source or (base_home / "Jonathan" / "Jonathan-Ai")) / "Skills"
        root = root.expanduser().resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def validate_skill_source(name: str, content: str) -> dict[str, Any]:
    normalized = str(name or "").strip().lower()
    errors: list[str] = []
    if not _NAME.fullmatch(normalized):
        errors.append("Name must use 1-64 lowercase letters, numbers, or hyphens.")
    parsed = parse_frontmatter(str(content or ""))
    declared = str(parsed.frontmatter.get("name") or "").strip().lower()
    description = str(parsed.frontmatter.get("description") or "").strip()
    if not declared:
        errors.append("Frontmatter requires a name field.")
    elif declared != normalized:
        errors.append("Frontmatter name must match the skill folder name.")
    if not description:
        errors.append("Frontmatter requires a description field.")
    if not parsed.body.strip():
        errors.append("The skill instructions cannot be empty.")
    return {
        "valid": not errors,
        "name": normalized,
        "description": description,
        "version": str(parsed.frontmatter.get("version") or "1.0.0"),
        "when_to_use": str(parsed.frontmatter.get("when_to_use") or ""),
        "errors": errors,
    }


def render_skill(
    *,
    name: str,
    description: str,
    instructions: str,
    version: str = "1.0.0",
    when_to_use: str = "",
    allowed_tools: list[str] | None = None,
    user_invocable: bool = True,
) -> str:
    normalized = str(name or "").strip().lower()
    lines = [
        "---",
        f"name: {json.dumps(normalized, ensure_ascii=False)}",
        f"description: {json.dumps(str(description or '').strip(), ensure_ascii=False)}",
        f"version: {json.dumps(str(version or '1.0.0'), ensure_ascii=False)}",
        f"user-invocable: {'true' if user_invocable else 'false'}",
    ]
    tools = [str(item).strip() for item in (allowed_tools or []) if str(item).strip()]
    if tools:
        lines.append("allowed-tools: [" + ", ".join(json.dumps(item) for item in tools) + "]")
    lines.extend(["---", "", f"# {normalized}", ""])
    if str(when_to_use or "").strip():
        lines.extend(["## When to use", "", str(when_to_use).strip(), ""])
    lines.extend([str(instructions or "").strip(), ""])
    return "\n".join(lines)


def save_user_skill(name: str, content: str, *, source_dir: str | Path | None = None) -> dict[str, Any]:
    validation = validate_skill_source(name, content)
    if not validation["valid"]:
        raise ValueError(" ".join(validation["errors"]))
    root = user_skill_library(source_dir=source_dir)
    directory = (root / validation["name"]).resolve()
    if root != directory.parent:
        raise ValueError("Invalid skill path.")
    path = directory / "SKILL.md"
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"SKILL.md.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temp.write_text(str(content).rstrip() + "\n", encoding="utf-8", newline="\n")
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    return {**validation, "path": str(path), "content": path.read_text(encoding="utf-8")}


def archive_user_skill(name: str, *, source_dir: str | Path | None = None) -> dict[str, Any]:
    root = user_skill_library(source_dir=source_dir)
    normalized = str(name or "").strip().lower()
    if not _NAME.fullmatch(normalized):
        raise ValueError("Invalid skill name.")
    source = (root / normalized).resolve()
    if source.parent != root or not source.is_dir():
        raise ValueError("Skill was not found in the shared library.")
    archive = root / ".archive"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / normalized
    if destination.exists():
        destination = archive / f"{normalized}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(source), str(destination))
    return {"name": normalized, "archived": True, "recoverable": True, "path": str(destination)}


def open_skill_library(*, source_dir: str | Path | None = None) -> Path:
    root = user_skill_library(source_dir=source_dir)
    if os.name == "nt":
        os.startfile(str(root))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(root)])
    else:
        subprocess.Popen(["xdg-open", str(root)])
    return root


def ensure_learning_skill(*, source_dir: str | Path | None = None) -> Path:
    """Seed a useful meta-skill once; never overwrite the user's edits."""
    root = user_skill_library(source_dir=source_dir)
    path = root / "learn-reusable-workflows" / "SKILL.md"
    if path.exists():
        return path
    content = render_skill(
        name="learn-reusable-workflows",
        description="Capture a proven, reusable workflow as an editable Jonathan Ai skill after completing real work.",
        version="1.0.0",
        when_to_use="Use when the user asks Jonathan to learn a workflow or a completed task reveals repeatable non-obvious steps.",
        allowed_tools=["SkillManager"],
        instructions=(
            "Create or update a user-scoped skill with `SkillManager` only when there is concrete, reusable learning. "
            "Keep the instructions specific to decisions that improved the completed task. Include verification and "
            "real constraints, but do not copy chat history, credentials, one-off details, or generic assistant advice. "
            "Validate the saved skill, tell the user its visible path, and preserve their existing edits."
        ),
    )
    save_user_skill("learn-reusable-workflows", content, source_dir=source_dir)
    return path
