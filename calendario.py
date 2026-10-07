"""Seconda fonte per il calendario: football-data.org (gratuita, serve una chiave).

Prende le partite in programma nei prossimi giorni e abbina i nomi delle squadre
a quelli di football-data.co.uk (es. "FC Internazionale Milano" -> "Inter").
Se la chiave non c'è o il servizio non risponde, l'app continua con la sola fonte principale.
"""
import difflib
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

# codice nostro -> codice football-data.org (solo campionati del piano gratuito)
COMPETITIONS = {"I1": "SA", "E0": "PL", "SP1": "PD", "D1": "BL1", "F1": "FL1", "E1": "ELC"}
DAYS_AHEAD = 10
ROME = ZoneInfo("Europe/Rome")

# nomi che il confronto automatico non può indovinare (forma normalizzata -> nome football-data.co.uk)
ALIASES = {
    "atletico madrid": "Ath Madrid", "athletic": "Ath Bilbao", "athletic club": "Ath Bilbao",
    "psg": "Paris SG", "paris saint germain": "Paris SG", "tottenham hotspur": "Tottenham", "spurs": "Tottenham",
    "wolverhampton": "Wolves", "wolverhampton wanderers": "Wolves", "nottingham": "Nott'm Forest",
    "nottingham forest": "Nott'm Forest", "hsv": "Hamburg", "hamburger": "Hamburg", "frankfurt": "Ein Frankfurt",
    "eintracht frankfurt": "Ein Frankfurt", "bayern": "Bayern Munich", "bayern munchen": "Bayern Munich",
    "koln": "FC Koln", "gladbach": "M'gladbach", "monchengladbach": "M'gladbach",
    "borussia monchengladbach": "M'gladbach", "man utd": "Man United", "manchester united": "Man United",
    "man city": "Man City", "manchester city": "Man City", "sheffield utd": "Sheffield United",
    "sheffield wednesday": "Sheffield Weds", "west bromwich albion": "West Brom", "queens park rangers": "QPR",
    "hellas verona": "Verona", "internazionale milano": "Inter", "internazionale": "Inter",
    "rayo vallecano": "Vallecano", "real betis": "Betis", "real sociedad": "Sociedad", "celta vigo": "Celta",
    "espanyol": "Espanol", "deportivo alaves": "Alaves", "saint etienne": "St Etienne", "leipzig": "RB Leipzig",
    "rb leipzig": "RB Leipzig", "werder": "Werder Bremen", "real oviedo": "Oviedo", "bor dortmund": "Dortmund",
    "borussia dortmund": "Dortmund", "bayer leverkusen": "Leverkusen", "leverkusen": "Leverkusen",
    "brighton hove albion": "Brighton", "newcastle united": "Newcastle", "west ham united": "West Ham",
    "leeds united": "Leeds", "paris": "Paris FC", "paris fc": "Paris FC",
}
DROP = {"fc", "cf", "ac", "afc", "ssc", "as", "us", "sc", "calcio", "club", "de", "sv", "vfl", "vfb", "tsg",
        "rcd", "ud", "cd", "sd", "ca", "sl", "olympique", "stade", "rc", "ogc", "losc", "acf", "bc", "fk",
        "1", "04", "05", "1846", "1899", "1904", "1907", "1909", "1913"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(w for w in s.split() if w not in DROP)


def match_team(variants: list[str], candidates: list[str]) -> str | None:
    cand_norm = {norm(c): c for c in candidates}
    variants = [v for v in variants if v]
    for v in variants:
        n = norm(v)
        if n in ALIASES and ALIASES[n] in candidates:
            return ALIASES[n]
        if n in cand_norm:
            return cand_norm[n]
    best, score = None, 0.0
    for v in variants:
        n = norm(v)
        for cn, c in cand_norm.items():
            if not cn or not n:
                continue
            r = difflib.SequenceMatcher(None, n, cn).ratio()
            if cn in n.split() or n.startswith(cn + " ") or cn.startswith(n + " "):
                r = max(r, 0.9)
            if r > score:
                best, score = c, r
    return best if score >= 0.75 else None


def fetch(matches: pd.DataFrame, leagues: dict) -> pd.DataFrame:
    key = os.environ.get("FOOTBALL_DATA_ORG_KEY", "").strip()
    if not key:
        print("  calendario extra: nessuna chiave football-data.org, salto")
        return pd.DataFrame()
    today = datetime.now(timezone.utc).date()
    rows, unmatched = [], set()
    current = matches["season"].max()
    for code, comp in COMPETITIONS.items():
        if code not in leagues:
            continue
        cur = matches[(matches["league"] == code) & (matches["season"] == current)]
        teams = sorted(set(cur["home"]) | set(cur["away"]))
        if not teams:
            continue
        try:
            r = requests.get(f"https://api.football-data.org/v4/competitions/{comp}/matches",
                             params={"dateFrom": str(today), "dateTo": str(today + timedelta(days=DAYS_AHEAD))},
                             headers={"X-Auth-Token": key}, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ! calendario extra {leagues[code]} non disponibile ({e})")
            continue
        n = 0
        for m in r.json().get("matches", []):
            if m.get("status") not in ("SCHEDULED", "TIMED"):
                continue
            ht, at = m.get("homeTeam") or {}, m.get("awayTeam") or {}
            h = match_team([ht.get("shortName"), ht.get("name")], teams)
            a = match_team([at.get("shortName"), at.get("name")], teams)
            if not h or not a or h == a:
                unmatched.update(t.get("name") for t, x in ((ht, h), (at, a)) if not x)
                continue
            when = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(ROME)
            rows.append({"league": code, "season": None, "date": pd.Timestamp(when.date()),
                         "home": h, "away": a, "time": when.strftime("%H:%M")})
            n += 1
        print(f"  calendario extra {leagues[code]}: {n} partite")
    if unmatched:
        print(f"  ! squadre non riconosciute: {sorted(x for x in unmatched if x)}")
    return pd.DataFrame(rows)


def merge(primary: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Unisce i calendari. Se una partita c'è in entrambi tiene quella principale, che ha anche le quote."""
    if extra.empty:
        return primary
    if not primary.empty:
        known = set(zip(primary["league"], primary["home"], primary["away"]))
        extra = extra[[k not in known for k in zip(extra["league"], extra["home"], extra["away"])]]
    out = pd.concat([primary, extra], ignore_index=True)
    for c in primary.columns:
        if c not in out.columns:
            out[c] = np.nan
    return out.sort_values("date").reset_index(drop=True)
