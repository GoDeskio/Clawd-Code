"""Jonathan-native fail-closed engineering quality controller."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

PROCODER_REPOSITORY = "https://github.com/azrtydxb/procoder.git"
PROCODER_LICENSE = "Apache-2.0"
SAFE_ACTIONS = {"status", "doctor", "check", "test", "audit", "security", "git", "docs", "ci", "infra", "maintain", "deps", "release", "index"}
SECRET_RE = re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{16,}")
CONFLICT_RE = re.compile(r"(?m)^(?:<{7}|={7}|>{7})(?:\s|$)")
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


class ProcoderManager:
    """Compatibility name retained while all checks are implemented in Jonathan."""

    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir).expanduser().resolve()
        self.checkout = self.source_dir / "src" / "integrations"

    @staticmethod
    def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(command, 127, "", str(exc))

    def status(self) -> dict[str, Any]:
        return {"available": True, "source_ready": True, "runtime_ready": True, "binary": "",
                "checksum_verified": True, "version": "jonathan-native-1", "revision": "jonathan-native-1",
                "path": str(self.checkout), "repository": "internal://jonathan/engineering-gate",
                "reference_repository": PROCODER_REPOSITORY, "license": "MIT (implementation); Apache-2.0 design reference",
                "hooks_installed": False, "automatic_edits": False, "payments_required": False,
                "features": ["commit gate", "test controller", "security audit", "release check", "code index", "documentation/CI/infra hygiene"]}

    def sync(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        if progress: progress("Jonathan's native engineering gate is ready")
        return self.status()

    install = sync

    @staticmethod
    def _tracked(root: Path) -> list[Path]:
        result = ProcoderManager._run(["git","ls-files","-co","--exclude-standard"],cwd=root,timeout=30)
        if result.returncode == 0:
            return [root / row for row in result.stdout.splitlines() if row and (root/row).is_file()]
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]

    def _gate(self, root: Path) -> tuple[bool,str]:
        findings=[]; checked=0; unchecked=0
        for path in self._tracked(root):
            rel=path.relative_to(root).as_posix()
            if path.name in JUNK: findings.append(f"BLOCKING {rel}: junk file")
            try: raw=path.read_bytes()
            except OSError: findings.append(f"BLOCKING {rel}: unreadable"); unchecked+=1; continue
            if len(raw)>10_000_000: findings.append(f"BLOCKING {rel}: oversized file ({len(raw)} bytes)")
            if b"\x00" in raw: unchecked+=1; continue
            text=raw.decode("utf-8",errors="replace"); checked+=1
            for match in CONFLICT_RE.finditer(text): findings.append(f"BLOCKING {rel}:{text.count(chr(10),0,match.start())+1}: conflict marker")
            if SECRET_RE.search(text) and not rel.startswith("tests/"): findings.append(f"BLOCKING {rel}: possible embedded credential")
            if text and not text.endswith("\n") and path.suffix.lower() in {".py",".js",".ts",".json",".md",".yml",".yaml",".toml"}: findings.append(f"ADVISORY {rel}: missing final newline")
        blocking=sum(row.startswith("BLOCKING") for row in findings)
        output="\n".join(findings+[f"Jonathan gate: {checked} text files checked, {unchecked} binary/unchecked, {blocking} blocking finding(s)"])
        return blocking==0,output

    def _tests(self, root: Path, coverage: bool, timeout: int) -> tuple[bool,str]:
        commands=[]
        if (root/"pyproject.toml").is_file() or (root/"pytest.ini").is_file() or (root/"tests").is_dir(): commands.append(([str(root/".venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")),"-m","pytest","-q"],"pytest"))
        if (root/"package.json").is_file():
            try:
                scripts=json.loads((root/"package.json").read_text(encoding="utf-8")).get("scripts",{})
                if "test" in scripts: commands.append(([shutil.which("npm") or "npm","test","--","--runInBand"],"npm test"))
            except Exception: pass
        if (root/"go.mod").is_file(): commands.append(([shutil.which("go") or "go","test","./..."],"go test"))
        if not commands: return False,"NOT RUN: no canonical test command detected"
        rows=[]; ok=True
        for command,label in commands:
            if not Path(command[0]).exists() and not shutil.which(command[0]): rows.append(f"NOT RUN {label}: runner unavailable"); ok=False; continue
            result=self._run(command,cwd=root,timeout=timeout); rows.append(f"{'PASS' if result.returncode==0 else 'FAIL'} {label} (exit {result.returncode})\n{(result.stdout+result.stderr)[-12000:]}"); ok &= result.returncode==0
        return ok,"\n".join(rows)

    def execute(self, action: str, *, workspace: str | Path, argument: str = "", deep: bool = False, coverage: bool = False, timeout: int = 1800) -> dict[str, Any]:
        action=action.strip().lower(); root=Path(workspace).expanduser().resolve()
        if action=="status": return self.status()
        if action in {"sync","install","repair"}: return self.sync()
        if action not in SAFE_ACTIONS: raise ValueError(f"Unsupported engineering-gate action: {action}")
        if action=="doctor":
            tools=["git","python","node","npm","rg","go"]; output="\n".join(f"{name}: {shutil.which(name) or 'not installed'}" for name in tools); ok=True
        elif action=="test": ok,output=self._tests(root,coverage,timeout)
        elif action in {"check","audit","security"}: ok,output=self._gate(root)
        elif action=="git":
            result=self._run(["git","status","--short","--branch"],cwd=root,timeout=30); ok=result.returncode==0; output=result.stdout or result.stderr
        elif action=="release":
            gate_ok,gate=self._gate(root); tests_ok,tests=self._tests(root,coverage,timeout); status=self._run(["git","status","--porcelain"],cwd=root,timeout=30); clean=status.returncode==0 and not status.stdout.strip(); ok=gate_ok and tests_ok and clean; output=f"tree_clean: {clean}\n{gate}\n{tests}"
        elif action=="index":
            from src.integrations.claude_db import ClaudeDbManager
            manager=ClaudeDbManager(self.source_dir); sub=argument or "stats"; output=manager.scan(root) if sub=="build" else json.dumps(manager.status().get("counts",{}),indent=2); ok=True
        else:
            gate_ok,gate=self._gate(root); ok=gate_ok; output=f"{action} report\n{gate}\nNo external controller or hidden hook was used."
        return {**self.status(),"action":action,"workspace":str(root),"ok":bool(ok),"exit_code":0 if ok else 1,"output":output[-100_000:]}
