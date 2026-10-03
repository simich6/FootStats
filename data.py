"""Download e normalizzazione dei dati di football-data.co.uk."""
import io
import sqlite3

import numpy as np
import pandas as pd
import requests

import config

STAT_COLUMNS = {
    "FTHG": "h_goals", "FTAG": "a_goals",
    "HS": "h_shots", "AS": "a_shots",
    "HST": "h_sot", "AST": "a_sot",
    "HF": "h_fouls", "AF": "a_fouls",
    "HC": "h_corners", "AC": "a_corners",
    "HY": "h_yellow", "AY": "a_yellow",
    "HR": "h_red", "AR": "a_red",
}

# Per ogni quota prendiamo la prima colonna disponibile (media mercato, poi Bet365, poi Pinnacle)
ODDS_COLUMNS = {
    "odds_h": ["AvgH", "B365H", "PSH"],
    "odds_d": ["AvgD", "B365D", "PSD"],
    "odds_a": ["AvgA", "B365A", "PSA"],
    "odds_o25": ["Avg>2.5", "B365>2.5", "P>2.5"],
    "odds_u25": ["Avg<2.5", "B365<2.5", "P<2.5"],
    "close_h": ["AvgCH", "B365CH", "PSCH"],
    "close_d": ["AvgCD", "B365CD", "PSCD"],
    "close_a": ["AvgCA", "B365CA", "PSCA"],
    "close_o25": ["AvgC>2.5", "B365C>2.5", "PC>2.5"],
    "close_u25": ["AvgC<2.5", "B365C<2.5", "PC<2.5"],
}

HEADERS = {"User-Agent": "Mozilla/5.0 (footstats personal research)"}


def _read_csv_bytes(content: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc, on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
    raise ValueError("Impossibile leggere il CSV")


def download(force: bool = False) -> None:
    """Scarica le stagioni. Le stagioni concluse vengono scaricate una volta sola."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    seasons = config.season_codes()
    current = seasons[-1]
    for season in seasons:
        for league in config.LEAGUES:
            path = config.RAW_DIR / f"{league}_{season}.csv"
            if path.exists() and season != current and not force:
                continue
            url = config.BASE_URL.format(season=season, league=league)
            try:
                r = requests.get(url, headers=HEADERS, timeout=30)
                r.raise_for_status()
                path.write_bytes(r.content)
                print(f"  scaricato {league} {season}")
            except requests.RequestException as e:
                print(f"  ! {league} {season} non disponibile ({e})")
    try:
        r = requests.get(config.FIXTURES_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        (config.RAW_DIR / "fixtures.csv").write_bytes(r.content)
        print("  scaricato calendario prossime partite")
    except requests.RequestException as e:
        print(f"  ! calendario non disponibile ({e})")


def _pick_odds(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for name, candidates in ODDS_COLUMNS.items():
        col = next((c for c in candidates if c in df.columns), None)
        out[name] = pd.to_numeric(df[col], errors="coerce") if col else np.nan
    return out


def normalize(raw: pd.DataFrame, league: str, season: str | None) -> pd.DataFrame:
    raw = raw.dropna(subset=["HomeTeam", "AwayTeam", "Date"])
    df = pd.DataFrame({
        "league": league,
        "season": season,
        "date": pd.to_datetime(raw["Date"], dayfirst=True, format="mixed", errors="coerce"),
        "home": raw["HomeTeam"].str.strip(),
        "away": raw["AwayTeam"].str.strip(),
        "time": raw["Time"].astype(str) if "Time" in raw.columns else "",
    })
    for src, dst in STAT_COLUMNS.items():
        # dato mancante = NaN, mai zero
        df[dst] = pd.to_numeric(raw[src], errors="coerce") if src in raw.columns else np.nan
    df["h_cards"] = df["h_yellow"] + df["h_red"]
    df["a_cards"] = df["a_yellow"] + df["a_red"]
    df = pd.concat([df, _pick_odds(raw)], axis=1)
    return df.dropna(subset=["date"])


def build_database() -> pd.DataFrame:
    frames = []
    for season in config.season_codes():
        for league in config.LEAGUES:
            path = config.RAW_DIR / f"{league}_{season}.csv"
            if not path.exists():
                continue
            raw = _read_csv_bytes(path.read_bytes())
            df = normalize(raw, league, season)
            frames.append(df.dropna(subset=["h_goals", "a_goals"]))
    if not frames:
        raise SystemExit("Nessun dato trovato: esegui prima il download.")
    matches = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
    with sqlite3.connect(config.DB_PATH) as con:
        matches.to_sql("matches", con, if_exists="replace", index=False)
    return matches


def load_matches() -> pd.DataFrame:
    with sqlite3.connect(config.DB_PATH) as con:
        df = pd.read_sql("SELECT * FROM matches", con, parse_dates=["date"])
    return df


def load_fixtures() -> pd.DataFrame:
    path = config.RAW_DIR / "fixtures.csv"
    if not path.exists():
        return pd.DataFrame()
    raw = _read_csv_bytes(path.read_bytes())
    if "Div" not in raw.columns:
        return pd.DataFrame()
    raw = raw[raw["Div"].isin(config.LEAGUES.keys())]
    frames = [normalize(g, league, None) for league, g in raw.groupby("Div")]
    if not frames:
        return pd.DataFrame()
    fx = pd.concat(frames, ignore_index=True)
    return fx.sort_values("date").reset_index(drop=True)
