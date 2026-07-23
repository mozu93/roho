import pytest
from datetime import date
from sqlalchemy import create_engine
from app.database.models import (
    Base, Member, InsuranceEntry, AnnualFeeRule, AnnualFeeRecord,
)
from app.database.connection import get_session
from app.services.fee_service import calculate_fee, determine_payment_period, FeeService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def svc(engine):
    return FeeService(engine)


def _rule(fiscal_year=2026):
    return AnnualFeeRule(
        fiscal_year=fiscal_year, fee_rate=0.05, member_min_fee=5000,
        non_member_addition=14000, tax_rate=0.10,
    )


def test_calculate_fee_member_below_minimum():
    result = calculate_fee({"branch_0": 80000}, True, _rule())
    assert result["premium_total"] == 80000
    assert result["five_percent_amount"] == 4000
    assert result["fee_without_tax"] == 5000
    assert result["tax_amount"] == 500
    assert result["total_amount"] == 5500


def test_calculate_fee_member_above_minimum():
    result = calculate_fee({"branch_0": 200000}, True, _rule())
    assert result["five_percent_amount"] == 10000
    assert result["fee_without_tax"] == 10000
    assert result["total_amount"] == 11000


def test_calculate_fee_non_member_below_minimum():
    result = calculate_fee({"branch_0": 80000}, False, _rule())
    assert result["fee_without_tax"] == 19000
    assert result["tax_amount"] == 1900
    assert result["total_amount"] == 20900


def test_calculate_fee_non_member_above_minimum():
    result = calculate_fee({"branch_0": 200000}, False, _rule())
    assert result["fee_without_tax"] == 24000
    assert result["total_amount"] == 26400


def test_calculate_fee_zero_premium_member():
    result = calculate_fee({}, True, _rule())
    assert result["premium_total"] == 0
    assert result["fee_without_tax"] == 5000
    assert result["total_amount"] == 5500


def test_calculate_fee_zero_premium_non_member():
    result = calculate_fee({}, False, _rule())
    assert result["fee_without_tax"] == 14000
    assert result["tax_amount"] == 1400
    assert result["total_amount"] == 15400


def test_calculate_fee_sums_all_branches():
    premiums = {"branch_0": 10000, "branch_2": 20000, "branch_4": 30000,
                "branch_5": 40000, "branch_6": 100000}
    result = calculate_fee(premiums, True, _rule())
    assert result["premium_total"] == 200000


def test_calculate_fee_rounding_floor():
    # 概算保険料合計 199,999円 → 5%計算額は floor(9999.95) = 9999円
    result = calculate_fee({"branch_0": 199999}, True, _rule())
    assert result["five_percent_amount"] == 9999
    assert result["fee_without_tax"] == 9999
    # 消費税 floor(9999 * 0.10) = 999円
    assert result["tax_amount"] == 999


def test_determine_payment_period_lump_sum_priority():
    # 一括払い かつ 新規委託月（本来3期相当）でも 1期が優先される
    result = determine_payment_period(2026, True, date(2026, 10, 1))
    assert result == "1期"


def test_determine_payment_period_existing_member_default():
    result = determine_payment_period(2026, False, None)
    assert result == "2期"


def test_determine_payment_period_new_entrust_summer():
    result = determine_payment_period(2026, False, date(2026, 6, 1))
    assert result == "2期"


def test_determine_payment_period_new_entrust_autumn():
    result = determine_payment_period(2026, False, date(2026, 10, 1))
    assert result == "3期"


def test_determine_payment_period_new_entrust_winter_no_billing():
    result = determine_payment_period(2026, False, date(2027, 2, 1))
    assert result == "請求なし"


def test_determine_payment_period_old_entrust_defaults_to_2ki():
    # 委託開始が年度範囲(2026-04-01〜2027-03-31)より前 → 既存事業所扱いで2期
    result = determine_payment_period(2026, False, date(2020, 6, 1))
    assert result == "2期"


def test_get_or_create_rule_creates_default(svc):
    rule = svc.get_or_create_rule(2026)
    assert rule.fiscal_year == 2026
    assert rule.fee_rate == 0.05
    assert rule.member_min_fee == 5000


def test_get_or_create_rule_returns_existing(svc):
    first = svc.get_or_create_rule(2026)
    with get_session(svc._engine) as session:
        r = session.get(AnnualFeeRule, 2026)
        r.member_min_fee = 6000
    second = svc.get_or_create_rule(2026)
    assert second.member_min_fee == 6000


def test_get_or_create_rule_copies_previous_year(svc):
    with get_session(svc._engine) as session:
        session.add(AnnualFeeRule(fiscal_year=2025, fee_rate=0.05,
                                   member_min_fee=4500, non_member_addition=13000,
                                   tax_rate=0.10))
    rule = svc.get_or_create_rule(2026)
    assert rule.member_min_fee == 4500
    assert rule.non_member_addition == 13000


def test_list_years_descending(svc):
    svc.get_or_create_rule(2025)
    svc.get_or_create_rule(2026)
    svc.get_or_create_rule(2024)
    assert svc.list_years() == [2026, 2025, 2024]


def test_generate_records_creates_for_active_members(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=False))
        session.add(Member(member_number="9003", org_name="C社", is_active=False, is_member=True))
    added = svc.generate_records(2026)
    assert added == 2  # 委託中の2件のみ
    with get_session(svc._engine) as session:
        records = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).all()
        assert len(records) == 2


def test_generate_records_skips_existing(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    added_second = svc.generate_records(2026)
    assert added_second == 0


def test_generate_records_copies_is_member_and_computes_zero_fee(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=False))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first()
        assert record.is_member_for_fee is False
        assert record.premium_total == 0
        assert record.fee_without_tax == 14000  # 非会員・0円例外ルール
        assert record.auto_payment_period == "2期"  # 委託開始月未設定は既存扱い


def test_update_recalculates_fee(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    updated = svc.update(record_id, {
        "premium_branch_0": 200000,
        "is_member_for_fee": True,
        "is_lump_sum_payment": False,
        "entrust_start_month": None,
        "payment_method": "振込",
    })
    assert updated.premium_total == 200000
    assert updated.fee_without_tax == 10000
    assert updated.total_amount == 11000


def test_update_requires_reason_for_member_override(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    with pytest.raises(ValueError):
        svc.update(record_id, {"is_member_for_fee": False})  # 理由なし → エラー

    updated = svc.update(record_id, {
        "is_member_for_fee": False, "member_override_reason": "特例対応のため",
    })
    assert updated.is_member_for_fee is False


def test_update_requires_reason_for_payment_period_override(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    with pytest.raises(ValueError):
        svc.update(record_id, {"final_payment_period": "1期"})  # 自動判定(2期)と異なるが理由なし

    updated = svc.update(record_id, {
        "final_payment_period": "1期", "payment_period_override_reason": "事業所希望のため",
    })
    assert updated.final_payment_period == "1期"


def test_update_sets_reminder_completed_when_paid(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    updated = svc.update(record_id, {"paid_amount": 5500, "paid_at": date(2026, 8, 1)})
    assert updated.reminder_status == "完了"


def test_confirm_debit_results_marks_failures_and_all_others_paid(svc):
    with get_session(svc._engine) as session:
        session.add_all([
            Member(member_number="9001", org_name="不能社", is_active=True),
            Member(member_number="9002", org_name="入金社", is_active=True),
        ])
    svc.generate_records(2026)
    records = svc.search(2026)
    failed_id = next(
        record.id for record in records if record.member.org_name == "不能社")

    count = svc.confirm_debit_results(2026, "1期", {
        failed_id: {
            "failure_reason": "資金不足",
            "notified_at": date(2026, 7, 20),
            "notice_sent_at": date(2026, 7, 21),
        },
    }, confirmed_at=date(2026, 7, 19))

    assert count == 2
    results = svc.get_debit_results(2026, "1期")
    assert results[failed_id]["is_paid"] is False
    assert results[failed_id]["failure_reason"] == "資金不足"
    assert results[failed_id]["notified_at"] == date(2026, 7, 20)
    paid = next(value for key, value in results.items() if key != failed_id)
    assert paid["is_paid"] is True
    assert paid["failure_reason"] is None


def test_confirm_debit_results_keeps_periods_independent(svc):
    with get_session(svc._engine) as session:
        session.add(Member(
            member_number="9001", org_name="対象社", is_active=True))
    svc.generate_records(2026)
    record_id = svc.search(2026)[0].id

    svc.confirm_debit_results(2026, "1期", {
        record_id: {"failure_reason": "預金取引なし"},
    })
    svc.confirm_debit_results(2026, "2期", {})

    assert svc.get_debit_results(2026, "1期")[record_id]["is_paid"] is False
    assert svc.get_debit_results(2026, "2期")[record_id]["is_paid"] is True


def test_confirm_debit_results_rejects_invalid_reason(svc):
    with get_session(svc._engine) as session:
        session.add(Member(
            member_number="9001", org_name="対象社", is_active=True))
    svc.generate_records(2026)
    record_id = svc.search(2026)[0].id

    with pytest.raises(ValueError, match="不能理由"):
        svc.confirm_debit_results(2026, "1期", {
            record_id: {"failure_reason": "理由不明"},
        })


def test_recalculate_all_applies_new_rule(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id
    svc.update(record_id, {"premium_branch_0": 80000})

    with get_session(svc._engine) as session:
        rule = session.get(AnnualFeeRule, 2026)
        rule.member_min_fee = 6000

    count = svc.recalculate_all(2026)
    assert count == 1
    with get_session(svc._engine) as session:
        record = session.get(AnnualFeeRecord, record_id)
        assert record.fee_without_tax == 6000


def test_search_by_keyword(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="㈱テスト商事", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="△△建設", is_active=True, is_member=True))
    svc.generate_records(2026)
    results = svc.search(2026, keyword="テスト")
    assert len(results) == 1
    assert results[0].member.org_name == "㈱テスト商事"


def test_search_loads_insurance_entries_for_inline_premium_columns(svc):
    with get_session(svc._engine) as session:
        member = Member(
            member_number="9001", org_name="枝番表示社",
            is_active=True, is_member=True,
        )
        member.insurance_entries.append(InsuranceEntry(
            ins_type="ippan", branch_number="0", ins_number="123",
        ))
        session.add(member)
    svc.generate_records(2026)

    records = svc.search(2026)

    # search()のセッション終了後も一覧が枝番を表示・判定できる。
    assert records[0].member.insurance_entries[0].ins_number == "123"


def test_search_filter_non_member(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=False))
    svc.generate_records(2026)
    results = svc.search(2026, status_filter="非会員")
    assert len(results) == 1
    assert results[0].member.org_name == "B社"


def test_search_filter_unpaid_excludes_no_billing(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        records = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).all()
        records[0].final_payment_period = "請求なし"
        records[1].final_payment_period = "2期"
    results = svc.search(2026, status_filter="未入金")
    assert len(results) == 1
    assert results[0].final_payment_period == "2期"


def test_search_filter_paid(svc):
    from datetime import date
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id
    svc.update(record_id, {"paid_amount": 5500, "paid_at": date(2026, 8, 1)})
    results = svc.search(2026, status_filter="入金済")
    assert len(results) == 1
