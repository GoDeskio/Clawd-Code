"""Isolated Kronos inference worker; invoked by :mod:`src.integrations.kronos`."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    request_path, response_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    checkout = Path(request["checkout"]).resolve()
    sys.path.insert(0, str(checkout))

    import pandas as pd
    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer

    frame = pd.read_csv(request["input_csv"])
    lower = {str(column).strip().lower(): column for column in frame.columns}
    missing = [name for name in ("open", "high", "low", "close") if name not in lower]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
    timestamp_name = next((lower[name] for name in ("timestamp", "timestamps", "datetime", "date", "time") if name in lower), None)
    if timestamp_name is None:
        raise ValueError("CSV requires a timestamp/date/datetime column")
    timestamps = pd.to_datetime(frame[timestamp_name], errors="coerce", utc=True).dt.tz_convert(None)
    if timestamps.isna().any() or len(timestamps) < 2:
        raise ValueError("CSV timestamps are invalid or insufficient")
    price = pd.DataFrame({name: pd.to_numeric(frame[lower[name]], errors="coerce") for name in ("open", "high", "low", "close")})
    for optional in ("volume", "amount"):
        if optional in lower:
            price[optional] = pd.to_numeric(frame[lower[optional]], errors="coerce")
    if price.isna().any().any():
        raise ValueError("CSV contains non-numeric or missing OHLCV values")
    lookback = min(int(request["lookback"]), int(request["max_context"]), len(price))
    if lookback < 16:
        raise ValueError("Kronos requires at least 16 historical rows")
    price = price.iloc[-lookback:].reset_index(drop=True)
    history_ts = timestamps.iloc[-lookback:].reset_index(drop=True)
    delta = history_ts.diff().dropna().median()
    if pd.isna(delta) or delta <= pd.Timedelta(0):
        raise ValueError("CSV timestamps must be increasing at a consistent interval")
    pred_len = int(request["pred_len"])
    future_ts = pd.Series(pd.date_range(history_ts.iloc[-1] + delta, periods=pred_len, freq=delta))

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    tokenizer = KronosTokenizer.from_pretrained(request["tokenizer"])
    model = Kronos.from_pretrained(request["model"])
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=int(request["max_context"]))
    forecast = predictor.predict(price, history_ts, future_ts, pred_len=pred_len,
                                 T=float(request["temperature"]), top_p=float(request["top_p"]),
                                 sample_count=int(request["sample_count"]), verbose=False)
    forecast.index.name = "timestamp"
    output = Path(request["output_csv"]).resolve()
    forecast.to_csv(output, encoding="utf-8")
    response = {
        "ok": True, "path": str(output), "rows": len(forecast), "lookback": lookback,
        "model": request["model"], "model_key": request["model_key"], "device": device,
        "first_timestamp": forecast.index[0].isoformat(), "last_timestamp": forecast.index[-1].isoformat(),
        "last_close": float(forecast.iloc[-1]["close"]),
    }
    response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

