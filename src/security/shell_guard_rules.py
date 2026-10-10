"""Dangerous shell-command rules adapted from Octop.

The detection patterns come from Octop's tool guard
(``dangerous_shell_commands.yaml`` in the MIT-licensed Octop project).

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Jonathan Ai adaptations: English descriptions only, no embedded service
hosts, Python 3.10, approvals required by default, and an added credential
exfiltration rule in the same format.
"""

from __future__ import annotations

from typing import Any


def _rule(
    rule_id: str,
    category: str,
    severity: str,
    patterns: list[str],
    description: str,
    remediation: str,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "tools": ["bash", "execute", "powershell", "acp", "device"],
        "params": ["command"],
        "category": category,
        "severity": severity,
        "patterns": patterns,
        "exclude_patterns": list(exclude or []),
        "description": description,
        "remediation": remediation,
    }


# Patterns are the Octop rule set, expressed as Python regex source so the
# runtime does not need a YAML parser.
SHELL_GUARD_RULES: list[dict[str, Any]] = [
    _rule(
        "TOOL_CMD_DANGEROUS_RM",
        "command_injection",
        "HIGH",
        [r"\brm\b", r"\bdel\b", r"\bRemove-Item\b"],
        "Shell command contains 'rm' which may cause data loss",
        "Confirm with the user before removing files or directories",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_DANGEROUS_MV",
        "command_injection",
        "HIGH",
        [r"\bmv\b"],
        "Shell command contains 'mv' which may move or overwrite files unexpectedly",
        "Confirm with the user before moving or renaming files",
    ),
    _rule(
        "TOOL_CMD_FS_DESTRUCTION",
        "command_injection",
        "CRITICAL",
        [
            r"\bmkfs(\.[a-zA-Z0-9_]+)?\b",
            r"\bmke2fs\b",
            r"\bdd\s+.*of=/dev/",
            r">\s*/dev/(sd[a-z][0-9]*|vd[a-z][0-9]*|nvme\d+n\d+(p\d+)?)",
        ],
        "Detects low-level disk formatting or wiping commands",
        "Block operation. Agents should not format or overwrite raw block devices.",
    ),
    _rule(
        "TOOL_CMD_DOS_FORK_BOMB",
        "resource_abuse",
        "CRITICAL",
        [
            r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
            r"\bkill\s+-9\s+(-1\b|1\b)",
        ],
        "Detects classic Bash fork bombs and mass process termination",
        "Block immediately. These commands will crash the host system.",
    ),
    _rule(
        "TOOL_CMD_PIPE_TO_SHELL",
        "code_execution",
        "CRITICAL",
        [r"\b(curl|wget)\b\s+.*\|.*\b(bash|sh|zsh|ash|dash)\b"],
        "Detects curl or wget piped into a shell, which runs a downloaded script from an untrusted host",
        "Confirm with the user. Agents should inspect scripts before executing them.",
    ),
    _rule(
        "TOOL_CMD_REVERSE_SHELL",
        "network_abuse",
        "CRITICAL",
        [
            r"/dev/(tcp|udp)/",
            r"\bnc\s+.*-e\s*\S+",
            r"\bncat\s+.*-e\s*\S+",
            r"\bsocat\s+.*EXEC:",
        ],
        "Detects attempts to establish reverse shells or unauthorized network tunnels",
        "Block operation. Agents do not need to bind interactive shells to network sockets.",
    ),
    _rule(
        "TOOL_CMD_SYSTEM_TAMPERING",
        "sensitive_file_access",
        "HIGH",
        [
            r"\bcrontab\b",
            r"\bauthorized_keys\b",
            r"/etc/sudoers",
            r"/etc/crontab",
        ],
        "Detects access to cron jobs, SSH keys, or sudo permissions (including reads and modifications)",
        "Confirm with the user. Treat any access to credential and scheduling files as sensitive.",
    ),
    _rule(
        "TOOL_CMD_UNSAFE_PERMISSIONS",
        "privilege_escalation",
        "HIGH",
        [
            r"\bchmod\s+-[a-zA-Z]*R[a-zA-Z]*\s+(777|a\+rwx)\s+/",
            r"\bchattr\s+\+i",
        ],
        "Detects global permission downgrades (chmod 777) or setting immutable flags",
        "Prompt for confirmation. Suggest least-privilege permission models.",
    ),
    _rule(
        "TOOL_CMD_OBFUSCATED_EXEC",
        "code_execution",
        "HIGH",
        [r"\bbase64\s+(-d|--decode)\s*\|\s*\b(bash|sh|zsh)\b"],
        "Detects execution of base64 encoded strings passed directly to a shell interpreter",
        "Block execution. Agents should use plain text commands.",
    ),
    _rule(
        "TOOL_CMD_SYSTEM_REBOOT",
        "resource_abuse",
        "CRITICAL",
        [
            r"\b(reboot|shutdown|halt|poweroff)\b",
            r"\binit\s+(0|6)\b",
            r"\btelinit\s+(0|6)\b",
            r"\bShutdown-Computer\b",
            r"\bRestart-Computer\b",
        ],
        "Detects system reboot or shutdown commands that will terminate the host system",
        "Block operation. Agents should not restart or shut down the system.",
    ),
    _rule(
        "TOOL_CMD_SERVICE_RESTART",
        "resource_abuse",
        "HIGH",
        [
            r"\bsystemctl\s+(restart|stop|start|reload|kill)\b",
            r"\bservice\s+\S+\s+(restart|stop|start|reload)\b",
            r"\b(sc|net)\s+(start|stop|restart)\b",
            r"\blaunchctl\s+(load|unload|stop|start|kickstart|kill)\b",
            r"\brc-service\s+(restart|stop|start)\b",
        ],
        "Detects service management commands that can disrupt system services",
        "Confirm with the user. Restarting services may cause downtime or data loss.",
    ),
    _rule(
        "TOOL_CMD_PROCESS_KILL",
        "resource_abuse",
        "HIGH",
        [
            r"\b(pkill|killall)\b",
            r"\bkill\s+(-(9|KILL|15|TERM|1|HUP|2|INT)\s+)?[^\-\s]",
            r"\btaskkill\s+/F\b",
            r"\bStop-Process\b.*-Force\b",
        ],
        "Detects process termination commands that may kill critical processes",
        "Confirm with the user. Killing processes may cause data loss or system instability.",
        exclude=[r"kill\s+\$\$"],
    ),
    _rule(
        "TOOL_CMD_PRIVILEGE_ESCALATION",
        "privilege_escalation",
        "CRITICAL",
        [
            r"\bsudo\s+",
            r"\bsu\b",
            r"\bdoas\s+",
            r"\bpkexec\b",
            r"\brunas\s+/user:",
        ],
        "Detects privilege escalation attempts using sudo, su, doas, pkexec, or runas",
        "Block operation. Agents should not execute commands with elevated privileges.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_IFS_INJECTION",
        "code_execution",
        "HIGH",
        [r"\$IFS(?![A-Za-z0-9_])", r"\$\{[^}]*IFS"],
        "Command uses $IFS variable which could bypass security validation",
        "Reject commands containing IFS manipulation. Legitimate commands do not need to reference $IFS directly.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_CONTROL_CHARS",
        "code_execution",
        "CRITICAL",
        ["[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"],
        "Command contains non-printable control characters that could bypass security checks",
        "Block commands containing control characters. These are never needed in legitimate shell commands.",
    ),
    _rule(
        "TOOL_CMD_UNICODE_WHITESPACE",
        "code_execution",
        "HIGH",
        ["[\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"],
        "Command contains Unicode whitespace characters that could cause parsing inconsistencies",
        "Block commands containing non-ASCII whitespace. Use standard spaces instead.",
    ),
    _rule(
        "TOOL_CMD_PROC_ENVIRON",
        "sensitive_file_access",
        "HIGH",
        [r"/proc/(?:self|\d+)/environ(?:\b|$)"],
        "Command accesses process environment files which could expose API keys and secrets",
        "Block access to process environment files. API keys and secrets may be exposed.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_JQ_SYSTEM",
        "code_execution",
        "HIGH",
        [r"\bjq\b.*\bsystem\s*\("],
        "jq command contains system() which can execute arbitrary shell commands",
        "Block jq commands using system(). Use jq only for data processing, not command execution.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_JQ_FILE_FLAGS",
        "code_execution",
        "HIGH",
        [
            r"\bjq\b.*(?:\s-f\b|\s--from-file\b|\s--rawfile\b|\s--slurpfile\b|\s-L\b|\s--library-path\b)"
        ],
        "jq command uses flags that could read arbitrary files or execute external code",
        "Confirm with the user. These jq flags can access files outside the intended scope.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_ZSH_DANGEROUS",
        "code_execution",
        "HIGH",
        [
            r"\bzmodload\b",
            r"\bemulate\b(?:\s+-\S+)*\s+-c\b",
            r"\b(sysopen|sysread|syswrite|sysseek)\b",
            r"\b(zpty|ztcp|zsocket)\b",
            r"\bzf_(rm|mv|ln|chmod|chown|mkdir|rmdir|chgrp)\b",
            r"\bfc\b.*\s-\S*e",
        ],
        "Command uses Zsh-specific builtins that can bypass security checks",
        "Block Zsh module and builtin commands that provide raw file I/O, network, or execution.",
        exclude=[r"^\s*#"],
    ),
    _rule(
        "TOOL_CMD_CREDENTIAL_EXFIL",
        "data_exfiltration",
        "CRITICAL",
        [
            r"\b(?:cat|type|Get-Content)\b.+(?:\.env\b|id_rsa|credentials|passwd|shadow|\.pem\b).{0,160}\|\s*(?:curl|wget|nc|ncat)\b",
            r"\b(?:env|printenv)\b\s*\|\s*(?:curl|wget|nc|ncat)\b",
            r"\b(?:curl|wget)\b.+(?:-d|--data|--data-raw|--data-binary|-F|--form)\b.+(?:api[_-]?key|token|password|secret)\b",
        ],
        "Detects commands that send credentials, tokens, passwords, or private keys to the network",
        "Block operation. Do not exfiltrate API keys, tokens, passwords, or private keys.",
    ),
]
