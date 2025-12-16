import re
import time
import logging
from typing import List, Dict, Tuple, Set
from urllib.parse import quote_plus

import requests
from flask import Flask, request, jsonify, render_template
from bs4 import BeautifulSoup
from transliterate import translit
from rapidfuzz import fuzz
from dateutil import parser as dateparser

# =========================
# CONFIG
# =========================

APP_NAME = "tt-parser-proxy"
TIMEOUT = 12
MAX_PROFILES = 12
MAX_MATCHES_PER_SOURCE = 25
FUZZY_THRESHOLD = 82

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"
}

SEARCH_DOMAINS = [
    "rttf.ru",
    "scores24.live",
    "aiscore.com",
    "sofascore.com",
    "flashscore.",
]

# =========================
# INIT
# =========================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

session = requests.Session()
session.headers.update(HEADERS)

# =========================
# UTILS
# =========================

def normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-zа-яё]", "", name)
    return name

def generate_name_variants(name: str) -> Set[str]:
    variants = set()
    base = normalize_name(name)
    variants.add(base)

    try:
        en = translit(base, "ru", reversed=True)
        variants.add(normalize_name(en))
    except Exception:
        pass

    return variants

def fuzzy_match(a: str, b: str) -> bool:
    return fuzz.ratio(a, b) >= FUZZY_THRESHOLD

def safe_get(url: str) -> str | None:
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and len(r.text) > 500:
            return r.text
    except Exception:
        return None
    return None

def parse_date(text: str) -> str | None:
    try:
        dt = dateparser.parse(text, dayfirst=True, fuzzy=True)
        if dt:
            return dt.date().isoformat()
    except Exception:
        pass
    return None

# =========================
# PROFILE SEARCH (GOOGLE)
# =========================

def google_search_profiles(player: str) -> List[str]:
    results = set()
    variants = generate_name_variants(player)

    for name in variants:
        query = f"{name} table tennis results profile"
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        html = safe_get(url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        for a in soup.select("a[href]"):
            href = a["href"]
            if href.startswith("/url?q="):
                href = href.split("/url?q=")[1].split("&")[0]

            if any(d in href for d in SEARCH_DOMAINS):
                results.add(href)

            if len(results) >= MAX_PROFILES:
                break

    return list(results)

# =========================
# MATCH PARSING
# =========================

def extract_matches_generic(html: str, player: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    matches = []
    player_norms = generate_name_variants(player)

    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 4:
            continue

        date = parse_date(cells[0])
        if not date:
            continue

        opponent = None
        score = None

        for c in cells:
            if ":" in c and re.search(r"\d+:\d+", c):
                score = c
            if re.search(r"[A-Za-zА-Яа-я]", c):
                opponent = c

        if not opponent or not score:
            continue

        opp_norm = normalize_name(opponent)
        if any(fuzzy_match(opp_norm, p) for p in player_norms):
            continue  # сам с собой

        matches.append({
            "date": date,
            "opponent": opponent,
            "score": score
        })

        if len(matches) >= MAX_MATCHES_PER_SOURCE:
            break

    return matches

# =========================
# CORE LOGIC
# =========================

def collect_player_matches(player: str) -> Tuple[List[Dict], List[str]]:
    logs = []
    all_matches = []

    profiles = google_search_profiles(player)
    logs.append(f"profiles_found={len(profiles)}")

    for url in profiles:
        html = safe_get(url)
        if not html:
            logs.append(f"fail_load: {url}")
            continue

        matches = extract_matches_generic(html, player)
        if matches:
            all_matches.extend(matches)
            logs.append(f"ok {url} -> {len(matches)}")
        else:
            logs.append(f"no_matches {url}")

    # дедупликация
    uniq = {}
    for m in all_matches:
        key = (m["date"], m["opponent"], m["score"])
        uniq[key] = m

    final = sorted(
        uniq.values(),
        key=lambda x: x["date"],
        reverse=True
    )[:20]

    return final, logs

# =========================
# ROUTES
# =========================

@app.route("/")
def index():
    return """
    <html>
    <head><meta charset="utf-8"><title>TT Parser</title></head>
    <body>
      <h3>TT Parser</h3>
      <form action="/api/search">
        <input name="p1" placeholder="Игрок 1"><br><br>
        <input name="p2" placeholder="Игрок 2"><br><br>
        <button>Поиск</button>
      </form>
    </body>
    </html>
    """

@app.route("/api/search")
def api_search():
    p1 = request.args.get("p1", "").strip()
    p2 = request.args.get("p2", "").strip()

    if not p1 or not p2:
        return jsonify({"error": "need two players"}), 400

    m1, log1 = collect_player_matches(p1)
    m2, log2 = collect_player_matches(p2)

    return jsonify({
        "player1": p1,
        "matches1": m1,
        "player2": p2,
        "matches2": m2,
        "audit": log1 + log2
    })

# =========================
# ENTRY
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
