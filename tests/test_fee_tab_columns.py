import pytest
from sqlalchemy import create_engine
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox

from app.database.connection import get_session
from app.database.models import Base, AnnualFeeRecord, InsuranceEntry, Member
from app.services.fee_service import FeeService
from app.ui.fee_tab import COL_INDEX, FeeTab
from app.utils.app_config import AppConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_fee_tab_sorts_amounts_numerically_and_persists_column_settings(engine, qapp):
    with get_session(engine) as session:
        session.add_all([
            Member(member_number="9001", org_name="A社", is_active=True, is_member=True),
            Member(member_number="9002", org_name="B社", is_active=True, is_member=True),
        ])
    service = FeeService(engine)
    service.generate_records(2026)
    records = service.search(2026)
    service.update(records[0].id, {"premium_branch_0": 1000000})
    service.update(records[1].id, {"premium_branch_0": 90000})

    config = AppConfig(last_staff_name="テスト")
    tab = FeeTab(engine, config, None)
    tab._table.sortItems(COL_INDEX["概算保険料合計"], Qt.SortOrder.AscendingOrder)

    assert tab._table.item(0, COL_INDEX["事業所名"]).text() == "B社"
    tab._toggle_column_visibility(COL_INDEX["支払方法"], False)
    assert tab._table.isColumnHidden(COL_INDEX["支払方法"])
    assert "支払方法" in config.staff_settings["テスト"]["fee_hidden_columns"]

    tab._set_freeze_col(COL_INDEX["事業所名"])
    assert tab._freeze_col == COL_INDEX["事業所名"]
    assert not tab._frozen_view.isColumnHidden(0)


def test_quick_input_uses_current_table_order(engine, qapp):
    with get_session(engine) as session:
        session.add_all([
            Member(member_number="9001", org_name="A社", is_active=True, is_member=True),
            Member(member_number="9002", org_name="B社", is_active=True, is_member=True),
        ])
    FeeService(engine).generate_records(2026)
    tab = FeeTab(engine, AppConfig(last_staff_name="テスト"), None)
    tab._table.sortItems(COL_INDEX["事業所名"], Qt.SortOrder.DescendingOrder)

    ids = tab._visible_unentered_record_ids()
    assert [tab._displayed_records[record_id].member.org_name for record_id in ids] == ["B社", "A社"]


def test_fee_tab_selects_reminder_email_recipients(engine, qapp):
    with get_session(engine) as session:
        session.add_all([
            Member(member_number="9001", org_name="A社", email="a@example.test", is_active=True),
            Member(member_number="9002", org_name="B社", email="b@example.test", is_active=True),
        ])
    FeeService(engine).generate_records(2026)
    tab = FeeTab(engine, AppConfig(last_staff_name="テスト"), None)

    tab._on_select_all(True)

    assert len(tab._checked_ids) == 2
    assert all(
        tab._table.cellWidget(row, 0).findChild(QCheckBox).isChecked()
        for row in range(tab._table.rowCount())
    )


def test_inline_premium_edit_saves_and_blank_sorts_last(engine, qapp):
    with get_session(engine) as session:
        first = Member(
            member_number="9001", org_name="A社", is_active=True, is_member=True)
        first.insurance_entries.append(InsuranceEntry(
            ins_type="ippan", branch_number="0", ins_number="101"))
        second = Member(
            member_number="9002", org_name="B社", is_active=True, is_member=True)
        second.insurance_entries.append(InsuranceEntry(
            ins_type="ippan", branch_number="0", ins_number="102"))
        session.add_all([first, second])
    FeeService(engine).generate_records(2026)
    tab = FeeTab(engine, AppConfig(last_staff_name="テスト"), None)
    premium_col = COL_INDEX["概算保険料（0）"]

    tab._table.item(0, premium_col).setText("120000")

    with get_session(engine) as session:
        saved = session.query(AnnualFeeRecord).join(Member).filter(
            Member.org_name == "A社").one()
        assert saved.premium_branch_0 == 120000
    assert tab._table.item(0, COL_INDEX["概算保険料合計"]).text() == "120,000"

    tab._table.sortItems(premium_col, Qt.SortOrder.AscendingOrder)
    assert tab._table.item(tab._table.rowCount() - 1, premium_col).text() == ""
    tab._table.sortItems(premium_col, Qt.SortOrder.DescendingOrder)
    assert tab._table.item(tab._table.rowCount() - 1, premium_col).text() == ""
