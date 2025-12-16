# -*- coding: utf-8 -*-
"""
TT Multi-Source Parser – Production Version
Работает на Render / gunicorn без Selenium
"""

import os
import re
import json
import time
import logging
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, request, jsonify, Response
from bs4 import BeautifulSoup
from transliterate import translit
from rapidfuzz import fuzz

# -------------------- CONFIG --------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

TIMEOUT = 12
MAX_WORKERS = 5
FUZZY_LIMIT = 82

SOURCES = {
    "rttf": "https://rttf.ru",
    "scores24": "https://scores24.live",
    "aiscore": "https://www.aiscore.com",
    "sofascore": "https://www.sofascore.com",
}

# -------------------- APP --------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------- UTILS --------------------

def normalize_name(name: str) -> List[str]:
    name = name.strip().lower()
    variants = {name}

    try:
        variants.add(translit(name, 'ru', reversed=True))
        variants.add(translit(name, 'ru'))
    except Exception:
        pass

    base = re.sub(r"[^a-zа-яё]", "", name)
    variants.add(base)

    return list(variants)


def fuzzy_match(a: str, b: str) -> bool:
    return fuzz.ratio(a.lower(), b.lower()) >= FUZZY_LIMIT


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

# -------------------- SEARCH --------------------

def search_profiles(player: str) -> Dict[str, str]:
    results = {}
    queries = normalize_name(player)

    for source, base_url in SOURCES.items():
        for q in queries:
            try:
                html = fetch(f"{base_url}/search?q={q}")
                soup = BeautifulSoup(html, "lxml")
                for a in soup.select("a[href]"):
                    href = a.get("href")
                    text = a.get_text(strip=True).lower()
                    if href and fuzzy_match(q, text):
                        results[source] = href if href.startswith("http") else base_url + href
                        break
            except Exception:
                continue
    return results

# -------------------- PARSERS --------------------

def parse_generic(url: str, source: str) -> List[Dict]:
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    matches = []

    for row in soup.select("tr"):
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        score = cols[-1].get_text(strip=True)
        if ":" not in score:
            continue
        matches.append({
            "date": cols[0].get_text(strip=True),
            "opponent": cols[1].get_text(strip=True),
            "score": score,
            "source": source
        })
    return matches

# -------------------- CORE --------------------

def collect_matches(player: str) -> List[Dict]:
    profiles = search_profiles(player)
    all_matches = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = []
        for source, url in profiles.items():
            futures.append(ex.submit(parse_generic, url, source))

        for f in as_completed(futures):
            try:
                all_matches.extend(f.result())
            except Exception:
                continue

    return all_matches


def validate_matches(p1: str, p2: str, matches: List[Dict]) -> List[Dict]:
    valid = []
    for m in matches:
        if fuzzy_match(p2, m["opponent"]):
            valid.append(m)
    return valid

# -------------------- ROUTES --------------------

@app.route("/")
def index():
    return Response("""
    <html><body>
    <h2>TT Parser</h2>
    <form method='get' action='/api/search'>
      Player 1: <input name='p1'><br>
      Player 2: <input name='p2'><br>
      <button>Search</button>
    </form>
    </body></html>
    """, mimetype="text/html")


@app.route("/api/search")
def api_search():
    p1 = request.args.get("p1", "").strip()
    p2 = request.args.get("p2", "").strip()

    if not p1 or not p2:
        return jsonify({"error": "players required"}), 400

    matches = collect_matches(p1)
    filtered = validate_matches(p1, p2, matches)

    return jsonify({
        "player1": p1,
        "player2": p2,
        "matches": filtered,
        "total": len(filtered)
    })

# -------------------- ENTRY --------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
