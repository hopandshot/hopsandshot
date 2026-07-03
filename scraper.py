#!/usr/bin/env python3
"""
scraper.py — собирает текущее меню напитков заведений Untappd и сохраняет
результат в CSV: текущий снимок + историю изменений.

Запуск:
    python3 scraper.py            # обычный запуск
    python3 scraper.py --debug    # + сохранить сырой HTML в debug/

Файл venues.json содержит список заведений: имя + ссылка на страницу
заведения на Untappd (https://untappd.com/v/<slug>/<id>).

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

import cloudscraper

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

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
}


def load_venues():
    with open(VENUES_FILE, encoding='utf-8') as f:
        return json.load(f)


def fetch_html(scraper, url, retries=2, backoff=8):
    """Загружает страницу с повторными попытками.

    Если все заведения в одном прогоне падают с 403 одновременно — это
    почти всегда означает, что весь IP-адрес, выданный GitHub Actions
    именно этому запуску, целиком попал под подозрение у Cloudflare, а не
    что конкретный запрос был "неудачным". Повтор с той же сессии и того
    же IP тогда не поможет — тут вытаскивает то, что следующий запланированный
    запуск workflow получит от GitHub уже другой IP. Ретраи здесь на случай
    более простых временных сбоев (таймаут, разовая ошибка сети и т.п.).
    """
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            resp = scraper.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
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


def main():
    debug = '--debug' in sys.argv
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if debug:
        os.makedirs(DEBUG_DIR, exist_ok=True)

    venues = load_venues()
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )

    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    all_rows = []
    venue_names = []

    for venue in venues:
        name = venue['name']
        url = venue['url']
        safe_name = name.lower().replace(' ', '_')
        venue_rows = []

        print(f'[{name}] загрузка {url} ...')
        try:
            html = fetch_html(scraper, url)
        except Exception as e:
            print(f'[{name}] ОШИБКА загрузки страницы: {e}', file=sys.stderr)
            continue

        if debug:
            debug_path = os.path.join(DEBUG_DIR, f'{safe_name}.html')
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f'[{name}] сырой HTML сохранён в {debug_path}')

        try:
            rows = parse_menu(html, name, url)
        except Exception as e:
            print(f'[{name}] ОШИБКА парсинга: {e}', file=sys.stderr)
            continue

        print(f'[{name}] найдено позиций меню: {len(rows)}')
        venue_rows.extend(rows)
        active_section = rows[0]['section'] if rows else None

        # На странице может быть несколько вкладок меню (Draft / Bottle-Can
        # / Food) — обычная загрузка отдаёт только активную. Остальные
        # непищевые вкладки пробуем дозапросить напрямую через
        # ?menu_id=<id>. Это экспериментальный приём (см. README) — если
        # Untappd не поддерживает такой параметр без JS, соответствующий
        # запрос просто не даст новых позиций и будет тихо пропущен.
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
            time.sleep(2)
            try:
                tab_html = fetch_html(scraper, tab_url)
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

        for r in venue_rows:
            r['scraped_at_utc'] = timestamp
            all_rows.append(r)
        venue_names.append(name)

        time.sleep(2)  # вежливая пауза между запросами к разным заведениям

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
