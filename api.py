"""API opzionale (FastAPI). Avvio:  uvicorn api:app --reload
Legge i risultati prodotti da run.py; utile per collegare in futuro un'app mobile o un frontend React."""
import json

from fastapi import FastAPI, HTTPException

import backtest
import config

app = FastAPI(title="Footstats API")


def _preds():
    path = config.OUTPUT_DIR / "predictions.json"
    if not path.exists():
        raise HTTPException(404, "Nessuna previsione: esegui prima python run.py")
    return json.loads(path.read_text())


@app.get("/leagues")
def leagues():
    return config.LEAGUES


@app.get("/predictions/upcoming")
def upcoming(league: str | None = None, min_prob: float = 0.0):
    out = []
    for m in _preds():
        if league and m["league"] != league:
            continue
        out.append({**m, "picks": [p for p in m["picks"] if p["prob"] >= min_prob]})
    return out


@app.get("/predictions/value")
def value(min_edge: float = config.MIN_EDGE):
    return [{"match": f"{m['home']} - {m['away']}", "date": m["date"], **p}
            for m in _preds() for p in m["picks"] if p.get("edge", -1) >= min_edge]


@app.get("/backtests")
def backtests():
    bt = backtest.load()
    if not bt:
        raise HTTPException(404, "Backtest non eseguito")
    return {k: bt[k] for k in ("periodo", "partite", "metrics", "value")}
