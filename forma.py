"""Stato di salute delle squadre: forma nelle ultime partite, riposo, partite ravvicinate.

Non cambia le percentuali del modello (che già dà più peso alle partite recenti): serve da contesto.
Le partite di coppa contano per il riposo e per il calendario fitto.
"""
import numpy as np
import pandas as pd


def _pts(gf, ga):
    return 3 if gf > ga else 1 if gf == ga else 0


def team(name: str, ref: pd.Timestamp, games: pd.DataFrame, cups: list[dict], n: int = 6) -> dict | None:
    g = games[((games["home"] == name) | (games["away"] == name)) & (games["date"] < ref)].sort_values("date")
    if g.empty:
        return None
    cur = g[g["season"] == g["season"].iloc[-1]]
    rows = []
    for r in g.tail(40).itertuples(index=False):
        home = r.home == name
        gf, ga = (r.h_goals, r.a_goals) if home else (r.a_goals, r.h_goals)
        sf, sa = (getattr(r, "h_sot"), getattr(r, "a_sot")) if home else (getattr(r, "a_sot"), getattr(r, "h_sot"))
        rows.append({"date": r.date, "gf": gf, "ga": ga, "sf": sf, "sa": sa, "res": "V" if gf > ga else "N" if gf == ga else "P",
                     "season": r.season})
    last = rows[-n:]
    season_rows = [x for x in rows if x["season"] == cur["season"].iloc[0]] or rows
    avg = lambda a, k: float(np.nanmean([x[k] for x in a])) if a and not all(pd.isna(x[k]) for x in a) else None
    ppg = lambda a: float(np.mean([_pts(x["gf"], x["ga"]) for x in a]))
    cup = [c for c in cups if name in (c["home"], c["away"]) and pd.Timestamp(c["date"]) < ref]
    dates = [x["date"] for x in rows] + [pd.Timestamp(c["date"]) for c in cup]
    last_date = max(dates)
    out = {
        "seq": "".join(x["res"] for x in last),
        "ppg": round(ppg(last), 2), "ppg_s": round(ppg(season_rows), 2),
        "gf": round(avg(last, "gf"), 2), "ga": round(avg(last, "ga"), 2),
        "gf_s": round(avg(season_rows, "gf"), 2), "ga_s": round(avg(season_rows, "ga"), 2),
        "rest": int((ref - last_date).days),
        "busy": int(sum(1 for d in dates if ref - pd.Timedelta(days=14) <= d < ref)),
        "cup_last": bool(cup) and max(pd.Timestamp(c["date"]) for c in cup) == last_date,
    }
    for k, s in (("sf", "sf_s"), ("sa", "sa_s")):
        a, b = avg(last, k), avg(season_rows, k)
        out[k], out[s] = (round(a, 2) if a is not None else None), (round(b, 2) if b is not None else None)
    # giudizio sintetico: punti e differenza reti delle ultime partite rispetto alla stagione
    score = (out["ppg"] - out["ppg_s"]) / 1.2 + ((out["gf"] - out["ga"]) - (out["gf_s"] - out["ga_s"])) / 2.5
    out["trend"] = "su" if score >= .25 else "giu" if score <= -.25 else "stabile"
    return out


def attach(preds: list[dict], games: pd.DataFrame, cups: list[dict]) -> None:
    for f in preds:
        ref = pd.Timestamp(f["date"])
        f["form"] = [team(f["home"], ref, games, cups), team(f["away"], ref, games, cups)]
