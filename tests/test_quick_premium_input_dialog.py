import pytest
from sqlalchemy import create_engine
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.database.connection import get_session
from app.database.models import Base, InsuranceEntry, Member
from app.services.fee_service import FeeService
from app.ui.dialogs.quick_premium_input_dialog import QuickPremiumInputDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_quick_input_shows_branch_number_and_saves_premiums(engine, qapp):
    with get_session(engine) as session:
        member = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(member)
        session.flush()
        session.add_all([
            InsuranceEntry(member_id=member.id, ins_type="ippan", branch_number="0", ins_number="1234"),
            InsuranceEntry(member_id=member.id, ins_type="kensetsu_koyou", branch_number="2", ins_number="567"),
        ])

    service = FeeService(engine)
    service.generate_records(2026)
    record = service.search(2026)[0]
    saved_callbacks = []
    dialog = QuickPremiumInputDialog(
        engine, [record.id], on_record_saved=lambda: saved_callbacks.append(True))

    assert set(dialog._fields) == {"ippan", "kensetsu_koyou"}
    label = dialog._premium_layout.labelForField(dialog._fields["ippan"])
    assert "番号: 1234" in label.text()

    QTest.keyClick(dialog._fields["ippan"], Qt.Key.Key_Return)
    qapp.processEvents()
    assert dialog._index == 0
    assert dialog.focusWidget() is dialog._fields["kensetsu_koyou"]

    dialog._fields["ippan"].setText("120000")
    dialog._fields["kensetsu_koyou"].setText("80000")
    dialog._on_save_next()

    saved = service.get(record.id)
    assert saved.premium_branch_0 == 120000
    assert saved.premium_branch_2 == 80000
    assert saved.premium_total == 200000
    assert saved.total_amount == 11000
    assert saved_callbacks == [True]


def test_enter_on_last_branch_saves_then_moves_to_next_office(engine, qapp):
    with get_session(engine) as session:
        first = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        second = Member(member_number="9002", org_name="B社", is_active=True, is_member=True)
        session.add_all([first, second])
        session.flush()
        session.add_all([
            InsuranceEntry(member_id=first.id, ins_type="ippan", branch_number="0", ins_number="1234"),
            InsuranceEntry(member_id=second.id, ins_type="ippan", branch_number="0", ins_number="5678"),
        ])

    service = FeeService(engine)
    service.generate_records(2026)
    records = service.search(2026)
    dialog = QuickPremiumInputDialog(engine, [record.id for record in records])

    dialog._fields["ippan"].setText("120000")
    QTest.keyClick(dialog._fields["ippan"], Qt.Key.Key_Return)
    qapp.processEvents()

    assert dialog._index == 1
    assert dialog._office_name.text() == "B社"
    assert service.get(records[0].id).premium_total == 120000
