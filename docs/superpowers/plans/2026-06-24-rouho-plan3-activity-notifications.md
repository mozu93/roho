# 労働保険名簿管理システム Plan 3: 対応履歴・新着通知

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 対応履歴（電話・相談ログ）のCRUD・カテゴリ管理・新着バナー（職員ごとの既読管理）を実装する

**Architecture:** `activity_service.py` がDB操作を担当。対応履歴保存時に他職員の `activity_confirmations` に未読レコードを作成。メインウィンドウ上部バナーが起動時に未読件数を表示し、ダブルクリックで該当事業所のダイアログへ遷移する。

**Tech Stack:** Python 3.11+, PyQt6, SQLAlchemy 2.x

## Global Constraints

- Plan 1・Plan 2 完了が前提
- 対応履歴は時系列（新しい順）で表示
- カテゴリは複数選択可
- 未読は「自分以外が書いた記録」かつ「自分がまだ確認していないもの」

---

### Task 1: ActivityService

**Files:**
- Create: `app/services/activity_service.py`
- Create: `tests/test_activity_service.py`

**Interfaces:**
- Produces:
  - `ActivityService(engine)`
  - `ActivityService.get_logs(member_id) -> list[ActivityLog]`（カテゴリ付き）
  - `ActivityService.add_log(member_id, content, category_ids, staff_name) -> ActivityLog`
  - `ActivityService.get_unread(staff_name) -> list[dict]`（activity_logs + member_changes の未読）
  - `ActivityService.confirm_activity(log_id, staff_name) -> None`
  - `ActivityService.confirm_change(change_id, staff_name) -> None`
  - `ActivityService.confirm_all(staff_name) -> None`
  - `ActivityService.get_categories() -> list[ActivityCategory]`
  - `ActivityService.add_category(name) -> ActivityCategory`
  - `ActivityService.delete_category(category_id) -> None`
  - `ActivityService.reorder_categories(ids: list[int]) -> None`

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_activity_service.py -v
```
Expected: ImportError

- [ ] **Step 3: app/services/activity_service.py を実装**

```python
# app/services/activity_service.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.connection import get_session
from app.database.models import (
    ActivityLog, ActivityCategory, ActivityConfirmation,
    MemberChange, ChangeConfirmation, Staff, Member,
)


class ActivityService:
    def __init__(self, engine):
        self._engine = engine

    def get_logs(self, member_id: int) -> list[ActivityLog]:
        with get_session(self._engine) as session:
            logs = (
                session.query(ActivityLog)
                .filter_by(member_id=member_id)
                .order_by(ActivityLog.logged_at.desc())
                .all()
            )
            for log in logs:
                _ = log.categories
            session.expunge_all()
            return logs

    def add_log(
        self,
        member_id: int,
        content: str,
        category_ids: list[int],
        staff_name: str,
    ) -> ActivityLog:
        with get_session(self._engine) as session:
            log = ActivityLog(
                member_id=member_id,
                logged_at=datetime.now(),
                logged_by=staff_name,
                content=content,
            )
            if category_ids:
                cats = session.query(ActivityCategory).filter(
                    ActivityCategory.id.in_(category_ids)
                ).all()
                log.categories = cats
            session.add(log)
            session.flush()

            # 他職員への未読通知
            other_staff = (
                session.query(Staff)
                .filter(Staff.is_active == True, Staff.name != staff_name)
                .all()
            )
            for s in other_staff:
                session.add(ActivityConfirmation(
                    activity_log_id=log.id,
                    staff_id=s.id,
                    confirmed_at=None,
                ))
            _ = log.categories
            session.expunge_all()
            return log

    def get_unread(self, staff_name: str) -> list[dict]:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name, is_active=True).first()
            if not staff:
                return []

            # 未読の activity_logs
            unread_logs = (
                session.query(ActivityConfirmation)
                .filter_by(staff_id=staff.id, confirmed_at=None)
                .all()
            )
            results = []
            for conf in unread_logs:
                log = session.get(ActivityLog, conf.activity_log_id)
                if not log:
                    continue
                member = session.get(Member, log.member_id)
                results.append({
                    "type": "activity",
                    "id": conf.id,
                    "event_id": log.id,
                    "member_id": log.member_id,
                    "org_name": member.org_name if member else "",
                    "logged_at": log.logged_at,
                    "logged_by": log.logged_by,
                    "content": log.content[:40],
                })

            # 未読の member_changes
            unread_changes = (
                session.query(ChangeConfirmation)
                .filter_by(staff_id=staff.id, confirmed_at=None)
                .all()
            )
            for conf in unread_changes:
                change = session.get(MemberChange, conf.member_change_id)
                if not change:
                    continue
                member = session.get(Member, change.member_id)
                results.append({
                    "type": "change",
                    "id": conf.id,
                    "event_id": change.id,
                    "member_id": change.member_id,
                    "org_name": member.org_name if member else "",
                    "logged_at": change.changed_at,
                    "logged_by": change.changed_by,
                    "content": change.change_reason[:40],
                })

            results.sort(key=lambda x: x["logged_at"], reverse=True)
            return results

    def confirm_activity(self, log_id: int, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            conf = (
                session.query(ActivityConfirmation)
                .filter_by(activity_log_id=log_id, staff_id=staff.id)
                .first()
            )
            if conf:
                conf.confirmed_at = datetime.now()

    def confirm_change(self, change_id: int, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            conf = (
                session.query(ChangeConfirmation)
                .filter_by(member_change_id=change_id, staff_id=staff.id)
                .first()
            )
            if conf:
                conf.confirmed_at = datetime.now()

    def confirm_all(self, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            now = datetime.now()
            for conf in session.query(ActivityConfirmation).filter_by(
                staff_id=staff.id, confirmed_at=None
            ).all():
                conf.confirmed_at = now
            for conf in session.query(ChangeConfirmation).filter_by(
                staff_id=staff.id, confirmed_at=None
            ).all():
                conf.confirmed_at = now

    def get_categories(self) -> list[ActivityCategory]:
        with get_session(self._engine) as session:
            cats = session.query(ActivityCategory).order_by(
                ActivityCategory.sort_order, ActivityCategory.id
            ).all()
            session.expunge_all()
            return cats

    def add_category(self, name: str) -> ActivityCategory:
        with get_session(self._engine) as session:
            max_order = session.query(ActivityCategory).count()
            cat = ActivityCategory(name=name, sort_order=max_order)
            session.add(cat)
            session.flush()
            session.expunge_all()
            return cat

    def delete_category(self, category_id: int) -> None:
        with get_session(self._engine) as session:
            cat = session.get(ActivityCategory, category_id)
            if cat:
                session.delete(cat)

    def reorder_categories(self, ids: list[int]) -> None:
        with get_session(self._engine) as session:
            for order, cat_id in enumerate(ids):
                cat = session.get(ActivityCategory, cat_id)
                if cat:
                    cat.sort_order = order
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_activity_service.py -v
```
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add app/services/activity_service.py tests/test_activity_service.py
git commit -m "feat: add activity service with unread notifications"
```

---

### Task 2: 対応履歴ダイアログ

**Files:**
- Create: `app/ui/dialogs/activity_log_dialog.py`

**Interfaces:**
- Consumes: `ActivityService`
- Produces: `ActivityLogDialog(engine, member_id, staff_name, parent=None)`

- [ ] **Step 1: app/ui/dialogs/activity_log_dialog.py を実装**

```python
# app/ui/dialogs/activity_log_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QTextEdit, QLabel, QPushButton, QGroupBox, QScrollArea,
    QWidget, QCheckBox, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from app.services.activity_service import ActivityService


class ActivityLogDialog(QDialog):
    def __init__(self, engine, member_id: int, staff_name: str, org_name: str = "", parent=None):
        super().__init__(parent)
        self._engine = engine
        self._member_id = member_id
        self._staff_name = staff_name
        self._svc = ActivityService(engine)
        self.setWindowTitle(f"対応履歴 - {org_name}")
        self.resize(560, 520)
        self._build_ui()
        self._load_logs()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 履歴表示エリア
        log_group = QGroupBox("対応履歴（新しい順）")
        log_layout = QVBoxLayout(log_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._log_container = QWidget()
        self._log_vbox = QVBoxLayout(self._log_container)
        self._log_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._log_container)
        log_layout.addWidget(scroll)
        layout.addWidget(log_group, stretch=2)

        # 新規入力エリア
        input_group = QGroupBox("新規対応メモを追加")
        input_layout = QVBoxLayout(input_group)

        # カテゴリ選択
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("カテゴリ："))
        self._cat_checks = []
        for cat in self._svc.get_categories():
            chk = QCheckBox(cat.name)
            chk.setProperty("cat_id", cat.id)
            self._cat_checks.append(chk)
            cat_row.addWidget(chk)
        cat_row.addStretch()
        input_layout.addLayout(cat_row)

        self._content_edit = QTextEdit()
        self._content_edit.setFixedHeight(80)
        self._content_edit.setPlaceholderText("対応内容を入力してください")
        input_layout.addWidget(self._content_edit)

        save_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        save_row.addStretch()
        save_row.addWidget(save_btn)
        input_layout.addLayout(save_row)
        layout.addWidget(input_group, stretch=1)

        close_row = QHBoxLayout()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        close_row.addStretch()
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _load_logs(self):
        # 既存ウィジェットを削除
        while self._log_vbox.count():
            item = self._log_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        logs = self._svc.get_logs(self._member_id)
        for log in logs:
            cat_names = "・".join(c.name for c in log.categories) if log.categories else "カテゴリなし"
            entry = QWidget()
            entry.setStyleSheet("border:1px solid #ddd; border-radius:4px; padding:4px; margin:2px;")
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(6, 4, 6, 4)
            header = QLabel(
                f"<b>{log.logged_at.strftime('%Y-%m-%d %H:%M')}</b>　{log.logged_by}　"
                f"<span style='color:#666'>[{cat_names}]</span>"
            )
            content = QLabel(log.content)
            content.setWordWrap(True)
            entry_layout.addWidget(header)
            entry_layout.addWidget(content)
            self._log_vbox.addWidget(entry)

        if not logs:
            self._log_vbox.addWidget(QLabel("対応履歴はありません。"))

    def _on_save(self):
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "入力エラー", "内容を入力してください。")
            return
        cat_ids = [
            chk.property("cat_id")
            for chk in self._cat_checks if chk.isChecked()
        ]
        try:
            self._svc.add_log(self._member_id, content, cat_ids, self._staff_name)
            self._content_edit.clear()
            for chk in self._cat_checks:
                chk.setChecked(False)
            self._load_logs()
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 2: member_tab.py の _on_activity を接続**

`app/ui/member_tab.py` の `_on_activity` メソッドを以下に更新：

```python
def _on_activity(self):
    m = self._selected_member()
    if not m:
        return
    from app.ui.dialogs.activity_log_dialog import ActivityLogDialog
    ActivityLogDialog(
        self._engine, m.id, self._config.last_staff_name, m.org_name, parent=self
    ).exec()
    self._refresh()  # 最終対応日更新のため
```

- [ ] **Step 3: コミット**

```bash
git add app/ui/dialogs/activity_log_dialog.py app/ui/member_tab.py
git commit -m "feat: add activity log dialog"
```

---

### Task 3: 新着バナー（メインウィンドウ上部）

**Files:**
- Create: `app/ui/notification_banner.py`
- Modify: `app/ui/main_window.py`

**Interfaces:**
- Consumes: `ActivityService`
- Produces: `NotificationBanner(engine, config, parent=None)` → シグナル `navigate_to_member(member_id: int, event_type: str, event_id: int)`

- [ ] **Step 1: app/ui/notification_banner.py を実装**

```python
# app/ui/notification_banner.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from app.services.activity_service import ActivityService


class NotificationBanner(QWidget):
    navigate_to_member = pyqtSignal(int, str, int)  # member_id, event_type, event_id

    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = ActivityService(engine)
        self._items = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.setStyleSheet(
            "NotificationBanner { background:#FEF9C3; border-bottom:2px solid #FDE047; }"
        )
        main = QVBoxLayout(self)
        main.setContentsMargins(6, 4, 6, 4)

        header_row = QHBoxLayout()
        self._title_label = QLabel("新着 0件")
        self._title_label.setStyleSheet("font-weight:bold;")
        header_row.addWidget(self._title_label)
        header_row.addStretch()
        confirm_all_btn = QPushButton("すべて既読にする")
        confirm_all_btn.setFixedHeight(24)
        confirm_all_btn.clicked.connect(self._on_confirm_all)
        header_row.addWidget(confirm_all_btn)
        main.addLayout(header_row)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        main.addWidget(self._list_widget)

    def refresh(self):
        staff_name = self._config.last_staff_name
        if not staff_name:
            self.hide()
            return

        self._items = self._svc.get_unread(staff_name)
        # リストをクリア
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._items:
            self.hide()
            return

        self.show()
        self._title_label.setText(f"新着 {len(self._items)}件")

        for item in self._items[:10]:  # 最大10件表示
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            dt_str = item["logged_at"].strftime("%m-%d %H:%M")
            event_icon = "📝" if item["type"] == "activity" else "✏️"
            text = (
                f"{dt_str}　{item['org_name']}　"
                f"{event_icon}{item['content']}（{item['logged_by']}）"
            )
            lbl = QLabel(text)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            member_id = item["member_id"]
            event_type = item["type"]
            event_id = item["event_id"]
            lbl.mouseDoubleClickEvent = lambda e, mid=member_id, et=event_type, eid=event_id: \
                self.navigate_to_member.emit(mid, et, eid)
            row_layout.addWidget(lbl)
            row_layout.addStretch()

            # 個別既読ボタン
            conf_btn = QPushButton("✓")
            conf_btn.setFixedSize(24, 20)
            conf_id = item["id"]
            conf_type = item["type"]
            conf_event_id = item["event_id"]
            conf_btn.clicked.connect(
                lambda _, t=conf_type, eid=conf_event_id: self._on_confirm_one(t, eid)
            )
            row_layout.addWidget(conf_btn)
            self._list_layout.addWidget(row)

    def _on_confirm_one(self, event_type: str, event_id: int):
        staff_name = self._config.last_staff_name
        if event_type == "activity":
            self._svc.confirm_activity(event_id, staff_name)
        else:
            self._svc.confirm_change(event_id, staff_name)
        self.refresh()

    def _on_confirm_all(self):
        self._svc.confirm_all(self._config.last_staff_name)
        self.refresh()
```

- [ ] **Step 2: main_window.py にバナーを追加**

`app/ui/main_window.py` の `_build_ui` メソッドを修正し、ヘッダーとタブウィジェットの間にバナーを挿入：

```python
# _build_ui 内のタブ追加前に以下を追加
from app.ui.notification_banner import NotificationBanner

self._banner = NotificationBanner(self._engine, self._config)
root.addWidget(self._banner)
```

また `_on_logout` の末尾にバナー更新を追加：

```python
self._banner.refresh()
```

- [ ] **Step 3: アプリ起動・バナー動作確認**

```
python main.py
```
確認項目：
- 職員Aでログイン → 対応メモを追加 → ログアウト → 職員Bでログイン → バナーに新着表示されること
- [✓] ボタンで個別既読になること
- [すべて既読にする] で全消えること

- [ ] **Step 4: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 5: コミット**

```bash
git add app/ui/notification_banner.py app/ui/main_window.py
git commit -m "feat: add notification banner with per-staff read tracking"
```

---

### Task 4: 設定タブ（職員・カテゴリ管理）

**Files:**
- Modify: `app/ui/settings_tab.py`

- [ ] **Step 1: app/ui/settings_tab.py を実装**

```python
# app/ui/settings_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QMessageBox,
)
from app.database.connection import get_session
from app.database.models import Staff
from app.services.activity_service import ActivityService


class SettingsTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = ActivityService(engine)
        self._build_ui()
        self._refresh_staff()
        self._refresh_categories()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 職員管理
        staff_group = QGroupBox("職員管理")
        staff_layout = QVBoxLayout(staff_group)
        self._staff_list = QListWidget()
        staff_layout.addWidget(self._staff_list)
        add_row = QHBoxLayout()
        self._staff_edit = QLineEdit()
        self._staff_edit.setPlaceholderText("職員名を入力")
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self._on_add_staff)
        toggle_btn = QPushButton("有効/無効切り替え")
        toggle_btn.clicked.connect(self._on_toggle_staff)
        add_row.addWidget(self._staff_edit)
        add_row.addWidget(add_btn)
        add_row.addWidget(toggle_btn)
        staff_layout.addLayout(add_row)
        layout.addWidget(staff_group)

        # カテゴリ管理
        cat_group = QGroupBox("対応カテゴリ管理")
        cat_layout = QVBoxLayout(cat_group)
        self._cat_list = QListWidget()
        cat_layout.addWidget(self._cat_list)
        cat_row = QHBoxLayout()
        self._cat_edit = QLineEdit()
        self._cat_edit.setPlaceholderText("カテゴリ名を入力")
        cat_add_btn = QPushButton("追加")
        cat_add_btn.clicked.connect(self._on_add_category)
        cat_del_btn = QPushButton("削除")
        cat_del_btn.clicked.connect(self._on_delete_category)
        cat_row.addWidget(self._cat_edit)
        cat_row.addWidget(cat_add_btn)
        cat_row.addWidget(cat_del_btn)
        cat_layout.addLayout(cat_row)
        layout.addWidget(cat_group)
        layout.addStretch()

    def _refresh_staff(self):
        self._staff_list.clear()
        with get_session(self._engine) as session:
            staff_list = session.query(Staff).order_by(Staff.id).all()
            for s in staff_list:
                status = "有効" if s.is_active else "無効"
                item = QListWidgetItem(f"{s.name}　[{status}]")
                item.setData(256, s.id)
                self._staff_list.addItem(item)

    def _on_add_staff(self):
        name = self._staff_edit.text().strip()
        if not name:
            return
        with get_session(self._engine) as session:
            session.add(Staff(name=name))
        self._staff_edit.clear()
        self._refresh_staff()

    def _on_toggle_staff(self):
        item = self._staff_list.currentItem()
        if not item:
            return
        staff_id = item.data(256)
        with get_session(self._engine) as session:
            s = session.get(Staff, staff_id)
            if s:
                s.is_active = not s.is_active
        self._refresh_staff()

    def _refresh_categories(self):
        self._cat_list.clear()
        for cat in self._svc.get_categories():
            item = QListWidgetItem(cat.name)
            item.setData(256, cat.id)
            self._cat_list.addItem(item)

    def _on_add_category(self):
        name = self._cat_edit.text().strip()
        if not name:
            return
        self._svc.add_category(name)
        self._cat_edit.clear()
        self._refresh_categories()

    def _on_delete_category(self):
        item = self._cat_list.currentItem()
        if not item:
            return
        reply = QMessageBox.question(
            self, "確認", f"「{item.text()}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._svc.delete_category(item.data(256))
            self._refresh_categories()
```

- [ ] **Step 2: コミット**

```bash
git add app/ui/settings_tab.py
git commit -m "feat: implement settings tab with staff and category management"
```
