"""Giocatori e assenti da API-Football (api-sports.io), piano gratuito: 100 richieste al giorno.

Serve il secret API_FOOTBALL_KEY. Senza chiave, o se il servizio non risponde, l'app funziona come prima.
Per stare nel limite giornaliero i dati dei giocatori vengono salvati e aggiornati un po' alla volta:
prima le squadre che giocano prima, ogni squadra al massimo una volta a settimana.
"""
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd
import requests

import calendario
import config

BASE = "https://v3.football.api-sports.io"
LEAGUE_IDS = {"I1": 135, "E0": 39, "SP1": 140, "D1": 78, "F1": 61,
              "I2": 136, "E1": 40, "SP2": 141, "D2": 79, "F2": 62}
DAILY_BUDGET = 90        # richieste al giorno (il limite gratuito è 100: ne lasciamo un po' di margine)
REFRESH_DAYS = 6         # ogni quanti giorni aggiornare i giocatori di una squadra
AHEAD_DAYS = 4           # squadre che giocano entro questi giorni
STATE = config.DATA_DIR / "giocatori.json"


class Stop(Exception):
    pass


def _season() -> int:
    t = date.today()
    return t.year if t.month >= 7 else t.year - 1


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


class Client:
    def __init__(self, key: str, st: dict):
        self.key, self.st = key, st
        today = str(date.today())
        if st.get("day") != today:
            st["day"], st["used"] = today, 0

    def get(self, path: str, **params):
        if self.st["used"] >= DAILY_BUDGET:
            raise Stop("limite giornaliero raggiunto, continuo domani")
        self.st["used"] += 1
        r = requests.get(f"{BASE}/{path}", params=params, headers={"x-apisports-key": self.key}, timeout=30)
        r.raise_for_status()
        js = r.json()
        err = js.get("errors")
        if err:
            msg = "; ".join(f"{k}: {v}" for k, v in err.items()) if isinstance(err, dict) else str(err)
            if any(w in msg.lower() for w in ("plan", "season", "subscription", "requests", "limit", "token", "key")):
                raise Stop(msg)
            print(f"  ! giocatori: {path} → {msg}")
            return []
        return js


def _team_ids(cl: Client, code: str, season: int, teams: list[str]) -> dict:
    cache = cl.st.setdefault("team_ids", {}).setdefault(f"{code}_{season}", {})
    if cache and all(t in cache for t in teams):
        return cache
    if cache.get("_done"):
        return cache
    js = cl.get("teams", league=LEAGUE_IDS[code], season=season)
    api = [(x["team"]["id"], x["team"]["name"]) for x in (js.get("response", []) if js else [])]
    for tid, name in api:
        ours = calendario.match_team([name], teams)
        if ours:
            cache[ours] = tid
    cache["_done"] = True
    missing = [t for t in teams if t not in cache]
    if missing:
        print(f"  ! giocatori: squadre non riconosciute in {config.LEAGUES[code]}: {missing}")
    return cache


def _players(cl: Client, tid: int, season: int, league_id: int) -> list[dict]:
    out, page, pages = [], 1, 1
    while page <= pages:
        js = cl.get("players", team=tid, season=season, page=page)
        if not js:
            break
        pages = min(js.get("paging", {}).get("total", 1), 4)
        for x in js.get("response", []):
            pl, stats = x.get("player", {}), x.get("statistics", [])
            s = next((s for s in stats if (s.get("league") or {}).get("id") == league_id), None)
            if not s:
                continue
            g, sh = s.get("games") or {}, s.get("shots") or {}
            apps, mins = g.get("appearences") or 0, g.get("minutes") or 0
            if not apps or mins < 90:
                continue
            out.append({"id": pl.get("id"), "n": pl.get("name"), "pos": (g.get("position") or "")[:1],
                        "apps": apps, "min": mins, "sot": sh.get("on") or 0, "sh": sh.get("total") or 0,
                        "g": (s.get("goals") or {}).get("total") or 0,
                        "inj": bool(pl.get("injured"))})
        page += 1
    out.sort(key=lambda p: -(p["sot"] / max(p["apps"], 1)))
    return out[:14]


def _injuries(cl: Client, code: str, season: int, teams_ids: dict) -> dict:
    """Assenti per le partite dei prossimi giorni: {squadra: [{n, reason, type}]}"""
    js = cl.get("injuries", league=LEAGUE_IDS[code], season=season)
    if not js:
        return {}
    by_id = {v: k for k, v in teams_ids.items() if k != "_done"}
    today, lim = date.today(), date.today() + timedelta(days=AHEAD_DAYS + 1)
    out = {}
    for x in js.get("response", []):
        try:
            d = datetime.fromisoformat(x["fixture"]["date"].replace("Z", "+00:00")).date()
        except (KeyError, TypeError, ValueError):
            continue
        team = by_id.get((x.get("team") or {}).get("id"))
        if not team or not (today <= d <= lim):
            continue
        pl = x.get("player") or {}
        lst = out.setdefault(team, [])
        if all(p["id"] != pl.get("id") for p in lst):
            lst.append({"id": pl.get("id"), "n": pl.get("name"), "type": pl.get("type"), "reason": pl.get("reason"),
                        "date": str(d)})
    return out


def update(fixtures: pd.DataFrame, matches: pd.DataFrame) -> dict:
    """Aggiorna la cache. Restituisce {"players": {squadra: [...]}, "injuries": {squadra: [...]}}."""
    st = _load()
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        print("  giocatori: nessuna chiave API-Football, salto")
        return st.get("out", {"players": {}, "injuries": {}})
    if fixtures is None or fixtures.empty:
        return st.get("out", {"players": {}, "injuries": {}})
    cl, season = Client(key, st), _season()
    today = pd.Timestamp.today().normalize()
    soon = fixtures[(fixtures["date"] >= today) & (fixtures["date"] <= today + pd.Timedelta(days=AHEAD_DAYS))].sort_values("date")
    players = st.setdefault("players", {})
    injuries = {}
    current = matches["season"].max()
    try:
        ids = {}
        for code in soon["league"].unique():
            cur = matches[(matches["league"] == code) & (matches["season"] == current)]
            ids[code] = _team_ids(cl, code, season, sorted(set(cur["home"]) | set(cur["away"])))
        for code in soon["league"].unique():
            injuries.update(_injuries(cl, code, season, ids[code]))
        st["injuries"] = {"day": str(date.today()), "data": injuries}
        for _, f in soon.iterrows():
            for team in (f["home"], f["away"]):
                rec = players.get(team)
                if rec and (date.today() - date.fromisoformat(rec["updated"])).days < REFRESH_DAYS:
                    continue
                tid = ids.get(f["league"], {}).get(team)
                if not tid:
                    continue
                players[team] = {"updated": str(date.today()), "list": _players(cl, tid, season, LEAGUE_IDS[f["league"]])}
    except Stop as e:
        print(f"  giocatori: mi fermo qui ({e})")
        if "plan" in str(e).lower() or "season" in str(e).lower():
            print("  ! giocatori: il piano gratuito di API-Football non sembra coprire la stagione in corso")
    except requests.RequestException as e:
        print(f"  ! giocatori: servizio non raggiungibile ({e})")
    inj = st.get("injuries", {})
    injuries = inj.get("data", {}) if inj.get("day") == str(date.today()) else {}  # assenti vecchi: meglio non mostrarli
    out = {"players": {t: r["list"] for t, r in players.items()}, "injuries": injuries}
    st["out"] = out
    config.DATA_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False))
    n = sum(1 for r in players.values() if r["list"])
    print(f"  giocatori: {n} squadre con dati, {sum(len(v) for v in injuries.values())} assenti, {st.get('used', 0)} richieste oggi")
    return out


def attach(preds: list[dict], info: dict) -> None:
    """Aggiunge a ogni partita i giocatori e gli assenti delle due squadre."""
    P, I = info.get("players", {}), info.get("injuries", {})
    for f in preds:
        abs_ = [I.get(f["home"], []), I.get(f["away"], [])]
        out_ids = [{p["id"] for p in a} for a in abs_]
        pl = []
        for k, t in enumerate((f["home"], f["away"])):
            lst = [dict(p, out=p["id"] in out_ids[k]) for p in P.get(t, [])]
            pl.append(lst)
        if any(pl) or any(abs_):
            f["players"], f["absent"] = pl, abs_
