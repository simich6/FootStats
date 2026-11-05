"""Coppe europee (Champions, Europa League, Conference League) — SPERIMENTALE.

Le statistiche delle partite europee non sono disponibili gratis, quindi ogni squadra viene stimata
con i dati del suo campionato, corretti da un coefficiente di forza del campionato
(config.LEAGUE_STRENGTH, aggiornato con i risultati di Champions della stagione).
Calendario e risultati della Champions: football-data.org (chiave che c'è già).
Europa League e Conference League: calendario e quote da The Odds API (se c'è la chiave).
Le giocate di coppa non entrano nello storico, nelle schedine e nelle notifiche: non sono verificabili
con il backtest come quelle di campionato.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import backtest
import calendario
import config
import markets as mk
import model
import predict
import quote

ROME = ZoneInfo("Europe/Rome")
ODDS_KEYS = {"CL": "soccer_uefa_champs_league", "EL": "soccer_uefa_europa_league", "ECL": "soccer_uefa_europa_conference_league"}
EXP = {"goals": 1.0, "ht": 1.0, "sh": 1.0, "sot": .8, "shots": .6, "corners": .5, "cards": 0.0, "fouls": 0.0}
STATE = config.DATA_DIR / "europa.json"
DAYS = 7


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _team_leagues(games: pd.DataFrame) -> dict:
    """Squadra -> campionato più recente in cui ha giocato."""
    g = games.sort_values("date")
    out = {}
    for r in g[["home", "away", "league"]].itertuples(index=False):
        out[r.home] = r.league
        out[r.away] = r.league
    return out


def _name(variants, known):
    return calendario.match_team([v for v in variants if v], known)


def _fd_champions(key: str, known: list[str]) -> tuple[list, list]:
    """Partite in programma e risultati della Champions (football-data.org)."""
    r = requests.get("https://api.football-data.org/v4/competitions/CL/matches", headers={"X-Auth-Token": key}, timeout=30)
    r.raise_for_status()
    fixtures, results = [], []
    now = datetime.now(timezone.utc)
    for m in r.json().get("matches", []):
        ht, at = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        if not ht.get("name") or not at.get("name"):
            continue  # squadre ancora da definire (fasi a eliminazione)
        h = _name([ht.get("shortName"), ht.get("name")], known) or ht.get("shortName") or ht["name"]
        a = _name([at.get("shortName"), at.get("name")], known) or at.get("shortName") or at["name"]
        when = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        stage = (m.get("stage") or "").replace("_", " ").title()
        if m.get("status") == "FINISHED":
            ft = (m.get("score") or {}).get("fullTime") or {}
            if ft.get("home") is not None:
                results.append({"comp": "CL", "date": str(when.astimezone(ROME).date()), "home": h, "away": a,
                                "hg": int(ft["home"]), "ag": int(ft["away"]), "stage": stage})
        elif m.get("status") in ("SCHEDULED", "TIMED") and now < when < now + timedelta(days=DAYS):
            fixtures.append({"comp": "CL", "home": h, "away": a, "ko": when.astimezone(timezone.utc).isoformat(),
                             "date": str(when.astimezone(ROME).date()), "time": when.astimezone(ROME).strftime("%H:%M"), "stage": stage})
    return fixtures, results


def _odds(key: str, comp: str, known: list[str], st: dict) -> list[dict]:
    """Partite e quote da The Odds API, al massimo una volta al giorno per coppa."""
    today = str(date.today())
    cache = st.setdefault("odds", {})
    if cache.get(comp, {}).get("day") != today:
        if st.get("remaining") is not None and st["remaining"] < quote.RESERVE:
            return cache.get(comp, {}).get("events", [])
        r = requests.get(f"https://api.the-odds-api.com/v4/sports/{ODDS_KEYS[comp]}/odds",
                         params={"apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"}, timeout=30)
        if r.headers.get("x-requests-remaining"):
            st["remaining"] = int(float(r.headers["x-requests-remaining"]))
        if r.status_code == 404:  # coppa senza partite in programma
            cache[comp] = {"day": today, "events": []}
            return []
        r.raise_for_status()
        evs = []
        for ev in r.json():
            h = _name([ev.get("home_team")], known) or ev.get("home_team")
            a = _name([ev.get("away_team")], known) or ev.get("away_team")
            when = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            evs.append({"comp": comp, "home": h, "away": a, "ko": when.isoformat(), "date": str(when.astimezone(ROME).date()),
                        "time": when.astimezone(ROME).strftime("%H:%M"), "q": quote._parse(ev, h, a)})
        cache[comp] = {"day": today, "events": evs}
        print(f"  coppe: quote {config.EURO_COMPS[comp]} {len(evs)} partite (crediti rimasti {st.get('remaining', '?')})")
    now = datetime.now(timezone.utc).isoformat()
    return [e for e in cache[comp]["events"] if e["ko"] > now]


def _strengths(results: list[dict], lg_of: dict, rat: dict) -> dict:
    """Corregge la forza dei campionati con i risultati di Champions della stagione (con zavorra)."""
    s = dict(config.LEAGUE_STRENGTH)
    acc = {}
    for r in results:
        lh, la = lg_of.get(r["home"]), lg_of.get(r["away"])
        if not lh or not la or lh == la or "goals" not in rat.get(lh, {}) or "goals" not in rat.get(la, {}):
            continue
        Rh, Ra = rat[lh]["goals"], rat[la]["goals"]
        ah, dh = Rh.team(r["home"])
        aa, da = Ra.team(r["away"])
        sh, sa = s.get(lh, config.UNKNOWN_STRENGTH), s.get(la, config.UNKNOWN_STRENGTH)
        eh = 1.45 * ah * sh * da / sa
        ea = 1.15 * aa * sa * dh / sh
        for L, gf, ef, ga, ea_ in ((lh, r["hg"], eh, r["ag"], ea), (la, r["ag"], ea, r["hg"], eh)):
            x = acc.setdefault(L, [0, 0.0, 0.0, 0.0, 0.0])
            x[0] += 1
            x[1] += gf
            x[2] += ef
            x[3] += ga
            x[4] += ea_
    for L, (n, fo, fe, ao, ae) in acc.items():
        P = 15.0  # equivale a 15 partite "come da previsione"
        rf = (fo + P * fe / n) / (fe + P * fe / n)
        ra = (ao + P * ae / n) / (ae + P * ae / n)
        s[L] = float(np.clip(s.get(L, config.UNKNOWN_STRENGTH) * np.sqrt(rf / ra), .6, 1.45))
    return s


def _combined(teams: set, lg_of: dict, rat: dict, strength: dict, results: list[dict]) -> dict:
    """Un unico insieme di valutazioni per tutte le squadre delle coppe, sulla stessa scala."""
    out = {}
    leagues = {lg_of[t] for t in teams if lg_of.get(t) in rat}
    for stat in model.STATS:
        Rs = [rat[L][stat] for L in leagues if stat in rat[L]]
        if not Rs:
            continue
        k = EXP.get(stat, .5)
        att, dfn = {}, {}
        for t in teams:
            L = lg_of.get(t)
            R = rat.get(L, {}).get(stat)
            # squadra di un campionato non coperto: chi arriva in coppa di solito è tra le migliori del suo campionato
            a, d = R.team(t) if R is not None else ((1.0, 1.0) if stat in ("cards", "fouls") else (1.2, 0.85))
            sv = strength.get(L, config.UNKNOWN_STRENGTH) if L else config.UNKNOWN_STRENGTH
            att[t], dfn[t] = a * sv ** k, d / sv ** k
        mh, ma = float(np.mean([r.mu_home for r in Rs])), float(np.mean([r.mu_away for r in Rs]))
        rho = float(np.mean([r.rho for r in Rs])) if stat == "goals" else 0.0
        out[stat] = model.Ratings(stat, mh, ma, att, dfn, float(np.mean([r.alpha for r in Rs])), rho)
    # livello gol delle coppe: dai risultati della stagione, con zavorra verso i campionati
    if "goals" in out and results:
        G = out["goals"]
        exp_g = sum(sum(G.expected(r["home"], r["away"])) for r in results if r["home"] in G.att and r["away"] in G.att)
        obs_g = sum(r["hg"] + r["ag"] for r in results if r["home"] in G.att and r["away"] in G.att)
        n = sum(1 for r in results if r["home"] in G.att and r["away"] in G.att)
        if n:
            c = float(np.clip((obs_g + 30 * exp_g / n) / (exp_g + 30 * exp_g / n), .85, 1.15))
            for s in ("goals", "ht", "sh"):
                if s in out:
                    out[s].mu_home *= c
                    out[s].mu_away *= c
    return out


def update(matches: pd.DataFrame, support: pd.DataFrame, bt: dict | None) -> dict:
    """Restituisce {"fixtures": [...], "results": [...], "ratings": {...}, "trend_teams": set}."""
    empty = {"fixtures": [], "results": [], "ratings": {}, "trend_teams": set()}
    fd_key = os.environ.get("FOOTBALL_DATA_ORG_KEY", "").strip()
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not fd_key and not odds_key:
        print("  coppe: nessuna chiave, salto")
        return empty
    games = pd.concat([matches, support], ignore_index=True) if not support.empty else matches
    recent = games[games["date"] >= games["date"].max() - pd.Timedelta(days=400)]
    lg_of = _team_leagues(recent)
    known = sorted(lg_of)
    st = _state()
    fixtures, results = [], []
    if fd_key:
        try:
            fixtures, results = _fd_champions(fd_key, known)
            print(f"  coppe: Champions {len(fixtures)} partite in programma, {len(results)} giocate")
        except requests.RequestException as e:
            print(f"  ! coppe: calendario Champions non disponibile ({e})")
    if odds_key:
        wd = date.today().weekday()
        cl_soon = any(f["date"] <= str(date.today() + timedelta(days=1)) for f in fixtures)
        for comp in ("CL", "EL", "ECL"):
            # per risparmiare crediti: Champions solo se si gioca a breve, EL e Conference il mercoledì e il giovedì
            if (comp == "CL" and not cl_soon) or (comp != "CL" and wd not in (2, 3)):
                evs = [e for e in st.get("odds", {}).get(comp, {}).get("events", []) if e["ko"] > datetime.now(timezone.utc).isoformat()]
            else:
                try:
                    evs = _odds(odds_key, comp, known, st)
                except requests.RequestException as e:
                    print(f"  ! coppe: quote {config.EURO_COMPS[comp]} non disponibili ({e})")
                    evs = []
            for e in evs:
                same = next((f for f in fixtures if f["comp"] == comp and f["home"] == e["home"] and f["away"] == e["away"]), None)
                if same:
                    same["q"] = e["q"]
                elif comp != "CL" or not fd_key:
                    fixtures.append(e)
    config.DATA_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))
    if not fixtures:
        return {**empty, "results": results}
    # valutazioni dei campionati coinvolti
    teams = {f["home"] for f in fixtures} | {f["away"] for f in fixtures} | {r["home"] for r in results} | {r["away"] for r in results}
    ref = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    rat, base = {}, {}
    for L in {lg_of[t] for t in teams if t in lg_of}:
        hist = games[games["league"] == L]
        r = model.fit_all(hist, ref)
        if "goals" in r:
            rat[L] = r
            base[L] = predict.base_rates(hist, ref)
    strength = _strengths(results, lg_of, rat)
    comb = _combined(teams, lg_of, rat, strength, results)
    if "goals" not in comb:
        return {**empty, "results": results}
    metrics = {m["market"]: m for m in (bt or {}).get("metrics", [])}
    iso = (bt or {}).get("iso", {})
    preds = []
    for f in sorted(fixtures, key=lambda x: x["ko"]):
        h, a = f["home"], f["away"]
        dist = model.distributions(comb, h, a)
        lh, la = lg_of.get(h), lg_of.get(a)
        limited = [lh not in rat, la not in rat]
        bases = [base[L] for L in (lh, la) if L in base]
        picks = []
        for mdef in mk.MARKETS:
            raw = mk.probability(mdef, dist)
            if raw is None:
                continue
            p = backtest.calibrate(raw, iso.get(mdef["key"]))
            mrow = metrics.get(mdef["key"])
            rel = mrow["reliability"] if mrow else "red"
            bv = [b[mdef["key"]] for b in bases if mdef["key"] in b]
            pick = {"key": mdef["key"], "group": mdef["group"], "label": mdef["label"], "prob": round(p, 4),
                    "fair_odds": round(1 / p, 2), "confidence": 3.0 if any(limited) else 5.0,
                    "reliability": "yellow" if rel == "green" else rel, "hist_hit": None,
                    "base": round(float(np.mean(bv)), 4) if bv else None}
            qi = quote.implied(f["q"], mdef["key"]) if f.get("q") else None
            if qi:
                odds, implied, info = qi
                pick.update(odds=round(float(odds), 2), implied=round(implied, 4), edge=round(p - implied, 4),
                            ev=round(p * odds - 1, 4), best=info["best"], pin=info["pin"], nbook=info["n"])
            picks.append(pick)
        path = [[r for r in results if t in (r["home"], r["away"])] for t in (h, a)]
        preds.append({
            "league": config.EURO_COMPS[f["comp"]], "code": f["comp"], "date": f["date"], "time": f["time"], "ko": f["ko"],
            "home": h, "away": a, "new_team": [False, False], "exp": True, "limited": limited, "stage": f.get("stage"),
            "leagues": [config.LEAGUES.get(lh, config.SUPPORT_LEAGUES.get(lh)) if lh else None,
                        config.LEAGUES.get(la, config.SUPPORT_LEAGUES.get(la)) if la else None],
            "strength": [round(strength.get(lh, config.UNKNOWN_STRENGTH), 3), round(strength.get(la, config.UNKNOWN_STRENGTH), 3)],
            "big": False,
            "expected": {s: [round(d["exp_h"], 2), round(d["exp_a"], 2)] for s, d in dist.items()},
            "alpha": {s: round(r.alpha, 4) for s, r in comb.items()},
            "lavg": {s: round(r.mu_home + r.mu_away, 2) for s, r in comb.items()},
            "lside": {s: [round(r.mu_home, 3), round(r.mu_away, 3)] for s, r in comb.items()},
            "dist": {s: predict._trim(d["total"]) for s, d in dist.items()},
            "scores": predict._scores(dist.get("goals")),
            "picks": picks,
            "h2h": __import__("rivalita").head_to_head(games, h, a),
            "similar": None, "rivalry": None,
            "climate": predict.climate(dist.get("cards"), comb.get("cards"), picks, {"games": []}, 1.0),
            "path": path,
        })
    exp_r = {s: {"mh": round(r.mu_home, 4), "ma": round(r.mu_away, 4), "alpha": round(r.alpha, 4), "rho": round(r.rho, 3),
                 "big": 1.0, "top": [], "prior": list(model.NEW_TEAM_PRIOR[s]),
                 "att": {t: round(v, 4) for t, v in r.att.items()}, "dfn": {t: round(v, 4) for t, v in r.dfn.items()},
                 "hf": {}, "af": {}} for s, r in comb.items()}
    ratings = {config.EURO_COMPS[c]: exp_r for c in {f["comp"] for f in fixtures}}
    print(f"  coppe: {len(preds)} partite stimate (sperimentale)")
    return {"fixtures": preds, "results": results, "ratings": ratings,
            "trend_teams": {f["home"] for f in fixtures} | {f["away"] for f in fixtures}}
