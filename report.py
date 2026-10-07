"""Genera la dashboard HTML con i dati incorporati."""
import json
from datetime import datetime

import config

TEMPLATE = config.ROOT / "templates" / "dashboard.html"


def build(fixtures: list, trends: dict, leagues: dict, bt: dict | None, demo: bool = False,
          history: list | None = None, results: list | None = None, mdefs: dict | None = None,
          ratings: dict | None = None) -> str:
    bt_view = None
    if bt:
        bt_view = {k: bt[k] for k in ("periodo", "partite", "metrics", "calibration")}
        bt_view["value"] = bt["value"]
    payload = {"generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
               "fixtures": fixtures, "trends": trends, "leagues": leagues,
               "backtest": bt_view, "demo": demo,
               "history": history or [], "results": results or [], "mdefs": mdefs or {},
               "ratings": ratings or {}}
    blob = json.dumps(payload, ensure_ascii=False, default=float).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out = config.OUTPUT_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return str(out)
