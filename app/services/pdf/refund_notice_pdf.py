from datetime import date
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


_FONT = "MSPGothic"
try:
    pdfmetrics.registerFont(TTFont(_FONT, "C:/Windows/Fonts/msgothic.ttc", subfontIndex=2))
except Exception:
    _FONT = "Helvetica"


def generate_refund_notice_pdf(records: list, output_path: str, notice_date: date | None = None) -> int:
    """還付金額を通知する事業所別のA4明細書を出力する。"""
    notice_date = notice_date or date.today()
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    canvas = Canvas(output_path, pagesize=A4)
    width, height = A4
    for record in records:
        member = record.member
        canvas.setFont(_FONT, 12)
        canvas.drawRightString(width - 20 * mm, height - 20 * mm, notice_date.strftime("%Y年%m月%d日"))
        canvas.setFont(_FONT, 16)
        canvas.drawCentredString(width / 2, height - 38 * mm, "還付金振込通知書")
        canvas.setFont(_FONT, 12)
        canvas.drawString(25 * mm, height - 58 * mm, f"{member.org_name}　御中")
        canvas.line(25 * mm, height - 61 * mm, width - 25 * mm, height - 61 * mm)
        canvas.setFont(_FONT, 11)
        canvas.drawString(25 * mm, height - 82 * mm,
                          f"{record.fiscal_year}年度の労働保険年度更新に伴う還付金について、")
        canvas.drawString(25 * mm, height - 90 * mm, "下記のとおりご登録口座へ振り込みますのでお知らせします。")
        box_x, box_y, box_w, box_h = 30 * mm, height - 145 * mm, width - 60 * mm, 35 * mm
        canvas.rect(box_x, box_y, box_w, box_h)
        canvas.setFont(_FONT, 12)
        canvas.drawString(box_x + 8 * mm, box_y + 22 * mm, "還付金額")
        canvas.setFont(_FONT, 20)
        canvas.drawRightString(box_x + box_w - 10 * mm, box_y + 20 * mm,
                               f"{record.refund_amount:,} 円")
        canvas.setFont(_FONT, 10)
        canvas.drawString(25 * mm, height - 170 * mm,
                          "※ 振込日および口座への反映時刻は、金融機関の処理状況により異なります。")
        if record.note:
            canvas.drawString(25 * mm, height - 182 * mm, f"備考：{record.note}")
        canvas.showPage()
    canvas.save()
    return len(records)
