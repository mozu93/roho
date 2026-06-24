# 労働保険名簿管理システム Plan 4: ラベル出力

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ラベル出力タブを実装する。検索・絞り込み・チェックボックス選択でPDF出力対象を選び、A-ONEラベル用紙に対応したPDFを生成する。

**Architecture:** `label_service.py` がフィルタリングと `label_pdf.py` の呼び出しを担当。`label_pdf.py` は `cci-billing-label` から流用。ラベルの宛名は郵送先住所優先、なければ事業所住所にフォールバック。

**Tech Stack:** Python 3.11+, PyQt6, SQLAlchemy 2.x, ReportLab

## Global Constraints

- Plan 1・Plan 2 完了が前提
- `label_pdf.py` は `cci-billing-label/app/services/pdf/label_pdf.py` からコピーして流用
- 郵送先住所優先フォールバック: `postal_code_mail` → `postal_code`、`address_mail` → `address`、`addressee_mail` → `org_name`
- バーコード機能は `label_pdf.py` 流用時に `customer_barcode.py` も必要（`cci-billing-label/app/utils/` から流用）

---

### Task 1: label_pdf.py の流用・LabelService

**Files:**
- Create: `app/services/pdf/__init__.py`
- Create: `app/services/pdf/label_pdf.py`（cci-billing-labelからコピー）
- Create: `app/utils/customer_barcode.py`（cci-billing-labelからコピー）
- Create: `app/services/label_service.py`
- Create: `tests/test_label_service.py`

**Interfaces:**
- Produces:
  - `LabelService(engine)`
  - `LabelService.get_label_targets(active_only, include_withdrawn, ins_types, tokubetsu_only) -> list[Member]`
  - `LabelService.build_label_entry(member) -> LabelEntry`（label_pdf.py が期待するオブジェクト）
  - `LabelService.generate_pdf(members, output_path, layout_key, font_key, barcode_enabled) -> str`

- [ ] **Step 1: cci-billing-label から label_pdf.py をコピー**

```
copy "C:\Users\taka\Documents\Gemini\0030Business\cci-billing-label\app\services\pdf\label_pdf.py" "app\services\pdf\label_pdf.py"
copy "C:\Users\taka\Documents\Gemini\0030Business\cci-billing-label\app\utils\customer_barcode.py" "app\utils\customer_barcode.py"
```

`label_pdf.py` の `from app.utils.customer_barcode import ...` の import パスが `app.utils.customer_barcode` になっていることを確認。パスが異なる場合は修正する。

- [ ] **Step 2: テストを書く**

```python
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
            is_active=True,
        )
        m2 = Member(
            member_number="9002", org_name="△△建設",
            postal_code_mail="510-0002", address_mail="鈴鹿市2-2",
            addressee_mail="総務部　御中",
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

def test_build_label_entry_uses_mail_address(svc, engine):
    with get_session(engine) as s:
        m = s.query(Member).filter_by(member_number="9002").first()
        s.expunge_all()
    entry = svc.build_label_entry(m)
    assert entry.postal_code == "510-0002"
    assert entry.address1 == "鈴鹿市2-2"
    assert entry.company_name == "総務部　御中"

def test_generate_pdf(svc, engine):
    members = svc.get_label_targets(active_only=True)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        svc.generate_pdf(members, path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)
```

- [ ] **Step 3: テスト実行（失敗を確認）**

```
pytest tests/test_label_service.py -v
```
Expected: ImportError

- [ ] **Step 4: app/services/label_service.py を実装**

```python
# app/services/label_service.py
from dataclasses import dataclass
from app.database.connection import get_session
from app.database.models import Member, InsuranceEntry
from app.services.member_service import MemberService


@dataclass
class LabelEntry:
    """label_pdf.py の generate_label_pdf が期待するエントリ形式"""
    company_name: str = ""
    postal_code: str = ""
    address1: str = ""
    address2: str = ""
    title: str = ""
    person_name: str = ""
    barcode_address: str = ""
    entry_mode: str = "inherit"


class LabelService:
    def __init__(self, engine):
        self._engine = engine

    def get_label_targets(
        self,
        active_only: bool = True,
        include_withdrawn: bool = False,
        ins_types: list[str] | None = None,
        tokubetsu_only: bool = False,
    ) -> list[Member]:
        with get_session(self._engine) as session:
            q = session.query(Member)
            if active_only and not include_withdrawn:
                q = q.filter(Member.is_active == True)
            elif not active_only and include_withdrawn:
                pass  # 全件
            elif active_only:
                pass  # is_active=True のみ（デフォルト）
            if ins_types:
                q = q.join(Member.insurance_entries).filter(
                    InsuranceEntry.ins_type.in_(ins_types)
                )
            if tokubetsu_only:
                q = q.join(Member.insurance_entries, isouter=not bool(ins_types)).filter(
                    InsuranceEntry.is_tokubetsu == True
                )
            members = q.distinct().order_by(Member.member_number).all()
            for m in members:
                _ = m.insurance_entries
            session.expunge_all()
            return members

    def build_label_entry(self, member: Member) -> LabelEntry:
        # 郵送先住所優先フォールバック
        if member.postal_code_mail:
            postal = member.postal_code_mail
            addr1 = member.address_mail or ""
            company = member.addressee_mail or member.org_name or ""
        else:
            postal = member.postal_code or ""
            addr1 = member.address or ""
            company = member.org_name or ""
        return LabelEntry(
            company_name=company,
            postal_code=postal,
            address1=addr1,
            address2="",
            title="",
            person_name="",
            barcode_address=addr1,
            entry_mode="inherit",
        )

    def generate_pdf(
        self,
        members: list[Member],
        output_path: str,
        layout_key: str = "a_one_28185",
        font_key: str = "MSPゴシック",
        barcode_enabled: bool = False,
        batch_mode: str = "no_person",
    ) -> str:
        from app.services.pdf.label_pdf import generate_label_pdf
        entries = [self.build_label_entry(m) for m in members]
        return generate_label_pdf(
            entries=entries,
            output_path=output_path,
            batch_mode=batch_mode,
            layout_key=layout_key,
            font_key=font_key,
            barcode_enabled=barcode_enabled,
        )
```

- [ ] **Step 5: テスト実行（全パスを確認）**

```
pytest tests/test_label_service.py -v
```
Expected: 5 passed

- [ ] **Step 6: コミット**

```bash
git add app/services/pdf/ app/utils/customer_barcode.py app/services/label_service.py tests/test_label_service.py
git commit -m "feat: add label service with address fallback"
```

---

### Task 2: ラベル出力タブ

**Files:**
- Modify: `app/ui/label_tab.py`

- [ ] **Step 1: app/ui/label_tab.py を実装**

```python
# app/ui/label_tab.py
import os
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QComboBox, QGroupBox, QHeaderView, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.services.label_service import LabelService
from app.services.member_service import MemberService, INS_TYPES
from app.services.pdf.label_pdf import LABEL_LAYOUTS, FONT_OPTIONS, DEFAULT_LAYOUT_KEY, DEFAULT_FONT_KEY

BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}


class LabelTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = LabelService(engine)
        self._member_svc = MemberService(engine)
        self._all_members = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 絞り込みエリア
        filter_group = QGroupBox("絞り込み・クイック選択")
        filter_layout = QVBoxLayout(filter_group)
        kw_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・住所で検索")
        self._keyword_edit.textChanged.connect(self._on_filter_changed)
        kw_row.addWidget(self._keyword_edit)
        filter_layout.addLayout(kw_row)

        flag_row = QHBoxLayout()
        flag_row.addWidget(QLabel("枝番："))
        self._ins_checks = {}
        for ins_type in INS_TYPES:
            chk = QCheckBox(BRANCH_LABELS[ins_type])
            chk.stateChanged.connect(self._on_filter_changed)
            self._ins_checks[ins_type] = chk
            flag_row.addWidget(chk)
        flag_row.addSpacing(12)
        self._tokubetsu_chk = QCheckBox("特別加入のみ")
        self._tokubetsu_chk.stateChanged.connect(self._on_filter_changed)
        flag_row.addWidget(self._tokubetsu_chk)
        self._withdrawn_chk = QCheckBox("脱会済みを含む")
        self._withdrawn_chk.stateChanged.connect(self._on_filter_changed)
        flag_row.addWidget(self._withdrawn_chk)
        flag_row.addStretch()
        filter_layout.addLayout(flag_row)

        quick_row = QHBoxLayout()
        all_btn = QPushButton("全アクティブ会員を選択")
        all_btn.clicked.connect(self._on_select_all_active)
        tokubetsu_btn = QPushButton("特別加入のみを選択")
        tokubetsu_btn.clicked.connect(self._on_select_tokubetsu)
        clear_btn = QPushButton("選択を解除")
        clear_btn.clicked.connect(self._on_clear_selection)
        quick_row.addWidget(all_btn)
        quick_row.addWidget(tokubetsu_btn)
        quick_row.addWidget(clear_btn)
        quick_row.addStretch()
        filter_layout.addLayout(quick_row)
        layout.addWidget(filter_group)

        # 一覧テーブル
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["選択", "会員No.", "事業所名", "住所（郵送先優先）", "特別"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 40)
        layout.addWidget(self._table)

        # ラベル設定
        settings_group = QGroupBox("ラベル設定")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("用紙："))
        self._layout_combo = QComboBox()
        for key, lyt in LABEL_LAYOUTS.items():
            self._layout_combo.addItem(lyt.name, key)
        settings_layout.addWidget(self._layout_combo)
        settings_layout.addWidget(QLabel("フォント："))
        self._font_combo = QComboBox()
        for label in FONT_OPTIONS:
            self._font_combo.addItem(label)
        if DEFAULT_FONT_KEY in FONT_OPTIONS:
            self._font_combo.setCurrentText(DEFAULT_FONT_KEY)
        settings_layout.addWidget(self._font_combo)
        self._barcode_chk = QCheckBox("バーコード印字")
        settings_layout.addWidget(self._barcode_chk)
        settings_layout.addStretch()
        layout.addWidget(settings_group)

        # 出力ボタン
        btn_row = QHBoxLayout()
        self._count_label = QLabel("選択中 0件")
        btn_row.addWidget(self._count_label)
        btn_row.addStretch()
        export_btn = QPushButton("選択中をPDF出力")
        export_btn.setFixedHeight(32)
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        ins_types = [t for t, chk in self._ins_checks.items() if chk.isChecked()]
        self._all_members = self._svc.get_label_targets(
            active_only=True,
            include_withdrawn=self._withdrawn_chk.isChecked(),
            ins_types=ins_types if ins_types else None,
            tokubetsu_only=self._tokubetsu_chk.isChecked(),
        )
        kw = self._keyword_edit.text().strip().lower()
        if kw:
            self._all_members = [
                m for m in self._all_members
                if kw in (m.org_name or "").lower()
                or kw in (m.org_kana or "").lower()
                or kw in (m.address or "").lower()
                or kw in (m.address_mail or "").lower()
            ]
        self._populate_table(check_all=False)

    def _on_filter_changed(self):
        self._refresh()

    def _populate_table(self, check_all: bool = False):
        self._table.setRowCount(len(self._all_members))
        for row, m in enumerate(self._all_members):
            chk = QCheckBox()
            chk.setChecked(check_all)
            chk.stateChanged.connect(self._update_count)
            self._table.setCellWidget(row, 0, chk)
            self._table.setItem(row, 1, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_name))
            entry = self._svc.build_label_entry(m)
            addr = f"〒{entry.postal_code}　{entry.address1}" if entry.postal_code else entry.address1
            self._table.setItem(row, 3, QTableWidgetItem(addr))
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            self._table.setItem(row, 4, QTableWidgetItem("●" if has_tokubetsu else ""))
        self._update_count()

    def _update_count(self):
        count = sum(
            1 for row in range(self._table.rowCount())
            if (w := self._table.cellWidget(row, 0)) and w.isChecked()
        )
        self._count_label.setText(f"選択中 {count}件")

    def _selected_members(self) -> list:
        return [
            self._all_members[row]
            for row in range(self._table.rowCount())
            if (w := self._table.cellWidget(row, 0)) and w.isChecked()
        ]

    def _on_select_all_active(self):
        self._keyword_edit.clear()
        for chk in self._ins_checks.values():
            chk.setChecked(False)
        self._tokubetsu_chk.setChecked(False)
        self._withdrawn_chk.setChecked(False)
        self._refresh()
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(True)
        self._update_count()

    def _on_select_tokubetsu(self):
        self._tokubetsu_chk.setChecked(True)
        self._refresh()
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(True)
        self._update_count()

    def _on_clear_selection(self):
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(False)
        self._update_count()

    def _on_export(self):
        members = self._selected_members()
        if not members:
            QMessageBox.warning(self, "エラー", "出力する会員を選択してください。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF保存先を選択", "宛名ラベル.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            layout_key = self._layout_combo.currentData()
            font_key = self._font_combo.currentText()
            barcode = self._barcode_chk.isChecked()
            self._svc.generate_pdf(members, path, layout_key, font_key, barcode)
            QMessageBox.information(self, "完了", f"{len(members)}件のラベルPDFを出力しました。\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 2: アプリ起動・ラベルタブ動作確認**

```
python main.py
```
確認項目：
- ラベル出力タブで会員が一覧表示されること
- チェックボックスで個別選択できること
- [全アクティブ会員を選択] で全チェックされること
- PDF出力ボタンでファイルが生成され、開けること（A-ONE用紙レイアウトを確認）

- [ ] **Step 3: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 4: コミット**

```bash
git add app/ui/label_tab.py
git commit -m "feat: implement label output tab with checkbox selection"
```
