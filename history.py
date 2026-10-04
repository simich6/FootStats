"""Storico automatico delle previsioni: salva le giocate del Top e le verifica a partita finita.

Lo storico viene salvato in data/history.json e pubblicato con la dashboard (history.json).
Su GitHub, se la cache dei dati si perde, viene recuperato dalla pagina pubblicata.
"""
import json
import os

import numpy as np
import pandas as pd
import requests

import config
import markets as mk

MDEF = {m["key"]: m for m in mk.MARKETS}
CAP, GAP = 0.85, 0.05  # stesse regole del Top della settimana


def top_candidates(preds: list[dict], has_backtest: bool) -> list[dict]:
    """Per ogni partita: la giocata più probabile + fino a 2 alternative entro 5 punti su mercati diversi."""
    out = []
    for f in preds:
        if any(f["new_team"]):
            continue
        ok = sorted((p for p in f["picks"] if (not has_backtest or p["reliability"] != "red") and p["prob"] <= CAP),
                    key=lambda p: -p["prob"])
        if not ok:
            continue
        chosen, groups = [ok[0]], {ok[0]["group"]}
        for p in ok[1:]:
            if len(chosen) >= 3:
                break
            if ok[0]["prob"] - p["prob"] <= GAP and p["group"] not in groups:
                chosen.append(p)
                groups.add(p["group"])
        for k, p in enumerate(chosen):
            out.append({"id": f"{f['date']}|{f['home']}|{f['away']}|{p['key']}", "date": f["date"],
                        "league": f["league"], "code": f["code"], "home": f["home"], "away": f["away"],
                        "key": p["key"], "group": p["group"], "label": p["label"], "prob": p["prob"],
                        "main": k == 0, "won": None})
    return out


def _remote_url() -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")  # es. simich6/FootStats, presente solo su GitHub
    if not repo:
        return None
    owner, name = repo.split("/")
    return f"https://{owner.lower()}.github.io/{name}/history.json"


def load() -> list[dict]:
    path = config.DATA_DIR / "history.json"
    if path.exists():
        return json.loads(path.read_text())
    url = _remote_url()
    if url:
        try:
            r = requests.get(url, timeout=20)
            if r.ok:
                print("    storico recuperato dalla pagina pubblicata")
                return r.json()
        except (requests.RequestException, ValueError):
            pass
    return []


def _find_result(matches: pd.DataFrame, rec: dict):
    d = pd.Timestamp(rec["date"])
    m = matches[(matches["league"] == rec["code"]) & (matches["home"] == rec["home"]) & (matches["away"] == rec["away"])
                & (matches["date"] >= d - pd.Timedelta(days=3)) & (matches["date"] <= d + pd.Timedelta(days=10))]
    return None if m.empty else m.iloc[0]


def update(history: list[dict], candidates: list[dict], matches: pd.DataFrame) -> list[dict]:
    today = str(pd.Timestamp.today().date())
    by_id = {h["id"]: h for h in history}
    # le giocate di partite non ancora giocate vengono aggiornate fino al calcio d'inizio
    open_future = {i for i, h in by_id.items() if h["won"] is None and h["date"] >= today}
    current = {c["id"] for c in candidates}
    for i in open_future - current:
        del by_id[i]  # non è più tra le migliori: esce dallo storico
    for c in candidates:
        if c["id"] not in by_id or by_id[c["id"]]["won"] is None:
            by_id[c["id"]] = c
    # verifica delle partite giocate
    for h in by_id.values():
        if h["won"] is not None or h["key"] not in MDEF:
            continue
        res = _find_result(matches, h)
        if res is not None:
            y = mk.outcome(MDEF[h["key"]], res)
            h["won"] = None if np.isnan(y) else int(y)
            h["result"] = f"{int(res['h_goals'])}-{int(res['a_goals'])}"
            if np.isnan(y):
                h["void"] = True  # statistica non disponibile
    return sorted(by_id.values(), key=lambda h: (h["date"], h["home"]))


def save(history: list[dict]) -> None:
    blob = json.dumps(history, ensure_ascii=False)
    (config.DATA_DIR / "history.json").write_text(blob)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    (config.OUTPUT_DIR / "history.json").write_text(blob)


def recent_results(matches: pd.DataFrame, days: int = 45) -> list[dict]:
    """Risultati recenti per chiudere in automatico le giocate del diario."""
    cut = pd.Timestamp.today() - pd.Timedelta(days=days)
    cols = [f"{s}_{st}" for st in ("goals", "shots", "sot", "corners", "fouls", "cards") for s in ("h", "a")]
    out = []
    for _, m in matches[matches["date"] >= cut].iterrows():
        r = {"date": str(m["date"].date()), "home": m["home"], "away": m["away"]}
        for c in cols:
            r[c] = None if pd.isna(m[c]) else float(m[c])
        out.append(r)
    return out


def market_defs() -> dict:
    return {m["key"]: {"stat": m["stat"], "kind": m["kind"], "args": list(m["args"])} for m in mk.MARKETS}
