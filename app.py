import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

app = Flask(__name__)

# ---------------- CONFIG ----------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}
TIMEOUT = 15
MAX_MATCHES = 20
MIN_MATCHES = 7

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------------- UTILS ----------------
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text
    except Exception as e:
        logging.warning(f"FETCH FAIL {url} | {e}")
    return None


def normalize_name(name):
    return re.sub(r"[^a-zа-яё ]", "", name.lower())


def parse_date(text):
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except:
            pass
    return None


# ---------------- SEARCH (REAL) ----------------
SEARCH_TEMPLATES = [
    "https://duckduckgo.com/html/?q={q}",
    "https://www.bing.com/search?q={q}"
]


def search_links(query):
    links = set()
    for tpl in SEARCH_TEMPLATES:
        html = fetch(tpl.format(q=query))
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href")
            if href and any(x in href for x in [
                "flashscore", "scores24", "aiscore",
                "sofascore", "2score", "rttf", "betcity"
            ]):
                links.add(href.split("&")[0])
    return list(links)


# ---------------- PARSERS ----------------
def parse_flashscore(url):
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.select("div.event__match"):
        date = row.select_one(".event__time")
        opp = row.select_one(".event__participant--away")
        score = row.select_one(".event__score")
        if date and opp and score:
            d = parse_date(date.text.strip())
            if d:
                out.append({
                    "date": d,
                    "opponent": opp.text.strip(),
                    "score": score.text.strip(),
                    "source": "flashscore"
                })
    return out


def parse_scores24(url):
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.select("tr"):
        cells = [c.text.strip() for c in row.select("td")]
        if len(cells) >= 4:
            d = parse_date(cells[0])
            if d:
                out.append({
                    "date": d,
                    "opponent": cells[2],
                    "score": cells[3],
                    "source": "scores24"
                })
    return out


def parse_aiscore(url):
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.select("div.match-row"):
        date = row.select_one(".date")
        opp = row.select_one(".away")
        score = row.select_one(".score")
        if date and opp and score:
            d = parse_date(date.text)
            if d:
                out.append({
                    "date": d,
                    "opponent": opp.text.strip(),
                    "score": score.text.strip(),
                    "source": "aiscore"
                })
    return out


PARSERS = {
    "flashscore": parse_flashscore,
    "scores24": parse_scores24,
    "aiscore": parse_aiscore,
}


# ---------------- VALIDATOR ----------------
def validate(matches):
    by_date = {}
    for m in matches:
        key = (m["date"], m["opponent"], m["score"])
        by_date.setdefault(key, []).append(m["source"])

    validated = []
    for (date, opp, score), srcs in by_date.items():
        if len(set(srcs)) >= 2:
            validated.append({
                "date": date,
                "opponent": opp,
                "score": score,
                "sources": list(set(srcs))
            })

    validated.sort(key=lambda x: x["date"], reverse=True)
    return validated[:MAX_MATCHES]


# ---------------- API ----------------
@app.route("/api/find_ids")
def find_ids():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "empty name"}), 400

    q = f"{name} настольный теннис профиль результаты"
    links = search_links(q)

    logging.info(f"IDS FOUND {name}: {len(links)}")
    return jsonify({"name": name, "links": links})


@app.route("/api/matches")
def get_matches():
    links = request.args.getlist("link")
    all_matches = []

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = []
        for link in links:
            for key, parser in PARSERS.items():
                if key in link:
                    futures.append(ex.submit(parser, link))

        for f in as_completed(futures):
            try:
                all_matches.extend(f.result())
            except Exception as e:
                logging.error(f"PARSER FAIL {e}")

    validated = validate(all_matches)

    return jsonify({
        "validated_count": len(validated),
        "matches": validated
    })


@app.route("/")
def root():
    return "TT parser API OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
