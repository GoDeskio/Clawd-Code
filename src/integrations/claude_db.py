"""Jonathan-native UTF-8 SQLite code graph and durable code notes."""

from __future__ import annotations

import ast
import re
import sqlite3
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CLAUDE_DB_REPOSITORY = "https://github.com/Avijit07x/claude-db.git"
CLAUDE_DB_LICENSE = "Apache-2.0"
SUPPORTED = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", "Integrations"}
SYMBOL_RE = re.compile(r"(?m)^\s*(?:async\s+)?(?:def|class|function|func|fn|interface|struct|enum)\s+([A-Za-z_$][\w$]*)")


class ClaudeDbManager:
    """Compatibility name retained while the implementation is fully Jonathan-native."""

    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir).expanduser().resolve()
        self.checkout = self.source_dir / "src" / "integrations"
        self.database = Path.home() / ".clawd" / "code_memory" / "jonathan-code-memory.sqlite"

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, project TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text, content='notes', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN INSERT INTO notes_fts(rowid,text) VALUES(new.id,new.text); END;
            CREATE TABLE IF NOT EXISTS files(project TEXT NOT NULL, path TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, PRIMARY KEY(project,path));
            CREATE TABLE IF NOT EXISTS symbols(project TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, line INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS symbols_project_name ON symbols(project,name);
            CREATE TABLE IF NOT EXISTS edges(project TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, path TEXT NOT NULL, line INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS edges_project_source ON edges(project,source);
        """)
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self) -> dict[str, Any]:
        try:
            with self._db() as db:
                notes = db.execute("SELECT count(*) FROM notes").fetchone()[0]
                symbols = db.execute("SELECT count(*) FROM symbols").fetchone()[0]
                files = db.execute("SELECT count(*) FROM files").fetchone()[0]
            ready = True
        except sqlite3.Error:
            notes = symbols = files = 0; ready = False
        return {"available": True, "source_ready": True, "runtime_ready": ready, "database": str(self.database),
                "repository": "internal://jonathan/code-memory", "reference_repository": CLAUDE_DB_REPOSITORY,
                "revision": "jonathan-native-1", "license": "MIT (implementation); Apache-2.0 design reference",
                "local_only": True, "hooks_installed": False, "payments_required": False,
                "counts": {"notes": notes, "symbols": symbols, "files": files},
                "features": ["incremental code graph", "symbol usages", "dependency paths", "local search", "manual durable notes"]}

    def sync(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        if progress: progress("Initializing Jonathan's native code-memory database")
        self._connect().close()
        return self.status()

    install = sync

    @staticmethod
    def _project(root: Path) -> str: return str(root).casefold()

    @staticmethod
    def _files(root: Path):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED and not any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                try:
                    if path.stat().st_size <= 2_000_000: yield path
                except OSError: continue

    @staticmethod
    def _extract(path: Path, root: Path) -> tuple[list[tuple[str, str, str, int]], list[tuple[str, str, str, int]]]:
        text = path.read_text(encoding="utf-8", errors="replace"); rel = path.relative_to(root).as_posix()
        symbols: list[tuple[str, str, str, int]] = []; edges: list[tuple[str, str, str, int]] = []
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbols.append((node.name, "class" if isinstance(node, ast.ClassDef) else "function", rel, node.lineno))
                    elif isinstance(node, ast.Call):
                        target = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                        if target: edges.append((rel, target, rel, getattr(node, "lineno", 1)))
                    elif isinstance(node, (ast.Import, ast.ImportFrom)):
                        for name in (a.name for a in node.names): edges.append((rel, name, rel, getattr(node, "lineno", 1)))
                return symbols, edges
            except SyntaxError: pass
        for match in SYMBOL_RE.finditer(text): symbols.append((match.group(1), "symbol", rel, text.count("\n", 0, match.start()) + 1))
        return symbols, edges

    def scan(self, root: Path, *, force: bool = False) -> str:
        project = self._project(root); parsed = skipped = symbol_count = edge_count = 0
        with self._db() as db:
            known = {row[0]: (row[1], row[2]) for row in db.execute("SELECT path,mtime_ns,size FROM files WHERE project=?", (project,))}; seen: set[str] = set()
            for path in self._files(root):
                rel = path.relative_to(root).as_posix(); seen.add(rel); stat = path.stat()
                if not force and known.get(rel) == (stat.st_mtime_ns, stat.st_size): skipped += 1; continue
                db.execute("DELETE FROM symbols WHERE project=? AND path=?", (project, rel)); db.execute("DELETE FROM edges WHERE project=? AND path=?", (project, rel))
                symbols, edges = self._extract(path, root)
                db.executemany("INSERT INTO symbols(project,name,kind,path,line) VALUES(?,?,?,?,?)", ((project,*row) for row in symbols))
                db.executemany("INSERT INTO edges(project,source,target,path,line) VALUES(?,?,?,?,?)", ((project,*row) for row in edges))
                db.execute("INSERT OR REPLACE INTO files(project,path,mtime_ns,size) VALUES(?,?,?,?)", (project,rel,stat.st_mtime_ns,stat.st_size))
                parsed += 1; symbol_count += len(symbols); edge_count += len(edges)
            for rel in set(known) - seen:
                db.execute("DELETE FROM files WHERE project=? AND path=?", (project,rel)); db.execute("DELETE FROM symbols WHERE project=? AND path=?", (project,rel)); db.execute("DELETE FROM edges WHERE project=? AND path=?", (project,rel))
        return f"Scanned {root}\n  {parsed} parsed, {skipped} unchanged\n  {symbol_count} symbols, {edge_count} edges updated"

    def execute(self, action: str, *, workspace: str | Path, query: str = "", target: str = "", mode: str = "text", force: bool = False, limit: int = 100) -> dict[str, Any]:
        action = action.strip().lower(); root = Path(workspace).expanduser().resolve(); project = self._project(root); limit = max(1,min(limit,1000))
        if action == "status": return self.status()
        if action in {"sync","install","repair"}: return self.sync()
        if action == "scan": output = self.scan(root, force=force)
        elif action == "remember":
            if not query.strip(): raise ValueError("text to remember is required")
            with self._db() as db: db.execute("INSERT INTO notes(project,text,created_at) VALUES(?,?,?)", (project,query.strip(),datetime.now(timezone.utc).isoformat()))
            output = "Remembered in Jonathan's local code-memory database."
        elif action == "search":
            if not query.strip(): raise ValueError("query is required")
            with self._db() as db: rows = db.execute("SELECT n.text,n.created_at FROM notes_fts f JOIN notes n ON n.id=f.rowid WHERE notes_fts MATCH ? AND n.project=? LIMIT ?", (query,project,limit)).fetchall()
            output = "\n".join(f"{r['created_at']}  {r['text']}" for r in rows) or "No matching notes."
        else:
            selected = action if action in {"explain","path"} else mode
            if not query.strip(): raise ValueError("symbol or search text is required")
            if selected == "text":
                matches=[]
                for path in self._files(root):
                    for number,line in enumerate(path.read_text(encoding="utf-8",errors="replace").splitlines(),1):
                        if query.casefold() in line.casefold(): matches.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
                        if len(matches)>=limit: break
                    if len(matches)>=limit: break
                output="\n".join(matches) or "No live text matches."
            else:
                self.scan(root)
                with self._db() as db:
                    defs=db.execute("SELECT kind,path,line FROM symbols WHERE project=? AND name=? LIMIT ?",(project,query,limit)).fetchall(); refs=db.execute("SELECT source,path,line FROM edges WHERE project=? AND target=? LIMIT ?",(project,query,limit)).fetchall()
                    if selected=="path":
                        if not target.strip(): raise ValueError("target symbol is required for path mode")
                        graph: dict[str,set[str]]={}
                        for row in db.execute("SELECT source,target FROM edges WHERE project=?",(project,)): graph.setdefault(row[0],set()).add(row[1])
                        queue=deque([(query,[query])]); found=[]; visited={query}
                        while queue:
                            node,path=queue.popleft()
                            if node==target: found=path; break
                            for nxt in graph.get(node,set()):
                                if nxt not in visited: visited.add(nxt); queue.append((nxt,path+[nxt]))
                        output=" -> ".join(found) if found else f"No dependency path found from {query} to {target}."
                    else: output="\n".join([*(f"definition {r['kind']} {r['path']}:{r['line']}" for r in defs),*(f"reference from {r['source']} at {r['path']}:{r['line']}" for r in refs)]) or "No graph matches."
        return {**self.status(),"action":action,"workspace":str(root),"output":output}
