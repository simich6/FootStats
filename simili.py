"""Partite simili: nello storico dello stesso campionato cerca le partite che, PRIMA di giocarsi,
avevano un profilo simile (gol e tiri in porta attesi per le due squadre) e conta cosa è successo davvero.
È un controllo indipendente dalle percentuali del modello: se i due numeri concordano ci si può fidare di più.

I profili vengono salvati dal backtest (data/profili.csv): sono stime fatte solo con i dati precedenti
a ogni partita, quindi il confronto è onesto.
"""
import numpy as np
import pandas as pd

import config
import markets as mk

K = 40
FEATS = [("eg_h", 1.0), ("eg_a", 1.0), ("es_h", 0.7), ("es_a", 0.7)]  # i tiri in porta pesano un po' meno


def load() -> pd.DataFrame | None:
    path = config.DATA_DIR / "profili.csv"
    if not path.exists():
        return None
    p = pd.read_csv(path)
    p["date"] = pd.to_datetime(p["date"])
    return p


def prepare(prof: pd.DataFrame | None, hist: pd.DataFrame, league: str):
    """Profili del campionato uniti ai risultati veri. Restituisce (tabella, colonne usate, scale)."""
    if prof is None:
        return None
    pl = prof[prof["league"] == league]
    if len(pl) < 100:
        return None
    pl = pl.merge(hist.drop(columns=["league"], errors="ignore"), on=["date", "home", "away"], how="inner")
    feats = [(c, w) for c, w in FEATS if c in pl and pl[c].notna().mean() > 0.9]
    if not any(c.startswith("eg") for c, _ in feats):
        return None
    pl = pl.dropna(subset=[c for c, _ in feats])
    scale = {c: float(pl[c].std()) or 1.0 for c, _ in feats}
    return pl.reset_index(drop=True), feats, scale


def similar(prep, expected: dict) -> dict | None:
    if prep is None:
        return None
    pl, feats, scale = prep
    key = {"eg": "goals", "es": "sot"}
    x = {}
    for c, _ in feats:
        e = expected.get(key[c[:2]])
        if not e:
            return None
        x[c] = e[0] if c.endswith("_h") else e[1]
    d2 = np.zeros(len(pl))
    for c, w in feats:
        d2 += w * ((pl[c].to_numpy() - x[c]) / scale[c]) ** 2
    idx = np.argsort(d2)[:K]
    near = pl.iloc[idx]
    rows = near.to_dict("records")
    freq = {}
    for mdef in mk.MARKETS:
        ys = [y for r in rows if not np.isnan(y := mk.outcome(mdef, r))]
        if len(ys) >= K * 0.6:
            freq[mdef["key"]] = round(float(np.mean(ys)), 3)
    avg = {}
    for s in ("goals", "sot", "corners", "cards", "ht"):
        v = (near[f"h_{s}"] + near[f"a_{s}"]).dropna()
        if len(v) >= K * 0.6:
            avg[s] = round(float(v.mean()), 2)
    first, last = near["date"].min(), near["date"].max()
    return {"n": len(rows), "freq": freq, "avg": avg, "from": str(first.date()), "to": str(last.date()),
            "ex": [f"{r['home']}–{r['away']} {int(r['h_goals'])}-{int(r['a_goals'])}" for r in rows[:5]]}
