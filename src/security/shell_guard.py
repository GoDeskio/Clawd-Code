"""Block dangerous shell commands until the user approves them.

The matcher follows Octop's rule guardian: a rule hits when one of its
patterns matches and none of its exclude patterns match. Approvals are
required by default (``require_approval``). ``block`` refuses even after an
approval mark, and ``warn`` only logs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..secret_mask import mask_secrets
from .shell_guard_rules import SHELL_GUARD_RULES

logger = logging.getLogger(__name__)

DEFAULT_SHELL_GUARD_MODE = "require_approval"
_MODES = frozenset({"block", "warn", "require_approval"})


class GuardSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    SAFE = "SAFE"


class GuardThreatCategory(str, Enum):
    COMMAND_INJECTION = "command_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PATH_TRAVERSAL = "path_traversal"
    SENSITIVE_FILE_ACCESS = "sensitive_file_access"
    NETWORK_ABUSE = "network_abuse"
    CREDENTIAL_EXPOSURE = "credential_exposure"
    RESOURCE_ABUSE = "resource_abuse"
    PROMPT_INJECTION = "prompt_injection"
    CODE_EXECUTION = "code_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"


@dataclass
class GuardFinding:
    rule_id: str
    category: GuardThreatCategory
    severity: GuardSeverity
    title: str
    tool_name: str
    param_name: str
    matched_pattern: str | None = None
    snippet: str | None = None
    remediation: str | None = None


class GuardRule:
    """A single regex rule from the Octop dangerous-command set."""

    def __init__(self, rule_data: dict[str, Any]) -> None:
        self.id = str(rule_data["id"])
        raw_tools = rule_data.get("tools") or rule_data.get("tool") or []
        if isinstance(raw_tools, str):
            raw_tools = [raw_tools]
        self.tools = [str(item).lower() for item in raw_tools if item]
        raw_params = rule_data.get("params") or rule_data.get("param") or []
        if isinstance(raw_params, str):
            raw_params = [raw_params]
        self.params = [str(item).lower() for item in raw_params if item]
        self.category = GuardThreatCategory(str(rule_data["category"]))
        self.severity = GuardSeverity(str(rule_data["severity"]))
        self.patterns = [str(item) for item in rule_data.get("patterns") or []]
        self.exclude_patterns = [str(item) for item in rule_data.get("exclude_patterns") or []]
        self.description = str(rule_data.get("description") or "")
        self.remediation = str(rule_data.get("remediation") or "")
        self.compiled_patterns: list[re.Pattern[str]] = []
        for pattern in self.patterns:
            try:
                self.compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Bad regex in guard rule %s: %s", self.id, exc)
        self.compiled_exclude_patterns: list[re.Pattern[str]] = []
        for pattern in self.exclude_patterns:
            try:
                self.compiled_exclude_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Bad exclude regex in guard rule %s: %s", self.id, exc)

    def applies_to_tool(self, tool_name: str) -> bool:
        if not self.tools:
            return True
        return tool_name.lower() in self.tools

    def applies_to_param(self, param_name: str) -> bool:
        if not self.params:
            return True
        return param_name.lower() in self.params

    def match(self, value: str) -> tuple[re.Match[str] | None, str | None]:
        if any(pattern.search(value) for pattern in self.compiled_exclude_patterns):
            return None, None
        for pattern in self.compiled_patterns:
            found = pattern.search(value)
            if found:
                return found, pattern.pattern
        return None, None


class RuleBasedToolGuardian:
    """Match tool parameter strings against the bundled command rules."""

    def __init__(self, rules: list[dict[str, Any]] | None = None) -> None:
        self._rules = [GuardRule(item) for item in (rules if rules is not None else SHELL_GUARD_RULES)]

    @property
    def rules(self) -> list[GuardRule]:
        return self._rules

    def guard(self, tool_name: str, params: dict[str, Any]) -> list[GuardFinding]:
        findings: list[GuardFinding] = []
        applicable = [rule for rule in self._rules if rule.applies_to_tool(tool_name)]
        if not applicable:
            return findings
        for param_name, param_value in params.items():
            value = "" if param_value is None else str(param_value)
            if not value:
                continue
            for rule in applicable:
                if not rule.applies_to_param(param_name):
                    continue
                found, pattern_text = rule.match(value)
                if not found:
                    continue
                start = max(0, found.start() - 40)
                end = min(len(value), found.end() + 40)
                findings.append(
                    GuardFinding(
                        rule_id=rule.id,
                        category=rule.category,
                        severity=rule.severity,
                        title=rule.description or rule.id,
                        tool_name=tool_name,
                        param_name=param_name,
                        matched_pattern=pattern_text,
                        snippet=value[start:end],
                        remediation=rule.remediation,
                    )
                )
        return findings


_GUARDIAN = RuleBasedToolGuardian()


def command_findings(command: str, tool_name: str = "bash") -> list[GuardFinding]:
    """Return rule hits for a shell command. Empty means the command is allowed."""
    if not isinstance(command, str) or not command:
        return []
    return _GUARDIAN.guard(tool_name, {"command": command})


def resolve_shell_guard_mode(context: object) -> str:
    mode = getattr(context, "shell_guard_mode", None)
    if isinstance(mode, str) and mode in _MODES:
        return mode
    return DEFAULT_SHELL_GUARD_MODE


def _approved(context: object, command: str) -> bool:
    approved = getattr(context, "approved_shell_commands", None)
    if not isinstance(approved, set):
        return False
    return command in approved


def format_shell_guard_message(tool_name: str, findings: list[GuardFinding], *, mode: str) -> str:
    """Clear, English explanation of why a command is held for approval."""
    if mode == "require_approval":
        header = (
            "Dangerous shell command blocked until you approve it. "
            "Approvals are required by default."
        )
    elif mode == "block":
        header = "Dangerous shell command blocked by security policy."
    else:
        header = "Dangerous shell command detected. Warning only; the command was not held."
    lines = [header, "Tool: {0}".format(tool_name), ""]
    for finding in findings[:5]:
        lines.append("- [{0}] {1} ({2})".format(finding.severity.value, finding.title, finding.rule_id))
        if finding.snippet:
            lines.append("  snippet: {0!r}".format(finding.snippet))
        if finding.remediation:
            lines.append("  remediation: {0}".format(finding.remediation))
    extra = len(findings) - 5
    if extra > 0:
        lines.append("... and {0} more finding(s)".format(extra))
    if mode == "require_approval":
        lines.append("")
        lines.append("Approve this command once to run it. Denying leaves the command unexecuted.")
    return mask_secrets("\n".join(lines))


def shell_command_permission(tool_name: str, command: str, context: object) -> Any:
    """Return an ask/deny decision, or None when the normal tool gate should apply.

    The return type is PermissionResult. Imported lazily so this module can
    load without pulling the tool registry.
    """
    findings = command_findings(command, tool_name)
    if not findings:
        return None
    mode = resolve_shell_guard_mode(context)
    if mode == "warn":
        return None
    from ..tool_system.permission_handler import PermissionResult

    message = format_shell_guard_message(tool_name, findings, mode=mode)
    if mode == "block":
        return PermissionResult.deny(message)
    if _approved(context, command):
        return None
    return PermissionResult.ask(message, "Approve this command once")


def enforce_shell_command(tool_name: str, command: str, context: object) -> None:
    """Refuse a dangerous command unless this call was explicitly approved.

    ``require_approval`` (the default) raises when the command is not in the
    context approval set. Dispatch records that set only after the user
    accepts the prompt. Direct execution with no approval is refused.
    """
    findings = command_findings(command, tool_name)
    if not findings:
        return
    mode = resolve_shell_guard_mode(context)
    message = format_shell_guard_message(tool_name, findings, mode=mode)
    if mode == "warn":
        logger.warning("%s", message)
        return
    if mode == "require_approval" and _approved(context, command):
        return
    from ..tool_system.errors import ToolPermissionError

    raise ToolPermissionError(message)
