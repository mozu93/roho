# tests/test_activity_service.py
import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Staff, Member
from app.database.connection import get_session
from app.services.activity_service import ActivityService

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with get_session(eng) as s:
        s.add(Staff(name="山田"))
        s.add(Staff(name="鈴木"))
        s.add(Member(member_number="9001", org_name="テスト商事"))
    return eng

@pytest.fixture
def svc(engine):
    return ActivityService(engine)

def test_add_log_and_get(svc, engine):
    with get_session(engine) as s:
        m_id = s.query(Member).first().id
    log = svc.add_log(m_id, "電話あり、新規加入の問い合わせ", [], "山田")
    logs = svc.get_logs(m_id)
    assert len(logs) == 1
    assert logs[0].content == "電話あり、新規加入の問い合わせ"

def test_add_log_creates_unread_for_others(svc, engine):
    with get_session(engine) as s:
        m_id = s.query(Member).first().id
    svc.add_log(m_id, "テスト", [], "山田")
    unread = svc.get_unread("鈴木")
    assert len(unread) == 1
    assert unread[0]["type"] == "activity"

def test_confirm_activity(svc, engine):
    with get_session(engine) as s:
        m_id = s.query(Member).first().id
    log = svc.add_log(m_id, "テスト", [], "山田")
    svc.confirm_activity(log.id, "鈴木")
    unread = svc.get_unread("鈴木")
    assert len(unread) == 0

def test_confirm_all(svc, engine):
    with get_session(engine) as s:
        m_id = s.query(Member).first().id
    svc.add_log(m_id, "テスト1", [], "山田")
    svc.add_log(m_id, "テスト2", [], "山田")
    svc.confirm_all("鈴木")
    assert len(svc.get_unread("鈴木")) == 0

def test_category_crud(svc):
    cat = svc.add_category("新規加入")
    cats = svc.get_categories()
    assert any(c.name == "新規加入" for c in cats)
    svc.delete_category(cat.id)
    assert not any(c.name == "新規加入" for c in svc.get_categories())
