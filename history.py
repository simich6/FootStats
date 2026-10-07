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
LO, HI, GAP = 0.40, 0.75, 1.0  # stesse regole del Top della settimana (fascia predefinita 50-75%)


def top_candidates(preds: list[dict], has_backtest: bool) -> list[dict]:
    """Per ogni partita: le 5 giocate più probabili nella fascia, su mercati diversi (come il Top con la tendina)."""
    out = []
    for f in preds:
        if any(f["new_team"]):
            continue
        ok = sorted((p for p in f["picks"] if (not has_backtest or p["reliability"] != "red") and LO <= p["prob"] <= HI),
                    key=lambda p: -p["prob"])
        if not ok:
            continue
        chosen, seen = [], set()
        for p in ok:
            if len(chosen) >= 5:
                break
            fam = (p["group"], p["label"].split(" ")[0] if p["label"].startswith(("Casa", "Ospite")) else "")
            if fam in seen:
                continue
            chosen.append(p)
            seen.add(fam)
        for k, p in enumerate(chosen):
            out.append({"id": f"{f['date']}|{f['home']}|{f['away']}|{p['key']}", "date": f["date"],
                        "league": f["league"], "code": f["code"], "home": f["home"], "away": f["away"],
                        "key": p["key"], "group": p["group"], "label": p["label"], "prob": p["prob"],
                        "raw": p.get("raw", p["prob"]), "main": k == 0, "won": None})
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


# ---------- Apprendimento adattivo ----------
ADAPT_MIN = 50       # previsioni verificate necessarie prima di correggere un mercato
ADAPT_PRIOR = 200    # zavorra: con 200 previsioni la correzione vale metà di quella stimata
K_GRID = np.arange(0.6, 1.41, 0.02)


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def adaptive(history: list[dict]) -> dict:
    """Mercato per mercato confronta quanto il modello prevedeva (prima della correzione) e quanto è
    uscito nelle giocate proposte, e stima un fattore k: le percentuali future diventano
    logit(p') = k * logit(p). k < 1 = percentuali più prudenti (il modello era troppo sicuro),
    k > 1 = più decise. È coerente: Goal e No Goal, Over e Under restano complementari."""
    out = {}
    groups: dict[str, list] = {}
    for h in history:
        if h.get("won") is not None:
            groups.setdefault(h["group"], []).append(h)
    for g, rows in groups.items():
        n = len(rows)
        raw = np.array([r.get("raw", r["prob"]) for r in rows], float)
        y = np.array([r["won"] for r in rows], float)
        lr = _logit(raw)
        best_k, best_ll = 1.0, np.inf
        for k in K_GRID:
            p = np.clip(1 / (1 + np.exp(-k * lr)), 1e-6, 1 - 1e-6)
            ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
            if ll < best_ll:
                best_k, best_ll = float(k), ll
        weight = n / (n + ADAPT_PRIOR)
        k = 1 + (best_k - 1) * weight if n >= ADAPT_MIN else 1.0
        out[g] = {"n": n, "pred": round(float(raw.mean()), 4), "hit": round(float(y.mean()), 4),
                  "k": round(k, 3), "active": n >= ADAPT_MIN}
    return out


def apply_adaptive(preds: list[dict], adapt: dict) -> None:
    """Applica la correzione alle percentuali; la probabilità originale resta in "raw"."""
    for f in preds:
        for p in f["picks"]:
            k = adapt.get(p["group"], {}).get("k", 1.0)
            p["raw"] = p["prob"]
            if abs(k - 1) < 1e-3:
                continue
            new = float(1 / (1 + np.exp(-k * _logit(p["prob"]))))
            p["adj"] = round(new - p["prob"], 4)
            p["prob"] = round(new, 4)
            p["fair_odds"] = round(1 / p["prob"], 2)
            if p.get("implied") is not None:
                p["edge"] = round(p["prob"] - p["implied"], 4)
                p["ev"] = round(p["prob"] * p["odds"] - 1, 4)
