# Footstats v0.1

Motore statistico per Serie A, Premier League, La Liga, Bundesliga e Ligue 1.
Scarica i dati, stima le probabilità di ogni giocata per le prossime partite,
verifica sul passato quanto il modello è affidabile e crea una dashboard.

## Avvio

Serve Python 3.10 o superiore.

    pip install -r requirements.txt
    python run.py

La prima volta scarica 5 stagioni e fa il backtest (qualche minuto). Poi apri
`output/dashboard.html` nel browser. Rilancia `python run.py` ogni giorno per
aggiornare risultati e calendario (puoi automatizzarlo con cron o Utilità di pianificazione).
Una volta a settimana usa `python run.py --backtest` per ricalcolare l'affidabilità.

**Taratura**: la prima volta lancia anche `python run.py --tune` (circa 10 minuti). Prova diverse
impostazioni sulle due stagioni concluse più recenti e tiene quella con le stime più precise.

**Aggiornamento automatico**: `aggiorna.sh` (Mac/Linux, con cron) o `aggiorna.bat`
(Windows, con Utilità di pianificazione). Ogni giorno aggiorna tutto, il lunedì rifà anche il backtest.

## Cosa trovi nella dashboard

- **Top della settimana** (pagina iniziale): le 3, 4 o 5 giocate più probabili del weekend o dei prossimi
  7 giorni. Per ogni partita la più probabile più fino a 2 alternative (su mercati diversi)
  se distano al massimo 5 o 10 punti. Solo mercati affidabili, con il motivo in una riga.
- **Partite**: barra 1X2, confronto atteso tra le squadre, grafico della distribuzione
  (es. probabilità di 8, 9, 10 corner), serie delle ultime 10 rispetto a una linea, andamento fatti/subiti.
- **Squadre**: forma, medie casa/trasferta, frequenze Over/Goal sulle ultime 10 e 20, trend con media mobile.
- **Campionati**: medie a partita rispetto alla stagione scorsa e andamento settimana per settimana.
- **Migliori giocate**: elenco filtrabile per campionato, mercato, probabilità e affidabilità.
- **Affidabilità**: dove il modello aiuta, calibrazione, confronto con la precisione dei bookmaker,
  profitto simulato delle giocate con valore.
- **Diario**: tocca una giocata, inserisci la quota di Eurobet/Admiral e vedi subito se conviene.
  Salvala e segna l'esito: il diario calcola profitto, ROI e se vinci quanto previsto dal modello.
  Con la gestione cassa suggerisce la puntata e avvisa quando superi il limite di perdita mensile.

La **quota giusta** è 1 / probabilità. Se Eurobet o Admiral pagano di più, secondo il modello
la giocata ha valore. Il pallino colorato indica quanto quel mercato è stato prevedibile nel backtest.

## Online, senza tenere acceso il PC (GitHub, gratis)

1. Crea un account su github.com e un nuovo repository chiamato `footstats` (pubblico:
   le pagine gratuite di GitHub richiedono un repository pubblico).
2. Carica tutti i file di questa cartella, compresa la cartella nascosta `.github`
   (dal sito: "Add file" > "Upload files", trascinando il contenuto della cartella).
3. Nel repository vai in Settings > Pages e alla voce "Source" scegli **GitHub Actions**.
4. Vai in Actions > "Aggiorna Footstats" > **Run workflow**. La prima esecuzione tara il modello
   e fa il backtest (fino a 30-40 minuti), le successive pochi minuti.
5. La dashboard sarà su `https://TUONOME.github.io/footstats/`. Dal telefono aprila e scegli
   "Aggiungi a schermata Home".

Da quel momento si aggiorna da sola ogni mattina. Per aggiornarla quando vuoi tu: app GitHub sul telefono >
repository > Actions > Aggiorna Footstats > Run workflow. Il diario resta salvato sul telefono.

## Come funziona

1. **Dati** (`providers.py`, `data.py`): CSV di football-data.co.uk con gol, tiri, tiri in porta,
   falli, corner, cartellini e quote 1X2 / Over-Under 2.5. I dati mancanti restano vuoti, mai zero.
   Database SQLite in `data/football.db`.
2. **Modello** (`model.py`): per ogni statistica stima quanto ogni squadra produce e concede,
   corretto per la forza degli avversari, separando casa e trasferta, con più peso alle partite recenti.
   Gol con distribuzione di Poisson e correzione Dixon-Coles (pareggi e risultati bassi),
   le altre statistiche con binomiale negativa.
3. **Giocate** (`markets.py`): 1X2, doppia chance, Goal/No Goal, Over/Under, Multigol,
   gol per squadra, corner, cartellini, falli, tiri, tiri in porta.
4. **Backtest** (`backtest.py`): ogni settimana il modello viene stimato solo con le partite
   precedenti. Misura Brier score, log loss, calibrazione, miglioramento rispetto alla semplice
   frequenza storica, e per i mercati con quote ROI, calo massimo e CLV. Le probabilità future
   vengono poi ricalibrate (isotonic regression) su questi risultati.
5. **Affidabilità 0-10** (`predict.py`): 60% qualità storica del mercato, 40% quantità di dati
   sulle due squadre. Non è la probabilità.
6. **API** opzionale: `uvicorn api:app --reload`.

## Limiti da conoscere

- Quote storiche solo per 1X2 e Over/Under 2.5: per corner e cartellini vedi la probabilità,
  il confronto con la quota lo fai tu con la quota giusta.
- Non considera ancora infortuni, squalifiche, turnover, arbitro e xG.
- Le squadre neopromosse partono con una stima prudente finché non accumulano partite.
- Un ROI positivo nel backtest non garantisce guadagni futuri.

## Prossimi passi

- Provider API-Football per MLS e Liga Argentina (nuova classe in `providers.py`)
- Fattore arbitro per i cartellini, xG
- PostgreSQL e scheduler automatico
