"""Notifiche Telegram: ogni mattina le giocate più interessanti, il lunedì il riepilogo della settimana.

Serve un solo segreto su GitHub, TELEGRAM_TOKEN (il token del bot creato con @BotFather).
La chat viene trovata da sola: basta scrivere un messaggio qualsiasi al bot prima del primo invio.
"""
import html
import json
import os
from datetime import date, datetime, timedelta

import requests

import config

STATE = config.DATA_DIR / "telegram.json"
API = "https://api.telegram.org/bot{token}/{method}"
LO, HI, MIN_LIFT = 0.40, 0.75, 0.05
DETAIL_STATS = ("corners", "cards", "fouls", "shots", "sot")


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    STATE.write_text(json.dumps(st))


def _call(token: str, method: str, **params):
    r = requests.post(API.format(token=token, method=method), json=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _chat_id(token: str, st: dict) -> int | None:
    cid = os.environ.get("TELEGRAM_CHAT_ID") or st.get("chat_id")
    if cid:
        return int(cid)
    try:
        upd = _call(token, "getUpdates").get("result", [])
    except requests.RequestException:
        return None
    for u in reversed(upd):
        chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
        if chat:
            st["chat_id"] = chat["id"]
            return chat["id"]
    return None


def _app_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/")
    return f"https://{owner.lower()}.github.io/{name}/"


def _main_lines(f: dict, mdefs: dict) -> set:
    """Per corner, cartellini, falli e tiri tiene solo la linea "principale" (quella più vicina al 50%),
    cioè quella che i bookmaker propongono di solito."""
    best = {}
    for p in f["picks"]:
        d = mdefs.get(p["key"])
        if not d or d["stat"] not in DETAIL_STATS or not d["kind"].endswith("over"):
            continue
        k = (d["stat"], d["kind"].split("_")[0])
        if k not in best or abs(p["prob"] - .5) < abs(best[k][1] - .5):
            best[k] = (d["args"][0], p["prob"])
    return {k: v[0] for k, v in best.items()}


def best_picks(preds: list[dict], mdefs: dict, days: int = 2, n: int = 5) -> list[tuple]:
    lim = str(date.today() + timedelta(days=days - 1))
    out = []
    for f in preds:
        if f["date"] > lim or any(f["new_team"]):
            continue
        main = _main_lines(f, mdefs)
        cands = []
        for p in f["picks"]:
            d = mdefs.get(p["key"], {})
            if d.get("stat") in DETAIL_STATS and "_" in d.get("kind", "") and d["kind"].split("_")[1] in ("over", "under"):
                if main.get((d["stat"], d["kind"].split("_")[0])) != d["args"][0]:
                    continue
            if p.get("base") is None or p.get("reliability") == "red" or not LO <= p["prob"] <= HI:
                continue
            lift = p["prob"] - p["base"]
            if lift >= MIN_LIFT:
                cands.append((lift, p))
        if cands:
            lift, p = max(cands, key=lambda x: x[0])
            out.append((lift, f, p))
    return sorted(out, key=lambda x: -x[0])[:n]


def _label(p: dict) -> str:
    g, l = p["group"], p["label"]
    if g == "Esito finale":
        return f"Esito {l}"
    if g == "Gol":
        return f"{l} gol" if l.split(" ")[0] in ("Over", "Under", "Casa", "Ospite") else l
    return f"{l} {g.lower()}"


def signals(preds: list[dict], days: int = 3, n: int = 8) -> list[tuple[float, str]]:
    """Segnali sui mercati preferiti: squadre che dovrebbero tirare molto in porta (attacco forte contro
    difesa che concede), partite da tiri in porta, clima caldo per i cartellini, quote con valore."""
    lim = str(date.today() + timedelta(days=days - 1))
    e = html.escape
    out = []
    for f in preds:
        if f["date"] > lim or any(f["new_team"]):
            continue
        when = f"{f['date'][8:]}/{f['date'][5:7]}"
        match = f"{e(f['home'])}–{e(f['away'])}"
        ex, ls = f.get("expected", {}).get("sot"), f.get("lside", {}).get("sot")
        if ex and ls:
            for i, t in enumerate((f["home"], f["away"])):
                r = ex[i] / ls[i]
                if r >= 1.25:
                    out.append((r - 1, f"🎯 <b>{e(t)}</b> ({match}, {when}): {ex[i]:.1f} tiri in porta attesi, +{(r - 1) * 100:.0f}% sulla media"))
            tot = (ex[0] + ex[1]) / (ls[0] + ls[1])
            if tot >= 1.18:
                out.append((tot - 1, f"🔥 {match} ({when}): partita da tiri in porta, {ex[0] + ex[1]:.1f} attesi (+{(tot - 1) * 100:.0f}%)"))
        c = f.get("climate")
        if c and (c["hot"] >= 0.15 or (f.get("rivalry") and c["hot"] >= 0.05)):
            der = f" · {e(f['rivalry']['name'])}" if f.get("rivalry") else ""
            out.append((c["hot"], f"🟨 {match} ({when}){der}: clima caldo, Over {c['line']} cartellini {c['pc'] * 100:.0f}%"))
        for p in f["picks"]:
            if p.get("edge") is not None and p.get("nbook") and p["edge"] >= 0.05 and 0.35 <= p["prob"] <= 0.8 and p.get("reliability") != "red":
                best = f" (migliore {p['best']:.2f})" if p.get("best") else ""
                out.append((p["edge"] * 2, f"💰 {match} ({when}): {e(_label(p))} al {p['prob'] * 100:.0f}%, "
                                           f"quota media {p['odds']:.2f}{best} contro quota giusta {1 / p['prob']:.2f}"))
    chosen, per = [], {}
    for sc, t in sorted(out, key=lambda x: -x[0]):
        kind = t[0]
        if per.get(kind, 0) < 2 and len(chosen) < n:  # al massimo 2 segnali dello stesso tipo
            chosen.append((sc, t))
            per[kind] = per.get(kind, 0) + 1
    return chosen


def daily_message(preds, mdefs) -> str | None:
    picks, when = best_picks(preds, mdefs, days=3), "dei prossimi 3 giorni"
    if not picks:
        picks, when = best_picks(preds, mdefs, days=7), "della settimana"
    sig = signals(preds)
    if not picks and not sig:
        return None
    e = html.escape
    lines = [f"⚽ <b>Footstats – giocate da partita {when}</b>", ""]
    for i, (lift, f, p) in enumerate(picks, 1):
        lines.append(f"<b>{i}. {e(f['home'])} – {e(f['away'])}</b> ({e(f['league'])}, {f['date'][8:]}/{f['date'][5:7]} {e(f.get('time') or '')})")
        lines.append(f"   {e(_label(p))}: <b>{p['prob']*100:.0f}%</b> · quota giusta {1/p['prob']:.2f}")
        lines.append(f"   media campionato {p['base']*100:.0f}% (+{lift*100:.0f} punti)")
    if sig:
        lines += ["", "<b>Segnali sui tuoi mercati</b>"] + [t for _, t in sig]
    lines += ["", "Gioca solo se la quota del bookmaker supera la quota giusta."]
    if _app_url():
        lines.append(f'<a href="{_app_url()}">Apri Footstats</a>')
    return "\n".join(lines)


def weekly_message(history: list[dict], adapt: dict) -> str | None:
    since = str(date.today() - timedelta(days=7))
    done = [h for h in history if h.get("won") is not None and h["date"] >= since and not h.get("extra")]
    if not done:
        return None
    hit = sum(h["won"] for h in done) / len(done)
    exp = sum(h.get("raw", h["prob"]) for h in done) / len(done)
    groups = {}
    for h in done:
        groups.setdefault(h["group"], []).append(h)
    e = html.escape
    lines = ["📊 <b>Footstats – riepilogo della settimana</b>", "",
             f"Previsioni verificate: <b>{len(done)}</b>",
             f"Uscite: <b>{hit*100:.0f}%</b> (il modello prevedeva {exp*100:.0f}%)", ""]
    for g, rows in sorted(groups.items(), key=lambda x: -len(x[1])):
        gh = sum(r["won"] for r in rows) / len(rows)
        ge = sum(r.get("raw", r["prob"]) for r in rows) / len(rows)
        lines.append(f"• {e(g)}: {gh*100:.0f}% uscite su {len(rows)} (previste {ge*100:.0f}%)")
    act = [(g, a) for g, a in adapt.items() if a.get("active") and abs(a.get("k", 1) - 1) >= 0.01]
    if act:
        lines += ["", "Correzioni adattive in uso:"]
        lines += [f"• {e(g)}: {'più prudente' if a['k'] < 1 else 'più decisa'} (×{a['k']:.2f})" for g, a in act]
    lines += ["", "Servono 100-200 previsioni prima di trarre conclusioni: una settimana dice poco."]
    return "\n".join(lines)


def send(preds: list[dict], mdefs: dict, history: list[dict], adapt: dict) -> None:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        print("  telegram: nessun token, salto")
        return
    st = _state()
    cid = _chat_id(token, st)
    if not cid:
        print("  ! telegram: chat non trovata. Scrivi un messaggio qualsiasi al tuo bot e rilancia l'aggiornamento.")
        _save(st)
        return
    today = str(date.today())
    msgs = []
    if st.get("daily") != today and (m := daily_message(preds, mdefs)):
        msgs.append(("daily", m))
    if date.today().weekday() == 0 and st.get("weekly") != today and (m := weekly_message(history, adapt)):
        msgs.append(("weekly", m))
    for kind, text in msgs:
        try:
            _call(token, "sendMessage", chat_id=cid, text=text, parse_mode="HTML", disable_web_page_preview=True)
            st[kind] = today
            print(f"  telegram: inviato messaggio {kind}")
        except requests.RequestException as ex:
            print(f"  ! telegram: invio non riuscito ({ex})")
    if not msgs:
        print("  telegram: niente di nuovo da inviare oggi")
    _save(st)
