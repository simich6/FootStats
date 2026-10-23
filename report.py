"""Genera la dashboard HTML con i dati incorporati."""
import json
import re
from datetime import datetime

import config

TEMPLATE = config.ROOT / "templates" / "dashboard.html"


def firebase_config() -> dict:
    """Legge la configurazione Firebase da firebase.txt (va bene incollare il blocco
    `const firebaseConfig = {...}` così come lo mostra la console Firebase)."""
    path = config.ROOT / "firebase.txt"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    cfg = dict(re.findall(r'["\']?(\w+)["\']?\s*:\s*["\']([^"\']+)["\']', text))
    keys = ("apiKey", "authDomain", "projectId", "appId")
    return {k: v for k, v in cfg.items() if k in keys + ("storageBucket", "messagingSenderId")} if all(k in cfg for k in keys) else {}


def build(fixtures: list, trends: dict, leagues: dict, bt: dict | None, demo: bool = False,
          history: list | None = None, results: list | None = None, mdefs: dict | None = None,
          ratings: dict | None = None, adapt: dict | None = None) -> str:
    bt_view = None
    if bt:
        bt_view = {k: bt[k] for k in ("periodo", "partite", "metrics", "calibration")}
        bt_view["value"] = bt["value"]
    payload = {"generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
               "fixtures": fixtures, "trends": trends, "leagues": leagues,
               "backtest": bt_view, "demo": demo,
               "history": history or [], "results": results or [], "mdefs": mdefs or {},
               "ratings": ratings or {}, "adapt": adapt or {}, "firebase": firebase_config()}
    blob = json.dumps(payload, ensure_ascii=False, default=float).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out = config.OUTPUT_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    write_app_files()
    return str(out)


MANIFEST = {
    "name": "Footstats", "short_name": "Footstats", "lang": "it",
    "start_url": ".", "scope": ".", "display": "standalone",
    "background_color": "#EEF1EC", "theme_color": "#2E6B4F",
    "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}

# Prima prova la rete (dati sempre freschi); senza connessione mostra l'ultima versione scaricata.
SERVICE_WORKER = """const C="footstats-v1";
self.addEventListener("install",e=>self.skipWaiting());
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{const r=e.request;if(r.method!=="GET"||new URL(r.url).origin!==location.origin)return;
  e.respondWith(fetch(r).then(res=>{const cp=res.clone();caches.open(C).then(c=>c.put(r,cp));return res}).catch(()=>caches.match(r)))});
"""


def write_app_files() -> None:
    """File per installare la dashboard come app sul telefono (icona nella schermata home)."""
    import shutil
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    (config.OUTPUT_DIR / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    (config.OUTPUT_DIR / "sw.js").write_text(SERVICE_WORKER, encoding="utf-8")
    for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        src = config.ROOT / "templates" / name
        if src.exists():
            shutil.copy(src, config.OUTPUT_DIR / name)
