# Notifiche Telegram (gratis, 5 minuti)

1. Su Telegram cerca **@BotFather** (spunta blu), apri la chat e scrivi `/newbot`.
2. Ti chiede un nome (es. `Footstats`) e poi un nome utente che finisca in `bot`
   (es. `footstats_simone_bot`). Alla fine ti manda un **token**, tipo
   `7412345678:AAH...`: copialo.
3. Tocca il link del tuo nuovo bot (t.me/...) e premi **Avvia** / scrivi un messaggio qualsiasi
   (es. "ciao"). Serve perché il bot sappia a chi scrivere.
4. Su GitHub: repository → **Settings → Secrets and variables → Actions → New repository secret**.
   Nome: `TELEGRAM_TOKEN`, valore: il token del punto 2 → **Add secret**.
5. **Actions → Aggiorna Footstats → Run workflow**. A fine aggiornamento ti arriva il primo messaggio.

Da quel momento: ogni mattina le 5 giocate "da partita" più interessanti dei prossimi giorni,
e il lunedì il riepilogo della settimana (quante previsioni sono uscite rispetto al previsto).

Se dopo il passaggio 5 non arriva niente, nel registro di Actions cerca la riga che inizia con
"telegram": ti dice cosa manca (di solito il messaggio al bot del punto 3).
