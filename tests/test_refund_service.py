from datetime import date

from sqlalchemy import create_engine

from app.database.connection import get_session
from app.database.models import AnnualFeeRecord, AnnualFeeRule, BankAccount, Base, Member
from app.services.refund_service import RefundService
from app.services.zengin_export_service import ZenginExportService


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with get_session(engine) as session:
        session.add(AnnualFeeRule(fiscal_year=2026))
        member = Member(member_number="1001", org_name="テスト商事", is_active=True)
        session.add(member)
        session.flush()
        session.add(AnnualFeeRecord(fiscal_year=2026, member_id=member.id, is_member_for_fee=True))
        session.add(BankAccount(
            member_id=member.id, bank_code="0001", bank_name="銀行", branch_code="001",
            branch_name="本店", account_type="1", account_number="1234567",
            recipient_name_kana="ﾃｽﾄ ｼｮｳｼﾞ", is_enabled=True,
        ))
    return engine


def test_refund_amount_is_created_and_updated():
    engine = _engine()
    service = RefundService(engine)
    assert service.ensure_records(2026) == 1
    record = service.list_records(2026)[0]
    service.update(record.id, 12345, "通知書確認済")

    updated = service.list_records(2026, status="振込対象")[0]
    assert updated.refund_amount == 12345
    assert updated.note == "通知書確認済"


def test_zengin_export_is_120_bytes_and_marks_exported(tmp_path):
    engine = _engine()
    service = RefundService(engine)
    service.ensure_records(2026)
    record = service.list_records(2026)[0]
    service.update(record.id, 12345)
    path = tmp_path / "refund.txt"
    count = ZenginExportService(engine).export(
        str(path), 2026, [record.id], date(2026, 7, 10), {
            "bank_code": "9999", "bank_name": "振込銀行", "branch_code": "123",
            "branch_name": "振込支店", "account_type": "1", "account_number": "7654321",
            "account_name_kana": "ﾛｳﾎｹﾝｼﾞﾑｸﾐｱｲ",
        })

    assert count == 1
    assert all(len(line.encode("cp932")) == 120 for line in path.read_text(encoding="cp932").splitlines())
    assert service.list_records(2026)[0].exported_at is not None
