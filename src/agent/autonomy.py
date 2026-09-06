"""Local evidence profiles for earned, revocable agent autonomy.

This module measures approval history; it never bypasses Jonathan's permission
enforcement.  A recommendation becomes authority only through an explicit user
grant such as "Always this session" or the separately confirmed device-access
setting.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_LEVELS = (
    "Observe only",
    "Suggest",
    "Draft",
    "Execute with approval",
    "Execute with sampling",
    "Conditional autonomy",
    "Exception-based supervision",
    "Delegated authority",
)
_HIGH_RISK = {
    "bash", "powershell", "terminal", "write", "edit", "notebookedit",
    "devicecontrol", "systemadmin", "repository", "trading",
}
_MEDIUM_RISK = {"webfetch", "websearch", "mcp", "externalagent", "remotetrigger"}


def autonomy_store_path() -> Path:
    path = Path.home() / ".clawd" / "autonomy" / "evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    """Return the conservative 95% lower bound for a binomial proportion."""
    if total <= 0:
        return 0.0
    successes = max(0, min(int(successes), int(total)))
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _read() -> dict[str, Any]:
    target = autonomy_store_path()
    if not target.is_file():
        return {"version": 1, "profiles": {}}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("profiles"), dict):
            return data
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {"version": 1, "profiles": {}}


def _write(data: dict[str, Any]) -> None:
    target = autonomy_store_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _risk(tool_name: str) -> tuple[str, int]:
    lowered = str(tool_name or "unknown").strip().lower()
    if lowered in _HIGH_RISK:
        return "high", 3
    if lowered in _MEDIUM_RISK:
        return "medium", 4
    return "low", 5


def record_permission_evidence(
    agent_id: str,
    tool_name: str,
    decision: str,
    event_id: str,
) -> dict[str, Any]:
    """Record one distinct human decision without storing prompts or tool input."""
    agent = str(agent_id or "default")
    tool = str(tool_name or "unknown").strip().lower()
    outcome = str(decision or "deny").strip().lower()
    clean = outcome in {"allow", "yes", "y", "once", "always", "always_allow", "session", "allow_docs", "enable_docs"}
    with _LOCK:
        data = _read()
        key = f"{agent}:{tool}"
        profile = data["profiles"].setdefault(key, {
            "agent_id": agent,
            "workflow": tool,
            "clean_approvals": 0,
            "rejections": 0,
            "event_ids": [],
        })
        ids = list(profile.get("event_ids") or [])
        if event_id in ids:
            return _profile(profile)
        ids.append(str(event_id))
        profile["event_ids"] = ids[-2000:]
        if clean:
            profile["clean_approvals"] = int(profile.get("clean_approvals") or 0) + 1
        else:
            profile["rejections"] = int(profile.get("rejections") or 0) + 1
        profile["last_decision"] = outcome
        profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(data)
        return _profile(profile)


def _profile(raw: dict[str, Any]) -> dict[str, Any]:
    clean = int(raw.get("clean_approvals") or 0)
    rejected = int(raw.get("rejections") or 0)
    total = clean + rejected
    confidence = wilson_lower_bound(clean, total)
    risk, ceiling = _risk(str(raw.get("workflow") or ""))
    recommended = 3
    if risk == "low" and total >= 20 and confidence >= 0.88:
        recommended = 5
    elif risk in {"low", "medium"} and total >= 8 and confidence >= 0.80:
        recommended = 4
    recommended = min(recommended, ceiling)
    return {
        "agent_id": str(raw.get("agent_id") or "default"),
        "workflow": str(raw.get("workflow") or "unknown"),
        "clean_approvals": clean,
        "rejections": rejected,
        "total_decisions": total,
        "clean_approval_lower_bound": round(confidence, 4),
        "risk": risk,
        "autonomy_ceiling": ceiling,
        "autonomy_ceiling_label": _LEVELS[ceiling],
        "recommended_level": recommended,
        "recommended_level_label": _LEVELS[recommended],
        "enforced_level": 3,
        "enforced_level_label": _LEVELS[3],
        "updated_at": str(raw.get("updated_at") or ""),
    }


def autonomy_status(agent_id: str | None = None) -> dict[str, Any]:
    """Return transparent recommendations for one agent or all agents."""
    with _LOCK:
        data = _read()
    profiles = [
        _profile(row) for row in data.get("profiles", {}).values()
        if not agent_id or str(row.get("agent_id")) == str(agent_id)
    ]
    profiles.sort(key=lambda row: (row["agent_id"], row["workflow"]))
    return {
        "agent_id": str(agent_id or ""),
        "profiles": profiles,
        "profile_count": len(profiles),
        "mode": "recommendation_only",
        "enforcement": "Explicit user approval remains required; recommendations never widen access.",
        "store_path": str(autonomy_store_path()),
    }
