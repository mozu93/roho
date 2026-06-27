# 労働保険名簿管理システム Plan 2: 名簿管理

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 名簿タブの全機能（CRUD・検索・変更履歴・Excelインポート・Excelエクスポート・脱会処理）を実装する

**Architecture:** `member_service.py` がDB操作を担当。UIは `member_tab.py` + 各ダイアログ。変更時は `member_changes` にスナップショットを自動記録し、他職員の `change_confirmations` に未読レコードを作成する。

**Tech Stack:** Python 3.11+, PyQt6, SQLAlchemy 2.x, openpyxl

## Global Constraints

- Plan 1 完了が前提（models.py, connection.py, app_config.py 実装済み）
- 保険種別の `ins_type` 値: `ippan` / `kensetsu_koyou` / `ringyo` / `kensetsu_genba` / `kensetsu_jimusho`
- 枝番対応: ippan=0, kensetsu_koyou=2, ringyo=4, kensetsu_genba=5, kensetsu_jimusho=6
- 変更保存時は変更理由が必須
- ウィンドウ・ダイアログは幅780px以内、高さ600px以内

---

### Task 1: MemberService（名簿CRUD・変更履歴）

**Files:**
- Create: `app/services/member_service.py`
- Create: `tests/test_member_service.py`

**Interfaces:**
- Produces:
  - `MemberService(engine)`
  - `MemberService.search(keyword, ins_types, tokubetsu_only, ikkatsu_only, active_only) -> list[Member]`
  - `MemberService.get(member_id) -> Member`
  - `MemberService.create(data: dict, staff_name: str) -> Member`
  - `MemberService.update(member_id, data: dict, reason: str, staff_name: str) -> Member`
  - `MemberService.withdraw(member_id, withdrawn_at, reason: str, staff_name: str) -> Member`
  - `MemberService.reactivate(member_id, staff_name: str) -> Member`
  - `MemberService.get_changes(member_id) -> list[MemberChange]`
  - `MemberService.member_to_dict(member: Member) -> dict`（スナップショット用JSON化）

- [ ] **Step 1: テストを書く**

```python
# tests/test_member_service.py
import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Staff
from app.database.connection import get_session
from app.services.member_service import MemberService

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with get_session(eng) as s:
        s.add(Staff(name="山田"))
        s.add(Staff(name="鈴木"))
    return eng

@pytest.fixture
def svc(engine):
    return MemberService(engine)

def test_create_member(svc):
    data = {
        "member_number": "9001",
        "org_name": "㈱テスト商事",
        "insurance_entries": [
            {"ins_type": "ippan", "branch_number": "0", "ins_number": "101",
             "is_tokubetsu": False, "is_ikkatsu": False}
        ]
    }
    m = svc.create(data, "山田")
    assert m.member_number == "9001"
    assert len(m.insurance_entries) == 1

def test_search_by_keyword(svc):
    svc.create({"member_number": "9001", "org_name": "㈱テスト商事", "insurance_entries": []}, "山田")
    svc.create({"member_number": "9002", "org_name": "△△建設", "insurance_entries": []}, "山田")
    results = svc.search(keyword="テスト")
    assert len(results) == 1
    assert results[0].org_name == "㈱テスト商事"

def test_search_by_ins_type(svc):
    svc.create({"member_number": "9001", "org_name": "A社", "insurance_entries": [
        {"ins_type": "ippan", "branch_number": "0", "ins_number": "101",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")
    svc.create({"member_number": "9002", "org_name": "B社", "insurance_entries": [
        {"ins_type": "kensetsu_koyou", "branch_number": "2", "ins_number": "202",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")
    results = svc.search(ins_types=["ippan"])
    assert len(results) == 1

def test_update_creates_change_record(svc):
    m = svc.create({"member_number": "9001", "org_name": "旧社名", "insurance_entries": []}, "山田")
    svc.update(m.id, {"org_name": "新社名", "insurance_entries": []}, "住所変更のため", "山田")
    changes = svc.get_changes(m.id)
    assert len(changes) == 1
    assert changes[0].change_reason == "住所変更のため"

def test_withdraw_and_reactivate(svc):
    from datetime import date
    m = svc.create({"member_number": "9001", "org_name": "㈱テスト", "insurance_entries": []}, "山田")
    svc.withdraw(m.id, date(2026, 6, 1), "自己都合", "山田")
    results = svc.search(active_only=True)
    assert len(results) == 0
    svc.reactivate(m.id, "山田")
    results = svc.search(active_only=True)
    assert len(results) == 1
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_member_service.py -v
```
Expected: ImportError

- [ ] **Step 3: app/services/member_service.py を実装**

```python
# app/services/member_service.py
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.connection import get_session
from app.database.models import (
    Member, InsuranceEntry, MemberChange, ChangeConfirmation, Staff,
)

INS_TYPES = ["ippan", "kensetsu_koyou", "ringyo", "kensetsu_genba", "kensetsu_jimusho"]


class MemberService:
    def __init__(self, engine):
        self._engine = engine

    def search(
        self,
        keyword: str = "",
        ins_types: list[str] | None = None,
        tokubetsu_only: bool = False,
        ikkatsu_only: bool = False,
        active_only: bool = True,
    ) -> list[Member]:
        with get_session(self._engine) as session:
            q = session.query(Member)
            if active_only:
                q = q.filter(Member.is_active == True)
            else:
                q = q.filter(Member.is_active == False)
            if keyword:
                kw = f"%{keyword}%"
                q = q.filter(
                    Member.org_name.like(kw)
                    | Member.org_kana.like(kw)
                    | Member.address.like(kw)
                    | Member.tel.like(kw)
                )
            if ins_types:
                q = q.join(Member.insurance_entries).filter(
                    InsuranceEntry.ins_type.in_(ins_types)
                )
            if tokubetsu_only:
                q = q.join(Member.insurance_entries, isouter=True).filter(
                    InsuranceEntry.is_tokubetsu == True
                )
            if ikkatsu_only:
                q = q.join(Member.insurance_entries, isouter=True).filter(
                    InsuranceEntry.is_ikkatsu == True
                )
            results = q.distinct().order_by(Member.member_number).all()
            # detach して返す
            for m in results:
                _ = m.insurance_entries  # eager load
            session.expunge_all()
            return results

    def get(self, member_id: int) -> Member:
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if m:
                _ = m.insurance_entries
            session.expunge_all()
            return m

    def create(self, data: dict, staff_name: str) -> Member:
        with get_session(self._engine) as session:
            entries_data = data.pop("insurance_entries", [])
            m = Member(**{k: v for k, v in data.items()})
            m.created_at = datetime.now()
            m.updated_at = datetime.now()
            session.add(m)
            session.flush()
            for e in entries_data:
                session.add(InsuranceEntry(member_id=m.id, **e))
            session.flush()
            _ = m.insurance_entries
            session.expunge_all()
            return m

    def update(self, member_id: int, data: dict, reason: str, staff_name: str) -> Member:
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            snapshot = json.dumps(self.member_to_dict(m), ensure_ascii=False)

            entries_data = data.pop("insurance_entries", [])
            for k, v in data.items():
                setattr(m, k, v)
            m.updated_at = datetime.now()

            # 保険番号を更新（全削除→再作成）
            for e in list(m.insurance_entries):
                session.delete(e)
            session.flush()
            for e in entries_data:
                session.add(InsuranceEntry(member_id=m.id, **e))

            # 変更履歴を記録
            change = MemberChange(
                member_id=m.id,
                changed_at=datetime.now(),
                changed_by=staff_name,
                change_reason=reason,
                snapshot=snapshot,
            )
            session.add(change)
            session.flush()

            # 他職員に未読通知を作成
            other_staff = (
                session.query(Staff)
                .filter(Staff.is_active == True, Staff.name != staff_name)
                .all()
            )
            for s in other_staff:
                session.add(ChangeConfirmation(
                    member_change_id=change.id,
                    staff_id=s.id,
                    confirmed_at=None,  # 未読
                ))

            _ = m.insurance_entries
            session.expunge_all()
            return m

    def withdraw(self, member_id: int, withdrawn_at, reason: str, staff_name: str) -> Member:
        data = {"is_active": False, "withdrawn_at": withdrawn_at, "withdraw_reason": reason}
        return self.update(member_id, data, f"脱会：{reason}", staff_name)

    def reactivate(self, member_id: int, staff_name: str) -> Member:
        data = {"is_active": True, "withdrawn_at": None, "withdraw_reason": None}
        return self.update(member_id, data, "再加入", staff_name)

    def get_changes(self, member_id: int) -> list[MemberChange]:
        with get_session(self._engine) as session:
            changes = (
                session.query(MemberChange)
                .filter_by(member_id=member_id)
                .order_by(MemberChange.changed_at.desc())
                .all()
            )
            session.expunge_all()
            return changes

    def member_to_dict(self, member: Member) -> dict:
        return {
            "id": member.id,
            "member_number": member.member_number,
            "org_name": member.org_name,
            "org_kana": member.org_kana,
            "rep_name": member.rep_name,
            "tel": member.tel,
            "address": member.address,
            "is_active": member.is_active,
            "insurance_entries": [
                {
                    "ins_type": e.ins_type,
                    "branch_number": e.branch_number,
                    "ins_number": e.ins_number,
                    "is_tokubetsu": e.is_tokubetsu,
                    "is_ikkatsu": e.is_ikkatsu,
                }
                for e in member.insurance_entries
            ],
        }
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_member_service.py -v
```
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add app/services/member_service.py tests/test_member_service.py
git commit -m "feat: add member service with CRUD and change history"
```

---

### Task 2: 加入者編集ダイアログ

**Files:**
- Create: `app/ui/dialogs/member_edit_dialog.py`

**Interfaces:**
- Consumes: `MemberService`
- Produces: `MemberEditDialog(engine, staff_name, member_id=None, parent=None)` → `exec()` → `saved: bool`

- [ ] **Step 1: app/ui/dialogs/member_edit_dialog.py を実装**

```python
# app/ui/dialogs/member_edit_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QGroupBox,
    QPushButton, QScrollArea, QWidget, QLabel, QMessageBox,
)
from app.services.member_service import MemberService, INS_TYPES

INS_LABELS = {
    "ippan":            "一般・労＆雇（枝番0）",
    "kensetsu_koyou":   "建設業・他雇用（枝番2）",
    "ringyo":           "林業・労災（枝番4）",
    "kensetsu_genba":   "建設業・現場（枝番5）",
    "kensetsu_jimusho": "建設業・事務所（枝番6）",
}
BRANCH_NUMBERS = {
    "ippan": "0", "kensetsu_koyou": "2",
    "ringyo": "4", "kensetsu_genba": "5", "kensetsu_jimusho": "6",
}


class MemberEditDialog(QDialog):
    def __init__(self, engine, staff_name: str, member_id: int | None = None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self._member_id = member_id
        self._svc = MemberService(engine)
        self.saved = False
        self.setWindowTitle("加入者編集" if member_id else "加入者追加")
        self.setMinimumWidth(620)
        self.resize(640, 580)
        self._build_ui()
        if member_id:
            self._load_member(member_id)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)

        # 基本情報
        basic = QGroupBox("基本情報")
        fl = QFormLayout(basic)
        self._f_member_number = QLineEdit()
        self._f_org_name = QLineEdit()
        self._f_org_kana = QLineEdit()
        self._f_dept_title = QLineEdit()
        self._f_rep_name = QLineEdit()
        self._f_rep_kana = QLineEdit()
        self._f_email = QLineEdit()
        self._f_tel_area = QLineEdit(); self._f_tel_area.setFixedWidth(60)
        self._f_tel = QLineEdit()
        self._f_fax_area = QLineEdit(); self._f_fax_area.setFixedWidth(60)
        self._f_fax = QLineEdit()
        self._f_postal_code = QLineEdit()
        self._f_address = QLineEdit()
        self._f_postal_code_mail = QLineEdit()
        self._f_address_mail = QLineEdit()
        self._f_addressee_mail = QLineEdit()
        self._f_employment_ins_no = QLineEdit()
        self._f_note = QTextEdit(); self._f_note.setFixedHeight(60)
        tel_row = QHBoxLayout()
        tel_row.addWidget(self._f_tel_area)
        tel_row.addWidget(QLabel("-"))
        tel_row.addWidget(self._f_tel)
        fax_row = QHBoxLayout()
        fax_row.addWidget(self._f_fax_area)
        fax_row.addWidget(QLabel("-"))
        fax_row.addWidget(self._f_fax)
        fl.addRow("会員No.*", self._f_member_number)
        fl.addRow("事業所名*", self._f_org_name)
        fl.addRow("フリガナ", self._f_org_kana)
        fl.addRow("所属・役職", self._f_dept_title)
        fl.addRow("代表者名", self._f_rep_name)
        fl.addRow("代表者フリガナ", self._f_rep_kana)
        fl.addRow("メール", self._f_email)
        fl.addRow("電話", tel_row)
        fl.addRow("FAX", fax_row)
        fl.addRow("郵便番号", self._f_postal_code)
        fl.addRow("住所", self._f_address)
        fl.addRow("郵送先郵便番号", self._f_postal_code_mail)
        fl.addRow("郵送先住所", self._f_address_mail)
        fl.addRow("郵送先宛名", self._f_addressee_mail)
        fl.addRow("雇用保険事業所番号", self._f_employment_ins_no)
        fl.addRow("メモ", self._f_note)
        form_layout.addWidget(basic)

        # 保険番号
        ins_group = QGroupBox("保険番号")
        ins_layout = QVBoxLayout(ins_group)
        self._ins_widgets = {}
        for ins_type in INS_TYPES:
            row = QHBoxLayout()
            chk = QCheckBox(INS_LABELS[ins_type])
            chk.setFixedWidth(220)
            num_edit = QLineEdit(); num_edit.setPlaceholderText("番号")
            tokubetsu_chk = QCheckBox("特別加入")
            ikkatsu_chk = QCheckBox("継続一括")
            row.addWidget(chk)
            row.addWidget(num_edit)
            row.addWidget(tokubetsu_chk)
            row.addWidget(ikkatsu_chk)
            ins_layout.addLayout(row)
            self._ins_widgets[ins_type] = (chk, num_edit, tokubetsu_chk, ikkatsu_chk)
            chk.toggled.connect(lambda checked, n=num_edit, t=tokubetsu_chk, k=ikkatsu_chk: (
                n.setEnabled(checked), t.setEnabled(checked), k.setEnabled(checked)
            ))
            num_edit.setEnabled(False); tokubetsu_chk.setEnabled(False); ikkatsu_chk.setEnabled(False)
        form_layout.addWidget(ins_group)

        # 変更理由
        reason_group = QGroupBox("変更理由（必須）")
        rl = QVBoxLayout(reason_group)
        self._f_reason = QLineEdit()
        self._f_reason.setPlaceholderText("例：住所変更、保険番号追加")
        rl.addWidget(self._f_reason)
        form_layout.addWidget(reason_group)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # ボタン
        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    def _load_member(self, member_id: int):
        m = self._svc.get(member_id)
        if not m:
            return
        self._f_member_number.setText(m.member_number or "")
        self._f_org_name.setText(m.org_name or "")
        self._f_org_kana.setText(m.org_kana or "")
        self._f_dept_title.setText(m.dept_title or "")
        self._f_rep_name.setText(m.rep_name or "")
        self._f_rep_kana.setText(m.rep_kana or "")
        self._f_email.setText(m.email or "")
        self._f_tel_area.setText(m.tel_area or "")
        self._f_tel.setText(m.tel or "")
        self._f_fax_area.setText(m.fax_area or "")
        self._f_fax.setText(m.fax or "")
        self._f_postal_code.setText(m.postal_code or "")
        self._f_address.setText(m.address or "")
        self._f_postal_code_mail.setText(m.postal_code_mail or "")
        self._f_address_mail.setText(m.address_mail or "")
        self._f_addressee_mail.setText(m.addressee_mail or "")
        self._f_employment_ins_no.setText(m.employment_ins_no or "")
        self._f_note.setPlainText(m.note or "")
        for e in m.insurance_entries:
            if e.ins_type in self._ins_widgets:
                chk, num_edit, tok_chk, ika_chk = self._ins_widgets[e.ins_type]
                chk.setChecked(True)
                num_edit.setText(e.ins_number or "")
                tok_chk.setChecked(e.is_tokubetsu)
                ika_chk.setChecked(e.is_ikkatsu)

    def _collect_data(self) -> dict:
        entries = []
        for ins_type, (chk, num_edit, tok_chk, ika_chk) in self._ins_widgets.items():
            if chk.isChecked():
                entries.append({
                    "ins_type": ins_type,
                    "branch_number": BRANCH_NUMBERS[ins_type],
                    "ins_number": num_edit.text().strip(),
                    "is_tokubetsu": tok_chk.isChecked(),
                    "is_ikkatsu": ika_chk.isChecked(),
                })
        return {
            "member_number": self._f_member_number.text().strip(),
            "org_name": self._f_org_name.text().strip(),
            "org_kana": self._f_org_kana.text().strip(),
            "dept_title": self._f_dept_title.text().strip(),
            "rep_name": self._f_rep_name.text().strip(),
            "rep_kana": self._f_rep_kana.text().strip(),
            "email": self._f_email.text().strip(),
            "tel_area": self._f_tel_area.text().strip(),
            "tel": self._f_tel.text().strip(),
            "fax_area": self._f_fax_area.text().strip(),
            "fax": self._f_fax.text().strip(),
            "postal_code": self._f_postal_code.text().strip(),
            "address": self._f_address.text().strip(),
            "postal_code_mail": self._f_postal_code_mail.text().strip(),
            "address_mail": self._f_address_mail.text().strip(),
            "addressee_mail": self._f_addressee_mail.text().strip(),
            "employment_ins_no": self._f_employment_ins_no.text().strip(),
            "note": self._f_note.toPlainText().strip(),
            "insurance_entries": entries,
        }

    def _on_save(self):
        data = self._collect_data()
        if not data["member_number"]:
            QMessageBox.warning(self, "入力エラー", "会員No.は必須です。")
            return
        if not data["org_name"]:
            QMessageBox.warning(self, "入力エラー", "事業所名は必須です。")
            return
        reason = self._f_reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "入力エラー", "変更理由を入力してください。")
            return
        try:
            if self._member_id:
                self._svc.update(self._member_id, data, reason, self._staff_name)
            else:
                self._svc.create(data, self._staff_name)
            self.saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", str(e))
```

- [ ] **Step 2: コミット**

```bash
git add app/ui/dialogs/member_edit_dialog.py
git commit -m "feat: add member edit dialog"
```

---

### Task 3: 変更履歴ダイアログ・脱会ダイアログ

**Files:**
- Create: `app/ui/dialogs/member_history_dialog.py`
- Create: `app/ui/dialogs/withdraw_dialog.py`

**Interfaces:**
- Consumes: `MemberService`
- Produces:
  - `MemberHistoryDialog(engine, member_id, parent=None)`
  - `WithdrawDialog(engine, staff_name, member_id, parent=None)` → `exec()` → `withdrawn: bool`

- [ ] **Step 1: member_history_dialog.py を実装**

```python
# app/ui/dialogs/member_history_dialog.py
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QTextEdit, QLabel, QPushButton, QSplitter,
)
from PyQt6.QtCore import Qt
from app.services.member_service import MemberService


class MemberHistoryDialog(QDialog):
    def __init__(self, engine, member_id: int, parent=None):
        super().__init__(parent)
        self._svc = MemberService(engine)
        self._member_id = member_id
        self.setWindowTitle("変更履歴")
        self.resize(700, 450)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["変更日時", "担当者", "変更理由"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_select)
        splitter.addWidget(self._table)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("行を選択すると変更前データを表示します")
        splitter.addWidget(self._detail)
        layout.addWidget(splitter)

        btn = QPushButton("閉じる")
        btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _load(self):
        self._changes = self._svc.get_changes(self._member_id)
        self._table.setRowCount(len(self._changes))
        for row, c in enumerate(self._changes):
            self._table.setItem(row, 0, QTableWidgetItem(c.changed_at.strftime("%Y-%m-%d %H:%M")))
            self._table.setItem(row, 1, QTableWidgetItem(c.changed_by))
            self._table.setItem(row, 2, QTableWidgetItem(c.change_reason))

    def _on_select(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        change = self._changes[row]
        try:
            data = json.loads(change.snapshot)
            self._detail.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            self._detail.setPlainText(change.snapshot)
```

- [ ] **Step 2: withdraw_dialog.py を実装**

```python
# app/ui/dialogs/withdraw_dialog.py
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDateEdit, QLineEdit, QPushButton, QMessageBox, QGroupBox,
)
from PyQt6.QtCore import QDate
from app.services.member_service import MemberService


class WithdrawDialog(QDialog):
    def __init__(self, engine, staff_name: str, member_id: int, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self._member_id = member_id
        self._svc = MemberService(engine)
        self.withdrawn = False
        self.setWindowTitle("脱会処理")
        self.setFixedSize(400, 200)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("脱会情報を入力")
        fl = QFormLayout(grp)
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("脱会理由を入力してください")
        fl.addRow("脱会日：", self._date_edit)
        fl.addRow("脱会理由：", self._reason_edit)
        layout.addWidget(grp)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("脱会処理を実行")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_ok(self):
        reason = self._reason_edit.text().strip()
        if not reason:
            QMessageBox.warning(self, "入力エラー", "脱会理由を入力してください。")
            return
        qd = self._date_edit.date()
        withdrawn_at = date(qd.year(), qd.month(), qd.day())
        reply = QMessageBox.question(
            self, "確認", "脱会処理を実行してよいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._svc.withdraw(self._member_id, withdrawn_at, reason, self._staff_name)
            self.withdrawn = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 3: コミット**

```bash
git add app/ui/dialogs/member_history_dialog.py app/ui/dialogs/withdraw_dialog.py
git commit -m "feat: add member history and withdraw dialogs"
```

---

### Task 4: 名簿タブ（一覧・検索・操作ボタン）

**Files:**
- Modify: `app/ui/member_tab.py`

**Interfaces:**
- Consumes: `MemberService`, `MemberEditDialog`, `MemberHistoryDialog`, `WithdrawDialog`

- [ ] **Step 1: app/ui/member_tab.py を実装**

```python
# app/ui/member_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QGroupBox, QButtonGroup, QRadioButton,
)
from PyQt6.QtCore import Qt
from app.services.member_service import MemberService, INS_TYPES
from app.ui.dialogs.member_edit_dialog import MemberEditDialog
from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
from app.ui.dialogs.withdraw_dialog import WithdrawDialog

BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}
COLS = ["会員No.", "事業所名", "フリガナ", "電話", "0", "2", "4", "5", "6", "特別", "最終対応日"]


class MemberTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = MemberService(engine)
        self._members = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 検索エリア
        search_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・住所・電話番号で検索")
        self._keyword_edit.textChanged.connect(self._refresh)
        search_row.addWidget(self._keyword_edit)
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("枝番："))
        self._ins_checks = {}
        for ins_type in INS_TYPES:
            chk = QCheckBox(BRANCH_LABELS[ins_type])
            chk.stateChanged.connect(self._refresh)
            self._ins_checks[ins_type] = chk
            filter_row.addWidget(chk)
        filter_row.addSpacing(12)
        self._tokubetsu_chk = QCheckBox("特別加入のみ")
        self._tokubetsu_chk.stateChanged.connect(self._refresh)
        filter_row.addWidget(self._tokubetsu_chk)
        self._ikkatsu_chk = QCheckBox("一括認可のみ")
        self._ikkatsu_chk.stateChanged.connect(self._refresh)
        filter_row.addWidget(self._ikkatsu_chk)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # 一覧テーブル
        self._table = QTableWidget(0, len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(self._on_edit)
        layout.addWidget(self._table)

        # ボタン行
        btn_row = QHBoxLayout()
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self._on_add)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self._on_edit)
        withdraw_btn = QPushButton("脱会処理")
        withdraw_btn.clicked.connect(self._on_withdraw)
        history_btn = QPushButton("変更履歴")
        history_btn.clicked.connect(self._on_history)
        activity_btn = QPushButton("対応履歴")
        activity_btn.clicked.connect(self._on_activity)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        for btn in [add_btn, edit_btn, withdraw_btn, history_btn, activity_btn, export_btn]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh(self):
        ins_types = [t for t, chk in self._ins_checks.items() if chk.isChecked()]
        members = self._svc.search(
            keyword=self._keyword_edit.text(),
            ins_types=ins_types if ins_types else None,
            tokubetsu_only=self._tokubetsu_chk.isChecked(),
            ikkatsu_only=self._ikkatsu_chk.isChecked(),
            active_only=True,
        )
        self._members = members
        self._table.setRowCount(len(members))
        for row, m in enumerate(members):
            active_types = {e.ins_type for e in m.insurance_entries}
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            self._table.setItem(row, 0, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 1, QTableWidgetItem(m.org_name))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_kana or ""))
            self._table.setItem(row, 3, QTableWidgetItem(
                f"{m.tel_area or ''}-{m.tel or ''}" if m.tel else ""
            ))
            for col_idx, ins_type in enumerate(INS_TYPES):
                self._table.setItem(row, 4 + col_idx,
                    QTableWidgetItem("●" if ins_type in active_types else ""))
            self._table.setItem(row, 9, QTableWidgetItem("●" if has_tokubetsu else ""))
            self._table.setItem(row, 10, QTableWidgetItem(""))  # 最終対応日（Plan3で実装）

    def _selected_member(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._members):
            return None
        return self._members[row]

    def _on_add(self):
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_edit(self):
        m = self._selected_member()
        if not m:
            return
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_withdraw(self):
        m = self._selected_member()
        if not m:
            return
        dlg = WithdrawDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == WithdrawDialog.DialogCode.Accepted and dlg.withdrawn:
            self._refresh()

    def _on_history(self):
        m = self._selected_member()
        if not m:
            return
        MemberHistoryDialog(self._engine, m.id, parent=self).exec()

    def _on_activity(self):
        pass  # Plan 3 で実装

    def _on_export(self):
        pass  # Task 5 で実装
```

- [ ] **Step 2: アプリ起動・名簿タブ動作確認**

```
python main.py
```
確認項目：
- 名簿タブで「追加」→ 入力 → 保存 → 一覧に表示されること
- キーワード検索で絞り込めること
- 「変更履歴」で変更記録が表示されること
- 「脱会処理」で一覧から消えること

- [ ] **Step 3: コミット**

```bash
git add app/ui/member_tab.py
git commit -m "feat: implement member tab with CRUD and search"
```

---

### Task 5: Excelインポート・エクスポート

**Files:**
- Create: `app/services/import_service.py`
- Create: `app/ui/dialogs/import_dialog.py`
- Create: `tests/test_import_service.py`

**Interfaces:**
- Produces:
  - `ImportService(engine).import_excel(path, column_map, overwrite, staff_name) -> dict`（{"added": int, "updated": int, "skipped": int}）
  - `ExportService(engine).export_excel(members, output_path) -> None`

- [ ] **Step 1: テストを書く**

```python
# tests/test_import_service.py
import os, tempfile
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
    "ins_ippan_branch": 17,   # R (0-indexed from 0)
    "ins_ippan_number": 18,   # S
    "ins_ippan_tokubetsu": 19,
    "ins_ippan_ikkatsu": 20,
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
    # B=会員No, C=事業所名, R=枝番0, S=番号
    row = [""] * 35
    row[1] = "9001"; row[2] = "テスト商事"
    row[17] = "0"; row[18] = "101"
    path = _make_excel([[""] * 35, row])  # 1行目ヘッダー
    try:
        svc = ImportService(engine)
        result = svc.import_excel(path, overwrite=False, staff_name="山田")
        assert result["added"] == 1
    finally:
        os.unlink(path)
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_import_service.py -v
```
Expected: ImportError

- [ ] **Step 3: app/services/import_service.py を実装**

```python
# app/services/import_service.py
import openpyxl
from app.database.connection import get_session
from app.database.models import Member, InsuranceEntry
from app.services.member_service import MemberService

# Excel列インデックス（0始まり）→フィールドマッピング
DEFAULT_COL_MAP = {
    "member_number":  1,   # B
    "org_name":       2,   # C
    "org_kana":       3,   # D
    "dept_title":     4,   # E
    "rep_name":       5,   # F
    "rep_kana":       6,   # G
    "email":          7,   # H
    "tel_area":       8,   # I
    "tel":            9,   # J
    "fax_area":      10,   # K
    "fax":           11,   # L
    "postal_code":   12,   # M
    "address":       13,   # N
    "postal_code_mail": 14,  # O
    "address_mail":  15,   # P
    "addressee_mail":16,   # Q
    # 保険番号（R=17始まり、各2列＋フラグ2列）
    "ins_ippan_branch":           17,  # R
    "ins_ippan_number":           18,  # S
    "ins_ippan_tokubetsu":        19,
    "ins_ippan_ikkatsu":          20,
    "ins_kensetsu_koyou_branch":  21,  # T
    "ins_kensetsu_koyou_number":  22,  # U
    "ins_kensetsu_koyou_tokubetsu": 23,
    "ins_kensetsu_koyou_ikkatsu": 24,
    "ins_ringyo_branch":          25,  # V
    "ins_ringyo_number":          26,  # W
    "ins_ringyo_tokubetsu":       27,
    "ins_ringyo_ikkatsu":         28,
    "ins_kensetsu_genba_branch":  29,  # X
    "ins_kensetsu_genba_number":  30,  # Y
    "ins_kensetsu_genba_tokubetsu": 31,
    "ins_kensetsu_genba_ikkatsu": 32,
    "ins_kensetsu_jimusho_branch": 33,  # Z
    "ins_kensetsu_jimusho_number": 34,  # AA
    "ins_kensetsu_jimusho_tokubetsu": 35,
    "ins_kensetsu_jimusho_ikkatsu": 36,
    "employment_ins_no": 28,  # AC（フラグ列挿入後はずれるため要確認）
    "note":              29,  # AD
}

INS_TYPE_KEYS = [
    ("ippan",            "ins_ippan"),
    ("kensetsu_koyou",   "ins_kensetsu_koyou"),
    ("ringyo",           "ins_ringyo"),
    ("kensetsu_genba",   "ins_kensetsu_genba"),
    ("kensetsu_jimusho", "ins_kensetsu_jimusho"),
]
BRANCH_NUMBERS = {
    "ippan": "0", "kensetsu_koyou": "2",
    "ringyo": "4", "kensetsu_genba": "5", "kensetsu_jimusho": "6",
}


class ImportService:
    def __init__(self, engine):
        self._engine = engine
        self._svc = MemberService(engine)

    def import_excel(
        self,
        path: str,
        col_map: dict | None = None,
        overwrite: bool = False,
        staff_name: str = "インポート",
    ) -> dict:
        col_map = col_map or DEFAULT_COL_MAP
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        result = {"added": 0, "updated": 0, "skipped": 0}

        for row in ws.iter_rows(min_row=2, values_only=True):
            member_number = str(row[col_map["member_number"]] or "").strip()
            org_name = str(row[col_map["org_name"]] or "").strip()
            if not member_number or not org_name:
                result["skipped"] += 1
                continue

            def _get(key):
                idx = col_map.get(key)
                if idx is None or idx >= len(row):
                    return None
                return row[idx]

            ins_entries = []
            for ins_type, prefix in INS_TYPE_KEYS:
                branch = str(_get(f"{prefix}_branch") or "").strip()
                number = str(_get(f"{prefix}_number") or "").strip()
                if branch or number:
                    ins_entries.append({
                        "ins_type": ins_type,
                        "branch_number": branch or BRANCH_NUMBERS[ins_type],
                        "ins_number": number,
                        "is_tokubetsu": bool(_get(f"{prefix}_tokubetsu")),
                        "is_ikkatsu": bool(_get(f"{prefix}_ikkatsu")),
                    })

            data = {
                "member_number": member_number,
                "org_name": org_name,
                "org_kana": str(_get("org_kana") or ""),
                "dept_title": str(_get("dept_title") or ""),
                "rep_name": str(_get("rep_name") or ""),
                "rep_kana": str(_get("rep_kana") or ""),
                "email": str(_get("email") or ""),
                "tel_area": str(_get("tel_area") or ""),
                "tel": str(_get("tel") or ""),
                "fax_area": str(_get("fax_area") or ""),
                "fax": str(_get("fax") or ""),
                "postal_code": str(_get("postal_code") or ""),
                "address": str(_get("address") or ""),
                "postal_code_mail": str(_get("postal_code_mail") or ""),
                "address_mail": str(_get("address_mail") or ""),
                "addressee_mail": str(_get("addressee_mail") or ""),
                "employment_ins_no": str(_get("employment_ins_no") or ""),
                "note": str(_get("note") or ""),
                "insurance_entries": ins_entries,
            }

            # 既存チェック
            with get_session(self._engine) as session:
                existing = session.query(Member).filter_by(
                    member_number=member_number
                ).first()
                exists = existing is not None
                if exists:
                    member_id = existing.id

            if exists and not overwrite:
                result["skipped"] += 1
                continue

            if exists:
                self._svc.update(member_id, data, "Excelインポートによる更新", staff_name)
                result["updated"] += 1
            else:
                self._svc.create(data, staff_name)
                result["added"] += 1

        return result


class ExportService:
    def __init__(self, engine):
        self._engine = engine

    def export_excel(self, members: list, output_path: str) -> None:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "加入者名簿"
        headers = [
            "会員No.", "事業所名", "フリガナ", "所属・役職", "代表者名", "代表者フリガナ",
            "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
            "郵便番号", "住所", "郵送先郵便番号", "郵送先住所", "郵送先宛名",
            "雇用保険事業所番号",
            "一般枝番", "一般番号", "一般特別加入", "一般一括",
            "建設他雇枝番", "建設他雇番号", "建設他雇特別", "建設他雇一括",
            "林業枝番", "林業番号", "林業特別", "林業一括",
            "建設現場枝番", "建設現場番号", "建設現場特別", "建設現場一括",
            "建設事務所枝番", "建設事務所番号", "建設事務所特別", "建設事務所一括",
            "メモ",
        ]
        ws.append(headers)
        ins_order = ["ippan", "kensetsu_koyou", "ringyo", "kensetsu_genba", "kensetsu_jimusho"]
        for m in members:
            ins_map = {e.ins_type: e for e in m.insurance_entries}
            ins_cols = []
            for ins_type in ins_order:
                e = ins_map.get(ins_type)
                ins_cols += [
                    e.branch_number if e else "",
                    e.ins_number if e else "",
                    1 if (e and e.is_tokubetsu) else "",
                    1 if (e and e.is_ikkatsu) else "",
                ]
            ws.append([
                m.member_number, m.org_name, m.org_kana or "", m.dept_title or "",
                m.rep_name or "", m.rep_kana or "", m.email or "",
                m.tel_area or "", m.tel or "", m.fax_area or "", m.fax or "",
                m.postal_code or "", m.address or "",
                m.postal_code_mail or "", m.address_mail or "", m.addressee_mail or "",
                m.employment_ins_no or "",
            ] + ins_cols + [m.note or ""])
        wb.save(output_path)
```

- [ ] **Step 4: テスト実行**

```
pytest tests/test_import_service.py -v
```
Expected: 1 passed

- [ ] **Step 5: インポートダイアログ・エクスポートを名簿タブに接続**

`app/ui/dialogs/import_dialog.py` を実装し、`member_tab.py` の `_on_export` に接続する。
インポートダイアログはファイル選択 + 上書き確認チェックボックス + 結果サマリー表示のシンプルな構成。

```python
# app/ui/dialogs/import_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QFileDialog, QMessageBox,
)
from app.services.import_service import ImportService


class ImportDialog(QDialog):
    def __init__(self, engine, staff_name: str, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self.setWindowTitle("Excelインポート")
        self.setFixedSize(500, 180)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        file_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Excelファイルを選択してください")
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(self._path_edit)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)
        self._overwrite_chk = QCheckBox("既存の会員番号を上書きする")
        layout.addWidget(self._overwrite_chk)
        btn_row = QHBoxLayout()
        import_btn = QPushButton("インポート実行")
        import_btn.setDefault(True)
        import_btn.clicked.connect(self._on_import)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Excelファイルを選択", "", "Excel (*.xlsx *.xls)")
        if path:
            self._path_edit.setText(path)

    def _on_import(self):
        path = self._path_edit.text()
        if not path:
            QMessageBox.warning(self, "エラー", "ファイルを選択してください。")
            return
        try:
            svc = ImportService(self._engine)
            result = svc.import_excel(path, overwrite=self._overwrite_chk.isChecked(),
                                      staff_name=self._staff_name)
            QMessageBox.information(
                self, "インポート完了",
                f"追加：{result['added']}件\n更新：{result['updated']}件\nスキップ：{result['skipped']}件"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "インポートエラー", str(e))
```

`member_tab.py` の `_on_export` に以下を追加：

```python
def _on_export(self):
    from PyQt6.QtWidgets import QFileDialog
    from app.services.import_service import ExportService
    path, _ = QFileDialog.getSaveFileName(self, "Excel出力", "加入者名簿.xlsx", "Excel (*.xlsx)")
    if not path:
        return
    try:
        ExportService(self._engine).export_excel(self._members, path)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "完了", f"{len(self._members)}件を出力しました。")
    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 6: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 7: コミット**

```bash
git add app/services/import_service.py app/ui/dialogs/import_dialog.py tests/test_import_service.py
git commit -m "feat: add Excel import and export"
```

---

### Task 6: 脱会済みタブ

**Files:**
- Modify: `app/ui/withdrawn_tab.py`

- [ ] **Step 1: app/ui/withdrawn_tab.py を実装**

```python
# app/ui/withdrawn_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView,
)
from app.services.member_service import MemberService


class WithdrawnTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = MemberService(engine)
        self._members = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["脱会日", "会員No.", "事業所名", "脱会理由"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)
        btn_row = QHBoxLayout()
        reactivate_btn = QPushButton("再加入")
        reactivate_btn.clicked.connect(self._on_reactivate)
        btn_row.addStretch()
        btn_row.addWidget(reactivate_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        members = self._svc.search(active_only=False)
        self._members = members
        self._table.setRowCount(len(members))
        for row, m in enumerate(members):
            self._table.setItem(row, 0, QTableWidgetItem(
                m.withdrawn_at.strftime("%Y-%m-%d") if m.withdrawn_at else ""
            ))
            self._table.setItem(row, 1, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_name))
            self._table.setItem(row, 3, QTableWidgetItem(m.withdraw_reason or ""))

    def _on_reactivate(self):
        row = self._table.currentRow()
        if row < 0:
            return
        m = self._members[row]
        reply = QMessageBox.question(
            self, "確認", f"{m.org_name} を再加入しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._svc.reactivate(m.id, self._config.last_staff_name)
            self._refresh()
```

- [ ] **Step 2: コミット**

```bash
git add app/ui/withdrawn_tab.py
git commit -m "feat: implement withdrawn member tab"
```
