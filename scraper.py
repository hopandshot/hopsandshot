#!/usr/bin/env python3
"""
scraper.py — собирает текущее меню напитков заведений Untappd и сохраняет
результат в CSV: текущий снимок + историю изменений.

Запуск:
    python3 scraper.py            # обычный запуск
    python3 scraper.py --debug    # + сохранить сырой HTML в debug/

Файл venues.json содержит список заведений: имя + ссылка на страницу
заведения на Untappd (https://untappd.com/v/<slug>/<id>).

Страницы загружаются через настоящий headless-браузер (Playwright), а не
через requests/cloudscraper — Untappd прикрыт защитой Cloudflare, которая
всё чаще блокирует трафик, похожий на "не настоящий браузер", даже когда
JS-проверка технически пройдена библиотекой-имитатором.

Результат:
    output/current_menu.csv  — перезаписывается каждый запуск,
                                "текущее" меню всех заведений
    output/menu_history.csv  — дополняется каждый запуск,
                                история изменений со временем
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from parser import parse_menu, list_menu_tabs, is_food_menu_label

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENUES_FILE = os.path.join(BASE_DIR, 'venues.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
DEBUG_DIR = os.path.join(BASE_DIR, 'debug')
CURRENT_CSV = os.path.join(OUTPUT_DIR, 'current_menu.csv')
HISTORY_CSV = os.path.join(OUTPUT_DIR, 'menu_history.csv')
CURRENT_JSON = os.path.join(OUTPUT_DIR, 'current_menu.json')

FIELDNAMES = [
    'scraped_at_utc', 'venue', 'section', 'category', 'serving_type',
    'beer_name', 'style', 'brewery', 'abv', 'ibu', 'rating',
    'servings_prices', 'beer_url', 'brewery_url', 'beer_id', 'venue_url',
]

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# Убирает самые очевидные признаки автоматизации, которые обычный headless
# Chromium оставляет "по умолчанию" (navigator.webdriver=true и т.п.) —
# без этого многие анти-бот системы отличают headless-браузер от настоящего
# ещё до какой-либо активности на странице.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

CLOUDFLARE_CHALLENGE_MARKERS = (
    'Just a moment',
    'cf-browser-verification',
    'Attention Required',
    'Checking your browser',
)


def load_venues():
    with open(VENUES_FILE, encoding='utf-8') as f:
        return json.load(f)


def fetch_html(page, url, retries=2, backoff=8):
    """Загружает страницу настоящим браузером, с повторными попытками.

    Если все заведения в одном прогоне падают одновременно — это почти
    всегда означает, что весь IP-адрес, выданный GitHub Actions именно
    этому запуску, целиком попал под подозрение у Cloudflare. Повтор с
    того же IP тогда не поможет — тут вытаскивает то, что следующий
    запланированный запуск получит от GitHub уже другой IP. Ретраи здесь —
    подстраховка на случай более простых временных сбоев (таймаут страницы,
    разовая сетевая ошибка и т.п.), а не средство от бана целого адреса.
    """
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            # даём странице время дорендерить контент / пройти JS-проверку
            try:
                page.wait_for_selector('.venue-page, p.menu-total', timeout=15000)
            except Exception:
                pass  # не дождались ожидаемого блока — проверим ниже по контенту

            html = page.content()

            if any(marker in html for marker in CLOUDFLARE_CHALLENGE_MARKERS):
                raise RuntimeError('Застряли на странице проверки Cloudflare')
            if '403 Forbidden' in html or 'Access denied' in html:
                raise RuntimeError('Страница вернула отказ в доступе')

            return html
        except Exception as e:
            last_error = e
            if attempt <= retries:
                print(f'  попытка {attempt} не удалась ({e}), '
                      f'жду {backoff} сек. и пробую снова...', file=sys.stderr)
                time.sleep(backoff)
    raise last_error


def write_csv(rows, path, mode):
    file_exists = os.path.exists(path)
    write_header = mode == 'w' or not file_exists
    with open(path, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_json(rows, path, venue_names, generated_at):
    data = {
        'generated_at_utc': generated_at,
        'venues': venue_names,
        'items': rows,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def scrape_venue(page, venue, debug):
    """Загружает и парсит все непищевые вкладки меню одного заведения."""
    name = venue['name']
    url = venue['url']
    safe_name = name.lower().replace(' ', '_')
    venue_rows = []

    print(f'[{name}] загрузка {url} ...')
    try:
        html = fetch_html(page, url)
    except Exception as e:
        print(f'[{name}] ОШИБКА загрузки страницы: {e}', file=sys.stderr)
        return venue_rows

    if debug:
        debug_path = os.path.join(DEBUG_DIR, f'{safe_name}.html')
        with open(debug_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'[{name}] сырой HTML сохранён в {debug_path}')

    try:
        rows = parse_menu(html, name, url)
    except Exception as e:
        print(f'[{name}] ОШИБКА парсинга: {e}', file=sys.stderr)
        return venue_rows

    print(f'[{name}] найдено позиций меню: {len(rows)}')
    venue_rows.extend(rows)
    active_section = rows[0]['section'] if rows else None

    # На странице может быть несколько вкладок меню (Draft / Bottle-Can
    # / Food) — обычная загрузка отдаёт только активную. Остальные
    # непищевые вкладки дозапрашиваем напрямую через ?menu_id=<id>.
    try:
        tabs = list_menu_tabs(html)
    except Exception as e:
        print(f'[{name}] не удалось получить список вкладок меню: {e}', file=sys.stderr)
        tabs = []

    for tab in tabs:
        if is_food_menu_label(tab['label']):
            continue
        if tab['label'] == active_section:
            continue  # это меню уже получили в основном запросе

        tab_url = f"{url}?menu_id={tab['menu_id']}"
        print(f'[{name}] пробую доп. вкладку "{tab["label"]}" ({tab_url}) ...')
        time.sleep(3)
        try:
            tab_html = fetch_html(page, tab_url)
        except Exception as e:
            print(f'[{name}] ОШИБКА загрузки вкладки "{tab["label"]}": {e}', file=sys.stderr)
            continue

        if debug:
            tab_debug_path = os.path.join(DEBUG_DIR, f"{safe_name}__menu_{tab['menu_id']}.html")
            with open(tab_debug_path, 'w', encoding='utf-8') as f:
                f.write(tab_html)
            print(f'[{name}] сырой HTML вкладки сохранён в {tab_debug_path}')

        try:
            tab_rows = parse_menu(tab_html, name, url, forced_section=tab['label'])
        except Exception as e:
            print(f'[{name}] ОШИБКА парсинга вкладки "{tab["label"]}": {e}', file=sys.stderr)
            continue

        print(f'[{name}] вкладка "{tab["label"]}": найдено позиций {len(tab_rows)}')
        venue_rows.extend(tab_rows)

    return venue_rows


def main():
    debug = '--debug' in sys.argv
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)

    venues = load_venues()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    all_rows = []
    venue_names = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale='es-ES',
            viewport={'width': 1366, 'height': 768},
            extra_http_headers={'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'},
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        page = context.new_page()

        for venue in venues:
            venue_rows = scrape_venue(page, venue, debug)
            for r in venue_rows:
                r['scraped_at_utc'] = timestamp
                all_rows.append(r)
            venue_names.append(venue['name'])
            time.sleep(3)  # вежливая пауза между заведениями

        browser.close()

    if not all_rows:
        print('Ни одной позиции меню не найдено — CSV не обновлён.', file=sys.stderr)
        sys.exit(1)

    write_csv(all_rows, CURRENT_CSV, 'w')
    write_csv(all_rows, HISTORY_CSV, 'a')
    write_json(all_rows, CURRENT_JSON, venue_names, timestamp)
    print(f'Готово: {len(all_rows)} позиций сохранено в:')
    print(f'  {CURRENT_CSV}')
    print(f'  {HISTORY_CSV}')
    print(f'  {CURRENT_JSON}')


if __name__ == '__main__':
    main()
