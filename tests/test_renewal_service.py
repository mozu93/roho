from datetime import date
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


def _setup_renewal(svc, ins_types=("ippan", "kensetsu_koyou")):
    with get_session(svc._engine) as session:
        m = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(m)
        session.flush()
        for ins_type in ins_types:
            session.add(InsuranceEntry(member_id=m.id, ins_type=ins_type, branch_number="0"))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        return session.query(AnnualRenewal).filter_by(fiscal_year=2026).first().id


def test_update_recomputes_overall_status_from_items(svc):
    renewal_id = _setup_renewal(svc)
    updated = svc.update(renewal_id, {
        "ippan": {"submission_status": "提出済", "confirmed_at": None},
        "kensetsu_koyou": {"submission_status": "未提出", "confirmed_at": None},
    }, {"overall_status_manual": False, "overall_status": None,
        "last_contacted_at": None, "note": ""})
    assert updated.overall_status == "一部提出"


def test_update_auto_sets_confirmed_at_when_submitted_without_date(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    updated = svc.update(renewal_id, {
        "ippan": {"submission_status": "提出済", "confirmed_at": None},
    }, {"overall_status_manual": False, "overall_status": None,
        "last_contacted_at": None, "note": ""})
    item = next(i for i in updated.items if i.branch_type == "ippan")
    assert item.confirmed_at == date.today()


def test_update_keeps_manual_overall_status(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    updated = svc.update(renewal_id, {
        "ippan": {"submission_status": "未提出", "confirmed_at": None},
    }, {"overall_status_manual": True, "overall_status": "完了",
        "last_contacted_at": None, "note": ""})
    assert updated.overall_status == "完了"


def test_update_saves_note_and_last_contacted(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    updated = svc.update(renewal_id, {
        "ippan": {"submission_status": "未提出", "confirmed_at": None},
    }, {"overall_status_manual": False, "overall_status": None,
        "last_contacted_at": date(2026, 7, 1), "note": "電話連絡済み"})
    assert updated.last_contacted_at == date(2026, 7, 1)
    assert updated.note == "電話連絡済み"


def test_search_by_keyword(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="㈱テスト商事", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="△△建設", is_active=True, is_member=True))
    svc.generate_records(2026)
    results = svc.search(2026, keyword="テスト")
    assert len(results) == 1
    assert results[0].member.org_name == "㈱テスト商事"


def test_search_filter_by_overall_status(svc):
    with get_session(svc._engine) as session:
        m1 = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        m2 = Member(member_number="9002", org_name="B社", is_active=True, is_member=True)
        session.add_all([m1, m2])
        session.flush()
        session.add(InsuranceEntry(member_id=m1.id, ins_type="ippan", branch_number="0"))
        session.add(InsuranceEntry(member_id=m2.id, ins_type="ippan", branch_number="0"))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        renewal_id = (
            session.query(AnnualRenewal).filter_by(fiscal_year=2026)
            .join(Member).filter(Member.org_name == "A社").first().id
        )
    svc.update(renewal_id, {"ippan": {"submission_status": "提出済", "confirmed_at": None}},
               {"overall_status_manual": False, "overall_status": None,
                "last_contacted_at": None, "note": ""})
    results = svc.search(2026, status_filter="提出済")
    assert len(results) == 1
    assert results[0].member.org_name == "A社"
