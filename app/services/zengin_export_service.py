from datetime import date

from app.services.refund_service import RefundService


def _fixed(value, width: int) -> bytes:
    """全銀データの項目をShift_JISのバイト幅で切り詰め・空白埋めする。"""
    encoded = str(value or "").encode("cp932", errors="replace")[:width]
    return encoded.ljust(width, b" ")


def _digits(value, width: int) -> bytes:
    value = str(value or "")
    if not value.isdigit() or len(value) > width:
        raise ValueError(f"数値{width}桁で指定してください。")
    return value.zfill(width).encode("ascii")


class ZenginExportService:
    """総合振込（全銀協規定形式・120バイト固定長）のデータを生成する。"""
    def __init__(self, engine):
        self._engine = engine
        self._refunds = RefundService(engine)

    def export(self, path: str, fiscal_year: int, record_ids: list[int], transfer_date: date, origin: dict) -> int:
        required = ("bank_code", "bank_name", "branch_code", "branch_name",
                    "account_type", "account_number", "account_name_kana")
        if any(not str(origin.get(key, "")).strip() for key in required):
            raise ValueError("設定タブで振込元口座をすべて入力してください。")
        rows = []
        for record in self._refunds.list_records(fiscal_year, status=None):
            if record.id not in record_ids or record.refund_amount <= 0:
                continue
            account = self._refunds.account_for(record)
            if not account:
                raise ValueError(f"{record.member.org_name}：有効な振込先口座がありません。")
            rows.append((record, account))
        if not rows:
            raise ValueError("出力対象の還付金がありません。")

        header = (
            b"1" + b"21" + b"0" + _fixed(origin["account_name_kana"], 40)
            + transfer_date.strftime("%m%d").encode("ascii")
            + _digits(origin["bank_code"], 4) + _fixed(origin["bank_name"], 15)
            + _digits(origin["branch_code"], 3) + _fixed(origin["branch_name"], 15)
            + _digits(origin["account_type"], 1) + _digits(origin["account_number"], 7)
        )
        lines = [header.ljust(120, b" ")]
        total = 0
        for record, account in rows:
            total += record.refund_amount
            line = (
                b"2" + _digits(account.bank_code, 4) + _fixed(account.bank_name, 15)
                + _digits(account.branch_code, 3) + _fixed(account.branch_name, 15)
                + b"0000" + _digits(account.account_type, 1) + _digits(account.account_number, 7)
                + _fixed(account.recipient_name_kana, 30) + str(record.refund_amount).zfill(10).encode("ascii")
                + b"0" + _fixed(record.member.company_code, 10)
            )
            lines.append(line.ljust(120, b" "))
        lines.append((b"8" + str(len(rows)).zfill(6).encode("ascii")
                      + str(total).zfill(12).encode("ascii")).ljust(120, b" "))
        lines.append(b"9".ljust(120, b" "))
        with open(path, "wb") as file:
            file.write(b"\r\n".join(lines) + b"\r\n")
        self._refunds.mark_exported([record.id for record, _ in rows])
        return len(rows)
