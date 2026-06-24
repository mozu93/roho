import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database.models import (
    Base, Member, InsuranceEntry, MemberChange,
    ActivityLog, ActivityCategory, ActivityLogCategory,
    ActivityConfirmation, ChangeConfirmation,
    Staff, EmailTemplate, SendJob, SendLog,
)

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

def test_member_create(db):
    m = Member(member_number="9001", org_name="㈱テスト商事")
    db.add(m)
    db.commit()
    assert db.get(Member, m.id).org_name == "㈱テスト商事"

def test_insurance_entry_relationship(db):
    m = Member(member_number="9001", org_name="㈱テスト商事")
    db.add(m)
    db.flush()
    e = InsuranceEntry(member_id=m.id, ins_type="ippan", branch_number="0", ins_number="101")
    db.add(e)
    db.commit()
    assert len(db.get(Member, m.id).insurance_entries) == 1

def test_activity_log_category_many_to_many(db):
    m = Member(member_number="9001", org_name="㈱テスト商事")
    cat = ActivityCategory(name="新規加入", sort_order=1)
    db.add_all([m, cat])
    db.flush()
    log = ActivityLog(member_id=m.id, logged_by="山田", content="電話あり")
    log.categories.append(cat)
    db.add(log)
    db.commit()
    assert db.get(ActivityLog, log.id).categories[0].name == "新規加入"

def test_staff_create(db):
    s = Staff(name="山田")
    db.add(s)
    db.commit()
    assert db.get(Staff, s.id).is_active is True

def test_send_job_status_default(db):
    j = SendJob(name="テスト送信")
    db.add(j)
    db.commit()
    assert db.get(SendJob, j.id).status == "draft"
