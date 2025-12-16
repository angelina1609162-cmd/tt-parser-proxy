from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import os
import re
from urllib.parse import quote

app = Flask(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 15


# ===== HEALTH CHECK =====
@app.route("/")
def home():
    return "OK", 200


# ===== UTILS =====
def safe_get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.text
    except:
        pass
    return None


def normalize_name(name):
    return re.sub(r"\s+", " ", name.lower()).strip()


# ===== FLASHCORE =====
def flashscore_search(player):
    url = f"https://www.flashscore.com/search/?q={quote(player)}"
    html = safe_get(url)
    results = []

    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("div.searchResult"):
        if "table tennis" in row.get_text().lower():
            results.append({
                "source": "flashscore",
                "text": row.get_text(strip=True)
            })
    return results


# ===== SOFASCORE =====
def sofascore_search(player):
    url = f"https://www.sofascore.com/search/{quote(player)}"
    html = safe_get(url)
    results = []

    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a"):
        txt = a.get_text(strip=True)
        if player.lower() in txt.lower():
            results.append({
                "source": "sofascore",
                "text": txt
            })
    return results


# ===== AISCORE =====
def aiscore_search(player):
    url = f"https://www.aiscore.com/search?keyword={quote(player)}"
    html = safe_get(url)
    results = []

    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")
    for div in soup.select("div"):
        txt = div.get_text(strip=True)
        if player.lower() in txt.lower() and "table" in txt.lower():
            results.append({
                "source": "aiscore",
                "text": txt
            })
    return results


# ===== SCORE24 / BETSITY MIRRORS =====
def score24_search(player):
    url = f"https://www.score24.live/search?q={quote(player)}"
    html = safe_get(url)
    results = []

    if not html:
        return results

    soup = BeautifulSoup(html, "html.parser")
    for div in soup.select("div"):
        txt = div.get_text(strip=True)
        if player.lower() in txt.lower():
            results.append({
                "source": "score24",
                "text": txt
            })
    return results


# ===== MAIN AGGREGATOR =====
@app.route("/matches")
def matches():
    player = request.args.get("player")

    if not player:
        return jsonify({"error": "player parameter required"}), 400

    player_norm = normalize_name(player)

    data = {
        "player": player,
        "sources": {},
        "total_hits": 0
    }

    sources = [
        flashscore_search,
        sofascore_search,
        aiscore_search,
        score24_search
    ]

    for src in sources:
        try:
            res = src(player_norm)
            if res:
                data["sources"][res[0]["source"]] = res
                data["total_hits"] += len(res)
        except:
            continue

    return jsonify(data)
    

# ===== RENDER ENTRY =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
