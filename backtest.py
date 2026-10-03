"""Backtest walk-forward senza "sbirciare nel futuro" + metriche + calibrazione.

Per ogni settimana del periodo di test il modello viene stimato SOLO con le partite
giocate prima di quella settimana, poi prevede le partite della settimana.
"""
import json

import numpy as np
import pandas as pd

import config
import markets as mk
import model


def walk_forward(matches: pd.DataFrame, test_seasons: list | None = None, quiet: bool = False) -> pd.DataFrame:
    test_seasons = test_seasons or sorted(matches["season"].unique())[-config.BACKTEST_SEASONS:]
    rows = []
    for league, lg in matches.groupby("league"):
        lg = lg.sort_values("date")
        test = lg[lg["season"].isin(test_seasons)]
        weeks = test["date"].dt.to_period("W-MON").dt.start_time
        for week_start, wk in test.groupby(weeks):
            ratings = model.fit_all(lg[lg["date"] < week_start], week_start)
            if "goals" not in ratings:
                continue
            for _, m in wk.iterrows():
                dist = model.distributions(ratings, m["home"], m["away"])
                for mdef in mk.MARKETS:
                    p = mk.probability(mdef, dist)
                    y = mk.outcome(mdef, m)
                    if p is None or np.isnan(y):
                        continue
                    row = {"date": m["date"], "league": league, "season": m["season"],
                           "home": m["home"], "away": m["away"], "market": mdef["key"],
                           "group": mdef["group"], "label": mdef["label"], "prob": p, "won": y}
                    fi = mk.fair_implied(m, mdef["key"])
                    if fi:
                        row["odds"], row["implied"] = fi
                        close = m.get(mk.ODDS_MAP[mdef["key"]][1])
                        row["close_odds"] = close if close and np.isfinite(close) else np.nan
                    rows.append(row)
        if not quiet:
            print(f"  backtest {config.LEAGUES[league]} completato")
    return pd.DataFrame(rows)


def _baseline(bt: pd.DataFrame) -> pd.Series:
    """Riferimento 'ingenuo': frequenza storica della giocata nel campionato fino a quel giorno."""
    bt = bt.sort_values("date")
    g = bt.groupby(["league", "market"])["won"]
    prev_sum = g.cumsum() - bt["won"]
    prev_n = g.cumcount()
    return (prev_sum + 0.5 * 10) / (prev_n + 10)  # parte da 50% e si aggiorna


def market_metrics(bt: pd.DataFrame) -> pd.DataFrame:
    bt = bt.copy()
    bt["base"] = _baseline(bt)
    eps = 1e-6
    out = []
    for key, g in bt.groupby("market"):
        brier = np.mean((g["prob"] - g["won"]) ** 2)
        brier_base = np.mean((g["base"] - g["won"]) ** 2)
        p = g["prob"].clip(eps, 1 - eps)
        logloss = -np.mean(g["won"] * np.log(p) + (1 - g["won"]) * np.log(1 - p))
        cal_err = _calibration_error(g["prob"].to_numpy(), g["won"].to_numpy())
        skill = 1 - brier / brier_base if brier_base > 0 else 0.0
        vs_market = brier_market = None
        if "implied" in g.columns and g["implied"].notna().sum() >= 200:
            sub = g.dropna(subset=["implied"])
            brier_market = float(np.mean((sub["implied"] - sub["won"]) ** 2))
            vs_market = 1 - float(np.mean((sub["prob"] - sub["won"]) ** 2)) / brier_market
        out.append({"market": key, "vs_market": vs_market, "brier_market": brier_market, "group": g["group"].iat[0], "label": g["label"].iat[0], "n": len(g),
                    "avg_prob": g["prob"].mean(), "hit_rate": g["won"].mean(), "brier": brier,
                    "brier_base": brier_base, "skill": skill, "logloss": logloss, "cal_error": cal_err,
                    "reliability": _grade(skill, cal_err, len(g))})
    return pd.DataFrame(out)


def _calibration_error(p, y, bins=10):
    idx = np.minimum((p * bins).astype(int), bins - 1)
    err = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.mean() * abs(p[m].mean() - y[m].mean())
    return err


def _grade(skill, cal_err, n):
    if n < 300:
        return "red"
    if skill > 0.03 and cal_err < 0.03:
        return "green"
    if skill > 0.0 and cal_err < 0.05:
        return "yellow"
    return "red"


def calibration_curves(bt: pd.DataFrame, bins=10) -> dict:
    curves = {}
    for key, g in bt.groupby("market"):
        idx = np.minimum((g["prob"] * bins).astype(int), bins - 1)
        pts = [{"p": float(s["prob"].mean()), "y": float(s["won"].mean()), "n": int(len(s))}
               for _, s in g.groupby(idx) if len(s) >= 20]
        curves[key] = pts
    return curves


def value_backtest(bt: pd.DataFrame, min_edge=config.MIN_EDGE) -> list[dict]:
    """Scommessa simulata da 1 unità quando il modello supera la quota di almeno min_edge."""
    if "implied" not in bt.columns:
        return []
    b = bt.dropna(subset=["implied"]).copy()
    b["edge"] = b["prob"] - b["implied"]
    b = b[b["edge"] >= min_edge].sort_values("date")
    results = []
    for key, g in b.groupby("market"):
        profit = np.where(g["won"] == 1, g["odds"] - 1, -1.0)
        equity = np.cumsum(profit)
        drawdown = float(np.max(np.maximum.accumulate(np.r_[0, equity]) - np.r_[0, equity]))
        clv = (g["odds"] / g["close_odds"] - 1).dropna()
        results.append({"market": key, "group": g["group"].iat[0], "label": g["label"].iat[0], "bets": len(g),
                        "wins": int(g["won"].sum()), "hit_rate": float(g["won"].mean()),
                        "avg_odds": float(g["odds"].mean()), "profit": float(equity[-1]),
                        "roi": float(equity[-1] / len(g)), "max_drawdown": drawdown,
                        "clv": float(clv.mean()) if len(clv) else None,
                        "equity": [round(float(x), 2) for x in equity]})
    return results


def isotonic_maps(bt: pd.DataFrame, min_n=500) -> dict:
    """Mappa di calibrazione per mercato (isotonic regression, algoritmo PAV)."""
    maps = {}
    for key, g in bt.groupby("market"):
        if len(g) < min_n:
            continue
        order = np.argsort(g["prob"].to_numpy())
        x, y = g["prob"].to_numpy()[order], g["won"].to_numpy()[order]
        blocks = [[yi, 1.0, xi, xi] for xi, yi in zip(x, y)]  # somma y, peso, x min, x max
        merged = []
        for blk in blocks:
            merged.append(blk)
            while len(merged) > 1 and merged[-2][0] / merged[-2][1] >= merged[-1][0] / merged[-1][1]:
                b2 = merged.pop()
                b1 = merged.pop()
                merged.append([b1[0] + b2[0], b1[1] + b2[1], b1[2], b2[3]])
        xs = [(b[2] + b[3]) / 2 for b in merged]
        ys = [b[0] / b[1] for b in merged]
        maps[key] = {"x": xs, "y": ys}
    return maps


def calibrate(p: float, cmap: dict | None) -> float:
    if not cmap:
        return p
    return float(np.clip(np.interp(p, cmap["x"], cmap["y"]), 0.01, 0.99))


def run(matches: pd.DataFrame) -> dict:
    bt = walk_forward(matches)
    bt.to_csv(config.DATA_DIR / "backtest_predictions.csv", index=False)
    metrics = market_metrics(bt)
    summary = {
        "periodo": [str(bt["date"].min().date()), str(bt["date"].max().date())],
        "partite": int(bt.drop_duplicates(["date", "home", "away"]).shape[0]),
        "metrics": metrics.astype(object).where(metrics.notna(), None).to_dict("records"),
        "calibration": calibration_curves(bt),
        "value": value_backtest(bt),
        "iso": isotonic_maps(bt),
    }
    (config.DATA_DIR / "backtest.json").write_text(json.dumps(summary, default=float))
    return summary


def load() -> dict | None:
    path = config.DATA_DIR / "backtest.json"
    return json.loads(path.read_text()) if path.exists() else None


def tune(matches: pd.DataFrame) -> dict:
    """Prova alcune impostazioni e tiene quella con le probabilità più accurate (log loss).
    Usa le due stagioni concluse più recenti; la stagione in corso resta fuori."""
    seasons = sorted(matches["season"].unique())
    test = seasons[-3:-1] if len(seasons) >= 4 else seasons[-2:]
    results = []
    for hl in (90, 150, 240):
        for dc in (True, False):
            config.HALF_LIFE_DAYS, config.DIXON_COLES = hl, dc
            bt = walk_forward(matches, test, quiet=True)
            p = bt["prob"].clip(1e-6, 1 - 1e-6)
            ll = float(-np.mean(bt["won"] * np.log(p) + (1 - bt["won"]) * np.log(1 - p)))
            results.append((ll, hl, dc))
            print(f"  memoria {hl} giorni, Dixon-Coles {'sì' if dc else 'no'}: log loss {ll:.5f}")
    ll, hl, dc = min(results)
    params = {"HALF_LIFE_DAYS": hl, "DIXON_COLES": dc}
    config.HALF_LIFE_DAYS, config.DIXON_COLES = hl, dc
    config.PARAMS_PATH.write_text(json.dumps(params))
    print(f"  scelto: memoria {hl} giorni, Dixon-Coles {'sì' if dc else 'no'}")
    return params
