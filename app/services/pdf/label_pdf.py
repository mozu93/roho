# -*- coding: utf-8 -*-
"""
宛名ラベル PDF 生成サービス

複数のラベルレイアウトに対応。
LABEL_LAYOUTS に仕様を追加するだけで新しいサイズを登録できる。

登録済みレイアウト:
  "a_one_28185" : A-ONE 28185  A4 3列×6行  70×42.3mm  上余白21.5mm
  "a_one_28187" : A-ONE 28187  A4 2列×6行  84×42mm    上余白22.5mm
  "a_one_51002" : A-ONE 51002  A4 2列×5行  91×55mm    上余白11mm（名札用）
"""
from dataclasses import dataclass, field
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
import os

from app.utils.customer_barcode import build_barcode_chars, draw_barcode, barcode_height

_FONT_FILES = {
    "Meiryo":        ("C:/Windows/Fonts/meiryo.ttc",           0),
    "MSPGothic":     ("C:/Windows/Fonts/msgothic.ttc",          2),
    "MSPMincho":     ("C:/Windows/Fonts/msmincho.ttc",          1),
    "UDKyokasho":    ("C:/Windows/Fonts/UDDigiKyokashoN-R.ttc", 0),
    "HGRMaruGothic": ("C:/Windows/Fonts/HGRSMP.TTF",            0),
}
_registered: set[str] = set()
for _name, (_path, _idx) in _FONT_FILES.items():
    try:
        pdfmetrics.registerFont(TTFont(_name, _path, subfontIndex=_idx))
        _registered.add(_name)
    except Exception:
        pass

_ALL_FONT_OPTIONS: dict[str, str] = {
    "MSPゴシック":   "MSPGothic",
    "MSP明朝":       "MSPMincho",
    "メイリオ":      "Meiryo",
    "UD教科書体":    "UDKyokasho",
    "HGR丸ゴシック": "HGRMaruGothic",
}
FONT_OPTIONS: dict[str, str] = {
    label: internal
    for label, internal in _ALL_FONT_OPTIONS.items()
    if internal in _registered
}
DEFAULT_FONT_KEY = "MSPゴシック"

FONT_G = "Meiryo"
C_BORDER = HexColor("#CCCCCC")
C_SUB    = HexColor("#555555")


@dataclass
class LabelLayout:
    """ラベル用紙レイアウト仕様"""
    name:            str
    cols:            int
    rows:            int
    label_w_mm:      float
    label_h_mm:      float
    margin_top_mm:   float
    margin_left_mm:  float
    gap_h_mm:        float
    gap_v_mm:        float
    page_h_mm:       float = 297.0
    col_offsets_mm:  list   = field(default=None)


LABEL_LAYOUTS: dict[str, LabelLayout] = {
    "a_one_28185": LabelLayout(
        name           = "A-ONE 28185  (A4 / 3列×6行 / 70×42.3mm)",
        cols           = 3,
        rows           = 6,
        label_w_mm     = 70.0,
        label_h_mm     = 42.3,
        margin_top_mm  = 21.5,
        margin_left_mm = 4.0,
        gap_h_mm       = 0.0,
        gap_v_mm       = 0.0,
        page_h_mm      = 296.9,
        col_offsets_mm = [1.0, 0.0, -1.0],
    ),
    "a_one_28187": LabelLayout(
        name           = "A-ONE 28187  (A4 / 2列×6行 / 84×42mm)",
        cols           = 2,
        rows           = 6,
        label_w_mm     = 84.0,
        label_h_mm     = 42.0,
        margin_top_mm  = 22.5,
        margin_left_mm = 20.0,
        gap_h_mm       = 2.0,
        gap_v_mm       = 0.0,
        page_h_mm      = 296.9,
    ),
    "a_one_51002": LabelLayout(
        name           = "A-ONE 51002  (A4 / 2列×5行 / 91×55mm・名札)",
        cols           = 2,
        rows           = 5,
        label_w_mm     = 91.0,
        label_h_mm     = 55.0,
        margin_top_mm  = 11.0,
        margin_left_mm = 14.0,
        gap_h_mm       = 0.0,
        gap_v_mm       = 0.0,
    ),
}

DEFAULT_LAYOUT_KEY = "a_one_28185"


def _label_wh(layout: LabelLayout) -> tuple[float, float]:
    return layout.label_w_mm * mm, layout.label_h_mm * mm


def _label_origin(
    col: int, row: int, layout: LabelLayout,
    offset_h_mm: float = 0.0, offset_v_mm: float = 0.0,
) -> tuple[float, float]:
    page_h = layout.page_h_mm * mm
    lw = layout.label_w_mm  * mm
    lh = layout.label_h_mm  * mm
    mt = (layout.margin_top_mm + offset_v_mm) * mm
    ml = (layout.margin_left_mm + offset_h_mm) * mm
    gh = layout.gap_h_mm * mm
    gv = layout.gap_v_mm * mm
    offsets = layout.col_offsets_mm or []
    col_offset = offsets[col] * mm if col < len(offsets) else 0.0
    x = ml + col * (lw + gh) + col_offset
    y = page_h - mt - (row + 1) * lh - row * gv
    return x, y


def generate_label_pdf(
    entries:         list,
    output_path:     str,
    batch_mode:      str  = "normal",
    layout_key:      str  = DEFAULT_LAYOUT_KEY,
    font_key:        str  = DEFAULT_FONT_KEY,
    barcode_enabled: bool = False,
    offset_h_mm:     float = 0.0,
    offset_v_mm:     float = 0.0,
    start_slot:      int = 0,
) -> str:
    layout = LABEL_LAYOUTS.get(layout_key) or LABEL_LAYOUTS[DEFAULT_LAYOUT_KEY]
    font   = FONT_OPTIONS.get(font_key, list(FONT_OPTIONS.values())[0])
    lw, lh = _label_wh(layout)
    per_page = layout.cols * layout.rows
    start_slot = max(0, min(start_slot, per_page - 1))

    if isinstance(output_path, str):
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    page_w = A4[0]
    page_h = layout.page_h_mm * mm
    c = Canvas(output_path, pagesize=(page_w, page_h))
    c.setTitle("宛名ラベル")

    slot = start_slot
    for entry in entries:
        if slot > 0 and slot % per_page == 0:
            c.showPage()

        page_slot = slot % per_page
        col = page_slot % layout.cols
        row = page_slot // layout.cols
        x0, y0 = _label_origin(col, row, layout, offset_h_mm, offset_v_mm)

        mode = batch_mode if entry.entry_mode == "inherit" else entry.entry_mode
        _draw_label(c, entry, x0, y0, lw, lh, mode, font, barcode_enabled)
        slot += 1

    c.save()
    return output_path


def _fit_text(text: str, font: str, max_size: float,
              max_width: float, min_size: float = 5.5) -> float:
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


def _split_line(text: str, font: str, fs: float, max_w: float) -> tuple[str, str]:
    if not text:
        return "", ""
    if stringWidth(text, font, fs) <= max_w:
        return text, ""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if stringWidth(text[:mid], font, fs) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo], text[lo:]


_SAFETY_H = 3.0 * mm  # 印刷ズレを見込んだ左右の安全余白
_SAFETY_V = 2.0 * mm  # 印刷ズレを見込んだ上下の安全余白


def _draw_label(c, entry, x0: float, y0: float, w: float, h: float, mode: str,
                font: str = "MSPGothic", barcode_enabled: bool = False):
    c.saveState()

    # ラベル枠外への描画を防ぎ、プリンタのわずかなズレにも対応する。
    clip = c.beginPath()
    clip.rect(x0, y0, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    x0 += _SAFETY_H
    y0 += _SAFETY_V
    w -= 2 * _SAFETY_H
    h -= 2 * _SAFETY_V

    company      = entry.company_name or ""
    postal       = entry.postal_code  or ""
    addr1        = entry.address1     or ""
    addr2        = entry.address2     or ""
    title        = entry.title        or ""
    person       = entry.person_name  or ""
    barcode_addr = getattr(entry, 'barcode_address', '') or ""

    if mode == "simple":
        _draw_simple(c, x0, y0, w, h, company, font)
    elif mode == "no_person":
        _draw_no_person(c, x0, y0, w, h, company, postal, addr1, addr2, font,
                        barcode_enabled, barcode_addr)
    elif mode == "nametag":
        _draw_nametag(c, x0, y0, w, h, company, title, person, font)
    else:
        _draw_normal(c, x0, y0, w, h, company, postal, addr1, addr2, title, person, font,
                     barcode_enabled, barcode_addr)

    c.restoreState()


def _draw_normal(c, x0, y0, w, h,
                 company, postal, addr1, addr2, title, person,
                 font: str = "MSPGothic",
                 barcode_enabled: bool = False,
                 barcode_addr: str = ""):
    _BC_MARGIN = 1.5 * mm
    _BC_TOP_MARGIN = 1.0 * mm
    use_barcode = barcode_enabled and bool(postal) and bool(barcode_addr)
    bc_reserve = (barcode_height() + _BC_MARGIN + _BC_TOP_MARGIN) if use_barcode else 0.0

    scale  = min(w / (92.5 * mm), (h - bc_reserve) / (53.0 * mm))
    P      = max(2.0 * mm, 3.0 * mm * scale)

    inner_w = w - 2 * P
    indent1 = P + 2.5 * mm * scale
    indent2 = P + 8.0 * mm * scale

    addr_fs     = 11.0
    co_max_fs   = 11.0
    title_fs    = 11.0
    name_max_fs = 11.0

    LH = addr_fs * 1.6

    effective_h = h - bc_reserve
    cur_y = y0 + effective_h - P - addr_fs * 0.85

    c.setFont(font, addr_fs)
    c.setFillColor(C_SUB)
    if postal:
        c.drawString(x0 + P, cur_y, f"〒{postal}")
        cur_y -= LH * 0.95

    if addr1:
        a = addr1
        while a:
            line, a = _split_line(a, font, addr_fs, inner_w)
            c.drawString(x0 + P, cur_y, line)
            cur_y -= addr_fs + (LH * 0.95 - addr_fs) * 0.25
    if addr2:
        c.drawString(x0 + P, cur_y, addr2)
        cur_y -= LH * 0.95

    if postal or addr1 or addr2:
        cur_y -= LH * 0.2

    if company:
        co_avail  = inner_w - (indent1 - P)
        target_fs = 10.0
        c.setFillColor(black)
        if "\n" not in company and stringWidth(company, font, target_fs) <= co_avail:
            fs = _fit_text(company, font, co_max_fs, co_avail, min_size=target_fs)
            c.setFont(font, fs)
            c.drawString(x0 + indent1, cur_y, company)
            cur_y -= LH * 1.26
        else:
            c.setFont(font, target_fs)
            for seg in company.split("\n"):
                if not seg:
                    continue
                rem = seg
                while rem:
                    line, rem = _split_line(rem, font, target_fs, co_avail)
                    c.drawString(x0 + indent1, cur_y, line)
                    cur_y -= target_fs + (LH * 0.9 - target_fs) * 0.25
            cur_y -= (target_fs + (LH * 0.9 - target_fs) * 0.25) * 0.2

    if title:
        title_avail = inner_w - (indent1 - P)
        target_fs   = 10.0
        c.setFillColor(black)
        t = title.strip()
        if "\n" not in t and stringWidth(t, font, target_fs) <= title_avail:
            fs = _fit_text(t, font, title_fs, title_avail, min_size=target_fs)
            c.setFont(font, fs)
            c.drawString(x0 + indent1, cur_y, t)
            cur_y -= LH * 0.95
        else:
            c.setFont(font, target_fs)
            for seg in t.split("\n"):
                seg = seg.strip()
                if not seg:
                    continue
                rem = seg
                while rem:
                    line, rem = _split_line(rem, font, target_fs, title_avail)
                    c.drawString(x0 + indent1, cur_y, line)
                    cur_y -= target_fs + (LH * 0.9 - target_fs) * 0.25

    if person:
        name_line = f"{person}　様"
        name_fs   = _fit_text(name_line, font, name_max_fs, inner_w - (indent2 - P))
        name_y    = max(y0 + P * 0.8, cur_y)
        c.setFont(font, name_fs)
        c.setFillColor(black)
        c.drawString(x0 + indent2, name_y, name_line)
    else:
        gochu_fs = max(7.0, 10.0 * scale)
        name_y   = max(y0 + P * 0.8, cur_y)
        c.setFont(font, gochu_fs)
        c.setFillColor(black)
        gw = stringWidth("御中", font, gochu_fs)
        c.drawString(x0 + w - P - gw, name_y, "御中")

    if use_barcode:
        try:
            chars = build_barcode_chars(re.sub(r'\D', '', postal), barcode_addr)
            draw_barcode(c, x0 + P, y0 + _BC_MARGIN, chars)
        except Exception:
            pass


def _draw_no_person(c, x0, y0, w, h, company, postal, addr1, addr2,
                    font: str = "MSPGothic",
                    barcode_enabled: bool = False,
                    barcode_addr: str = ""):
    _BC_MARGIN = 1.5 * mm
    _BC_TOP_MARGIN = 1.0 * mm
    use_barcode = barcode_enabled and bool(postal) and bool(barcode_addr)
    bc_reserve = (barcode_height() + _BC_MARGIN + _BC_TOP_MARGIN) if use_barcode else 0.0

    scale    = min(w / (92.5 * mm), (h - bc_reserve) / (53.0 * mm))
    P        = max(2.0 * mm, 3.0 * mm * scale)
    inner_w  = w - 2 * P
    indent1  = P + 2.5 * mm * scale
    co_avail = inner_w - (indent1 - P)

    addr_fs   = 11.0
    co_max_fs = 11.0
    LH        = addr_fs * 1.6

    effective_h = h - bc_reserve
    cur_y = y0 + effective_h - P - addr_fs * 0.85

    c.setFont(font, addr_fs)
    c.setFillColor(C_SUB)
    if postal:
        c.drawString(x0 + P, cur_y, f"〒{postal}")
        cur_y -= LH * 0.95

    if addr1:
        a = addr1
        while a:
            line, a = _split_line(a, font, addr_fs, inner_w)
            c.drawString(x0 + P, cur_y, line)
            cur_y -= LH * 0.95
    if addr2:
        c.drawString(x0 + P, cur_y, addr2)
        cur_y -= LH * 0.95

    if postal or addr1 or addr2:
        cur_y -= LH * 0.4

    if not company:
        return

    c.setFillColor(black)
    gochu = " 御中"

    if "\n" not in company and stringWidth(company + gochu, font, 10.0) <= co_avail:
        fs = _fit_text(company + gochu, font, co_max_fs, co_avail, min_size=10.0)
        c.setFont(font, fs)
        c.drawString(x0 + indent1, cur_y, company + gochu)
        return

    co_fs   = 10.0
    c.setFont(font, co_fs)
    gochu_w = stringWidth(gochu, font, co_fs)

    segments  = [s for s in company.split("\n") if s]
    all_lines = []

    for seg_idx, seg in enumerate(segments):
        is_last = (seg_idx == len(segments) - 1)
        rem = seg
        while rem:
            if is_last and stringWidth(rem + gochu, font, co_fs) <= co_avail:
                all_lines.append(rem + gochu)
                rem = ""
            else:
                line, rem = _split_line(rem, font, co_fs, co_avail)
                if is_last and not rem:
                    trimmed, rem = _split_line(line, font, co_fs, co_avail - gochu_w)
                    all_lines.append(trimmed)
                else:
                    all_lines.append(line)

    if not all_lines:
        return

    for i, line in enumerate(all_lines):
        c.drawString(x0 + indent1, cur_y, line)
        if i < len(all_lines) - 1:
            cur_y -= LH * 0.9

    if use_barcode:
        try:
            chars = build_barcode_chars(re.sub(r'\D', '', postal), barcode_addr)
            draw_barcode(c, x0 + P, y0 + _BC_MARGIN, chars)
        except Exception:
            pass


def _draw_nametag(c, x0, y0, w, h, company, title, person, font: str = "MSPGothic"):
    P = 4.0 * mm
    inner_w = w - 2 * P

    CO_MAX = 24.0
    CO_MIN = 16.0
    TI_MAX = 20.0
    TI_MIN = 14.0
    NA_FS  = 28.0

    cur_y = y0 + h - P - CO_MAX * 0.85

    if company:
        c.setFillColor(black)
        if "\n" in company:
            for line in company.split("\n"):
                if not line:
                    cur_y -= CO_MAX * 0.6
                    continue
                fs = _fit_text(line, font, CO_MAX, inner_w, min_size=CO_MIN)
                c.setFont(font, fs)
                c.drawString(x0 + P, cur_y, line)
                cur_y -= fs * 1.1
        else:
            fs = _fit_text(company, font, CO_MAX, inner_w, min_size=CO_MIN)
            if stringWidth(company, font, fs) <= inner_w:
                c.setFont(font, fs)
                c.drawString(x0 + P, cur_y, company)
                cur_y -= fs * 1.4
            else:
                c.setFont(font, CO_MIN)
                text = company
                while text:
                    line, text = _split_line(text, font, CO_MIN, inner_w)
                    c.drawString(x0 + P, cur_y, line)
                    cur_y -= CO_MIN * 1.1
    else:
        cur_y -= CO_MAX * 1.4

    if title:
        c.setFillColor(black)
        if "\n" in title:
            for line in title.split("\n"):
                if not line:
                    cur_y -= TI_MAX * 0.6
                    continue
                fs = _fit_text(line, font, TI_MAX, inner_w, min_size=TI_MIN)
                c.setFont(font, fs)
                indent = stringWidth("　", font, fs)
                c.drawString(x0 + P + indent, cur_y, line)
                cur_y -= fs * 1.1
        else:
            tl = title.strip()
            fs = _fit_text(tl, font, TI_MAX, inner_w, min_size=TI_MIN)
            if stringWidth(tl, font, fs) <= inner_w:
                c.setFont(font, fs)
                indent = stringWidth("　", font, fs)
                c.drawString(x0 + P + indent, cur_y, tl)
                cur_y -= fs * 1.4
            else:
                c.setFont(font, TI_MIN)
                text = tl
                while text:
                    line, text = _split_line(text, font, TI_MIN, inner_w)
                    indent = stringWidth("　", font, TI_MIN)
                    c.drawString(x0 + P + indent, cur_y, line)
                    cur_y -= TI_MIN * 1.1
    else:
        cur_y -= TI_MAX * 1.4

    cur_y -= 4.0

    if person:
        fs = _fit_text(person, font, NA_FS, inner_w)
        c.setFont(font, fs)
        c.setFillColor(black)
        nw = stringWidth(person, font, fs)
        c.drawString(x0 + (w - nw) / 2, cur_y, person)


def _draw_simple(c, x0, y0, w, h, company, font: str = "MSPGothic"):
    P       = 5.0 * mm
    inner_w = w - 2 * P
    co_fs   = 12.0
    go_fs   = 11.0
    line_h  = co_fs * 1.5

    co_lines = []
    for seg in (company or "").split("\n"):
        if not seg:
            continue
        rem = seg
        while rem:
            line, rem = _split_line(rem, font, co_fs, inner_w)
            co_lines.append(line)

    if not co_lines:
        return

    gw     = stringWidth("御中", font, go_fs)
    go_h   = go_fs * 1.5
    block_h = len(co_lines) * line_h + go_h
    cur_y   = y0 + (h + block_h) / 2 - co_fs * 0.15

    c.setFillColor(black)
    c.setFont(font, co_fs)
    for line in co_lines:
        c.drawString(x0 + P, cur_y, line)
        cur_y -= line_h

    c.setFont(font, go_fs)
    c.drawString(x0 + w - P - gw, cur_y, "御中")


