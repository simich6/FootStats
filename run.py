"""Uso:
    python run.py              scarica i dati, prevede le prossime partite, crea la dashboard
    python run.py --backtest   come sopra, ma rifà anche il backtest (lento: qualche minuto)
    python run.py --offline    usa i dati già scaricati
    python run.py --tune       tara il modello sui dati (circa 10 minuti, poi rifà il backtest)
"""
import argparse

import pandas as pd
import json

import backtest
import config
import history
import predict
from providers import FootballDataCoUkProvider


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true", help="rifai il backtest walk-forward")
    ap.add_argument("--tune", action="store_true", help="tara i parametri del modello")
    ap.add_argument("--offline", action="store_true", help="non scaricare nulla")
    args = ap.parse_args()

    config.DATA_DIR.mkdir(exist_ok=True)
    provider = FootballDataCoUkProvider()
    if not args.offline:
        print("1/4 Download dati")
        provider.sync()
        import data as _data
        _data.download_support()
    print("2/4 Database")
    matches = provider.matches()
    print(f"    {len(matches)} partite, {matches['date'].min().date()} → {matches['date'].max().date()}")

    tuned = args.tune or config.PARAMS_OUTDATED
    if tuned:
        print("   Taratura del modello")
        backtest.tune(matches)
    bt = backtest.load()
    import markets
    if args.backtest or tuned or bt is None or bt.get("mv") != markets.MARKETS_VERSION \
            or not (config.DATA_DIR / "profili.csv").exists():
        print("3/4 Backtest walk-forward (una tantum, qualche minuto)")
        bt = backtest.run(matches)
    else:
        print("3/4 Backtest: uso quello salvato (--backtest per rifarlo)")

    print("4/4 Previsioni e dashboard")
    fixtures = provider.fixtures(matches)
    import giocatori
    import quote
    quotes = {}
    if not args.offline:
        try:  # le fonti extra non devono mai bloccare l'aggiornamento
            quotes = quote.update(fixtures)
        except Exception as ex:
            print(f"  ! quote: errore ({ex})")
    preds = predict.predict_fixtures(matches, fixtures, bt, quotes) if len(fixtures) else []
    if not args.offline:
        try:
            giocatori.attach(preds, giocatori.update(fixtures, matches))
        except Exception as ex:
            print(f"  ! giocatori: errore ({ex})")
    # coppe europee (sperimentale) e stato di forma delle squadre
    import data as _data
    import europa
    import forma
    support = _data.build_support()
    euro = {"fixtures": [], "results": [], "ratings": {}, "trend_teams": set()}
    if not args.offline:
        try:
            euro = europa.update(matches, support, bt)
        except Exception as ex:
            print(f"  ! coppe: errore ({ex})")
    preds += euro["fixtures"]
    games = pd.concat([matches, support], ignore_index=True) if not support.empty else matches
    try:
        forma.attach(preds, games, euro["results"])
    except Exception as ex:
        print(f"  ! forma: errore ({ex})")
    trends = predict.team_trends(matches)
    if not support.empty and euro["trend_teams"]:
        trends.update(predict.team_trends(support, only=euro["trend_teams"]))
    leagues = predict.league_trends(matches)
    (config.OUTPUT_DIR).mkdir(exist_ok=True)
    past = history.load()
    adapt = history.adaptive(past)
    history.apply_adaptive(preds, adapt)
    active = {g: a["k"] for g, a in adapt.items() if a["active"]}
    (config.OUTPUT_DIR / "predictions.json").write_text(json.dumps(preds, ensure_ascii=False, default=float))
    print(f"    correzioni adattive attive: {active or 'nessuna (servono 50 previsioni verificate per mercato)'}")
    hist = history.update(past, history.top_candidates(preds, bt is not None) + history.climate_candidates(preds), matches)
    history.save(hist)
    done = [h for h in hist if h["won"] is not None]
    print(f"    storico: {len(hist)} previsioni, {len(done)} verificate")
    import schedine
    today_slips, slips = [], []
    try:  # schedine a quota: proposte del giorno e verifica di quelle passate
        today_slips = schedine.propose(preds, hist, bt is not None)
        slips = schedine.update(schedine.load(), today_slips, matches)
        schedine.save(slips)
        print(f"    schedine a quota: {len(today_slips)} proposte oggi, {sum(1 for s in slips if s.get('won') is not None)} verificate")
    except Exception as ex:
        print(f"  ! schedine: errore ({ex})")
    import report
    path = report.build(preds, trends, leagues, bt, history=hist, adapt=adapt,
                        results=history.recent_results(matches), mdefs=history.market_defs(),
                        ratings={**predict.export_ratings(matches), **euro["ratings"]}, slips=slips)
    try:
        import notify
        notify.send(preds, history.market_defs(), hist, adapt, today_slips)
    except Exception as ex:  # le notifiche non devono mai bloccare l'aggiornamento
        print(f"  ! telegram: errore ({ex})")
    print(f"\nFatto. Apri {path} nel browser.")


if __name__ == "__main__":
    main()
