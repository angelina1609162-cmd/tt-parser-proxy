from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
from transliterate import translit
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}

# === Функции загрузки и поиска профилей ===
def fetch_url(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.text
    except Exception:
        return None
    return None

def search_profiles(name_ru):
    """
    Мультиисточниковый поиск профилей через Google.
    Возвращает уникальные ссылки на RTTF, Sofascore, Scores24, Flashscore, Aiscore, Betcity.
    """
    name_en = translit(name_ru, 'ru', reversed=True).lower().replace(' ', '-')
    queries = [
        f"{name_ru} настольный теннис профиль результаты статистика",
        f"{name_en} table tennis profile results statistics"
    ]
    profiles = set()
    for q in queries:
        search_url = f"https://www.google.com/search?q={quote_plus(q)}"
        html = fetch_url(search_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/url?q='):
                href = requests.utils.unquote(href.split('/url?q=')[1].split('&')[0])
            if any(domain in href for domain in ['rttf.ru/players/', 'sofascore.com', 'aiscore.com', 'scores24.live', 'flashscore.', 'betcity.ru']):
                profiles.add(href)
    return list(profiles)

# === Нормализация данных ===
def normalize_opponent(opp):
    return re.sub(r'[^a-zа-я]', '', opp.lower())

def normalize_date(date_str):
    match = re.match(r'(\d{2})\.(\d{2})\.(\d{4}|\d{2})', date_str)
    if match:
        d, m, y = match.groups()
        if len(y) == 2:
            y = '20' + y
        return f"{y}-{m}-{d}"
    return None

# === Парсеры по сайтам ===
def parse_rttf(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    tables = soup.find_all('table')
    for table in tables:
        for row in table.find_all('tr'):
            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
            if len(cells) >= 6 and normalize_date(cells[0]):
                date = normalize_date(cells[0])
                opponent = normalize_opponent(cells[5] or cells[6])
                score = cells[-1]
                matches.append((date, opponent, score))
    return matches[-20:]

def parse_sofascore(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    items = soup.find_all('div', {'class': re.compile('MatchRow')})
    for item in items:
        date_el = item.find('div', text=re.compile(r'\d{2}\.\d{2}'))
        if date_el:
            date = normalize_date(date_el.text)
            opp = item.find('div', string=re.compile(r'[A-Za-zА-Яа-я]'))
            score = item.find('div', string=re.compile(r'\d+:\d+'))
            if date and opp and score:
                matches.append((date, normalize_opponent(opp.text), score.text))
    return matches[-20:]

def parse_generic(html):
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for row in soup.find_all('tr'):
        cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
        if len(cells) >= 4 and normalize_date(cells[0]):
            date = normalize_date(cells[0])
            score = next((c for c in cells if ':' in c and c.count(':') == 1 and c.replace(':', '').isdigit()), None)
            opponent = next((c for c in cells if re.match(r'^[A-Za-zА-Яа-я\s\-\.]+$', c)), None)
            if date and opponent and score:
                matches.append((date, normalize_opponent(opponent), score))
    return matches[-20:]

# === Получение матчей из всех профилей ===
def get_matches_from_profiles(profiles):
    matches_set = set()
    logs = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(fetch_url, url): url for url in profiles}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            html = future.result()
            if not html:
                logs.append(f"Ошибка загрузки {url}")
                continue
            if 'rttf.ru' in url:
                src_matches = parse_rttf(html)
            elif 'sofascore.com' in url:
                src_matches = parse_sofascore(html)
            else:
                src_matches = parse_generic(html)
            if src_matches:
                matches_set.update(src_matches)
                logs.append(f"Успех {url}: {len(src_matches)} матчей")
            else:
                logs.append(f"Нет матчей в {url}")
    # сортировка по дате
    return sorted(list(matches_set), reverse=True)[:20], logs

# === Flask маршруты ===
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['GET'])
def api_search():
    p1 = request.args.get('p1', '').strip()
    p2 = request.args.get('p2', '').strip()
    if not p1 or not p2:
        return jsonify({"error": "Введите обе фамилии"}), 400

    profiles1 = search_profiles(p1)
    profiles2 = search_profiles(p2)

    matches1, logs1 = get_matches_from_profiles(profiles1)
    matches2, logs2 = get_matches_from_profiles(profiles2)

    return jsonify({
        "player1": p1,
        "matches1": [f"{d} vs {o} {s}" for d, o, s in matches1],
        "player2": p2,
        "matches2": [f"{d} vs {o} {s}" for d, o, s in matches2],
        "logs": logs1 + logs2
    })

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
