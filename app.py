from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import httpx
from bs4 import BeautifulSoup
import re
import unicodedata
import difflib
import logging

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROXY = "https://tt-parser-proxy.onrender.com?url="

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# Источники
SOURCES = {
    "flashscore": "flashscore.com/player/",
    "sofascore": "sofascore.com/table-tennis/player/",
    "scores24": "scores24.live",
    "aiscore": "aiscore.com",
    "betcity": "betcity.ru",
    "rttf": "rttf.ru/players/"
}

# Логгер
logger = logging.getLogger("parser")
logging.basicConfig(level=logging.INFO)

# Транслитерация
def translit(name: str) -> str:
    table = str.maketrans({
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
        'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i',
        'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
        'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'shch', 'ы': 'y', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'ь': '', 'ъ': ''
    })
    return name.lower().translate(table)

# Поиск ID игрока
@app.get("/search_ids")
async def search_ids(name: str) -> Dict[str, Any]:
    query_variants = [
        name,
        translit(name),
        f"{name} настольный теннис профиль результаты",
        f"{translit(name)} table tennis profile results"
    ]

    found_links = set()
    async with httpx.AsyncClient(timeout=30) as client:
        for q in query_variants:
            for engine in ["https://www.google.com/search?q=", "https://yandex.ru/search/?text="]:
                try:
                    full_url = PROXY + engine + q.replace(" ", "+")
                    r = await client.get(full_url, headers=HEADERS)
                    soup = BeautifulSoup(r.text, "lxml")
                    links = [a['href'] for a in soup.find_all("a", href=True)]
                    for link in links:
                        for key in SOURCES:
                            if SOURCES[key] in link:
                                found_links.add(link.split("?")[0])
                except Exception as e:
                    logger.warning(f"Search error: {e}")
    return {"player": name, "links": list(found_links)}

# Валидация матчей
def extract_matches(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    matches = []

    for table in tables:
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) >= 3 and re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", " ".join(cells)):
                matches.append(" | ".join(cells))
    return matches

# Сопоставление матчей двух игроков
def intersect_matches(m1: List[str], m2: List[str]) -> List[str]:
    return [m for m in m1 if any(difflib.SequenceMatcher(None, m, x).ratio() > 0.85 for x in m2)]

# Получение матчей по ссылкам
@app.post("/get_matches")
async def get_matches(players: Dict[str, List[str]]) -> Dict[str, Any]:
    results = {}
    logs = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for player, links in players.items():
            all_matches = []
            logs[player] = []
            for url in links:
                try:
                    r = await client.get(PROXY + url, headers=HEADERS)
                    if r.status_code != 200:
                        logs[player].append(f"❌ {url} — HTTP {r.status_code}")
                        continue
                    matches = extract_matches(r.text)
                    if matches:
                        logs[player].append(f"✅ {url} — {len(matches)} матчей")
                        all_matches.extend(matches)
                    else:
                        logs[player].append(f"⚠️ {url} — таблицы не найдены")
                except Exception as e:
                    logs[player].append(f"❌ {url} — ошибка: {str(e)}")
            results[player] = all_matches[:50]

    # Валидация: пересечение матчей
    players_list = list(results.keys())
    if len(players_list) == 2:
        common = intersect_matches(results[players_list[0]], results[players_list[1]])
        if len(common) >= 2:
            return {
                "validated": True,
                "common_matches": common[:20],
                "logs": logs
            }
        else:
            return {
                "validated": False,
                "reason": "Недостаточно совпадающих матчей",
                "logs": logs
            }
    else:
        raise HTTPException(status_code=400, detail="Нужно два игрока для валидации")
