"""Jonathan-native probabilistic OHLCV research forecasting engine."""
from __future__ import annotations
import math
import importlib.util
from pathlib import Path
from typing import Any,Callable
KRONOS_REPOSITORY="https://github.com/shiyu-coder/Kronos.git"; KRONOS_LICENSE="MIT"
MODELS={"mini":{"paths":1000},"small":{"paths":3000},"base":{"paths":8000}}

class KronosManager:
    """Compatibility name retained; no upstream checkout or runtime is required."""
    def __init__(self,source_dir:str|Path)->None:
        self.source_dir=Path(source_dir).expanduser().resolve(); self.checkout=self.source_dir/"src"/"integrations"; self.venv=Path(); self.cache=Path.home()/".clawd"/"forecast-cache"
    def status(self)->dict[str,Any]:
        ready=all(importlib.util.find_spec(module) is not None for module in ("numpy","pandas"))
        return {"available":True,"source_ready":True,"runtime_ready":ready,"runtime_python":"","repository":"internal://jonathan/market-forecast",
                "reference_repository":KRONOS_REPOSITORY,"revision":"jonathan-native-1","license":"MIT","models":list(MODELS),"device":"cpu",
                "disclaimer":"Research forecast only; not investment advice and never places orders."}
    def sync(self,progress:Callable[[str],None]|None=None)->dict[str,Any]:
        if progress: progress("Jonathan's native market forecast engine is ready")
        return self.status()
    install=sync
    def forecast(self,input_csv:str|Path,output_csv:str|Path,*,model:str="mini",pred_len:int=24,lookback:int=400,sample_count:int=1,temperature:float=1.0,top_p:float=.9,timeout:int=1800)->dict[str,Any]:
        if model not in MODELS: raise ValueError(f"Unsupported model: {model}")
        import numpy as np
        import pandas as pd
        source=Path(input_csv).expanduser().resolve(); target=Path(output_csv).expanduser().resolve()
        if not source.is_file(): raise ValueError(f"OHLCV CSV does not exist: {source}")
        data=pd.read_csv(source); cols={str(c).lower():c for c in data.columns}
        if "close" not in cols: raise ValueError("CSV must contain close")
        close=pd.to_numeric(data[cols["close"]],errors="coerce").dropna().tail(max(16,lookback)).to_numpy(float)
        if len(close)<2: raise ValueError("At least two valid close rows are required")
        returns=np.diff(np.log(np.maximum(close,1e-12))); weights=np.exp(np.linspace(-3,0,len(returns))); weights/=weights.sum(); drift=float(np.sum(returns*weights)); vol=float(np.sqrt(np.sum(weights*(returns-drift)**2)))
        rng=np.random.default_rng(int(abs(close[-1])*1_000_003)%2**32); paths=MODELS[model]["paths"]*max(1,min(sample_count,20)); shocks=rng.normal(drift, max(vol,1e-8)*max(.05,temperature),(paths,pred_len)); simulated=close[-1]*np.exp(np.cumsum(shocks,axis=1))
        median=np.median(simulated,axis=0); low=np.quantile(simulated,.1,axis=0); high=np.quantile(simulated,.9,axis=0)
        interval=None
        if "timestamp" in cols:
            parsed=pd.to_datetime(data[cols["timestamp"]],errors="coerce").dropna()
            if len(parsed)>=2: interval=parsed.iloc[-1]-parsed.iloc[-2]
            stamps=[(parsed.iloc[-1]+(i+1)*(interval or pd.Timedelta(days=1))).isoformat() for i in range(pred_len)] if len(parsed) else list(range(1,pred_len+1))
        else: stamps=list(range(len(data),len(data)+pred_len))
        output=pd.DataFrame({"timestamp":stamps,"open":np.r_[close[-1],median[:-1]],"high":high,"low":low,"close":median,"p10":low,"p90":high})
        target.parent.mkdir(parents=True,exist_ok=True); output.to_csv(target,index=False)
        return {"ok":True,"path":str(target),"rows":pred_len,"device":"cpu","engine":"Jonathan probabilistic EWMA Monte Carlo","model":model,"paths":paths,
                "revision":"jonathan-native-1","repository":"internal://jonathan/market-forecast","reference_repository":KRONOS_REPOSITORY,
                "disclaimer":"Research forecast only; validate with walk-forward testing, costs, slippage, and risk controls. Not investment advice."}
