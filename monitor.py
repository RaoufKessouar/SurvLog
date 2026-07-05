#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Surveillance des disponibilités — résidences Smerra / Fac-Habitat.

Pour chaque résidence listée dans residences.json :
  1. Récupère la page smerra.fr  -> badge global (Dispo immédiate / Dispo à venir / Complet)
  2. Récupère l'iframe de réservation w2.fac-habitat.com -> statut par type de logement.
     Vocabulaire réel observé sur le site : "Complet", "A venir", "Disponible".
  3. Compare avec l'état précédent (state.json). Chaque statut a un rang :
        0 = Complet / Indisponible   1 = A venir   2 = Disponible
     Toute AMÉLIORATION de rang déclenche une alerte (Complet -> A venir compris).
  4. Alerte : alert.md (GitHub Actions crée une issue -> email) + Telegram si
     TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID sont définis.
"""
import csv
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "residences.json"
STATE_FILE = ROOT / "state.json"
ALERT_FILE = ROOT / "alert.md"
HIST_FILE = ROOT / "historique.csv"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Badges globaux observés sur les pages smerra.fr
BADGES = ["Disponible immédiatement", "Dispo immédiate", "Dispo à venir", "Complet"]

# Statuts par type de logement observés dans l'iframe w2.fac-habitat.com
STATUS_RE = (r"(Complet|Indisponible|[AÀ]\s?venir|Dispo\s+à\s+venir"
             r"|Dispo(?:nible)?\s+immédiate(?:ment)?"
             r"|Disponible(?:\s+à\s+partir\s+du\s+[\d/.-]+)?)")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def strip_tags(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw)


def normalize(s: str) -> str:
    """minuscules + sans accents, pour comparer les statuts de façon robuste."""
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def rank(status: str | None) -> int:
    """0 = fermé, 1 = à venir, 2 = disponible."""
    if not status:
        return 0
    s = normalize(status)
    if "complet" in s or "indisponible" in s or "inconnu" in s:
        return 0
    if "venir" in s:
        return 1
    if "dispo" in s:
        return 2
    return 0  # statut inconnu : prudent, considéré fermé (le fallback texte contient "Disponible")


RANK_LABEL = {1: "⏳ BIENTÔT DISPONIBLE (A venir)", 2: "✅ DISPONIBLE"}


def parse_badge(text: str) -> str:
    """Premier badge de statut trouvé sur la page résidence (= statut global)."""
    best = None
    for b in BADGES:
        i = text.find(b)
        if i != -1 and (best is None or i < best[1]):
            best = (b, i)
    return best[0] if best else "Inconnu"


def find_iframe_url(raw: str) -> str | None:
    m = re.search(r'https://w2\.(?:fac-habitat\.com|logifac\.fr)/[^"\'<>\s]*iframe_reservation[^"\'<>\s]*',
                  raw, re.I)
    return m.group(0) if m else None


def parse_units(raw: str) -> dict:
    """Statut par type de logement dans l'iframe de réservation."""
    text = strip_tags(raw)
    # Les types de logement sont listés dans les liens "Déposer une demande"
    types = []
    for t in re.findall(r"TYPE_LOGEMENT=([^/&\"'<>\s]+)", raw):
        t = urllib.parse.unquote_plus(t).strip()
        if t and t not in types:
            types.append(t)
    # Fallback si aucun lien trouvé : types usuels repérés dans le texte
    if not types:
        types = sorted(set(re.findall(
            r"\b(T\d(?:\s?(?:BIS|PRIME|Duplex))?(?:\s?EN\s?COLOCATION)?|Studio(?:\s?Double)?|Duo|Duplex)\b",
            text, re.I)), key=len, reverse=True)

    units = {}
    for t in sorted(types, key=len, reverse=True):  # les plus longs d'abord (T1 BIS avant T1)
        if t in units:
            continue
        m = re.search(re.escape(t) + r"\s{1,4}" + STATUS_RE, text, re.I)
        if m:
            units[t] = re.sub(r"\s+", " ", m.group(1)).strip()
        else:
            # Type présent mais aucun statut reconnu à côté -> hypothèse optimiste
            units[t] = "Disponible (statut non précisé)"
    return units


def check_residence(res: dict) -> dict:
    result = {"badge": "Inconnu", "units": {}, "erreur": None}
    try:
        raw = fetch(res["url"])
        result["badge"] = parse_badge(strip_tags(raw))
        iframe = find_iframe_url(raw)
        if iframe:
            result["iframe"] = iframe
            result["units"] = parse_units(fetch(iframe))
    except Exception as e:  # site injoignable : on garde l'ancien état
        result["erreur"] = str(e)
    return result


def diff_alerts(name: str, url: str, old: dict | None, new: dict) -> list[str]:
    """Alerte sur toute amélioration de rang (Complet -> A venir -> Disponible)."""
    alerts = []
    if new.get("erreur"):
        return alerts
    old = old or {}
    # Badge global de la résidence
    old_badge, new_badge = old.get("badge", "Inconnu"), new["badge"]
    if rank(new_badge) > rank(old_badge):
        alerts.append(f"{RANK_LABEL[rank(new_badge)]}\n"
                      f"**{name}** : statut global « {old_badge} » → « **{new_badge}** »\n{url}")
    # Statut par type de logement
    old_units = old.get("units", {})
    for t, status in new.get("units", {}).items():
        prev = old_units.get(t)  # None si type absent au passage précédent = considéré fermé
        if rank(status) > rank(prev):
            alerts.append(f"{RANK_LABEL[rank(status)]}\n"
                          f"**{name}** — logement **{t}** : « {prev or 'absent'} » → « **{status}** »\n"
                          f"Postule vite : {url}#reservation")
    return alerts


def history_rows(ts: str, name: str, old: dict | None, new: dict) -> list[list[str]]:
    """Toutes les transitions (y compris dégradations) pour l'historique CSV."""
    rows = []
    if new.get("erreur"):
        return rows
    if old is None:  # première apparition de la résidence : baseline
        rows.append([ts, name, "badge", "(début du suivi)", new["badge"]])
        for t_, s in new.get("units", {}).items():
            rows.append([ts, name, f"logement {t_}", "(début du suivi)", s])
        return rows
    if old.get("badge") != new["badge"]:
        rows.append([ts, name, "badge", old.get("badge", "?"), new["badge"]])
    old_units = old.get("units", {})
    for t_, s in new.get("units", {}).items():
        prev = old_units.get(t_)
        if prev != s:
            rows.append([ts, name, f"logement {t_}", prev or "(nouveau type)", s])
    for t_ in old_units:
        if t_ not in new.get("units", {}):
            rows.append([ts, name, f"logement {t_}", old_units[t_], "(retiré de la page)"])
    return rows


def append_history(rows: list[list[str]]) -> None:
    if not rows:
        return
    new_file = not HIST_FILE.exists()
    with HIST_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date_utc", "residence", "element", "ancien_statut", "nouveau_statut"])
        w.writerows(rows)


def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message.replace("**", ""),
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print(f"[warn] envoi Telegram échoué : {e}", file=sys.stderr)


def main() -> None:
    residences = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    old_state = {}
    first_run = not STATE_FILE.exists()
    if not first_run:
        old_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    new_state, all_alerts, hist = {}, [], []
    for res in residences:
        name, url = res["nom"], res["url"]
        result = check_residence(res)
        if result.get("erreur"):
            print(f"[warn] {name} : {result['erreur']}", file=sys.stderr)
            if name in old_state:  # garder l'ancien état pour ne pas générer de fausse alerte
                new_state[name] = old_state[name]
                continue
        new_state[name] = {"badge": result["badge"], "units": result["units"]}
        print(f"{name} -> badge: {result['badge']} | logements: {result['units']}")
        hist += history_rows(ts, name, old_state.get(name), result)
        if not first_run:
            all_alerts += diff_alerts(name, url, old_state.get(name), result)
    append_history(hist)

    new_state["_maj"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")

    if ALERT_FILE.exists():
        ALERT_FILE.unlink()
    if all_alerts:
        body = "## 🏠 Changement de disponibilité détecté !\n\n" + \
               "\n\n---\n\n".join(all_alerts) + \
               f"\n\n_Vérifié le {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}_\n"
        ALERT_FILE.write_text(body, encoding="utf-8")
        send_telegram("🏠 CHANGEMENT DE DISPONIBILITÉ !\n\n" + "\n\n".join(all_alerts))
        print(f"\n>>> {len(all_alerts)} alerte(s) générée(s) !")
    elif first_run:
        print("\nPremier passage : état de référence enregistré, pas d'alerte.")
    else:
        print("\nAucun changement de disponibilité.")


if __name__ == "__main__":
    main()
