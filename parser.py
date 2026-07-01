"""
parser.py — извлечение данных о напитках из HTML-страницы заведения на Untappd.

Парсинг построен не на конкретных CSS-классах (они могут поменяться без
предупреждения), а на стабильных текстовых маркерах ("ABV", "IBU",
"(N Item/Items)", "EUR") и на ссылках вида:

    /b/<slug>/<id>   — страница конкретного пива
    /w/<slug>/<id>   — страница пивоварни

Эти URL — часть роутинга Untappd, и они меняются крайне редко, в отличие
от вёрстки страницы.
"""

import re
from bs4 import BeautifulSoup

BEER_LINK_RE = re.compile(r'^/b/[^/]+/\d+/?$')
BREWERY_LINK_RE = re.compile(r'^/w/[^/]+/\d+/?$')
ITEM_HEADER_RE = re.compile(r'^(.+?)\s*\(\s*\d+\s*items?\s*\)\s*$', re.IGNORECASE)
PRICE_LINE_RE = re.compile(r'^\s*([\d]+(?:[.,]\d{1,2})?)\s*(?:EUR|€)\s*$', re.IGNORECASE)
PRICE_WITH_LABEL_RE = re.compile(r'^(.+?)\s+([\d]+(?:[.,]\d{1,2})?)\s*(?:EUR|€)\s*$', re.IGNORECASE)

# Untappd группирует позиции меню на два уровня: "секция" (h2/h3/h4 без
# счётчика количества, например "DRAFT BEER/PIZARRA" или "Botellas y
# Latas") и "категория" внутри неё (h5/h6 со счётчиком "(N Items)",
# например "GRIFO 1"). Тип подачи определяем по ключевым словам в тексте
# секции/категории — испанский и английский варианты сразу, так как
# заведения в Валенсии смешивают языки на странице.
BOTTLE_CAN_KEYWORDS_RE = re.compile(
    r'\b(bottle|can|botella|lata|latas|botellin|nevera|fridge|packaged)\b',
    re.IGNORECASE,
)
DRAFT_KEYWORDS_RE = re.compile(
    r'\b(draft|tap|barril|grifo|grifos|pizarra|keg|on\s*tap|pinchad\w*)\b',
    re.IGNORECASE,
)


def normalize_ws(s):
    """Сжимает любые пробельные символы (включая переводы строк и
    многократные отступы внутри одного текстового узла) в один пробел.

    Untappd часто рендерит текст так:
        '1. \n                    HELL'
    что после обычного .strip() остаётся как есть (strip убирает только
    края строки, а не внутренние переводы строк). normalize_ws превращает
    это в '1. HELL'.
    """
    return re.sub(r'\s+', ' ', s or '').strip()


def text_segments(tag):
    """Возвращает список нормализованных текстовых фрагментов — по одному
    на исходный текстовый узел внутри tag, в порядке документа, без пустых.

    Используется вместо get_text('\\n').split('\\n'), потому что у Untappd
    разные узлы (название варианта подачи и цена) иногда оказываются
    в одном текстовом узле с лишними пробелами/переводами строк, а
    разбиение по '\\n' и .strip() построчно с этим не справляется."""
    segments = []
    for s in tag.find_all(string=True):
        t = normalize_ws(str(s))
        if t:
            segments.append(t)
    return segments


def extract_beer_stats(text):
    """Достаёт ABV, IBU, пивоварню и рейтинг из текста карточки пива.

    Ожидаемый формат (примерно): '... 5.5% ABV • N/A IBU • Brewery Name • (3.7)'
    Разделители могут отличаться, поэтому ищем якоря ABV / IBU / (rating)
    и берём текст между ними.
    """
    abv_m = re.search(r'([\d.]+\s*%|N\s*/\s*A)\s*ABV', text, re.IGNORECASE)
    if not abv_m:
        return None

    ibu_m = re.search(r'ABV(.*?)([\d.]+|N\s*/\s*A)\s*IBU', text, re.IGNORECASE | re.DOTALL)
    rating_m = re.search(r'IBU(.*?)\(\s*([\d.]+|N\s*/\s*A)\s*\)', text, re.IGNORECASE | re.DOTALL)

    abv = re.sub(r'\s+', '', abv_m.group(1)).upper()
    ibu = re.sub(r'\s+', '', ibu_m.group(2)).upper() if ibu_m else None

    brewery = None
    rating = None
    if rating_m:
        brewery_raw = rating_m.group(1)
        brewery = re.sub(r'^[\s•·|/\\\-–—:]+|[\s•·|/\\\-–—:]+$', '', brewery_raw)
        brewery = re.sub(r'\s+', ' ', brewery).strip()
        rating = re.sub(r'\s+', '', rating_m.group(2)).upper()

    return {'abv': abv, 'ibu': ibu, 'brewery': brewery, 'rating': rating}


def extract_prices(container):
    """Извлекает варианты подачи и цены. Untappd показывает их в двух
    форматах в зависимости от заведения:

    1) название и цена в разных текстовых узлах (например, Valhalla):
        Teku
        5.00 EUR
       -> 'Teku: 5.00 EUR'

    2) название и цена в одном текстовом узле (например, Olhöps):
        280ml Draft 3.50 EUR
       -> '280ml Draft: 3.50 EUR'
    """
    segments = text_segments(container)

    prices = []
    for i, seg in enumerate(segments):
        # Формат 2: "<название> <цена> EUR" в одном фрагменте
        m2 = PRICE_WITH_LABEL_RE.match(seg)
        if m2:
            label = m2.group(1).strip()
            if 'ABV' in label.upper() or 'IBU' in label.upper():
                continue
            price = m2.group(2).replace(',', '.')
            prices.append(f"{label}: {price} EUR")
            continue

        # Формат 1: цена отдельным фрагментом, название — фрагментом выше
        m1 = PRICE_LINE_RE.match(seg)
        if m1 and i > 0:
            serving = segments[i - 1]
            if PRICE_LINE_RE.match(serving):
                continue
            if 'ABV' in serving.upper() or 'IBU' in serving.upper():
                continue
            price = m1.group(1).replace(',', '.')
            prices.append(f"{serving}: {price} EUR")

    return '; '.join(prices) if prices else None


def infer_serving_type(section, category):
    """Определяет тип подачи ('Draft' или 'Bottle/Can') по ключевым словам
    в названии секции/категории. Если ни один паттерн не совпал —
    возвращает None (тип неизвестен, чаще всего это и есть draft, но
    лучше не гадать и показать пусто, чем ошибиться)."""
    text = f"{section or ''} {category or ''}"
    if BOTTLE_CAN_KEYWORDS_RE.search(text):
        return 'Bottle/Can'
    if DRAFT_KEYWORDS_RE.search(text):
        return 'Draft'
    return None


def find_container(a_tag, max_levels=6):
    """Поднимается по родителям от ссылки на пиво, пока не найдёт блок,
    в тексте которого есть и 'ABV', и 'IBU' — это и есть карточка напитка."""
    node = a_tag
    for _ in range(max_levels):
        if node.parent is None:
            break
        node = node.parent
        text = node.get_text(' ', strip=True).upper()
        if 'ABV' in text and 'IBU' in text:
            return node
    return a_tag.parent or a_tag


def parse_menu(html, venue_name, venue_url):
    """Возвращает список словарей — по одной записи на позицию в меню."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    current_section = None
    current_category = None
    seen = set()

    for tag in soup.find_all(True):
        # --- заголовок секции меню, например "DRAFT BEER/PIZARRA" или
        #     "Botellas y Latas" — верхний уровень группировки, без счётчика
        #     "(N Items)" (в отличие от заголовка категории/крана ниже) ---
        if tag.name in ('h2', 'h3', 'h4'):
            if tag.find('a', href=BEER_LINK_RE) is None:
                own_text = normalize_ws(tag.get_text(' ', strip=True))
                if own_text and len(own_text) < 80 and not ITEM_HEADER_RE.match(own_text):
                    current_section = own_text
                    continue

        # --- заголовок категории/крана, например "GRIFO 1 (1 Item)" ---
        if tag.name in ('h2', 'h3', 'h4', 'h5', 'h6', 'div', 'p', 'li', 'span'):
            if tag.find('a', href=BEER_LINK_RE) is None:
                own_text = tag.get_text(' ', strip=True)
                m = ITEM_HEADER_RE.match(own_text)
                if m and len(own_text) < 100:
                    current_category = normalize_ws(m.group(1))
                    continue

        # --- ссылка на конкретное пиво ---
        if tag.name == 'a':
            href = tag.get('href', '')
            if not BEER_LINK_RE.match(href):
                continue
            beer_name_raw = tag.get_text(' ', strip=True)
            beer_name = normalize_ws(beer_name_raw)
            if not beer_name:
                # это ссылка на картинку этикетки, а не на название
                continue

            container = find_container(tag)
            key = (id(container), beer_name)
            if key in seen:
                continue
            seen.add(key)

            ctext = container.get_text(' ', strip=True)
            stats = extract_beer_stats(ctext)
            if not stats:
                continue

            # стиль пива обычно находится рядом с названием в том же
            # заголовочном элементе (h5/h6 и т.п.)
            style = None
            name_parent = tag.parent
            if name_parent is not None:
                parent_text = name_parent.get_text(' ', strip=True)
                style = normalize_ws(parent_text.replace(beer_name_raw, '', 1)).strip(' *•·-–—|')
                style = style or None

            brewery_url = None
            brewery_tag = container.find('a', href=BREWERY_LINK_RE)
            if brewery_tag is not None:
                brewery_url = 'https://untappd.com' + brewery_tag['href']

            prices = extract_prices(container)
            beer_id = href.rstrip('/').rsplit('/', 1)[-1]
            serving_type = infer_serving_type(current_section, current_category)

            rows.append({
                'venue': venue_name,
                'venue_url': venue_url,
                'section': current_section,
                'category': current_category,
                'serving_type': serving_type,
                'beer_name': beer_name,
                'beer_url': 'https://untappd.com' + href,
                'beer_id': beer_id,
                'style': style,
                'abv': stats['abv'],
                'ibu': stats['ibu'],
                'brewery': stats['brewery'],
                'brewery_url': brewery_url,
                'rating': stats['rating'],
                'servings_prices': prices,
            })

    return rows
