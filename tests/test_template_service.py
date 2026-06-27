import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Member
from app.database.connection import get_session
from app.services.template_service import TemplateService

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng

@pytest.fixture
def svc(engine):
    return TemplateService(engine)

def test_create_and_get(svc):
    t = svc.create("テスト", "件名テスト", "本文テスト")
    assert t.name == "テスト"
    all_templates = svc.get_all()
    assert len(all_templates) == 1

def test_render_placeholders(svc, engine):
    t = svc.create("案内", "{事業所名} 御中\n{会員No.}番", "代表 {代表者名} 様")
    with get_session(engine) as s:
        m = Member(
            member_number="9001", org_name="㈱テスト商事",
            rep_name="山田太郎", dept_title="代表取締役"
        )
        s.add(m)
    subject, body = svc.render(t, m)
    assert "㈱テスト商事" in subject
    assert "9001" in subject
    assert "山田太郎" in body

def test_delete(svc):
    t = svc.create("削除テスト", "件名", "本文")
    svc.delete(t.id)
    assert len(svc.get_all()) == 0
