"""Schedine a quota: ogni mattina propone, per ogni quota obiettivo (1,90 … 5,00), la combinazione di
giocate con la probabilità più alta che ci arriva; le salva e a partite finite le verifica.
Così in Andamento si vede quante schedine escono per ogni fascia di quota.

Stessa logica della sezione "Schedine a quota" della dashboard (che però usa anche i filtri personali
dell'utente: campionati e mercati scelti).
"""
import json
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

import config
import markets as mk

TARGETS = [1.9, 2.0, 2.5, 3.0, 3.5, 5.0]
MARGIN = {"1X2": .05, "DC": .05, "GGNG": .06, "OUG": .06, "GS": .08, "MG": .09, "MGS": .10, "HT": .09}
REL = {"green": 1.0, "yellow": 0.5, "red": 0.0}
DETAIL = ("corners", "cards", "fouls", "shots", "sot")
MDEF = {m["key"]: m for m in mk.MARKETS}
PATH = config.DATA_DIR / "schedine.json"


def family(key: str) -> str | None:
    d = MDEF.get(key)
    if not d:
        return None
    s, k = d["stat"], d["kind"]
    if s in ("ht", "sh"):
        return "HT"
    if k == "result":
        return "1X2" if key in ("1", "X", "2") else "DC"
    if k == "btts":
        return "GGNG"
    if k == "range":
        return "MG"
    if k.endswith("_range"):
        return "MGS"
    team = not k.startswith("total")
    pair = {"goals": ("OUG", "GS"), "corners": ("CT", "CS"), "cards": ("KT", "KS"), "fouls": ("FT", "FS"),
            "shots": ("ST", "SS"), "sot": ("OT", "OS")}.get(s)
    return pair[1 if team else 0] if pair else None


def _form(history: list[dict], days: int = 30, min_n: int = 6) -> dict:
    since = str(date.today() - timedelta(days=days))
    g = {}
    for h in history:
        if h.get("won") is None or h.get("void") or h.get("extra") or h["date"] < since:
            continue
        g.setdefault(family(h["key"]) or h["group"], []).append(h)
    return {k: np.mean([x["won"] for x in a]) - np.mean([x["prob"] for x in a]) for k, a in g.items() if len(a) >= min_n}


def grade(p: dict, form: dict) -> float:
    lift = p["prob"] - p["base"] if p.get("base") is not None else 0.0
    pr = p["prob"]
    f = form.get(family(p["key"]))
    parts = [(min(1, max(0, lift / .15)), .30), (REL.get(p.get("reliability"), .5), .25),
             (1.0 if .5 <= pr <= .78 else max(0, (pr - .3) / .2) if pr < .5 else max(0, (.92 - pr) / .14), .15),
             (min(1, max(0, (p["edge"] + .04) / .1)) if p.get("edge") is not None else .5, .15),
             (.5 if f is None else min(1, max(0, .5 + f / .2)), .15)]
    return sum(v * w for v, w in parts)


def _main_lines(f: dict) -> set:
    """Per corner, cartellini, falli e tiri: solo la linea principale (quella vicina al 50%)."""
    best = {}
    for p in f["picks"]:
        d = MDEF.get(p["key"])
        if not d or d["stat"] not in DETAIL or not d["kind"].endswith("over"):
            continue
        k = (d["stat"], d["kind"].split("_")[0])
        if k not in best or abs(p["prob"] - .5) < abs(best[k][1] - .5):
            best[k] = (d["args"][0], p["prob"])
    return {k: v[0] for k, v in best.items()}


def _legs(preds: list[dict], form: dict, days: int, has_bt: bool) -> list[dict]:
    now = datetime.now(timezone.utc)
    lim = now + timedelta(days=days)
    out = []
    for f in preds:
        if any(f["new_team"]) or f.get("exp"):
            continue
        ko = datetime.fromisoformat(f["ko"]) if f.get("ko") else datetime.fromisoformat(f["date"] + "T23:00:00+00:00")
        if not (now < ko < lim):
            continue
        main = _main_lines(f)
        cands = []
        for p in f["picks"]:
            d = MDEF.get(p["key"])
            if d is None or not .38 <= p["prob"] <= .88 or (has_bt and p.get("reliability") == "red"):
                continue
            if p.get("base") is not None and p["prob"] - p["base"] < -.01:
                continue
            if d["stat"] in DETAIL and d["kind"].split("_")[-1] in ("over", "under") \
                    and main.get((d["stat"], d["kind"].split("_")[0])) != d["args"][0]:
                continue
            g = grade(p, form)
            if g < .44:  # pagella D
                continue
            cands.append((g, p))
        seen = set()
        for g, p in sorted(cands, key=lambda x: -x[0]):
            fa = family(p["key"])
            if fa in seen or len(seen) >= 3:
                continue
            seen.add(fa)
            odds = p.get("odds") or max(1.01, (1 / p["prob"]) * (1 - MARGIN.get(fa, .10)))
            out.append({"f": f, "p": p, "g": g, "o": float(odds), "real": bool(p.get("odds"))})
    return out


def build(preds: list[dict], target: float, history: list[dict], has_bt: bool, n: int = 1) -> list[dict]:
    form = _form(history)
    for days in (3, 7):
        hi = target * 1.18
        allc = [x for x in _legs(preds, form, days, has_bt) if 1.08 < x["o"] <= hi and (target >= 3.5 or x["p"]["prob"] >= .45)]
        by_eff = sorted(allc, key=lambda x: -x["p"]["prob"] * x["o"])[:30]
        by_prob = sorted(allc, key=lambda x: -x["p"]["prob"])[:12]
        L = sorted({id(x): x for x in by_eff + by_prob}.values(), key=lambda x: x["o"])
        res, legs, used = [], [], set()

        def rec(start, odds, prob):
            if odds >= target:
                res.append((list(legs), odds, prob))
                return
            if len(legs) >= 4:
                return
            for i in range(start, len(L)):
                x = L[i]
                key = (x["f"]["home"], x["f"]["away"], x["f"]["date"])
                no = odds * x["o"]
                if key in used or no > hi:
                    continue
                legs.append(x)
                used.add(key)
                rec(i + 1, no, prob * x["p"]["prob"])
                legs.pop()
                used.discard(key)
        rec(0, 1.0, 1.0)
        if res:
            res.sort(key=lambda r: -(r[2] + .02 * np.mean([x["g"] for x in r[0]])))
            out = []
            for r in res:
                if all(len([x for x in r[0] if x in o[0]]) <= 1 for o in out):
                    out.append(r)
                if len(out) == n:
                    break
            return [{"target": target, "odds": round(o, 2), "prob": round(p, 4), "real": all(x["real"] for x in L_),
                     "legs": [{"date": x["f"]["date"], "ko": x["f"].get("ko"), "code": x["f"]["code"], "league": x["f"]["league"],
                               "home": x["f"]["home"], "away": x["f"]["away"], "key": x["p"]["key"], "group": x["p"]["group"],
                               "label": x["p"]["label"], "prob": x["p"]["prob"], "odds": round(x["o"], 2)} for x in L_]}
                    for L_, o, p in out]
    return []


def propose(preds: list[dict], history: list[dict], has_bt: bool) -> list[dict]:
    today = str(date.today())
    out = []
    for t in TARGETS:
        for s in build(preds, t, history, has_bt):
            s.update(id=f"{today}|{t}", day=today, won=None)
            out.append(s)
    return out


def _remote_url() -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/")
    return f"https://{owner.lower()}.github.io/{name}/schedine.json"


def load() -> list[dict]:
    if PATH.exists():
        return json.loads(PATH.read_text())
    url = _remote_url()
    if url:
        try:
            r = requests.get(url, timeout=20)
            if r.ok:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
    return []


def update(past: list[dict], proposals: list[dict], matches: pd.DataFrame) -> list[dict]:
    by_id = {s["id"]: s for s in past}
    for s in proposals:  # la proposta del giorno si salva una volta sola (la prima della giornata)
        by_id.setdefault(s["id"], s)
    for s in by_id.values():
        if s.get("won") is not None:
            continue
        outs = []
        for leg in s["legs"]:
            d = pd.Timestamp(leg["date"])
            m = matches[(matches["league"] == leg["code"]) & (matches["home"] == leg["home"]) & (matches["away"] == leg["away"])
                        & (matches["date"] >= d - pd.Timedelta(days=3)) & (matches["date"] <= d + pd.Timedelta(days=10))]
            if m.empty or leg["key"] not in MDEF:
                outs.append(None)
                continue
            y = mk.outcome(MDEF[leg["key"]], m.iloc[0])
            leg["won"] = None if np.isnan(y) else int(y)
            outs.append(leg["won"] if not np.isnan(y) else "void")
        if any(o == 0 for o in outs):
            s["won"] = 0
        elif outs and all(o == 1 for o in outs):
            s["won"] = 1
        elif outs and all(o is not None for o in outs):
            s["won"], s["void"] = 0, True  # un dato mancante: la schedina non si può verificare
    # teniamo gli ultimi 6 mesi
    cut = str(date.today() - timedelta(days=183))
    return sorted((s for s in by_id.values() if s["day"] >= cut), key=lambda s: (s["day"], s["target"]))


def save(slips: list[dict]) -> None:
    blob = json.dumps(slips, ensure_ascii=False)
    PATH.write_text(blob)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    (config.OUTPUT_DIR / "schedine.json").write_text(blob)


def summary(slips: list[dict]) -> dict:
    out = {}
    for t in TARGETS:
        a = [s for s in slips if s["target"] == t and s.get("won") is not None and not s.get("void")]
        if a:
            out[str(t)] = {"n": len(a), "won": sum(s["won"] for s in a), "pred": round(float(np.mean([s["prob"] for s in a])), 4),
                           "roi": round(float(np.mean([s["odds"] - 1 if s["won"] else -1 for s in a])), 4)}
    return out
