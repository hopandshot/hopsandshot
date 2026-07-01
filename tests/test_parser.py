"""
Простой тест parser.py на смоделированном HTML.

Запуск:
    python3 tests/test_parser.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from parser import parse_menu, list_menu_tabs, is_food_menu_label  # noqa: E402


def main():
    tests_dir = os.path.dirname(__file__)

    with open(os.path.join(tests_dir, 'sample_menu.html'), encoding='utf-8') as f:
        draft_html = f.read()
    with open(os.path.join(tests_dir, 'sample_menu_bottles.html'), encoding='utf-8') as f:
        bottles_html = f.read()

    # --- секция определяется из <p class="menu-total">, без forced_section ---
    draft_rows = parse_menu(draft_html, 'Test Venue', 'https://untappd.com/v/test-venue/123')
    assert len(draft_rows) == 3, f'Ожидалось 3 позиции на draft-странице, получено {len(draft_rows)}'

    by_name = {r['beer_name']: r for r in draft_rows}

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

    assert by_name['1. 499']['category'] == 'GRIFO 11'
    assert by_name['1. 499']['servings_prices'] == 'Teku: 5.00 EUR; Pint: 7.00 EUR'

    # ни одна позиция с draft-страницы не должна была подхватить служебный
    # заголовок навигации "All Menus" как секцию
    for r in draft_rows:
        assert r['section'] != 'All Menus'

    # --- страница вкладки Cans & Bottles (как при ?menu_id=260119) ---
    bottle_rows = parse_menu(bottles_html, 'Test Venue', 'https://untappd.com/v/test-venue/123')
    assert len(bottle_rows) == 1, f'Ожидалась 1 позиция на bottles-странице, получено {len(bottle_rows)}'
    stout = bottle_rows[0]
    assert stout['beer_name'] == 'Imperial Stout'
    assert stout['section'] == 'CANS AND BOTTLES /LATAS Y BOTELLAS'
    assert stout['category'] == 'Nevera'
    assert stout['serving_type'] == 'Bottle/Can'
    assert stout['servings_prices'] == '33cl Bottle: 6.00 EUR'

    # --- forced_section перекрывает то, что нашлось бы в <p class="menu-total"> ---
    forced_rows = parse_menu(
        bottles_html, 'Test Venue', 'https://untappd.com/v/test-venue/123',
        forced_section='Custom Override Label',
    )
    assert forced_rows[0]['section'] == 'Custom Override Label'

    # --- список вкладок меню (select.menu-selector) ---
    tabs = list_menu_tabs(draft_html)
    assert len(tabs) == 3
    labels = [t['label'] for t in tabs]
    assert 'DRAFT BEER/PIZARRA' in labels
    assert 'CANS AND BOTTLES /LATAS Y BOTELLAS' in labels
    assert 'FOOD MENU/ CARTA DE COMIDA' in labels

    draft_tab = next(t for t in tabs if t['label'] == 'DRAFT BEER/PIZARRA')
    assert draft_tab['menu_id'] == '259771'
    bottles_tab = next(t for t in tabs if t['label'] == 'CANS AND BOTTLES /LATAS Y BOTELLAS')
    assert bottles_tab['menu_id'] == '260119'

    # --- фильтр пищевых вкладок ---
    assert is_food_menu_label('FOOD MENU/ CARTA DE COMIDA') is True
    assert is_food_menu_label('CANS AND BOTTLES /LATAS Y BOTELLAS') is False
    assert is_food_menu_label('DRAFT BEER/PIZARRA') is False

    print('Все проверки прошли успешно ✅')
    for r in draft_rows + bottle_rows:
        print(f"  - [{r['venue']}] {r['section']} / {r['category']} ({r['serving_type']}): {r['beer_name']} "
              f"({r['style']}, {r['abv']}, {r['brewery']})")


if __name__ == '__main__':
    main()
