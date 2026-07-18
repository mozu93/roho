# Excel出力（全件一覧）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手数料計算タブに「Excel出力」ボタンを追加し、選択中の年度の全件一覧（仕様書9.2節の26列）をExcelファイルへ出力できるようにする。

**Architecture:** 既存の `ExportService.export_excel`（`app/services/import_service.py`）と同じ openpyxl 素朴出力パターンを踏襲し、新規サービス `FeeExportService` を作る。UI側は `app/ui/member_tab.py:_on_export` と同じ「保存先選択→サービス呼び出し→完了/エラーメッセージ」パターンで `app/ui/fee_tab.py` に「Excel出力」ボタンを追加する。

**Tech Stack:** Python 3.11+ / PyQt6 / openpyxl / pytest（サービス層のTDD）

## Global Constraints

- 出力対象は「全件一覧」シートのみ（未入金一覧・入金済一覧・期別集計・支払方法別集計・非会員一覧は対象外）
- 出力列は仕様書9.2節の26列。列順は本計画の Task 1 で示す `HEADERS` リストの順序を正とする
- 数値列は生の `int`（または空欄）、文字列列は `None` の場合に空文字列へフォールバック（既存 `export_excel` の慣習）
- 差額列（入金額−請求合計）は `paid_amount` が `None` の場合は空欄（8.1節の方針）
- 初期ファイル名は `手数料計算_{年度}年度.xlsx`
- 参照設計書: `docs/superpowers/specs/2026-07-18-fee-excel-export-design.md`

---

### Task 1: FeeExportService（Excel出力サービス）

**Files:**
- Create: `app/services/fee_export_service.py`
- Test: `tests/test_fee_export_service.py`

**Interfaces:**
- Consumes: `FeeService.search(fiscal_year)`（`app.services.fee_service`、第1段階で実装済み。`AnnualFeeRecord` の `.member` はロード済みで安全に参照可能）
- Produces: `FeeExportService(engine)`、`FeeExportService.export_excel(fiscal_year: int, output_path: str) -> int`（出力件数を返す）。モジュールレベル定数 `HEADERS`（26列のヘッダー名リスト）を公開する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_export_service.py` を新規作成：

```python
import pytest
from sqlalchemy import create_engine
import openpyxl
from app.database.models import Base, Member
from app.database.connection import get_session
from app.services.fee_service import FeeService
from app.services.fee_export_service import FeeExportService, HEADERS


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def fee_svc(engine):
    return FeeService(engine)


@pytest.fixture
def export_svc(engine):
    return FeeExportService(engine)


def test_export_excel_writes_header_row(tmp_path, engine, fee_svc, export_svc):
    with get_session(engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    fee_svc.generate_records(2026)
    out = tmp_path / "out.xlsx"
    count = export_svc.export_excel(2026, str(out))
    assert count == 1
    wb = openpyxl.load_workbook(str(out))
    ws = wb["全件一覧"]
    header_row = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert header_row == HEADERS
    assert len(HEADERS) == 26


def test_export_excel_writes_member_and_non_member_rows(tmp_path, engine, fee_svc, export_svc):
    with get_session(engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=False))
    fee_svc.generate_records(2026)
    out = tmp_path / "out.xlsx"
    export_svc.export_excel(2026, str(out))
    wb = openpyxl.load_workbook(str(out))
    ws = wb["全件一覧"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == 2
    kubun_by_org = {r[3]: r[4] for r in rows}
    assert kubun_by_org["A社"] == "会員"
    assert kubun_by_org["B社"] == "非会員"


def test_export_excel_diff_blank_when_unpaid(tmp_path, engine, fee_svc, export_svc):
    with get_session(engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    fee_svc.generate_records(2026)
    out = tmp_path / "out.xlsx"
    export_svc.export_excel(2026, str(out))
    wb = openpyxl.load_workbook(str(out))
    ws = wb["全件一覧"]
    row = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    assert row[23] in (None, "")  # 差額列（0始まりで24列目）


def test_export_excel_handles_none_note_without_crashing(tmp_path, engine, fee_svc, export_svc):
    with get_session(engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    fee_svc.generate_records(2026)
    out = tmp_path / "out.xlsx"
    # note, payment_method 等が未設定(None)の状態でも例外を出さずに出力できること
    count = export_svc.export_excel(2026, str(out))
    assert count == 1


def test_export_excel_premium_and_total_amount_values(tmp_path, engine, fee_svc, export_svc):
    with get_session(engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    fee_svc.generate_records(2026)
    with get_session(engine) as session:
        from app.database.models import AnnualFeeRecord
        record = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first()
        record_id = record.id
    fee_svc.update(record_id, {"premium_branch_0": 200000})
    out = tmp_path / "out.xlsx"
    export_svc.export_excel(2026, str(out))
    wb = openpyxl.load_workbook(str(out))
    ws = wb["全件一覧"]
    row = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))[0]
    # 概算保険料合計(index 10), 請求合計(index 16)
    assert row[10] == 200000
    assert row[16] == 11000
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_export_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.fee_export_service'`）

- [ ] **Step 3: 実装を書く**

`app/services/fee_export_service.py` を新規作成：

```python
import openpyxl
from app.services.fee_service import FeeService

HEADERS = [
    "年度", "管理No.", "会員No.", "事業所名", "会員区分",
    "枝番0概算", "枝番2概算", "枝番4概算", "枝番5概算", "枝番6概算",
    "概算保険料合計", "5%計算額", "下限適用後手数料", "非会員加算",
    "税抜手数料", "消費税", "請求合計",
    "自動判定支払時期", "確定支払時期", "変更理由", "支払方法",
    "入金額", "入金日", "差額", "督促状況", "備考",
]


class FeeExportService:
    def __init__(self, engine):
        self._engine = engine

    def export_excel(self, fiscal_year: int, output_path: str) -> int:
        """指定年度の全件一覧をExcel出力する。出力件数を返す。"""
        records = FeeService(self._engine).search(fiscal_year)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "全件一覧"
        ws.append(HEADERS)

        for r in records:
            m = r.member
            diff = (r.paid_amount - r.total_amount) if r.paid_amount is not None else ""
            ws.append([
                r.fiscal_year,
                m.company_code or "",
                m.member_number or "",
                m.org_name,
                "会員" if r.is_member_for_fee else "非会員",
                r.premium_branch_0, r.premium_branch_2, r.premium_branch_4,
                r.premium_branch_5, r.premium_branch_6,
                r.premium_total, r.five_percent_amount, r.base_fee_amount,
                r.non_member_addition_amount, r.fee_without_tax, r.tax_amount,
                r.total_amount,
                r.auto_payment_period or "", r.final_payment_period or "",
                r.payment_period_override_reason or "", r.payment_method or "",
                r.paid_amount if r.paid_amount is not None else "",
                r.paid_at.strftime("%Y-%m-%d") if r.paid_at else "",
                diff,
                r.reminder_status or "", r.note or "",
            ])

        wb.save(output_path)
        return len(records)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_export_service.py -v`
Expected: PASS（5件）

- [ ] **Step 5: 全体のテストも壊れていないことを確認**

Run: `python -m pytest tests/ -v`
Expected: 既存の全テストがPASS（`tests/test_import_service.py::test_import_new_members` の既知の無関係な失敗1件を除く）

- [ ] **Step 6: コミット**

```bash
git add app/services/fee_export_service.py tests/test_fee_export_service.py
git commit -m "feat: add FeeExportService for Excel export of fee records"
```

---

### Task 2: fee_tab.py への「Excel出力」ボタン追加

**Files:**
- Modify: `app/ui/fee_tab.py`

**Interfaces:**
- Consumes: `FeeExportService.export_excel(fiscal_year, output_path)`（Task 1）

このタスクはUIのため既存プロジェクトの慣例に合わせ、自動テストではなく手動確認で検証する。

- [ ] **Step 1: importを追加する**

`app/ui/fee_tab.py` 冒頭のimport群を以下のように変更する。

現在:
```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog,
)
from PyQt6.QtCore import Qt
from app.services.fee_service import FeeService
from app.ui.dialogs.fee_edit_dialog import FeeEditDialog
```

変更後:
```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QFileDialog,
)
from PyQt6.QtCore import Qt
from app.services.fee_service import FeeService
from app.services.fee_export_service import FeeExportService
from app.ui.dialogs.fee_edit_dialog import FeeEditDialog
```

- [ ] **Step 2: ボタンを追加する**

`_build_ui` メソッド内、以下の既存コード：

```python
        recalc_btn = QPushButton("再計算")
        recalc_btn.clicked.connect(self._on_recalculate)
        top_row.addWidget(recalc_btn)
        top_row.addStretch()
```

を、次のように変更する（`export_btn` を追加）：

```python
        recalc_btn = QPushButton("再計算")
        recalc_btn.clicked.connect(self._on_recalculate)
        top_row.addWidget(recalc_btn)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        top_row.addWidget(export_btn)
        top_row.addStretch()
```

- [ ] **Step 3: ハンドラを追加する**

`_on_recalculate` メソッドの後（クラスの末尾）に追記：

```python
    def _on_export(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に年度を選択または追加してください。")
            return
        default_name = f"手数料計算_{fiscal_year}年度.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Excel出力", default_name, "Excel (*.xlsx)")
        if not path:
            return
        try:
            count = FeeExportService(self._engine).export_excel(fiscal_year, path)
            QMessageBox.information(self, "完了", f"{count}件を出力しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 4: インポート確認**

Run: `python -c "from app.ui.fee_tab import FeeTab; print(1)"`
Expected: `1` が出力されること（エラーなくインポートできること）

- [ ] **Step 5: 手動確認**

`python main.py` でアプリを起動し、以下を確認する。

1. 手数料計算タブに「Excel出力」ボタンが表示される
2. 年度未選択の状態でクリックすると警告が出る
3. 年度選択・対象生成済みの状態でクリックすると保存ダイアログが開き、初期ファイル名が `手数料計算_{年度}年度.xlsx` になっている
4. 保存後、生成されたExcelファイルをExcel等で開き、「全件一覧」シートに26列のヘッダーと、一覧の件数分のデータ行が出力されていることを確認する

- [ ] **Step 6: コミット**

```bash
git add app/ui/fee_tab.py
git commit -m "feat: add Excel export button to FeeTab"
```

---

## 完了後の確認事項

- 「全件一覧」シートのみの出力機能が完成。未入金一覧・入金済一覧・期別集計・支払方法別集計・非会員一覧は未実装のまま（今後の段階で追加）。
