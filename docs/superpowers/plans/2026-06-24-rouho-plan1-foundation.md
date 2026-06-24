# 労働保険名簿管理システム Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** プロジェクト骨格・DBモデル・接続・設定管理・メインウィンドウ（5タブスケルトン）・職員ログインを構築する

**Architecture:** SQLAlchemy + SQLite（WALモード）でNAS共有フォルダのDBに複数ユーザーが接続。メインウィンドウは5タブ構成（名簿・脱会済み・ラベル出力・メール送信・設定）。起動時に職員名を選択してapp_config.jsonに記憶する。

**Tech Stack:** Python 3.11+, PyQt6, SQLAlchemy 2.x, SQLite

## Global Constraints

- Python 3.11+
- PyQt6（PySide6は不可）
- SQLAlchemy 2.x（`declarative_base` は `sqlalchemy.orm` から）
- ウィンドウ初期サイズ: 幅780px × 高さ728px 以内
- 日本語UIテキスト
- DB名: `rouho.db`、設定ファイル名: `app_config.json`
- 保険種別の `ins_type` 値: `ippan` / `kensetsu_koyou` / `ringyo` / `kensetsu_genba` / `kensetsu_jimusho`

---

### Task 1: プロジェクトスキャフォールディング

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `start.bat`
- Create: `pytest.ini`
- Create: `app/__init__.py`
- Create: `app/database/__init__.py`
- Create: `app/services/__init__.py`
- Create: `app/ui/__init__.py`
- Create: `app/ui/dialogs/__init__.py`
- Create: `app/utils/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: インストール可能な依存関係、テスト実行環境

- [ ] **Step 1: requirements.txt を作成**

```
PyQt6>=6.6.0
SQLAlchemy>=2.0.0
openpyxl>=3.1.0
reportlab>=4.0.0
requests>=2.31.0
msal>=1.26.0
packaging>=23.0
```

- [ ] **Step 2: requirements-dev.txt を作成**

```
pytest>=8.0.0
pytest-qt>=4.4.0
```

- [ ] **Step 3: pytest.ini を作成**

```ini
[pytest]
testpaths = tests
qt_api = pyqt6
```

- [ ] **Step 4: start.bat を作成**

```bat
@echo off
cd /d "%~dp0"
python main.py
pause
```

- [ ] **Step 5: 全 __init__.py を空ファイルとして作成**

```
app/__init__.py
app/database/__init__.py
app/services/__init__.py
app/ui/__init__.py
app/ui/dialogs/__init__.py
app/utils/__init__.py
tests/__init__.py
```

- [ ] **Step 6: 依存をインストール**

```
pip install -r requirements.txt -r requirements-dev.txt
```

- [ ] **Step 7: git init & 初回コミット**

```bash
git init
git add .
git commit -m "chore: initial project scaffolding"
```

---

### Task 2: バージョン管理

**Files:**
- Create: `app/version.py`

**Interfaces:**
- Produces: `__version__: str`（例: `"1.0.0"`）

- [ ] **Step 1: app/version.py を作成**

```python
__version__ = "1.0.0"
```

- [ ] **Step 2: コミット**

```bash
git add app/version.py
git commit -m "chore: add version module"
```

---

### Task 3: データベースモデル

**Files:**
- Create: `app/database/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `Base`, `Member`, `InsuranceEntry`, `MemberChange`, `ActivityLog`, `ActivityCategory`, `ActivityLogCategory`, `ActivityConfirmation`, `ChangeConfirmation`, `Staff`, `EmailTemplate`, `SendJob`, `SendLog`

- [ ] **Step 1: テストを書く**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_models.py -v
```
Expected: ImportError または AttributeError

- [ ] **Step 3: app/database/models.py を実装**

```python
# app/database/models.py
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date,
    Text, ForeignKey, Table,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# 中間テーブル（activity_log ↔ category）
activity_log_categories = Table(
    "activity_log_categories",
    Base.metadata,
    Column("activity_log_id", Integer, ForeignKey("activity_logs.id"), primary_key=True),
    Column("category_id", Integer, ForeignKey("activity_categories.id"), primary_key=True),
)


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    member_number = Column(String, unique=True, nullable=False)
    org_name = Column(String, nullable=False)
    org_kana = Column(String)
    dept_title = Column(String)
    rep_name = Column(String)
    rep_kana = Column(String)
    email = Column(String)
    tel_area = Column(String)
    tel = Column(String)
    fax_area = Column(String)
    fax = Column(String)
    postal_code = Column(String)
    address = Column(String)
    postal_code_mail = Column(String)
    address_mail = Column(String)
    addressee_mail = Column(String)
    label_tag = Column(String)
    employment_ins_no = Column(String)
    note = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    withdrawn_at = Column(Date)
    withdraw_reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    insurance_entries = relationship(
        "InsuranceEntry", back_populates="member", cascade="all, delete-orphan"
    )
    member_changes = relationship("MemberChange", back_populates="member")
    activity_logs = relationship("ActivityLog", back_populates="member")


class InsuranceEntry(Base):
    __tablename__ = "insurance_entries"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    ins_type = Column(String, nullable=False)
    branch_number = Column(String)
    ins_number = Column(String)
    is_tokubetsu = Column(Boolean, nullable=False, default=False)
    is_ikkatsu = Column(Boolean, nullable=False, default=False)

    member = relationship("Member", back_populates="insurance_entries")


class MemberChange(Base):
    __tablename__ = "member_changes"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    changed_at = Column(DateTime, nullable=False, default=datetime.now)
    changed_by = Column(String, nullable=False)
    change_reason = Column(Text, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON文字列

    member = relationship("Member", back_populates="member_changes")
    confirmations = relationship(
        "ChangeConfirmation", back_populates="member_change", cascade="all, delete-orphan"
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False, default=datetime.now)
    logged_by = Column(String, nullable=False)
    content = Column(Text, nullable=False)

    member = relationship("Member", back_populates="activity_logs")
    categories = relationship(
        "ActivityCategory", secondary=activity_log_categories, back_populates="activity_logs"
    )
    confirmations = relationship(
        "ActivityConfirmation", back_populates="activity_log", cascade="all, delete-orphan"
    )


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    activity_logs = relationship(
        "ActivityLog", secondary=activity_log_categories, back_populates="categories"
    )


class ActivityConfirmation(Base):
    __tablename__ = "activity_confirmations"
    id = Column(Integer, primary_key=True)
    activity_log_id = Column(Integer, ForeignKey("activity_logs.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=False, default=datetime.now)

    activity_log = relationship("ActivityLog", back_populates="confirmations")


class ChangeConfirmation(Base):
    __tablename__ = "change_confirmations"
    id = Column(Integer, primary_key=True)
    member_change_id = Column(Integer, ForeignKey("member_changes.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=False, default=datetime.now)

    member_change = relationship("MemberChange", back_populates="confirmations")


class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class SendJob(Base):
    __tablename__ = "send_jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    template_id = Column(Integer, ForeignKey("email_templates.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    status = Column(String, nullable=False, default="draft")
    total_count = Column(Integer)
    success_count = Column(Integer)
    error_count = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    sent_at = Column(DateTime)

    logs = relationship("SendLog", back_populates="job", cascade="all, delete-orphan")


class SendLog(Base):
    __tablename__ = "send_logs"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("send_jobs.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"))
    to_address = Column(String, nullable=False)
    subject = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    error_message = Column(Text)
    sent_at = Column(DateTime)

    job = relationship("SendJob", back_populates="logs")
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_models.py -v
```
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add app/database/models.py tests/test_models.py
git commit -m "feat: add all database models"
```

---

### Task 4: データベース接続・WALモード

**Files:**
- Create: `app/database/connection.py`
- Create: `tests/test_connection.py`

**Interfaces:**
- Consumes: `Base`（`app.database.models`）
- Produces: `get_engine(db_path: str) -> Engine`, `get_session(engine) -> Session`（コンテキストマネージャ）

- [ ] **Step 1: テストを書く**

```python
# tests/test_connection.py
import os, tempfile
from app.database.connection import get_engine, get_session
from app.database.models import Base, Staff

def test_wal_mode_enabled():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        engine = get_engine(path)
        with engine.connect() as conn:
            result = conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode")).scalar()
        assert result == "wal"
    finally:
        os.unlink(path)

def test_session_creates_tables():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        engine = get_engine(path)
        with get_session(engine) as session:
            s = Staff(name="山田")
            session.add(s)
        with get_session(engine) as session:
            assert session.query(Staff).count() == 1
    finally:
        os.unlink(path)
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_connection.py -v
```
Expected: ImportError

- [ ] **Step 3: app/database/connection.py を実装**

```python
# app/database/connection.py
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from app.database.models import Base


def get_engine(db_path: str):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    return engine


@contextmanager
def get_session(engine):
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_connection.py -v
```
Expected: 2 passed

- [ ] **Step 5: コミット**

```bash
git add app/database/connection.py tests/test_connection.py
git commit -m "feat: add database connection with WAL mode"
```

---

### Task 5: 設定ファイル管理（app_config.py）

**Files:**
- Create: `app/utils/app_config.py`
- Create: `tests/test_app_config.py`

**Interfaces:**
- Produces:
  - `AppConfig` クラス
  - `AppConfig.load(path: str) -> AppConfig`
  - `AppConfig.save(path: str) -> None`
  - `AppConfig.db_path: str`
  - `AppConfig.last_staff_name: str`
  - `AppConfig.m365_tenant_id: str`
  - `AppConfig.m365_client_id: str`
  - `AppConfig.m365_test_address: str`

- [ ] **Step 1: テストを書く**

```python
# tests/test_app_config.py
import json, os, tempfile
from app.utils.app_config import AppConfig

def test_load_defaults():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({}, f)
        path = f.name
    try:
        cfg = AppConfig.load(path)
        assert cfg.db_path == ""
        assert cfg.last_staff_name == ""
    finally:
        os.unlink(path)

def test_save_and_reload():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({}, f)
        path = f.name
    try:
        cfg = AppConfig.load(path)
        cfg.last_staff_name = "山田"
        cfg.db_path = r"\\nas\share\rouho.db"
        cfg.save(path)
        cfg2 = AppConfig.load(path)
        assert cfg2.last_staff_name == "山田"
        assert cfg2.db_path == r"\\nas\share\rouho.db"
    finally:
        os.unlink(path)

def test_load_missing_file_returns_defaults():
    cfg = AppConfig.load("/nonexistent/path.json")
    assert cfg.db_path == ""
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_app_config.py -v
```
Expected: ImportError

- [ ] **Step 3: app/utils/app_config.py を実装**

```python
# app/utils/app_config.py
import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class AppConfig:
    db_path: str = ""
    last_staff_name: str = ""
    m365_tenant_id: str = ""
    m365_client_id: str = ""
    m365_test_address: str = ""

    @classmethod
    def load(cls, path: str) -> "AppConfig":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: data.get(k, v) for k, v in asdict(cls()).items()})
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_app_config.py -v
```
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add app/utils/app_config.py tests/test_app_config.py
git commit -m "feat: add app config manager"
```

---

### Task 6: 職員ログインダイアログ

**Files:**
- Create: `app/ui/dialogs/staff_login_dialog.py`

**Interfaces:**
- Consumes: `Staff`（`app.database.models`）、`get_session`（`app.database.connection`）
- Produces: `StaffLoginDialog(engine, parent=None)` → `exec()` → `selected_name: str | None`（キャンセル時は None）

- [ ] **Step 1: app/ui/dialogs/staff_login_dialog.py を実装**

```python
# app/ui/dialogs/staff_login_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QMessageBox,
)
from app.database.connection import get_session
from app.database.models import Staff


class StaffLoginDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self.selected_name: str | None = None
        self.setWindowTitle("担当者を選択してください")
        self.setFixedSize(320, 140)
        self._build_ui()
        self._load_staff()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("担当者："))
        self._combo = QComboBox()
        layout.addWidget(self._combo)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _load_staff(self):
        with get_session(self._engine) as session:
            staff_list = (
                session.query(Staff)
                .filter_by(is_active=True)
                .order_by(Staff.id)
                .all()
            )
            for s in staff_list:
                self._combo.addItem(s.name)

    def _on_ok(self):
        name = self._combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "エラー", "担当者を選択してください。")
            return
        self.selected_name = name
        self.accept()
```

- [ ] **Step 2: コミット**

```bash
git add app/ui/dialogs/staff_login_dialog.py
git commit -m "feat: add staff login dialog"
```

---

### Task 7: メインウィンドウ（5タブスケルトン）

**Files:**
- Create: `app/ui/main_window.py`
- Create: `app/ui/member_tab.py`（プレースホルダー）
- Create: `app/ui/withdrawn_tab.py`（プレースホルダー）
- Create: `app/ui/label_tab.py`（プレースホルダー）
- Create: `app/ui/email_tab.py`（プレースホルダー）
- Create: `app/ui/settings_tab.py`（プレースホルダー）

**Interfaces:**
- Consumes: `AppConfig`、`StaffLoginDialog`、全タブクラス
- Produces: `MainWindow(config_path: str)`

- [ ] **Step 1: プレースホルダータブを作成**

各タブに同じ構造で作成（例: member_tab.py）：

```python
# app/ui/member_tab.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

class MemberTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).addWidget(QLabel("名簿タブ（実装予定）"))
```

withdrawn_tab.py / label_tab.py / email_tab.py / settings_tab.py も同様に作成（ラベルテキストのみ変更）。

- [ ] **Step 2: app/ui/main_window.py を実装**

```python
# app/ui/main_window.py
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.utils.app_config import AppConfig
from app.database.connection import get_engine
from app.ui.dialogs.staff_login_dialog import StaffLoginDialog
from app.ui.member_tab import MemberTab
from app.ui.withdrawn_tab import WithdrawnTab
from app.ui.label_tab import LabelTab
from app.ui.email_tab import EmailTab
from app.ui.settings_tab import SettingsTab
from app.version import __version__


class MainWindow(QMainWindow):
    def __init__(self, config_path: str):
        super().__init__()
        self._config_path = config_path
        self._config = AppConfig.load(config_path)
        self._engine = None
        self._current_staff = ""
        self.setWindowTitle(f"労働保険名簿管理システム v{__version__}")
        self.setMinimumSize(700, 500)
        self.resize(780, 720)
        self._init_db()
        self._ensure_login()
        self._build_ui()

    def _init_db(self):
        db_path = self._config.db_path or os.path.join(
            os.path.dirname(self._config_path), "rouho.db"
        )
        self._engine = get_engine(db_path)

    def _ensure_login(self):
        last = self._config.last_staff_name
        if last:
            self._current_staff = last
        else:
            self._show_login_dialog()

    def _show_login_dialog(self):
        dlg = StaffLoginDialog(self._engine, self)
        if dlg.exec() == StaffLoginDialog.DialogCode.Accepted and dlg.selected_name:
            self._current_staff = dlg.selected_name
            self._config.last_staff_name = self._current_staff
            self._config.save(self._config_path)
        else:
            # キャンセル時は終了
            raise SystemExit(0)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 上部ヘッダー（担当者表示 + ログアウトボタン）
        header = QWidget()
        header.setStyleSheet("background:#f0f4f8; border-bottom:1px solid #ddd;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addStretch()
        self._staff_label = QLabel(f"ログイン中：{self._current_staff}　さん")
        h_layout.addWidget(self._staff_label)
        logout_btn = QPushButton("ログアウト")
        logout_btn.setFixedWidth(90)
        logout_btn.clicked.connect(self._on_logout)
        h_layout.addWidget(logout_btn)
        root.addWidget(header)

        # タブウィジェット
        tabs = QTabWidget()
        tabs.addTab(MemberTab(self._engine, self._config), "名簿")
        tabs.addTab(WithdrawnTab(self._engine, self._config), "脱会済み")
        tabs.addTab(LabelTab(self._engine, self._config), "ラベル出力")
        tabs.addTab(EmailTab(self._engine, self._config), "メール送信")
        tabs.addTab(SettingsTab(self._engine, self._config), "設定")
        root.addWidget(tabs)

        self.statusBar().showMessage(f"v{__version__}")

    def _on_logout(self):
        self._config.last_staff_name = ""
        self._config.save(self._config_path)
        self._show_login_dialog()
        self._staff_label.setText(f"ログイン中：{self._current_staff}　さん")
```

- [ ] **Step 3: コミット**

```bash
git add app/ui/
git commit -m "feat: add main window with 5-tab skeleton and staff login"
```

---

### Task 8: エントリポイント（main.py）

**Files:**
- Create: `main.py`

**Interfaces:**
- Consumes: `MainWindow`

- [ ] **Step 1: main.py を実装**

```python
# main.py
import sys
import os
from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app_config.json")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("労働保険名簿管理システム")
    try:
        window = MainWindow(CONFIG_PATH)
        window.show()
        sys.exit(app.exec())
    except SystemExit as e:
        sys.exit(int(str(e)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: アプリを起動して確認**

```
python main.py
```
確認項目:
- 職員が0名の場合はログインダイアログが空で表示される（設定タブで職員追加後に再確認）
- 5タブが表示されること
- ウィンドウサイズが780×720以内であること
- 右上に「ログイン中：〇〇さん」とログアウトボタンが表示されること

- [ ] **Step 3: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 4: 最終コミット**

```bash
git add main.py
git commit -m "feat: add application entry point"
```
