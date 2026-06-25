# tests/test_import_service.py
import os
import tempfile
import pytest
import openpyxl
from sqlalchemy import create_engine
from app.database.models import Base
from app.database.connection import get_session
from app.services.import_service import ImportService

COLUMN_MAP = {
    "member_number": 1,   # B
    "org_name": 2,        # C
    "org_kana": 3,        # D
    "rep_name": 5,        # F
    "email": 7,           # H
    "tel_area": 8,        # I
    "tel": 9,             # J
    "postal_code": 12,    # M
    "address": 13,        # N
    "employment_ins_no": 17,  # R
    "ins_ippan_branch": 18,   # S
    "ins_ippan_number": 19,   # T
    "ins_ippan_tokubetsu": 20,
    "ins_ippan_ikkatsu": 21,
}

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng

def _make_excel(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row_data in rows:
        ws.append(row_data)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    wb.save(path)
    return path

def test_import_new_members(engine):
    # B=会員No, C=事業所名, S=枝番0, T=番号
    row = [""] * 39
    row[1] = "9001"; row[2] = "テスト商事"
    row[18] = "0"; row[19] = "101"
    path = _make_excel([[""] * 39, row])  # 1行目ヘッダー
    try:
        svc = ImportService(engine)
        result = svc.import_excel(path, overwrite=False, staff_name="山田")
        assert result["added"] == 1
    finally:
        os.unlink(path)
