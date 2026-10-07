"""Uso:
    python run.py              scarica i dati, prevede le prossime partite, crea la dashboard
    python run.py --backtest   come sopra, ma rifà anche il backtest (lento: qualche minuto)
    python run.py --offline    usa i dati già scaricati
    python run.py --tune       tara il modello sui dati (circa 10 minuti, poi rifà il backtest)
"""
import argparse
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
    print("2/4 Database")
    matches = provider.matches()
    print(f"    {len(matches)} partite, {matches['date'].min().date()} → {matches['date'].max().date()}")

    tuned = args.tune or config.PARAMS_OUTDATED
    if tuned:
        print("   Taratura del modello")
        backtest.tune(matches)
    bt = backtest.load()
    if args.backtest or tuned or bt is None:
        print("3/4 Backtest walk-forward (una tantum, qualche minuto)")
        bt = backtest.run(matches)
    else:
        print("3/4 Backtest: uso quello salvato (--backtest per rifarlo)")

    print("4/4 Previsioni e dashboard")
    fixtures = provider.fixtures(matches)
    preds = predict.predict_fixtures(matches, fixtures, bt) if len(fixtures) else []
    trends = predict.team_trends(matches)
    leagues = predict.league_trends(matches)
    (config.OUTPUT_DIR).mkdir(exist_ok=True)
    (config.OUTPUT_DIR / "predictions.json").write_text(json.dumps(preds, ensure_ascii=False, default=float))
    hist = history.update(history.load(), history.top_candidates(preds, bt is not None), matches)
    history.save(hist)
    done = [h for h in hist if h["won"] is not None]
    print(f"    storico: {len(hist)} previsioni, {len(done)} verificate")
    import report
    path = report.build(preds, trends, leagues, bt, history=hist,
                        results=history.recent_results(matches), mdefs=history.market_defs(),
                        ratings=predict.export_ratings(matches))
    print(f"\nFatto. Apri {path} nel browser.")


if __name__ == "__main__":
    main()
