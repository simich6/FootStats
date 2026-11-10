"""Nazionali (Nations League, qualificazioni, amichevoli) — SPERIMENTALE.

Per le nazionali non ci sono statistiche gratuite di tiri, corner e cartellini: la forza delle squadre
viene dal rating Elo (eloratings.net), da cui si ricavano i gol attesi e quindi 1X2, gol, Goal/No Goal,
multigol e primo tempo. Partite e quote da The Odds API (stessa chiave delle quote).
Come le coppe, queste partite non entrano in storico, schedine e notifiche.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import requests

import config
import markets as mk
import model
import predict
import quote

ROME = ZoneInfo("Europe/Rome")
STATE = config.DATA_DIR / "nazionali.json"
# competizioni di nazionali da cercare tra quelle attive su The Odds API
KEYWORDS = ("nations_league", "euro_qual", "uefa_euro", "world_cup_qual", "friendl")
HOME_ADV = 80          # punti Elo di vantaggio per chi gioca in casa
HT_SHARE = 0.44        # quota di gol nel primo tempo
ALIASES = {"czechrepublic": "czechia", "turkiye": "turkey", "republicofireland": "ireland", "irelandrepublic": "ireland",
           "bosniaherzegovina": "bosniaandherzegovina", "northmacedonia": "macedonia", "fyrmacedonia": "macedonia",
           "usa": "unitedstates", "southkorea": "korearepublic", "korea": "korearepublic", "ivorycoast": "cotedivoire",
           "faroeislands": "faroes", "holland": "netherlands", "kosovo": "kosovo", "moldova": "moldova"}


IT = {"Italy": "Italia", "France": "Francia", "Germany": "Germania", "Spain": "Spagna", "England": "Inghilterra",
      "Belgium": "Belgio", "Netherlands": "Olanda", "Portugal": "Portogallo", "Croatia": "Croazia", "Switzerland": "Svizzera",
      "Denmark": "Danimarca", "Norway": "Norvegia", "Sweden": "Svezia", "Poland": "Polonia", "Turkey": "Turchia",
      "Türkiye": "Turchia", "Czech Republic": "Rep. Ceca", "Czechia": "Rep. Ceca", "Scotland": "Scozia", "Wales": "Galles",
      "Ireland": "Irlanda", "Republic of Ireland": "Irlanda", "Northern Ireland": "Irlanda del Nord", "Hungary": "Ungheria",
      "Greece": "Grecia", "Ukraine": "Ucraina", "Slovakia": "Slovacchia", "Iceland": "Islanda", "Finland": "Finlandia",
      "Israel": "Israele", "Bosnia and Herzegovina": "Bosnia", "Bosnia & Herzegovina": "Bosnia", "North Macedonia": "Macedonia del Nord",
      "Cyprus": "Cipro", "Luxembourg": "Lussemburgo", "Latvia": "Lettonia", "Lithuania": "Lituania", "Belarus": "Bielorussia",
      "Moldova": "Moldavia", "Kazakhstan": "Kazakistan", "Azerbaijan": "Azerbaigian", "Faroe Islands": "Fær Øer",
      "Gibraltar": "Gibilterra", "Brazil": "Brasile", "Argentina": "Argentina", "United States": "Stati Uniti", "USA": "Stati Uniti",
      "Mexico": "Messico", "Japan": "Giappone", "Morocco": "Marocco", "South Korea": "Corea del Sud"}


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = "".join(c for c in s if c.isalnum())
    return ALIASES.get(s, s)


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def elo_table(st: dict) -> dict:
    """{nome normalizzato: (nome, elo)} da eloratings.net, scaricato al massimo una volta al giorno."""
    today = str(date.today())
    if st.get("elo_day") != today or not st.get("elo"):
        try:
            names = {}
            t = requests.get("https://www.eloratings.net/en.teams.tsv", timeout=30)
            t.raise_for_status()
            for line in t.text.splitlines():
                p = line.split("\t")
                if len(p) >= 2:
                    names[p[0]] = p[1:]
            w = requests.get("https://www.eloratings.net/World.tsv", timeout=30)
            w.raise_for_status()
            elo = {}
            for line in w.text.splitlines():
                p = line.split("\t")
                if len(p) < 4 or p[2] not in names:
                    continue
                try:
                    r = float(p[3])
                except ValueError:
                    continue
                for nm in names[p[2]]:
                    if nm:
                        elo.setdefault(_norm(nm), [names[p[2]][0], r])
            if len(elo) > 100:
                st["elo"], st["elo_day"] = elo, today
                print(f"  nazionali: rating Elo di {len({v[0] for v in elo.values()})} nazionali")
        except requests.RequestException as e:
            print(f"  ! nazionali: rating Elo non disponibili ({e})")
    return st.get("elo", {})


def _lambdas(d: float) -> tuple[float, float]:
    """Gol attesi da una differenza Elo (già con il vantaggio campo)."""
    w = 1 / (10 ** (-d / 400) + 1)  # aspettativa Elo: vittoria + metà pareggio
    tot = 2.35 + 0.9 * min(1.0, abs(d) / 600)  # le partite squilibrate hanno più gol
    lo, hi = -tot + .05, tot - .05
    for _ in range(50):  # cerca la differenza di gol attesi che dà la stessa aspettativa
        s = (lo + hi) / 2
        lh, la = (tot + s) / 2, (tot - s) / 2
        ph, pa = model.pmf(lh, 0, 10), model.pmf(la, 0, 10)
        j = np.outer(ph, pa)
        e = np.tril(j, -1).sum() + .5 * np.trace(j)
        lo, hi = (s, hi) if e < w else (lo, s)
    s = (lo + hi) / 2
    return (tot + s) / 2, (tot - s) / 2


def _dist(lh: float, la: float) -> dict:
    def block(h, a, rho):
        ph, pa = model.pmf(h, 0, 10), model.pmf(a, 0, 10)
        j = np.outer(ph, pa)
        if rho:
            j[0, 0] *= 1 - h * a * rho
            j[0, 1] *= 1 + h * rho
            j[1, 0] *= 1 + a * rho
            j[1, 1] *= 1 - rho
            j /= j.sum()
        n = j.shape[0]
        tot = np.array([np.trace(np.fliplr(j), offset=n - 1 - k) for k in range(2 * n - 1)])
        return {"exp_h": h, "exp_a": a, "ph": j.sum(1), "pa": j.sum(0), "joint": j, "total": tot}
    return {"goals": block(lh, la, -0.06), "ht": block(lh * HT_SHARE, la * HT_SHARE, 0),
            "sh": block(lh * (1 - HT_SHARE), la * (1 - HT_SHARE), 0)}


def update() -> dict:
    empty = {"fixtures": [], "ratings": {}}
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("  nazionali: nessuna chiave The Odds API, salto")
        return empty
    st = _state()
    try:
        # elenco delle competizioni attive ed eventi in programma: queste richieste non consumano crediti
        sports = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": key}, timeout=30)
        sports.raise_for_status()
        comps = [s for s in sports.json() if s["key"].startswith("soccer_") and any(k in s["key"] for k in KEYWORDS)]
    except requests.RequestException as e:
        print(f"  ! nazionali: elenco competizioni non disponibile ({e})")
        return empty
    now = datetime.now(timezone.utc)
    events = []
    for c in comps:
        try:
            r = requests.get(f"https://api.the-odds-api.com/v4/sports/{c['key']}/events", params={"apiKey": key}, timeout=30)
            r.raise_for_status()
        except requests.RequestException:
            continue
        for ev in r.json():
            ko = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            if now < ko < now + timedelta(days=5):
                events.append((c, ev, ko))
    if not events:
        STATE.write_text(json.dumps(st))
        return empty
    elo = elo_table(st)
    # quote: solo per le competizioni con partite entro 2 giorni, una volta al giorno (2 crediti ciascuna)
    odds = st.setdefault("odds", {})
    today = str(date.today())
    for c in {c["key"]: c for c, ev, ko in events if ko < now + timedelta(days=2)}.values():
        if odds.get(c["key"], {}).get("day") == today or (st.get("remaining") is not None and st["remaining"] < quote.RESERVE):
            continue
        try:
            r = requests.get(f"https://api.the-odds-api.com/v4/sports/{c['key']}/odds",
                             params={"apiKey": key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"}, timeout=30)
            if r.headers.get("x-requests-remaining"):
                st["remaining"] = int(float(r.headers["x-requests-remaining"]))
            r.raise_for_status()
            odds[c["key"]] = {"day": today, "ev": {e["id"]: quote._parse(e, e["home_team"], e["away_team"]) for e in r.json()}}
        except requests.RequestException as e:
            print(f"  ! nazionali: quote {c['title']} non disponibili ({e})")
    STATE.write_text(json.dumps(st))
    preds, att, dfn = [], {}, {}
    for c, ev, ko in sorted(events, key=lambda x: x[2]):
        eh, ea = elo.get(_norm(ev["home_team"])), elo.get(_norm(ev["away_team"]))
        h, a = IT.get(ev["home_team"], ev["home_team"]), IT.get(ev["away_team"], ev["away_team"])
        if not eh or not ea:
            print(f"  ! nazionali: rating mancante per {h if not eh else a}")
            continue
        d = eh[1] + HOME_ADV - ea[1]
        lh, la = _lambdas(d)
        dist = _dist(lh, la)
        q = odds.get(c["key"], {}).get("ev", {}).get(ev["id"])
        picks = []
        for mdef in mk.MARKETS:
            if mdef["stat"] not in dist:
                continue
            p = mk.probability(mdef, dist)
            if p is None:
                continue
            p = float(np.clip(p, .01, .99))
            pick = {"key": mdef["key"], "group": mdef["group"], "label": mdef["label"], "prob": round(p, 4),
                    "fair_odds": round(1 / p, 2), "confidence": 4.0, "reliability": "yellow", "hist_hit": None, "base": None}
            qi = quote.implied(q, mdef["key"]) if q else None
            if qi:
                o, implied, info = qi
                pick.update(odds=round(float(o), 2), implied=round(implied, 4), edge=round(p - implied, 4),
                            ev=round(p * o - 1, 4), best=info["best"], pin=info["pin"], nbook=info["n"])
            picks.append(pick)
        for t, e in ((h, eh[1]), (a, ea[1])):
            x = (e - 1700) / 400
            att[t], dfn[t] = float(np.exp(.35 * x)), float(np.exp(-.35 * x))
        preds.append({
            "league": "Nazionali", "code": "NAZ", "date": str(ko.astimezone(ROME).date()), "time": ko.astimezone(ROME).strftime("%H:%M"),
            "ko": ko.isoformat(), "home": h, "away": a, "new_team": [False, False], "exp": True, "limited": [False, False],
            "stage": c.get("title"), "elo": [round(eh[1]), round(ea[1])], "big": False,
            "expected": {s: [round(v["exp_h"], 2), round(v["exp_a"], 2)] for s, v in dist.items()},
            "alpha": {s: 0.0 for s in dist}, "lavg": {"goals": 2.4, "ht": round(2.4 * HT_SHARE, 2), "sh": round(2.4 * (1 - HT_SHARE), 2)},
            "lside": {"goals": [1.35, 1.05]},
            "dist": {s: predict._trim(v["total"]) for s, v in dist.items()},
            "scores": predict._scores(dist["goals"]), "picks": picks, "h2h": {"n": 0, "games": [], "avg": {}},
            "similar": None, "rivalry": None, "climate": None, "path": None,
        })
    ratings = {"Nazionali": {"goals": {"mh": 1.35, "ma": 1.05, "alpha": 0.0, "rho": -0.06, "big": 1.0, "top": [], "prior": [1.0, 1.0],
                                       "att": {t: round(v, 4) for t, v in att.items()}, "dfn": {t: round(v, 4) for t, v in dfn.items()},
                                       "hf": {}, "af": {}}}} if preds else {}
    print(f"  nazionali: {len(preds)} partite stimate (sperimentale)")
    return {"fixtures": preds, "ratings": ratings}
