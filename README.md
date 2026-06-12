# Untappd Menu Scraper — крафтовые бары Валенсии

Собирает текущее меню напитков из профилей заведений на Untappd,
сохраняет в одну таблицу (CSV/JSON) и показывает её на веб-странице
(`index.html`) с сортировкой по столбцам и фильтром по заведениям.
Предполагается запуск раз в час.

## Структура

```
venues.json              — список заведений (имя + ссылка на страницу Untappd)
parser.py                 — парсинг HTML (без сети, легко тестировать)
scraper.py                — загрузка страниц + парсинг + запись в CSV/JSON
index.html                 — веб-страница с сортируемой таблицей (читает output/current_menu.json)
requirements.txt
output/
  current_menu.csv         — "снимок" текущего меню всех заведений (перезаписывается)
  current_menu.json         — то же самое в JSON — источник данных для index.html (перезаписывается)
  menu_history.csv         — история всех запусков (дополняется)
debug/                     — сырой HTML страниц (только с флагом --debug)
tests/sample_menu.html     — тестовая страница для проверки parser.py
.github/workflows/scrape.yml — готовый workflow для запуска раз в час на GitHub Actions
```

## Установка и быстрый запуск

```bash
pip install -r requirements.txt
python3 scraper.py
```

После запуска появится `output/current_menu.csv` со столбцами:

`scraped_at_utc, venue, category, beer_name, style, brewery, abv, ibu, rating, servings_prices, beer_url, brewery_url, beer_id, venue_url`

`category` — это название секции/крана на странице (например, `GRIFO 1`
у Bukowski или `Tenemos pinchado` у Valhalla).
`servings_prices` — варианты подачи и цены, если Untappd их показывает
(например, `Teku: 5.00 EUR; Pint: 7.00 EUR`).

## Веб-страница (UI)

`index.html` — статическая страница без сборки (HTML/CSS/JS в одном
файле), которая загружает `output/current_menu.json` и показывает
таблицу: заведение, пиво, стиль, пивоварня, ABV, IBU, рейтинг, цены и
ссылка на Untappd. Клик по заголовку столбца сортирует (повторный клик —
меняет порядок), есть поиск и фильтр по заведению, на телефоне таблица
превращается в карточки.

Локальный просмотр (нужен Python, JSON не загрузится при открытии файла
напрямую через file:// из-за CORS):

```bash
python3 scraper.py        # обновит output/current_menu.json
python3 -m http.server 8000
# открыть http://localhost:8000/index.html
```

## Важно: про Cloudflare и проверку

Untappd прикрыт защитой Cloudflare, поэтому обычный `requests` обычно
получает 403. Скрипт использует `cloudscraper`, который в большинстве
случаев это обходит. **Я не смог протестировать сетевой запрос к
untappd.com из своей песочницы — туда нет доступа.** Логику парсинга я
проверил на смоделированном HTML (`tests/sample_menu.html`, основан на
реальных страницах Bukowski и Valhalla) — она работает корректно.

Что сделать на твоей стороне:

1. Запусти `python3 scraper.py --debug`.
2. Если всё ок — увидишь в консоли `найдено позиций меню: N` для каждого
   заведения (для Bukowski сейчас на странице ~15 позиций на кранах, для
   Valhalla — 11 в секции "Tenemos pinchado").
3. Если `N = 0` или будет ошибка/403:
   - открой `debug/<venue>.html` — это сырой ответ сервера;
   - если там страница Cloudflare-проверки ("Checking your browser…") —
     значит, `cloudscraper` не справился, и понадобится более тяжёлый
     вариант через headless-браузер (Playwright). Дай знать — допишу
     отдельный вариант scraper.py на Playwright;
   - если страница нормальная, но `N = 0` — пришли мне фрагмент
     `debug/<venue>.html` вокруг блока с пивом, я подправлю `parser.py`
     под актуальную вёрстку (сама логика парсинга вынесена в отдельный
     файл и легко тестируется через `tests/sample_menu.html`).

## Добавление новых заведений

Добавь объект в `venues.json`:

```json
{
  "name": "Название бара",
  "url": "https://untappd.com/v/<slug>/<id>"
}
```

Ссылку проще всего найти через поиск на untappd.com → страница заведения
→ скопировать URL (формат `https://untappd.com/v/<slug>/<id>`).

## Запуск раз в час + публикация по ссылке

### Вариант 1: GitHub Actions + GitHub Pages (бесплатно, без своего сервера)

Это самый простой способ получить именно "ссылку, по которой видно
актуальное меню":

1. Создай репозиторий на GitHub (можно публичный — это бесплатно для
   GitHub Pages) и залей туда содержимое этой папки целиком, включая
   `index.html`.
2. Workflow `.github/workflows/scrape.yml` уже настроен на запуск каждый
   час (`cron: '0 * * * *'`), сбор меню и коммит обновлённых
   `output/current_menu.csv` / `current_menu.json` / `menu_history.csv`
   обратно в репозиторий.
3. Включи права на запись для Actions: Settings → Actions → General →
   Workflow permissions → Read and write permissions.
4. Включи GitHub Pages: Settings → Pages → Source: "Deploy from a
   branch" → branch `main`, папка `/ (root)` → Save.
5. Через пару минут страница будет доступна по ссылке вида
   `https://<твой-юзернейм>.github.io/<репозиторий>/` — её и отправляешь
   друзьям. После каждого часового запуска workflow данные на странице
   обновятся автоматически (страница сама перезапрашивает
   `current_menu.json` при каждом открытии/обновлении).

> ⚠️ Учти: расписание `schedule` в GitHub Actions — это "не раньше, чем",
> при высокой нагрузке на инфраструктуру GitHub запуск может задержаться
> на несколько минут.

### Вариант 2: cron на своём сервере/VPS

```cron
0 * * * * cd /path/to/untappd-menu-scraper && /usr/bin/python3 scraper.py >> run.log 2>&1
```

### Вариант 3: локально на компьютере

Для регулярного запуска без выключения компьютера подойдёт `cron` (macOS/Linux)
или Планировщик заданий Windows с тем же интервалом — раз в час.

## Если нужен вывод в Google Sheets вместо CSV

Самый простой путь — оставить `output/current_menu.csv` как есть и
подтянуть его в Google Sheets формулой:

```
=IMPORTDATA("https://raw.githubusercontent.com/<user>/<repo>/main/output/current_menu.csv")
```

(репозиторий должен быть публичным, либо нужен отдельный механизм с
сервис-аккаунтом Google — могу добавить, если понадобится).

## Следующие шаги

- Добавить остальные крафтовые бары Валенсии в `venues.json`.
- Если у заведения отдельные секции "на кранах" / "в бутылках/банках" —
  сейчас парсер собирает вообще все позиции меню, которые отрендерены на
  странице (для некоторых заведений Untappd подгружает часть позиций по
  кнопке "Show More" через JS и они не попадут в обычный HTML-запрос —
  если для конкретного бара это критично, нужен Playwright).
