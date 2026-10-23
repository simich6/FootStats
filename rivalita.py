"""Derby e rivalità sentite, scontri diretti.

L'elenco dei derby è scritto a mano (nomi come li usa football-data.co.uk).
Quanto un derby "scalda" la partita invece non è inventato: si misura dallo storico,
confrontando cartellini e falli dei derby con la media del campionato nella stessa stagione.
"""
import numpy as np
import pandas as pd

DERBIES = [
    # Italia
    ("Inter", "Milan", "Derby della Madonnina"), ("Roma", "Lazio", "Derby della Capitale"),
    ("Juventus", "Torino", "Derby della Mole"), ("Genoa", "Sampdoria", "Derby della Lanterna"),
    ("Juventus", "Inter", "Derby d'Italia"), ("Napoli", "Roma", "Derby del Sole"),
    ("Fiorentina", "Juventus", "Rivalità storica"), ("Bologna", "Fiorentina", "Derby dell'Appennino"),
    ("Atalanta", "Brescia", "Derby lombardo"), ("Verona", "Chievo", "Derby di Verona"),
    ("Napoli", "Lazio", "Rivalità storica"), ("Napoli", "Juventus", "Rivalità storica"),
    ("Milan", "Juventus", "Rivalità storica"), ("Napoli", "Salernitana", "Derby campano"),
    ("Parma", "Reggiana", "Derby dell'Enza"), ("Modena", "Reggiana", "Derby emiliano"),
    ("Bari", "Lecce", "Derby di Puglia"), ("Pisa", "Fiorentina", "Derby toscano"),
    ("Cagliari", "Torres", "Derby sardo"), ("Spezia", "Sampdoria", "Derby ligure"),
    # Inghilterra
    ("Man United", "Man City", "Derby di Manchester"), ("Liverpool", "Everton", "Derby del Merseyside"),
    ("Arsenal", "Tottenham", "Derby del Nord di Londra"), ("Man United", "Liverpool", "Rivalità del Nord-Ovest"),
    ("Chelsea", "Tottenham", "Derby di Londra"), ("Arsenal", "Chelsea", "Derby di Londra"),
    ("Newcastle", "Sunderland", "Derby del Tyne-Wear"), ("Aston Villa", "Birmingham", "Derby di Birmingham"),
    ("West Ham", "Millwall", "Derby di Londra Est"), ("Crystal Palace", "Brighton", "Derby M23"),
    ("Nott'm Forest", "Derby", "Derby delle East Midlands"), ("Leeds", "Man United", "Rivalità delle Rose"),
    ("Sheffield United", "Sheffield Weds", "Derby di Sheffield"), ("Cardiff", "Swansea", "Derby del Galles del Sud"),
    ("Bristol City", "Cardiff", "Derby del Severn"), ("Norwich", "Ipswich", "Derby dell'East Anglia"),
    ("Southampton", "Portsmouth", "Derby della costa Sud"), ("West Brom", "Wolves", "Derby del Black Country"),
    ("Blackburn", "Burnley", "Derby del Lancashire"), ("Middlesbrough", "Sunderland", "Derby del Nord-Est"),
    ("Middlesbrough", "Newcastle", "Derby del Nord-Est"), ("Leicester", "Nott'm Forest", "Derby delle East Midlands"),
    ("Chelsea", "West Ham", "Derby di Londra"), ("Tottenham", "West Ham", "Derby di Londra"),
    # Spagna
    ("Real Madrid", "Barcelona", "El Clásico"), ("Real Madrid", "Ath Madrid", "Derby di Madrid"),
    ("Barcelona", "Espanol", "Derby di Barcellona"), ("Sevilla", "Betis", "Derby di Siviglia"),
    ("Ath Bilbao", "Sociedad", "Derby basco"), ("Valencia", "Levante", "Derby di Valencia"),
    ("Valencia", "Villarreal", "Derby della Comunità Valenciana"), ("Celta", "La Coruna", "Derby galiziano"),
    ("Oviedo", "Sp Gijon", "Derby asturiano"), ("Getafe", "Leganes", "Derby del sud di Madrid"),
    ("Las Palmas", "Tenerife", "Derby canario"), ("Zaragoza", "Huesca", "Derby aragonese"),
    ("Ath Madrid", "Barcelona", "Rivalità storica"), ("Real Madrid", "Ath Bilbao", "Rivalità storica"),
    ("Malaga", "Granada", "Derby andaluso"), ("Sevilla", "Real Madrid", "Rivalità storica"),
    # Germania
    ("Dortmund", "Schalke 04", "Revierderby"), ("Bayern Munich", "Dortmund", "Der Klassiker"),
    ("FC Koln", "M'gladbach", "Derby del Reno"), ("FC Koln", "Leverkusen", "Derby del Reno"),
    ("FC Koln", "Fortuna Dusseldorf", "Derby del Reno"), ("Hamburg", "Werder Bremen", "Nordderby"),
    ("Hamburg", "St Pauli", "Derby di Amburgo"), ("Hertha", "Union Berlin", "Derby di Berlino"),
    ("Nurnberg", "Greuther Furth", "Derby di Franconia"), ("Stuttgart", "Karlsruhe", "Derby del Baden-Württemberg"),
    ("Kaiserslautern", "Karlsruhe", "Südwestderby"), ("Ein Frankfurt", "Darmstadt", "Derby dell'Assia"),
    ("Hannover", "Braunschweig", "Derby della Bassa Sassonia"), ("Schalke 04", "Bochum", "Derby della Ruhr"),
    ("Dortmund", "Bochum", "Derby della Ruhr"), ("Ein Frankfurt", "Mainz", "Derby Reno-Meno"),
    ("Bayern Munich", "Augsburg", "Derby bavarese"), ("Bayern Munich", "Nurnberg", "Derby bavarese"),
    # Francia
    ("Paris SG", "Marseille", "Le Classique"), ("Lyon", "St Etienne", "Derby del Rodano"),
    ("Nice", "Monaco", "Derby della Costa Azzurra"), ("Lens", "Lille", "Derby del Nord"),
    ("Nantes", "Rennes", "Derby bretone"), ("Marseille", "Lyon", "Olympico"),
    ("Marseille", "Nice", "Derby del Sud"), ("Brest", "Lorient", "Derby bretone"),
    ("Rennes", "Brest", "Derby bretone"), ("Rennes", "Lorient", "Derby bretone"),
    ("Paris SG", "Lyon", "Rivalità storica"), ("Bordeaux", "Toulouse", "Derby della Garonna"),
    ("Montpellier", "Nimes", "Derby dell'Occitania"), ("Ajaccio", "Bastia", "Derby corso"),
]


def _norm(s: str) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


_INDEX = {frozenset((_norm(a), _norm(b))): name for a, b, name in DERBIES}


def derby(home: str, away: str) -> str | None:
    return _INDEX.get(frozenset((_norm(home), _norm(away))))


def derby_factors(matches: pd.DataFrame, prior: float = 30.0) -> dict:
    """Quanti cartellini/falli in più (o in meno) si vedono nei derby rispetto alla media
    del campionato nella stessa stagione. Con pochi derby nello storico il fattore resta vicino a 1."""
    is_d = np.array([derby(h, a) is not None for h, a in zip(matches["home"], matches["away"])])
    out = {}
    for stat in ("cards", "fouls"):
        tot = matches[f"h_{stat}"] + matches[f"a_{stat}"]
        base = tot.groupby([matches["league"], matches["season"]]).transform("mean")
        ok = is_d & tot.notna().to_numpy() & base.notna().to_numpy()
        n = int(ok.sum())
        if not n:
            out[stat] = {"factor": 1.0, "n": 0}
            continue
        obs, exp = float(tot[ok].sum()), float(base[ok].sum())
        pr = prior * exp / n
        out[stat] = {"factor": round((obs + pr) / (exp + pr), 3), "n": n}
    return out


def head_to_head(matches: pd.DataFrame, home: str, away: str, n: int = 6) -> dict:
    """Ultimi scontri diretti (in qualsiasi campionato e campo) con i totali delle statistiche."""
    m = matches[((matches["home"] == home) & (matches["away"] == away))
                | ((matches["home"] == away) & (matches["away"] == home))].sort_values("date").tail(n)
    games = []
    for r in m.to_dict("records"):
        g = {"date": str(r["date"].date()), "home": r["home"], "away": r["away"],
             "hg": int(r["h_goals"]), "ag": int(r["a_goals"])}
        for s in ("cards", "fouls", "sot", "corners", "shots"):
            h, a = r.get(f"h_{s}"), r.get(f"a_{s}")
            g[s] = None if h is None or a is None or pd.isna(h) or pd.isna(a) else float(h + a)
        games.append(g)
    avg = {}
    for s in ("cards", "fouls", "sot", "corners", "shots"):
        v = [g[s] for g in games if g[s] is not None]
        if v:
            avg[s] = round(float(np.mean(v)), 2)
    if games:
        avg["goals"] = round(float(np.mean([g["hg"] + g["ag"] for g in games])), 2)
        avg["btts"] = round(float(np.mean([g["hg"] > 0 and g["ag"] > 0 for g in games])), 2)
    return {"n": len(games), "games": games[::-1], "avg": avg}
