#!/bin/sh
# Aggiornamento automatico (Mac/Linux). Per eseguirlo ogni mattina alle 8:
#   crontab -e   e aggiungi la riga:
#   0 8 * * * /percorso/footstats/aggiorna.sh >> /percorso/footstats/aggiorna.log 2>&1
cd "$(dirname "$0")"
if [ "$(date +%u)" = "1" ]; then python3 run.py --backtest; else python3 run.py; fi
