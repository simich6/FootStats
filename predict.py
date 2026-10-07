"""Previsioni per le prossime partite + trend delle squadre."""
import numpy as np
import pandas as pd

import backtest
import config
import markets as mk
import model


def _confidence(market_row: dict | None, n_home: int, n_away: int) -> float:
    """0-10. Non è la probabilità: misura quanto fidarsi della stima.
    60% affidabilità storica del mercato (skill + calibrazione), 40% quantità di dati sulle squadre."""
    if market_row is None:
        market_score = 0.3
    else:
        market_score = (0.6 * np.clip(market_row["skill"] / 0.08, 0, 1)
                        + 0.4 * np.clip(1 - market_row["cal_error"] / 0.05, 0, 1))
    data_score = np.clip(min(n_home, n_away) / 20, 0, 1)
    return round(float(10 * (0.6 * market_score + 0.4 * data_score)), 1)


def _scores(d, n: int = 6) -> dict | None:
    """Matrice dei risultati esatti 0-0 -> 5-5 e i più probabili."""
    if not d:
        return None
    j = d["joint"] if "joint" in d else np.outer(d["ph"], d["pa"])
    m = j[:6, :6]
    order = np.dstack(np.unravel_index(np.argsort(-m, axis=None), m.shape))[0][:n]
    return {"grid": [[round(float(v), 4) for v in row] for row in m],
            "top": [[int(i), int(k), round(float(m[i, k]), 4)] for i, k in order]}


def _trim(p: np.ndarray, mass: float = 0.998) -> list[float]:
    """Distribuzione del totale, tagliata dove la probabilità residua diventa trascurabile."""
    cut = int(np.searchsorted(np.cumsum(p), mass)) + 1
    return [round(float(x), 4) for x in p[:cut]]


def predict_fixtures(matches: pd.DataFrame, fixtures: pd.DataFrame, bt: dict | None) -> list[dict]:
    metrics = {m["market"]: m for m in (bt or {}).get("metrics", [])}
    iso = (bt or {}).get("iso", {})
    out = []
    today = pd.Timestamp.today().normalize()
    fixtures = fixtures[fixtures["date"] >= today]
    for league, fx in fixtures.groupby("league"):
        hist = matches[matches["league"] == league]
        ratings = model.fit_all(hist, today + pd.Timedelta(days=1))
        if "goals" not in ratings:
            continue
        recent = hist[hist["date"] >= today - pd.Timedelta(days=365)]
        counts = pd.concat([recent["home"], recent["away"]]).value_counts()
        for _, f in fx.iterrows():
            dist = model.distributions(ratings, f["home"], f["away"])
            nh, na = int(counts.get(f["home"], 0)), int(counts.get(f["away"], 0))
            picks = []
            for mdef in mk.MARKETS:
                raw = mk.probability(mdef, dist)
                if raw is None:
                    continue
                p = backtest.calibrate(raw, iso.get(mdef["key"]))
                mrow = metrics.get(mdef["key"])
                pick = {"key": mdef["key"], "group": mdef["group"], "label": mdef["label"],
                        "prob": round(p, 4), "fair_odds": round(1 / p, 2),
                        "confidence": _confidence(mrow, nh, na),
                        "reliability": mrow["reliability"] if mrow else "red",
                        "hist_hit": round(mrow["hit_rate"], 3) if mrow else None}
                fi = mk.fair_implied(f, mdef["key"])
                if fi:
                    odds, implied = fi
                    pick.update(odds=round(float(odds), 2), implied=round(implied, 4),
                                edge=round(p - implied, 4), ev=round(p * odds - 1, 4))
                picks.append(pick)
            out.append({
                "league": config.LEAGUES[league], "code": league, "date": str(f["date"].date()), "time": f.get("time", ""),
                "home": f["home"], "away": f["away"], "new_team": [nh == 0, na == 0],
                "big": ratings["goals"].is_big(f["home"], f["away"]),
                "expected": {s: [round(d["exp_h"], 2), round(d["exp_a"], 2)] for s, d in dist.items()},
                "alpha": {s: round(r.alpha, 4) for s, r in ratings.items()},
                "lavg": {s: round(r.mu_home + r.mu_away, 2) for s, r in ratings.items()},
                "dist": {s: _trim(d["total"]) for s, d in dist.items()},
                "scores": _scores(dist.get("goals")),
                "picks": picks,
            })
    return out


def team_trends(matches: pd.DataFrame, last_n: int = 20) -> dict:
    """Ultime partite di ogni squadra della stagione in corso (fatti/subiti per ogni statistica)."""
    current = matches["season"].max()
    teams = matches[matches["season"] == current][["home", "league"]].drop_duplicates("home")
    trends = {}
    for team, league in teams.itertuples(index=False):
        tm = matches[(matches["home"] == team) | (matches["away"] == team)].sort_values("date").tail(last_n)
        games = []
        for _, m in tm.iterrows():
            home = m["home"] == team
            s, o = ("h_", "a_") if home else ("a_", "h_")
            gf, ga = m[s + "goals"], m[o + "goals"]
            g = {"date": str(m["date"].date()), "opp": m["away"] if home else m["home"],
                 "venue": "C" if home else "T", "res": "V" if gf > ga else "N" if gf == ga else "P"}
            for stat in model.STATS:
                f_, a_ = m[s + stat], m[o + stat]
                g[stat] = [None if pd.isna(f_) else float(f_), None if pd.isna(a_) else float(a_)]
            games.append(g)
        trends[team] = {"league": config.LEAGUES[league], "games": games}
    return trends


def league_trends(matches: pd.DataFrame) -> dict:
    """Medie per campionato: stagione in corso vs precedente, e andamento settimana per settimana."""
    out = {}
    seasons = sorted(matches["season"].unique())[-2:]
    for league, lg in matches[matches["season"].isin(seasons)].groupby("league"):
        lg = lg.copy()
        for st in model.STATS:
            lg["t_" + st] = lg["h_" + st] + lg["a_" + st]
        info = {}
        for season, sg in lg.groupby("season"):
            weeks = sg.groupby(sg["date"].dt.to_period("W-MON").dt.start_time)
            info[season] = {
                "label": f"20{season[:2]}/{season[2:]}", "n": len(sg),
                "avg": {st: round(float(sg["t_" + st].mean()), 2) for st in model.STATS if sg["t_" + st].notna().any()},
                "home_win": round(float((sg["h_goals"] > sg["a_goals"]).mean()), 3),
                "over25": round(float((sg["t_goals"] > 2.5).mean()), 3),
                "btts": round(float(((sg["h_goals"] > 0) & (sg["a_goals"] > 0)).mean()), 3),
                "weekly": {st: [round(float(v), 2) for v in weeks["t_" + st].mean().dropna()] for st in model.STATS},
            }
        out[config.LEAGUES[league]] = info
    return out


def export_ratings(matches: pd.DataFrame) -> dict:
    """Parametri del modello per ogni campionato: servono alla dashboard per analizzare
    qualsiasi giocata (linea, squadra, partita) anche non presente nell'elenco."""
    today = pd.Timestamp.today().normalize()
    out = {}
    for league, hist in matches.groupby("league"):
        ratings = model.fit_all(hist, today + pd.Timedelta(days=1))
        if "goals" not in ratings:
            continue
        out[config.LEAGUES[league]] = {
            s: {"mh": round(r.mu_home, 4), "ma": round(r.mu_away, 4), "alpha": round(r.alpha, 4),
                "rho": round(r.rho, 3), "big": round(r.big, 4), "top": sorted(r.top),
                "prior": list(model.NEW_TEAM_PRIOR[s]),
                "att": {t: round(v, 4) for t, v in r.att.items()}, "dfn": {t: round(v, 4) for t, v in r.dfn.items()},
                "hf": {t: round(float(v), 4) for t, v in (r.hf or {}).items()},
                "af": {t: round(float(v), 4) for t, v in (r.af or {}).items()}}
            for s, r in ratings.items()}
    return out
