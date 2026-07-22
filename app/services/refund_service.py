from datetime import datetime

from sqlalchemy.orm import joinedload

from app.database.connection import get_session
from app.database.models import AnnualFeeRecord, AnnualFeeRule, Member, RefundTransferRecord


class RefundService:
    def __init__(self, engine):
        self._engine = engine

    def list_years(self) -> list[int]:
        with get_session(self._engine) as session:
            return [row[0] for row in session.query(AnnualFeeRule.fiscal_year)
                    .order_by(AnnualFeeRule.fiscal_year.desc()).all()]

    def ensure_records(self, fiscal_year: int) -> int:
        """手数料計算対象ごとに、還付金入力用レコードを年度単位で用意する。"""
        with get_session(self._engine) as session:
            member_ids = [row[0] for row in session.query(AnnualFeeRecord.member_id)
                          .filter_by(fiscal_year=fiscal_year).all()]
            existing = {row[0] for row in session.query(RefundTransferRecord.member_id)
                        .filter_by(fiscal_year=fiscal_year).all()}
            rows = [RefundTransferRecord(fiscal_year=fiscal_year, member_id=member_id)
                    for member_id in member_ids if member_id not in existing]
            session.add_all(rows)
            return len(rows)

    def list_records(self, fiscal_year: int, keyword: str = "", status: str | None = None) -> list:
        self.ensure_records(fiscal_year)
        with get_session(self._engine) as session:
            query = (session.query(RefundTransferRecord)
                     .options(joinedload(RefundTransferRecord.member).joinedload(Member.bank_accounts))
                     .filter_by(fiscal_year=fiscal_year))
            if keyword:
                like = f"%{keyword}%"
                query = query.join(RefundTransferRecord.member).filter(
                    Member.org_name.like(like) | Member.member_number.like(like))
            rows = query.all()
            if status == "振込対象":
                rows = [row for row in rows if row.refund_amount > 0]
            elif status == "未入力":
                rows = [row for row in rows if row.refund_amount == 0]
            elif status == "口座未登録":
                rows = [row for row in rows if row.refund_amount > 0 and not self.account_for(row)]
            elif status == "出力済":
                rows = [row for row in rows if row.exported_at]
            session.expunge_all()
            return rows

    @staticmethod
    def account_for(record):
        return next((a for a in record.member.bank_accounts if a.is_enabled), None)

    def update(self, record_id: int, refund_amount: int, note: str = ""):
        if refund_amount < 0:
            raise ValueError("還付金額は0円以上で入力してください。")
        with get_session(self._engine) as session:
            row = session.get(RefundTransferRecord, record_id)
            if not row:
                raise ValueError("還付金レコードが見つかりません。")
            row.refund_amount = refund_amount
            row.note = note
            row.updated_at = datetime.now()

    def mark_exported(self, record_ids: list[int]) -> None:
        with get_session(self._engine) as session:
            session.query(RefundTransferRecord).filter(
                RefundTransferRecord.id.in_(record_ids)
            ).update({RefundTransferRecord.exported_at: datetime.now()}, synchronize_session=False)
