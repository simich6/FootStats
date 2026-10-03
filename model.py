"""Modello: forza delle squadre corretta per l'avversario + distribuzioni di probabilità.

Per ogni statistica (gol, tiri, tiri in porta, corner, falli, cartellini) il valore atteso è
    casa:     media_casa_campionato  x  attacco[casa]    x  difesa[ospite]
    ospite:   media_ospite_campionato x attacco[ospite]  x  difesa[casa]
dove "attacco" = quanto la squadra produce e "difesa" = quanto concede all'avversario,
stimati insieme (quindi già corretti per la forza degli avversari affrontati),
con più peso alle partite recenti.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

import config

STATS = ["goals", "shots", "sot", "corners", "fouls", "cards"]
MAX_COUNT = {"goals": 10, "shots": 55, "sot": 25, "corners": 25, "fouls": 50, "cards": 14}
# Prior per squadre senza storico (es. neopromosse): producono un po' meno e concedono un po' di più
NEW_TEAM_PRIOR = {"goals": (0.85, 1.15), "shots": (0.9, 1.1), "sot": (0.88, 1.12),
                  "corners": (0.92, 1.08), "fouls": (1.0, 1.0), "cards": (1.0, 1.0)}


@dataclass
class Ratings:
    stat: str
    mu_home: float
    mu_away: float
    att: dict
    dfn: dict
    alpha: float  # sovradispersione: 0 = Poisson
    rho: float = 0.0  # correzione Dixon-Coles (solo gol): risultati bassi e pareggi

    def team(self, name):
        if name in self.att:
            return self.att[name], self.dfn[name]
        return NEW_TEAM_PRIOR[self.stat]

    def expected(self, home, away):
        ah, dh = self.team(home)
        aa, da = self.team(away)
        return self.mu_home * ah * da, self.mu_away * aa * dh


def fit_ratings(hist: pd.DataFrame, ref_date: pd.Timestamp, stat: str) -> Ratings | None:
    hc, ac = f"h_{stat}", f"a_{stat}"
    age = (ref_date - hist["date"]).dt.days
    h = hist[(age > 0) & (age <= config.LOOKBACK_DAYS)].dropna(subset=[hc, ac])
    if len(h) < config.MIN_HISTORY:
        return None
    age = (ref_date - h["date"]).dt.days.to_numpy()
    w = 0.5 ** (age / config.HALF_LIFE_DAYS)
    yh, ya = h[hc].to_numpy(float), h[ac].to_numpy(float)
    teams = pd.Index(sorted(set(h["home"]) | set(h["away"])))
    ih, ia = teams.get_indexer(h["home"]), teams.get_indexer(h["away"])
    n, k = len(teams), config.SHRINK_MATCHES
    mu_h, mu_a = np.average(yh, weights=w), np.average(ya, weights=w)
    att, dfn = np.ones(n), np.ones(n)

    for _ in range(30):
        # attacco: prodotto osservato / prodotto atteso con attacco=1
        num = np.bincount(ih, w * yh, n) + np.bincount(ia, w * ya, n) + k
        den = np.bincount(ih, w * mu_h * dfn[ia], n) + np.bincount(ia, w * mu_a * dfn[ih], n) + k
        att = num / den
        num = np.bincount(ia, w * yh, n) + np.bincount(ih, w * ya, n) + k
        den = np.bincount(ia, w * mu_h * att[ih], n) + np.bincount(ih, w * mu_a * att[ia], n) + k
        dfn = num / den
        dfn /= np.exp(np.mean(np.log(dfn)))  # identificabilità

    alpha = 0.0
    if stat != "goals":
        eh, ea = mu_h * att[ih] * dfn[ia], mu_a * att[ia] * dfn[ih]
        y, e, ww = np.r_[yh, ya], np.r_[eh, ea], np.r_[w, w]
        alpha = max(0.0, np.sum(ww * ((y - e) ** 2 - e)) / np.sum(ww * e ** 2))

    rho = 0.0
    if stat == "goals" and config.DIXON_COLES:
        eh, ea = mu_h * att[ih] * dfn[ia], mu_a * att[ia] * dfn[ih]
        best = -np.inf
        for r in np.arange(-0.20, 0.051, 0.01):
            ll = np.sum(w * np.log(np.clip(_tau(yh, ya, eh, ea, r), 1e-9, None)))
            if ll > best:
                best, rho = ll, float(r)

    return Ratings(stat, mu_h, mu_a, dict(zip(teams, att)), dict(zip(teams, dfn)), alpha, rho)


def _tau(x, y, lh, la, rho):
    t = np.ones_like(lh, dtype=float)
    t = np.where((x == 0) & (y == 0), 1 - lh * la * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lh * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + la * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


def fit_all(hist: pd.DataFrame, ref_date: pd.Timestamp) -> dict:
    return {s: r for s in STATS if (r := fit_ratings(hist, ref_date, s)) is not None}


def pmf(lam: float, alpha: float, nmax: int) -> np.ndarray:
    k = np.arange(nmax + 1)
    if alpha < 1e-6:
        p = poisson.pmf(k, lam)
    else:
        r = 1.0 / alpha
        p = nbinom.pmf(k, r, r / (r + lam))
    return p / p.sum()


def distributions(ratings: dict, home: str, away: str) -> dict:
    """Per ogni statistica: distribuzioni casa, ospite, totale e valori attesi."""
    out = {}
    for stat, r in ratings.items():
        lh, la = r.expected(home, away)
        ph, pa = pmf(lh, r.alpha, MAX_COUNT[stat]), pmf(la, r.alpha, MAX_COUNT[stat])
        if r.rho:
            joint = np.outer(ph, pa)
            joint[0, 0] *= 1 - lh * la * r.rho
            joint[0, 1] *= 1 + lh * r.rho
            joint[1, 0] *= 1 + la * r.rho
            joint[1, 1] *= 1 - r.rho
            joint /= joint.sum()
            n = joint.shape[0]
            total = np.array([np.trace(np.fliplr(joint), offset=n - 1 - k) for k in range(2 * n - 1)])
            out[stat] = {"exp_h": lh, "exp_a": la, "ph": joint.sum(1), "pa": joint.sum(0),
                         "joint": joint, "total": total}
            continue
        out[stat] = {"exp_h": lh, "exp_a": la, "ph": ph, "pa": pa, "total": np.convolve(ph, pa)}
    return out
