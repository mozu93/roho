import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Member, InsuranceEntry, AnnualRenewal, AnnualRenewalItem
from app.database.connection import get_session
from app.services.renewal_service import compute_overall_status, RenewalService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def svc(engine):
    return RenewalService(engine)


def test_compute_overall_status_all_submitted():
    assert compute_overall_status(["提出済", "提出済"]) == "提出済"


def test_compute_overall_status_all_not_submitted():
    assert compute_overall_status(["未提出", "未提出"]) == "未提出"


def test_compute_overall_status_mixed_is_partial():
    assert compute_overall_status(["提出済", "未提出"]) == "一部提出"


def test_compute_overall_status_deficiency_takes_priority():
    assert compute_overall_status(["提出済", "不備あり"]) == "不備あり"


def test_compute_overall_status_excludes_not_applicable():
    assert compute_overall_status(["提出済", "対象外"]) == "提出済"


def test_compute_overall_status_empty_list_is_not_submitted():
    assert compute_overall_status([]) == "未提出"


def test_compute_overall_status_all_not_applicable_is_not_submitted():
    assert compute_overall_status(["対象外", "対象外"]) == "未提出"


def test_generate_records_creates_for_active_members_with_branches(svc):
    with get_session(svc._engine) as session:
        m1 = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        m2 = Member(member_number="9002", org_name="B社", is_active=False, is_member=True)
        session.add_all([m1, m2])
        session.flush()
        session.add(InsuranceEntry(member_id=m1.id, ins_type="ippan", branch_number="0"))
        session.add(InsuranceEntry(member_id=m1.id, ins_type="kensetsu_koyou", branch_number="2"))
    added = svc.generate_records(2026)
    assert added == 1  # 委託中の1件のみ
    with get_session(svc._engine) as session:
        renewal = session.query(AnnualRenewal).filter_by(fiscal_year=2026).first()
        assert renewal.overall_status == "未提出"
        items = session.query(AnnualRenewalItem).filter_by(annual_renewal_id=renewal.id).all()
        assert len(items) == 2
        assert {i.branch_type for i in items} == {"ippan", "kensetsu_koyou"}
        assert all(i.submission_status == "未提出" for i in items)


def test_generate_records_skips_existing(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    added_second = svc.generate_records(2026)
    assert added_second == 0


def test_generate_records_member_without_branches_has_no_items(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    added = svc.generate_records(2026)
    assert added == 1
    with get_session(svc._engine) as session:
        renewal = session.query(AnnualRenewal).filter_by(fiscal_year=2026).first()
        assert renewal.overall_status == "未提出"
        items = session.query(AnnualRenewalItem).filter_by(annual_renewal_id=renewal.id).all()
        assert len(items) == 0


def test_list_years_distinct_descending(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=True))
    svc.generate_records(2025)
    svc.generate_records(2026)
    assert svc.list_years() == [2026, 2025]


def test_get_returns_renewal_with_items(svc):
    with get_session(svc._engine) as session:
        m = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(m)
        session.flush()
        session.add(InsuranceEntry(member_id=m.id, ins_type="ippan", branch_number="0"))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        renewal_id = session.query(AnnualRenewal).filter_by(fiscal_year=2026).first().id

    renewal = svc.get(renewal_id)
    assert renewal.member.org_name == "A社"
    assert len(renewal.items) == 1


def test_get_backfills_newly_added_branch(svc):
    with get_session(svc._engine) as session:
        m = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(m)
        session.flush()
        session.add(InsuranceEntry(member_id=m.id, ins_type="ippan", branch_number="0"))
        member_id = m.id
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        renewal_id = session.query(AnnualRenewal).filter_by(fiscal_year=2026).first().id

    # 生成後に枝番を追加（後発の委託拡大を想定）
    with get_session(svc._engine) as session:
        session.add(InsuranceEntry(member_id=member_id, ins_type="kensetsu_koyou", branch_number="2"))

    renewal = svc.get(renewal_id)
    assert {i.branch_type for i in renewal.items} == {"ippan", "kensetsu_koyou"}
    new_item = next(i for i in renewal.items if i.branch_type == "kensetsu_koyou")
    assert new_item.submission_status == "未提出"


def test_get_does_not_duplicate_existing_items(svc):
    with get_session(svc._engine) as session:
        m = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(m)
        session.flush()
        session.add(InsuranceEntry(member_id=m.id, ins_type="ippan", branch_number="0"))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        renewal_id = session.query(AnnualRenewal).filter_by(fiscal_year=2026).first().id

    svc.get(renewal_id)
    svc.get(renewal_id)  # 2回呼んでも重複しない
    with get_session(svc._engine) as session:
        count = session.query(AnnualRenewalItem).filter_by(annual_renewal_id=renewal_id).count()
        assert count == 1
