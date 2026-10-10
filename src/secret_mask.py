"""Mask API keys, tokens, passwords, and private keys in text.

Adapted from the Octop tool-output secret detector (MIT). Jonathan Ai keeps
the provider-key and assignment masking, and does not detect personal-id
numbers or call any remote service.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import logging
import re
from typing import Any

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Known key shapes are listed before generic assignments so a nested key is
# masked once. Patterns stay conservative so commit hashes and UUIDs survive.
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_project", re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai", re.compile(r"sk-(?!proj-|ant-)[A-Za-z0-9_-]{20,}")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("huggingface", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("github_token", re.compile(r"\b(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("telegram_bot", re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("discord_bot", re.compile(r"\b[MN][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "bearer",
        re.compile(r"(?i)\bBearer\s+(?P<value>[A-Za-z0-9._\-]{12,})"),
    ),
    (
        "assignment",
        re.compile(
            r"(?i)(?:api[_\s-]?key|secret[_\s-]?key|access[_\s-]?token|"
            r"auth[_\s-]?token|refresh[_\s-]?token|password|passwd|pwd)"
            r"\s*[=:]\s*['\"]?(?P<value>[A-Za-z0-9_\-+/=!@#$%^&().]{8,})"
        ),
    ),
)

_REDACTED_PRIVATE_KEY = "[REDACTED PRIVATE KEY]"


def _mask_value(value: str) -> str:
    """Keep a short prefix and the last four characters."""
    if len(value) <= 8:
        return "*" * len(value)
    hidden = len(value) - 8
    return value[:4] + ("*" * hidden) + value[-4:]


def mask_secrets(text: str) -> str:
    """Return ``text`` with secrets replaced.

    The result is stable when applied more than once. Asterisks in the
    replacement are outside the secret alphabets, so a second pass does not
    chew the already-masked value.
    """
    if not text or not isinstance(text, str):
        return text

    pieces: list[str] = []
    cursor = 0
    for match in _PRIVATE_KEY.finditer(text):
        pieces.append(text[cursor:match.start()])
        pieces.append(_REDACTED_PRIVATE_KEY)
        cursor = match.end()
    pieces.append(text[cursor:])
    masked = "".join(pieces)

    spans: list[tuple[int, int, str]] = []
    for _label, pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(masked):
            if "value" in match.groupdict() and match.group("value") is not None:
                start, end = match.span("value")
                value = match.group("value")
            else:
                start, end = match.span()
                value = match.group(0)
            if start is None or end is None or not value:
                continue
            spans.append((start, end, value))

    if not spans:
        return masked

    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    chosen: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, value in spans:
        if start < last_end:
            continue
        chosen.append((start, end, value))
        last_end = end

    parts: list[str] = []
    cursor = 0
    for start, end, value in chosen:
        parts.append(masked[cursor:start])
        parts.append(_mask_value(value))
        cursor = end
    parts.append(masked[cursor:])
    return "".join(parts)


def mask_tool_output(value: Any) -> Any:
    """Mask secrets inside tool output structures."""
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {
            mask_secrets(key) if isinstance(key, str) else key: mask_tool_output(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_tool_output(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_tool_output(item) for item in value)
    return value


def _mask_log_record(record: logging.LogRecord) -> None:
    if getattr(record, "_jonathan_secrets_masked", False):
        return
    msg = record.msg
    rendered = msg if isinstance(msg, str) else str(msg)
    args = record.args
    if args:
        try:
            rendered = rendered % args
        except Exception:
            rendered = rendered if isinstance(rendered, str) else str(rendered)
    record.msg = mask_secrets(rendered if isinstance(rendered, str) else str(rendered))
    record.args = ()
    if record.exc_text:
        record.exc_text = mask_secrets(record.exc_text)
    record._jonathan_secrets_masked = True  # type: ignore[attr-defined]


def install_log_masking() -> None:
    """Mask secrets in every log record before it is emitted.

    Safe to call more than once. Python 3.10 compatible: no version-specific
    logging APIs.
    """
    if getattr(logging.Logger, "_jonathan_secret_mask", False):
        return
    original_handle = logging.Logger.handle
    original_format = logging.Formatter.format

    def handle(self: logging.Logger, record: logging.LogRecord) -> None:
        _mask_log_record(record)
        return original_handle(self, record)

    def format(self: logging.Formatter, record: logging.LogRecord) -> str:
        _mask_log_record(record)
        rendered = original_format(self, record)
        if isinstance(rendered, str):
            return mask_secrets(rendered)
        return rendered

    logging.Logger.handle = handle  # type: ignore[method-assign]
    logging.Formatter.format = format  # type: ignore[method-assign]
    logging.Logger._jonathan_secret_mask = True  # type: ignore[attr-defined]


install_log_masking()
