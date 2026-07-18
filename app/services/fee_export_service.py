import openpyxl
from app.services.fee_service import FeeService

HEADERS = [
    "年度", "管理No.", "会員No.", "事業所名", "会員区分",
    "枝番0概算", "枝番2概算", "枝番4概算", "枝番5概算", "枝番6概算",
    "概算保険料合計", "5%計算額", "下限適用後手数料", "非会員加算",
    "税抜手数料", "消費税", "請求合計",
    "自動判定支払時期", "確定支払時期", "変更理由", "支払方法",
    "入金額", "入金日", "差額", "督促状況", "備考",
]


class FeeExportService:
    def __init__(self, engine):
        self._engine = engine

    def export_excel(self, fiscal_year: int, output_path: str) -> int:
        """指定年度の全件一覧をExcel出力する。出力件数を返す。"""
        records = FeeService(self._engine).search(fiscal_year)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "全件一覧"
        ws.append(HEADERS)

        for r in records:
            m = r.member
            diff = (r.paid_amount - r.total_amount) if r.paid_amount is not None else ""
            ws.append([
                r.fiscal_year,
                m.company_code or "",
                m.member_number or "",
                m.org_name,
                "会員" if r.is_member_for_fee else "非会員",
                r.premium_branch_0, r.premium_branch_2, r.premium_branch_4,
                r.premium_branch_5, r.premium_branch_6,
                r.premium_total, r.five_percent_amount, r.base_fee_amount,
                r.non_member_addition_amount, r.fee_without_tax, r.tax_amount,
                r.total_amount,
                r.auto_payment_period or "", r.final_payment_period or "",
                r.payment_period_override_reason or "", r.payment_method or "",
                r.paid_amount if r.paid_amount is not None else "",
                r.paid_at.strftime("%Y-%m-%d") if r.paid_at else "",
                diff,
                r.reminder_status or "", r.note or "",
            ])

        wb.save(output_path)
        return len(records)
