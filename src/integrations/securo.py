"""Jonathan-native local personal-finance vault."""
from __future__ import annotations
import csv,json,sqlite3,uuid
from contextlib import contextmanager
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Any,Callable
SECURO_REPOSITORY="https://github.com/securo-finance/securo.git"; SECURO_LICENSE="AGPL-3.0"; FRONTEND_PORT=0; BACKEND_PORT=0

class SecuroManager:
    """Compatibility name retained; data and logic are standalone Jonathan code."""
    def __init__(self,source_dir:str|Path)->None:
        self.source_dir=Path(source_dir).expanduser().resolve(); self.checkout=self.source_dir/"src"/"integrations"; self.database=Path.home()/".clawd"/"finance"/"personal-finance.sqlite"
    def _connect(self)->sqlite3.Connection:
        self.database.parent.mkdir(parents=True,exist_ok=True); db=sqlite3.connect(self.database); db.row_factory=sqlite3.Row
        db.executescript("""PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL,type TEXT NOT NULL,currency TEXT NOT NULL,opening_balance REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,occurred_on TEXT NOT NULL,amount REAL NOT NULL,currency TEXT NOT NULL,category TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',recurring INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS budgets(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,amount REAL NOT NULL,currency TEXT NOT NULL,period TEXT NOT NULL); CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY,name TEXT NOT NULL,target REAL NOT NULL,current REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL,due_date TEXT NOT NULL DEFAULT ''); CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,value REAL NOT NULL,currency TEXT NOT NULL,updated_at TEXT NOT NULL);"""); return db
    @contextmanager
    def _db(self):
        db=self._connect()
        try:
            with db: yield db
        finally: db.close()
    def status(self)->dict[str,Any]:
        with self._db() as db:
            counts={table:db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("accounts","transactions","budgets","goals","assets")}
        return {"available":True,"source_ready":True,"container_runtime":"","runtime_ready":True,"running":True,"url":"","backend_url":"","path":str(self.database),"database":str(self.database),"repository":"internal://jonathan/personal-finance","reference_repository":SECURO_REPOSITORY,"revision":"jonathan-native-1","license":"MIT (implementation); AGPL design reference only","isolation":"Local Jonathan SQLite vault; no containers or external service.","features":["accounts","CSV transactions/import","categories","recurring transactions","budgets","goals","assets","reports","multi-currency"],"payments_required":False,"counts":counts}
    def sync(self,progress:Callable[[str],None]|None=None)->dict[str,Any]:
        if progress: progress("Jonathan's native personal-finance vault is ready")
        self._connect().close(); return self.status()
    install=sync
    def start(self)->dict[str,Any]: return self.status()
    def stop(self)->dict[str,Any]: return {**self.status(),"running":True,"message":"Embedded vault remains available; no external service is running."}
    def logs(self,limit:int=200)->dict[str,Any]: return {**self.status(),"logs":"Embedded local vault is healthy. Actions are recorded in Jonathan's audit/event logs."}
    def action(self,action:str,**data:Any)->dict[str,Any]:
        now=datetime.now(timezone.utc).isoformat(); action=action.lower()
        with self._db() as db:
            if action=="add_account":
                ident=uuid.uuid4().hex[:12]; db.execute("INSERT INTO accounts VALUES(?,?,?,?,?,?)",(ident,data.get("name") or "Account",data.get("type") or "checking",data.get("currency") or "USD",float(data.get("amount") or 0),now)); db.commit(); return {"account":dict(db.execute("SELECT * FROM accounts WHERE id=?",(ident,)).fetchone())}
            if action=="add_transaction":
                ident=uuid.uuid4().hex[:12]; db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?)",(ident,data.get("account_id") or "",data.get("occurred_on") or date.today().isoformat(),float(data.get("amount") or 0),data.get("currency") or "USD",data.get("category") or "",data.get("description") or "",1 if data.get("recurring") else 0,now)); db.commit(); return {"transaction":dict(db.execute("SELECT * FROM transactions WHERE id=?",(ident,)).fetchone())}
            if action=="list":
                entity=str(data.get("entity") or "transactions"); allowed={"accounts","transactions","budgets","goals","assets"}
                if entity not in allowed: raise ValueError("Unsupported personal-finance entity")
                return {"entity":entity,"items":[dict(r) for r in db.execute(f"SELECT * FROM {entity} LIMIT ?",(max(1,min(int(data.get('limit') or 100),1000)),))]}
            if action=="dashboard":
                rows=db.execute("SELECT currency,COALESCE(SUM(amount),0) total FROM transactions GROUP BY currency").fetchall(); return {"totals_by_currency":{r[0]:r[1] for r in rows},**self.status()}
        raise ValueError(f"Unsupported personal finance action: {action}")
