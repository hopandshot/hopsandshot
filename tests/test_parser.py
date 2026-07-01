"""
Простой тест parser.py на смоделированном HTML.

Запуск:
    python3 tests/test_parser.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from parser import parse_menu  # noqa: E402


def main():
    html_path = os.path.join(os.path.dirname(__file__), 'sample_menu.html')
    with open(html_path, encoding='utf-8') as f:
        html = f.read()

    rows = parse_menu(html, 'Test Venue', 'https://untappd.com/v/test-venue/123')

    assert len(rows) == 6, f'Ожидалось 6 позиций, получено {len(rows)}'

    by_name = {r['beer_name']: r for r in rows}

    assert by_name['Tostada']['category'] == 'GRIFO 1'
    assert by_name['Tostada']['section'] == 'DRAFT BEER/PIZARRA'
    assert by_name['Tostada']['serving_type'] == 'Draft'
    assert by_name['Tostada']['abv'] == '5.5%'
    assert by_name['Tostada']['ibu'] == 'N/A'
    assert by_name['Tostada']['brewery'] == 'Cervezas Antiga'
    assert by_name['Tostada']['rating'] == 'N/A'

    assert by_name['Barbaritat']['style'] == 'IPA - American'
    assert by_name['Barbaritat']['ibu'] == '63'
    assert by_name['Barbaritat']['rating'] == '3.83'
    assert by_name['Barbaritat']['serving_type'] == 'Draft'

    assert by_name['1. 499']['category'] == 'Tenemos pinchado'
    assert by_name['1. 499']['section'] == 'Barril'
    assert by_name['1. 499']['serving_type'] == 'Draft'
    assert by_name['1. 499']['servings_prices'] == 'Teku: 5.00 EUR; Pint: 7.00 EUR'

    assert by_name['11. Ambar Especial']['servings_prices'] == '400ml: 2.20 EUR; 300ml: 1.80 EUR'

    assert by_name['1. HELL']['category'] == 'En Pizarra / On Board'
    assert by_name['1. HELL']['serving_type'] == 'Draft'
    assert by_name['1. HELL']['servings_prices'] == '280ml Draft: 3.50 EUR; 470ml Draft: 5.50 EUR'

    assert by_name['Imperial Stout']['section'] == 'Botellas y Latas'
    assert by_name['Imperial Stout']['category'] == 'Nevera'
    assert by_name['Imperial Stout']['serving_type'] == 'Bottle/Can'
    assert by_name['Imperial Stout']['servings_prices'] == '33cl Bottle: 6.00 EUR'

    print('Все проверки прошли успешно ✅')
    for r in rows:
        print(f"  - [{r['venue']}] {r['section']} / {r['category']} ({r['serving_type']}): {r['beer_name']} "
              f"({r['style']}, {r['abv']}, {r['brewery']})")


if __name__ == '__main__':
    main()
