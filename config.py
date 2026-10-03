"""Impostazioni generali del progetto."""
from datetime import date
from pathlib import Path

LEAGUES = {
    "I1": "Serie A",
    "E0": "Premier League",
    "SP1": "La Liga",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
}

N_SEASONS = 5  # stagioni di storico (compresa quella in corso)

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "football.db"
OUTPUT_DIR = ROOT / "output"

# Modello
HALF_LIFE_DAYS = 150     # una partita di 150 giorni fa pesa la metà di una di oggi
LOOKBACK_DAYS = 730      # storico massimo usato per stimare le squadre
SHRINK_MATCHES = 4.0     # "partite fittizie" nella media: evita valutazioni estreme con pochi dati
MIN_HISTORY = 120
DIXON_COLES = True       # corregge la sottostima di pareggi e risultati bassi        # partite minime di campionato prima di iniziare a prevedere

# Backtest e valore
BACKTEST_SEASONS = 3     # ultime stagioni simulate (walk-forward)
MIN_EDGE = 0.03          # vantaggio minimo (3 punti %) per contare una giocata "di valore"


def season_codes(n: int = N_SEASONS, today: date | None = None) -> list[str]:
    """Codici stagione in formato football-data, es. '2627' per 2026/27."""
    today = today or date.today()
    start = today.year if today.month >= 7 else today.year - 1
    years = range(start - n + 1, start + 1)
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in years]


# Parametri tarati con `python run.py --tune` (se presenti sostituiscono quelli sopra)
PARAMS_PATH = DATA_DIR / "params.json"
if PARAMS_PATH.exists():
    import json as _json
    for _k, _v in _json.loads(PARAMS_PATH.read_text()).items():
        globals()[_k] = _v
