"""Quote reali dei bookmaker da The Odds API (piano gratuito: 500 crediti al mese).

Serve il secret ODDS_API_KEY. Ogni richiesta per un campionato costa 2 crediti (esito 1X2 + under/over gol).
Per stare nel limite si scaricano solo i campionati che giocano entro 2 giorni, al massimo una volta al giorno,
e ci si ferma se i crediti rimasti scendono sotto una riserva.
Bet365 non è tra i bookmaker disponibili: si usano la media dei bookmaker europei, la quota migliore
e Pinnacle (il bookmaker "di riferimento", con margini bassi).
"""
import json
import os
from datetime import date, datetime

import numpy as np
import pandas as pd
import requests

import calendario
import config

SPORTS = {"I1": "soccer_italy_serie_a", "E0": "soccer_epl", "SP1": "soccer_spain_la_liga",
          "D1": "soccer_germany_bundesliga", "F1": "soccer_france_ligue_one", "I2": "soccer_italy_serie_b",
          "E1": "soccer_efl_champ", "SP2": "soccer_spain_segunda_division", "D2": "soccer_germany_bundesliga2",
          "F2": "soccer_france_ligue_two"}
AHEAD_DAYS = 2
RESERVE = 30
STATE = config.DATA_DIR / "quote.json"


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _summ(prices: dict) -> dict | None:
    """prices: {bookmaker: quota} -> media, migliore, Pinnacle"""
    v = [p for p in prices.values() if p and p > 1]
    if len(v) < 2:
        return None
    return {"avg": round(float(np.mean(v)), 3), "best": round(float(max(v)), 3),
            "pin": round(prices["pinnacle"], 3) if prices.get("pinnacle") else None, "n": len(v)}


def _parse(ev: dict, home: str, away: str) -> dict:
    h2h, tot = {"1": {}, "X": {}, "2": {}}, {}
    for b in ev.get("bookmakers", []):
        for m in b.get("markets", []):
            if m["key"] == "h2h":
                for o in m["outcomes"]:
                    k = "X" if o["name"] == "Draw" else "1" if o["name"] == ev["home_team"] else "2" if o["name"] == ev["away_team"] else None
                    if k:
                        h2h[k][b["key"]] = o["price"]
            elif m["key"] == "totals":
                for o in m["outcomes"]:
                    pt = o.get("point")
                    if pt not in (1.5, 2.5, 3.5):
                        continue
                    k = f"goals_total_{'o' if o['name'] == 'Over' else 'u'}{pt}"
                    tot.setdefault(k, {})[b["key"]] = o["price"]
    out = {}
    for k, prices in {**h2h, **tot}.items():
        s = _summ(prices)
        if s:
            out[k] = s
    return out


def update(fixtures: pd.DataFrame) -> dict:
    """Restituisce {(codice, casa, ospite): {mercato: {avg, best, pin, n}}} serializzato come "codice|casa|ospite"."""
    st = _load()
    key = os.environ.get("ODDS_API_KEY", "").strip()
    cache = st.setdefault("events", {})
    if key and fixtures is not None and not fixtures.empty:
        today = pd.Timestamp.today().normalize()
        soon = fixtures[(fixtures["date"] >= today) & (fixtures["date"] <= today + pd.Timedelta(days=AHEAD_DAYS))]
        fetched = st.setdefault("fetched", {})
        for code in sorted(soon["league"].unique()):
            if code not in SPORTS or fetched.get(code) == str(date.today()):
                continue
            if st.get("remaining") is not None and st["remaining"] < RESERVE:
                print(f"  quote: crediti quasi finiti ({st['remaining']}), salto fino al rinnovo mensile")
                break
            try:
                r = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORTS[code]}/odds",
                                 params={"apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"},
                                 timeout=30)
                if r.headers.get("x-requests-remaining"):
                    st["remaining"] = int(float(r.headers["x-requests-remaining"]))
                if r.status_code in (401, 403):
                    print(f"  ! quote: chiave non valida o crediti finiti ({r.text[:120]})")
                    break
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"  ! quote {config.LEAGUES[code]}: non disponibili ({e})")
                continue
            fetched[code] = str(date.today())
            teams = sorted(set(fixtures.loc[fixtures["league"] == code, "home"]) | set(fixtures.loc[fixtures["league"] == code, "away"]))
            n = 0
            for ev in r.json():
                h = calendario.match_team([ev.get("home_team")], teams)
                a = calendario.match_team([ev.get("away_team")], teams)
                if not h or not a or h == a:
                    continue
                q = _parse(ev, h, a)
                if q:
                    cache[f"{code}|{h}|{a}"] = {"t": ev.get("commence_time"), "q": q}
                    n += 1
            print(f"  quote {config.LEAGUES[code]}: {n} partite (crediti rimasti {st.get('remaining', '?')})")
    elif not key:
        print("  quote: nessuna chiave The Odds API, salto")
    # via le partite già iniziate
    now = datetime.utcnow().isoformat()
    st["events"] = {k: v for k, v in cache.items() if (v.get("t") or "9999") > now}
    config.DATA_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))
    return {k: v["q"] for k, v in st["events"].items()}


def implied(q: dict, key: str) -> tuple[float, float, dict] | None:
    """Quota media e probabilità implicita senza margine (da Pinnacle se c'è, altrimenti dalla media)."""
    groups = {"1": ["1", "X", "2"], "X": ["1", "X", "2"], "2": ["1", "X", "2"]}
    if key.startswith("goals_total_"):
        ln = key[len("goals_total_") + 1:]
        groups[key] = [f"goals_total_o{ln}", f"goals_total_u{ln}"]
    if key not in groups or key not in q or any(k not in q for k in groups[key]):
        return None
    use = "pin" if all(q[k].get("pin") for k in groups[key]) else "avg"
    inv = [1 / q[k][use] for k in groups[key]]
    return q[key]["avg"], (1 / q[key][use]) / sum(inv), q[key]
