# -*- coding: utf-8 -*-
"""
日本郵便 カスタマバーコード（4ステイト3バー）

  - 住所表示番号の抽出
  - バーコード文字列の構築（スタート＋郵便番号7桁＋住所表示番号13桁＋チェックデジット＋ストップ）
  - チェックデジット計算（合計が19の倍数）
  - reportlab canvas への描画

仕様参照: https://www.post.japanpost.jp/zipcode/zipmanual/
"""
import re
from reportlab.lib.units import mm
from reportlab.lib.colors import black


def _normalize(text: str) -> str:
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:
            result.append(chr(code - 0xFF10 + ord('0')))
        elif ch in ('－', '−', 'ー', '‐', '–', '—'):
            result.append('-')
        else:
            result.append(ch)
    return ''.join(result)


def extract_address_code(address: str) -> tuple[str, bool]:
    if not address or not address.strip():
        return "", False
    text = _normalize(address)
    m = re.search(r'(\d+)丁目(\d+)番地?(\d+)?号?', text)
    if m:
        parts = [m.group(1), m.group(2)]
        if m.group(3):
            parts.append(m.group(3))
        return '-'.join(parts), True
    m = re.search(r'(\d+)番地(\d+)号?', text)
    if m:
        return f'{m.group(1)}-{m.group(2)}', True
    m = re.search(r'(\d+)番地', text)
    if m:
        return m.group(1), True
    m = re.search(r'(\d+(?:-\d+)+)', text)
    if m:
        return m.group(1), True
    m = re.search(r'(\d+)', text)
    if m:
        return m.group(1), False
    return "", False


_CHAR_VALUES: dict[str, int] = {str(i): i for i in range(10)}
_CHAR_VALUES['-'] = 10
_CHAR_VALUES.update({f'CC{i}': 10 + i for i in range(1, 9)})

_CHAR_PATTERNS: dict[str, tuple[str, str, str]] = {
    '0':    ('F', 'T', 'T'),
    '1':    ('A', 'T', 'D'),
    '2':    ('D', 'T', 'A'),
    '3':    ('T', 'F', 'T'),
    '4':    ('T', 'A', 'D'),
    '5':    ('A', 'D', 'T'),
    '6':    ('T', 'D', 'A'),
    '7':    ('D', 'A', 'T'),
    '8':    ('T', 'T', 'F'),
    '9':    ('F', 'A', 'T'),
    '-':    ('A', 'F', 'T'),
    'CC1':  ('D', 'F', 'T'),
    'CC2':  ('T', 'A', 'F'),
    'CC3':  ('F', 'T', 'A'),
    'CC4':  ('T', 'D', 'F'),
    'CC5':  ('F', 'D', 'T'),
    'CC6':  ('T', 'F', 'A'),
    'CC7':  ('A', 'A', 'D'),
    'CC8':  ('D', 'D', 'A'),
    'S':    ('F', 'A', 'D'),
    'STOP': ('D', 'A', 'F'),
}


def calc_check_digit(chars: list[str]) -> str:
    total = sum(_CHAR_VALUES.get(c, 0) for c in chars)
    remainder = total % 19
    check_val = (19 - remainder) % 19
    if check_val <= 9:
        return str(check_val)
    if check_val == 10:
        return '-'
    return f'CC{check_val - 10}'


def build_barcode_chars(postal: str, addr_code: str) -> list[str]:
    postal_clean = re.sub(r'\D', '', postal)
    if len(postal_clean) != 7:
        raise ValueError(f"郵便番号が7桁ではありません: {postal!r}")
    addr_chars: list[str] = [ch for ch in addr_code if ch.isdigit() or ch == '-']
    while len(addr_chars) < 13:
        addr_chars.append('CC4')
    addr_chars = addr_chars[:13]
    payload = list(postal_clean) + addr_chars
    check = calc_check_digit(payload)
    return ['S'] + payload + [check] + ['STOP']


_A = 8.0
_LONG_H  = 3.6 * _A / 10 * mm
_SHORT_H = 1.2 * _A / 10 * mm
_PITCH   = 1.2 * _A / 10 * mm
_BAR_W   = 0.6 * _A / 10 * mm
_EXTEND  = (_LONG_H - _SHORT_H) / 2


def barcode_height() -> float:
    return _LONG_H


def barcode_total_width(num_chars: int = 23) -> float:
    return num_chars * 3 * _PITCH


def draw_barcode(canvas, x0: float, y0: float, chars: list[str]) -> None:
    mid_y = y0 + _SHORT_H / 2 + _EXTEND
    canvas.saveState()
    canvas.setFillColor(black)
    canvas.setStrokeColor(black)
    x = x0
    for char in chars:
        patterns = _CHAR_PATTERNS.get(char, ('T', 'T', 'T'))
        for bar_type in patterns:
            if bar_type == 'F':
                bar_y = mid_y - _LONG_H / 2
                bar_h = _LONG_H
            elif bar_type == 'A':
                bar_y = mid_y - _SHORT_H / 2
                bar_h = _SHORT_H + _EXTEND
            elif bar_type == 'D':
                bar_y = mid_y - _SHORT_H / 2 - _EXTEND
                bar_h = _SHORT_H + _EXTEND
            else:
                bar_y = mid_y - _SHORT_H / 2
                bar_h = _SHORT_H
            canvas.rect(x, bar_y, _BAR_W, bar_h, fill=1, stroke=0)
            x += _PITCH
    canvas.restoreState()
