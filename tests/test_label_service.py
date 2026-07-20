# tests/test_label_service.py
import os, tempfile
import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Member, InsuranceEntry
from app.database.connection import get_session
from app.services.label_service import LabelService

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with get_session(eng) as s:
        m1 = Member(
            member_number="9001", org_name="㈱テスト商事",
            postal_code="510-0001", address="四日市市1-1",
            dept_title="総務部長", rep_name="鈴木一郎",
            is_active=True,
        )
        m2 = Member(
            member_number="9002", org_name="△△建設",
            postal_code_mail="510-0002", address_mail="鈴鹿市2-2",
            mail_org_name="総務部",
            mail_dept_title="総務課",
            mail_person_name="山田花子",
            is_active=True,
        )
        s.add_all([m1, m2])
        s.flush()
        s.add(InsuranceEntry(
            member_id=m1.id, ins_type="ippan", branch_number="0",
            ins_number="101", is_tokubetsu=True, is_ikkatsu=False
        ))
    return eng

@pytest.fixture
def svc(engine):
    return LabelService(engine)

def test_get_all_active(svc):
    members = svc.get_label_targets(active_only=True)
    assert len(members) == 2

def test_filter_tokubetsu(svc):
    members = svc.get_label_targets(active_only=True, tokubetsu_only=True)
    assert len(members) == 1
    assert members[0].member_number == "9001"

def test_build_label_entry_fallback(svc, engine):
    with get_session(engine) as s:
        m = s.query(Member).filter_by(member_number="9001").first()
        s.expunge_all()
    entry = svc.build_label_entry(m)
    assert entry.postal_code == "510-0001"
    assert entry.address1 == "四日市市1-1"
    assert entry.company_name == "㈱テスト商事"
    assert entry.title == "総務部長"
    assert entry.person_name == "鈴木一郎"

def test_build_label_entry_uses_mail_address(svc, engine):
    with get_session(engine) as s:
        m = s.query(Member).filter_by(member_number="9002").first()
        s.expunge_all()
    entry = svc.build_label_entry(m)
    assert entry.postal_code == "510-0002"
    assert entry.address1 == "鈴鹿市2-2"
    assert entry.company_name == "総務部"
    assert entry.title == "総務課"
    assert entry.person_name == "山田花子"

def test_generate_pdf(svc, engine):
    members = svc.get_label_targets(active_only=True)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        svc.generate_pdf(members, path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)
