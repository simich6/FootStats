"""Definizione delle giocate: probabilità dal modello ed esito reale per il backtest."""
import numpy as np

GROUP = {"goals": "Gol", "corners": "Calci d'angolo", "cards": "Cartellini",
         "fouls": "Falli", "shots": "Tiri totali", "sot": "Tiri in porta"}


def _m(key, group, label, stat, kind, *args):
    return {"key": key, "group": group, "label": label, "stat": stat, "kind": kind, "args": args}


def _ou(stat, lines, side="total", prefix=""):
    out = []
    for ln in lines:
        tag = {"total": "", "home": "Casa ", "away": "Ospite "}[side]
        out.append(_m(f"{stat}_{side}_o{ln}", GROUP[stat], f"{prefix}{tag}Over {ln}", stat, f"{side}_over", ln))
        out.append(_m(f"{stat}_{side}_u{ln}", GROUP[stat], f"{prefix}{tag}Under {ln}", stat, f"{side}_under", ln))
    return out


MARKETS = [
    _m("1", "Esito finale", "1", "goals", "result", "H"),
    _m("X", "Esito finale", "X", "goals", "result", "D"),
    _m("2", "Esito finale", "2", "goals", "result", "A"),
    _m("1X", "Esito finale", "1X", "goals", "result", "HD"),
    _m("X2", "Esito finale", "X2", "goals", "result", "DA"),
    _m("12", "Esito finale", "12", "goals", "result", "HA"),
    _m("GG", "Gol", "Goal", "goals", "btts", True),
    _m("NG", "Gol", "No Goal", "goals", "btts", False),
    *_ou("goals", [0.5, 1.5, 2.5, 3.5, 4.5]),
    _m("MG12", "Gol", "Multigol 1-2", "goals", "range", 1, 2),
    _m("MG13", "Gol", "Multigol 1-3", "goals", "range", 1, 3),
    _m("MG23", "Gol", "Multigol 2-3", "goals", "range", 2, 3),
    _m("MG24", "Gol", "Multigol 2-4", "goals", "range", 2, 4),
    _m("MG14", "Gol", "Multigol 1-4", "goals", "range", 1, 4),
    _m("MG25", "Gol", "Multigol 2-5", "goals", "range", 2, 5),
    _m("MG35", "Gol", "Multigol 3-5", "goals", "range", 3, 5),
    _m("MGH12", "Gol", "Multigol Casa 1-2", "goals", "home_range", 1, 2),
    _m("MGH13", "Gol", "Multigol Casa 1-3", "goals", "home_range", 1, 3),
    _m("MGH23", "Gol", "Multigol Casa 2-3", "goals", "home_range", 2, 3),
    _m("MGA12", "Gol", "Multigol Ospite 1-2", "goals", "away_range", 1, 2),
    _m("MGA13", "Gol", "Multigol Ospite 1-3", "goals", "away_range", 1, 3),
    _m("MGA23", "Gol", "Multigol Ospite 2-3", "goals", "away_range", 2, 3),
    *_ou("goals", [0.5, 1.5], "home"),
    *_ou("goals", [0.5, 1.5], "away"),
    *_ou("corners", [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]),
    *_ou("corners", [3.5, 4.5, 5.5, 6.5], "home"),
    *_ou("corners", [2.5, 3.5, 4.5, 5.5], "away"),
    *_ou("cards", [2.5, 3.5, 4.5, 5.5]),
    *_ou("cards", [1.5, 2.5], "home"),
    *_ou("cards", [1.5, 2.5], "away"),
    *_ou("fouls", [20.5, 22.5, 24.5, 26.5]),
    *_ou("fouls", [9.5, 10.5, 11.5, 12.5, 13.5], "home"),
    *_ou("fouls", [9.5, 10.5, 11.5, 12.5, 13.5], "away"),
    *_ou("shots", [20.5, 22.5, 24.5, 26.5]),
    *_ou("shots", [9.5, 11.5, 13.5, 15.5], "home"),
    *_ou("shots", [7.5, 9.5, 11.5, 13.5], "away"),
    *_ou("sot", [6.5, 7.5, 8.5, 9.5]),
    *_ou("sot", [2.5, 3.5, 4.5, 5.5], "home"),
    *_ou("sot", [2.5, 3.5, 4.5], "away"),
]


def probability(m: dict, dist: dict) -> float | None:
    d = dist.get(m["stat"])
    if d is None:
        return None
    kind, args = m["kind"], m["args"]
    if kind in ("result", "btts"):
        joint = d["joint"] if "joint" in d else np.outer(d["ph"], d["pa"])
        if kind == "result":
            parts = {"H": np.tril(joint, -1).sum(), "D": np.trace(joint), "A": np.triu(joint, 1).sum()}
            return float(sum(parts[c] for c in args[0]))
        yes = joint[1:, 1:].sum()
        return float(yes if args[0] else 1 - yes)
    if kind in ("range", "home_range", "away_range"):
        p = {"range": d["total"], "home_range": d["ph"], "away_range": d["pa"]}[kind]
        return float(p[args[0]: args[1] + 1].sum())
    side, direction = kind.split("_")
    p = {"total": d["total"], "home": d["ph"], "away": d["pa"]}[side]
    over = p[int(np.floor(args[0])) + 1:].sum()
    return float(over if direction == "over" else 1 - over)


def outcome(m: dict, row) -> float:
    """1 se la giocata è vinta, 0 se persa, NaN se il dato non c'è."""
    h, a = row[f"h_{m['stat']}"], row[f"a_{m['stat']}"]
    if np.isnan(h) or np.isnan(a):
        return np.nan
    kind, args = m["kind"], m["args"]
    if kind == "result":
        res = "H" if h > a else "D" if h == a else "A"
        return float(res in args[0])
    if kind == "btts":
        return float((h > 0 and a > 0) == args[0])
    if kind in ("range", "home_range", "away_range"):
        v = {"range": h + a, "home_range": h, "away_range": a}[kind]
        return float(args[0] <= v <= args[1])
    side, direction = kind.split("_")
    v = {"total": h + a, "home": h, "away": a}[side]
    return float(v > args[0]) if direction == "over" else float(v < args[0])


# Quote disponibili nei dati (solo per questi mercati possiamo misurare il valore)
ODDS_MAP = {"1": ("odds_h", "close_h", ["odds_h", "odds_d", "odds_a"]),
            "X": ("odds_d", "close_d", ["odds_h", "odds_d", "odds_a"]),
            "2": ("odds_a", "close_a", ["odds_h", "odds_d", "odds_a"]),
            "goals_total_o2.5": ("odds_o25", "close_o25", ["odds_o25", "odds_u25"]),
            "goals_total_u2.5": ("odds_u25", "close_u25", ["odds_o25", "odds_u25"])}


def fair_implied(row, key: str) -> tuple[float, float] | None:
    """Quota e probabilità implicita senza margine del bookmaker."""
    if key not in ODDS_MAP:
        return None
    col, _, group = ODDS_MAP[key]
    odds = [row.get(c) for c in group]
    if any(o is None or not np.isfinite(o) or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    return row[col], (1 / row[col]) / sum(inv)
