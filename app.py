from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import requests, re, time, threading
from transliterate import translit
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from difflib import SequenceMatcher
from urllib.parse import quote_plus

app = Flask(__name__)

# ------------------------
# Настройки
# ------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}
MAX_THREADS = 5
TIMEOUT = 12

AUDIT_LOG = []

# ------------------------
# Утилиты
# ------------------------
def log_audit(event: str, url: str = "", info: str = ""):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    AUDIT_LOG.append(f"{timestamp} | {event} | {url} | {info}")

def normalize_name(name: str) -> str:
    return re.sub(r'[^a-zа-я]', '', name.lower())

def normalize_date(date_str: str) -> str:
    match = re.match(r'(\d{2})\.(\d{2})\.(\d{2,4})', date_str)
    if match:
        d, m, y = match.groups()
        if len(y) == 2: y = '20' + y
        return f"{y}-{m}-{d}"
    return None

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

# ------------------------
# Selenium driver
# ------------------------
def create_driver():
    options = Options()
    options.headless = True
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(TIMEOUT)
    return driver

# ------------------------
# Поиск профилей
# ------------------------
def search_profiles(name_ru):
    name_en = translit(name_ru, 'ru', reversed=True).lower().replace(' ', '-')
    queries = [
        f"{name_ru} настольный теннис профиль результаты статистика",
        f"{name_en} table tennis profile results statistics"
    ]
    profiles = set()
    for q in queries:
        search_url = f"https://www.google.com/search?q={quote_plus(q)}"
        try:
            r = requests.get(search_url, headers=HEADERS, timeout=TIMEOUT)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('/url?q='):
                    href = requests.utils.unquote(href.split('/url?q=')[1].split('&')[0])
                if any(domain in href for domain in ['rttf.ru/players/', 'sofascore.com', 'aiscore.com', 'scores24.live', 'flashscore.', 'betcity.ru']):
                    profiles.add(href)
        except Exception as e:
            log_audit("SEARCH_ERROR", search_url, str(e))
    log_audit("PROFILES_FOUND", "", f"{len(profiles)} профилей для {name_ru}")
    return list(profiles)

# ------------------------
# Парсинг страниц
# ------------------------
def fetch_matches(url):
    matches = []
    try:
        driver = create_driver()
        driver.get(url)
        time.sleep(2)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        if 'rttf.ru' in url:
            tables = soup.find_all('table')
            for table in tables:
                for row in table.find_all('tr'):
                    cells = [c.get_text(strip=True) for c in row.find_all(['td','th'])]
                    if len(cells) >= 6 and normalize_date(cells[0]):
                        matches.append((normalize_date(cells[0]), normalize_name(cells[5]), cells[-1]))
        elif 'sofascore.com' in url:
            items = soup.find_all('div', {'class': re.compile('MatchRow|match-row')})
            for item in items:
                date_el = item.find('div', string=re.compile(r'\d{2}\.\d{2}'))
                score_el = item.find('div', string=re.compile(r'\d+:\d+'))
                opp_el = item.find('div', string=re.compile(r'[A-Za-zА-Яа-я]'))
                if date_el and score_el and opp_el:
                    matches.append((normalize_date(date_el.text), normalize_name(opp_el.text), score_el.text))
        else:
            for row in soup.find_all('tr'):
                cells = [c.get_text(strip=True) for c in row.find_all(['td','th'])]
                if len(cells) >= 4 and normalize_date(cells[0]):
                    opponent = next((c for c in cells if re.match(r'^[A-Za-zА-Яа-я\s\-\.]+$', c)), "")
                    score = next((c for c in cells if ':' in c), "")
                    if opponent and score:
                        matches.append((normalize_date(cells[0]), normalize_name(opponent), score))
        log_audit("FETCH_SUCCESS", url, f"{len(matches)} матчей")
    except TimeoutException:
        log_audit("TIMEOUT", url)
    except WebDriverException as e:
        log_audit("SELENIUM_ERROR", url, str(e))
    except Exception as e:
        log_audit("PARSE_ERROR", url, str(e))
    finally:
        try: driver.quit()
        except: pass
    return matches[-20:]

# ------------------------
# Мультипрофильный fetch
# ------------------------
def get_matches_from_profiles(profiles):
    matches_set = set()
    logs = []
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(fetch_matches, url): url for url in profiles}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                src_matches = future.result()
                if src_matches:
                    matches_set.update(src_matches)
                    logs.append(f"{url}: {len(src_matches)} матчей")
                else:
                    logs.append(f"{url}: нет матчей")
            except Exception as e:
                logs.append(f"{url}: ошибка {e}")
    # сортировка по дате
    matches_sorted = sorted(list(matches_set), reverse=True)[:20]
    return matches_sorted, logs

# ------------------------
# Flask endpoints
# ------------------------
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
        "logs": logs1 + logs2,
        "audit": AUDIT_LOG[-50:]  # последние 50 записей аудита
    })

@app.route('/api/audit', methods=['GET'])
def get_audit():
    return jsonify({"audit": AUDIT_LOG})

if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=5000)
