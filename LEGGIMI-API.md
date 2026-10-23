# Giocatori, assenti e quote vere

Due servizi gratuiti. Entrambi sono facoltativi: senza chiave l'app funziona come prima.

## 1. API-Football (giocatori e assenti)
1. Vai su https://dashboard.api-football.com/register e crea un account gratuito (conferma l'email).
2. Nella dashboard apri **Account → My Access**: copia la **API Key**.
3. Su GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `API_FOOTBALL_KEY`
   - Secret: la chiave copiata

Il piano gratuito dà 100 richieste al giorno: l'app scarica i giocatori un po' alla volta,
prima le squadre che giocano prima. Servono circa 5-6 giorni per avere tutte le squadre.
Se nel registro dell'aggiornamento compare "il piano gratuito non sembra coprire la stagione in corso",
il servizio non dà i dati di quest'anno gratis: l'app continua senza, e il calcolatore manuale resta.

## 2. The Odds API (quote vere)
1. Vai su https://the-odds-api.com e premi **Get API Key**, scegli il piano gratuito (**Starter**, 500 crediti al mese).
2. La chiave arriva per email.
3. Su GitHub, nuovo secret:
   - Name: `ODDS_API_KEY`
   - Secret: la chiave

Bet365 non è tra i bookmaker di questo servizio: l'app mostra la quota media dei bookmaker europei,
la migliore e Pinnacle. La quota Bet365 di solito è vicina alla media.

## 3. Aggiorna
**Actions → Aggiorna Footstats → Run workflow**. Nel registro, alla voce "Aggiorna dati e dashboard",
cerca le righe che iniziano con `quote` e `giocatori`.

## 4. L'app sul telefono
- **Android (Chrome)**: apri il sito, menu ⋮ → **Installa app** (o "Aggiungi a schermata Home").
- **iPhone (Safari)**: apri il sito, tasto Condividi → **Aggiungi alla schermata Home**.
