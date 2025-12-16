from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from transliterate import translit
import concurrent.futures
import re

app = Flask(__name__)

# Источники для поиска ID
PLAYER_SOURCES = [
    "https://www.flashscore.com/player/{slug}/results/",
    "https://www.sofascore.com/player/{slug}/matches",
    "https://m.aiscore.com/ru/table-tennis/player-{slug}/",
    "https://scores24.live/ru/table-tennis/t-{slug}",
]

# Бетсити отдельный поиск пары
BETCITY_PAIR_URL = "https://betcity.ru/ru/mstat/{p1_id}:{p2_id}"  # пример формата

def slugify(name):
    # транслитерация и приведение к lower-case
    return translit(name, 'ru', reversed=True).replace(" ", "-").lower()

def fetch_html(url):
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        return None
    return None

def parse_flashscore(html):
    # базовый пример парсинга таблиц матчей
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for row in soup.select("table tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
        if cells:
            matches.append(cells)
    return matches

def search_player_ids(name):
    slug = slugify(name)
    results = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(fetch_html, url.format(slug=slug)): url for url in PLAYER_SOURCES}
        for fut in concurrent.futures.as_completed(futures):
            url = futures[fut]
            html = fut.result()
            if html:
                matches = parse_flashscore(html)
                if matches:
                    results[url] = matches
    return results

def search_pair_matches(p1_name, p2_name):
    # заглушка для Betcity, прямой поиск пары через slug
    p1_id, p2_id = 123, 456  # тут можно расширить поиск реальных ID через общий поиск
    url = BETCITY_PAIR_URL.format(p1_id=p1_id, p2_id=p2_id)
    html = fetch_html(url)
    if html:
        return parse_flashscore(html)
    return []

@app.route("/api/matches")
def get_matches():
    player1 = request.args.get("player1")
    player2 = request.args.get("player2")
    if not player1 or not player2:
        return jsonify({"error":"Введите двух игроков"}),400

    result = {
        "player1": player1,
        "player2": player2,
        "matches": [],
        "status":"ok",
        "logs":[]
    }

    # ищем ID и матчи параллельно
    try:
        p1_results = search_player_ids(player1)
        p2_results = search_player_ids(player2)
        pair_results = search_pair_matches(player1, player2)
        
        # простой валидатор совпадений
        validated_matches = []
        for src, matches in p1_results.items():
            for m in matches:
                for src2, matches2 in p2_results.items():
                    if m in matches2:
                        validated_matches.append(m)
        validated_matches.extend(pair_results)

        result["matches"] = validated_matches
    except Exception as e:
        result["logs"].append(str(e))
        result["status"] = "error"

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
