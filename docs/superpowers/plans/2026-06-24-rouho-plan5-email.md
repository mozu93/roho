# 労働保険名簿管理システム Plan 5: メール送信

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Microsoft Graph API（委任認証）を使ったメール一斉送信機能を実装する。テンプレート管理・差し込み・添付ファイル・送信履歴を含む。

**Architecture:** `email_service.py` がMSALトークン管理とGraph API呼び出しを担当。`template_service.py` がテンプレートCRUD。`send_job_service.py` が送信ジョブとログを管理。メール送信タブはステップ形式で宛先→テンプレート→添付→送信確認の流れ。

**Tech Stack:** Python 3.11+, PyQt6, SQLAlchemy 2.x, msal, requests

## Global Constraints

- Plan 1 完了が前提（models.py に EmailTemplate / SendJob / SendLog が定義済み）
- 認証: MSALデバイスコードフロー（委任アクセス許可、クライアントシークレット不要）
- 差し込みプレースホルダー: `{事業所名}` `{代表者名}` `{会員No.}` `{所属・役職}`
- メールアドレスがない会員は自動スキップ
- テスト送信先は `app_config.json` の `m365_test_address`

---

### Task 1: TemplateService

**Files:**
- Create: `app/services/template_service.py`
- Create: `tests/test_template_service.py`

**Interfaces:**
- Produces:
  - `TemplateService(engine)`
  - `TemplateService.get_all() -> list[EmailTemplate]`
  - `TemplateService.get(template_id) -> EmailTemplate`
  - `TemplateService.create(name, subject, body) -> EmailTemplate`
  - `TemplateService.update(template_id, name, subject, body) -> EmailTemplate`
  - `TemplateService.delete(template_id) -> None`
  - `TemplateService.render(template, member) -> tuple[str, str]`（件名, 本文）

- [ ] **Step 1: テストを書く**

```python
# tests/test_template_service.py
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
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_template_service.py -v
```
Expected: ImportError

- [ ] **Step 3: app/services/template_service.py を実装**

```python
# app/services/template_service.py
from datetime import datetime
from app.database.connection import get_session
from app.database.models import EmailTemplate, Member


class TemplateService:
    def __init__(self, engine):
        self._engine = engine

    def get_all(self) -> list[EmailTemplate]:
        with get_session(self._engine) as session:
            templates = session.query(EmailTemplate).order_by(EmailTemplate.name).all()
            session.expunge_all()
            return templates

    def get(self, template_id: int) -> EmailTemplate | None:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            if t:
                session.expunge_all()
            return t

    def create(self, name: str, subject: str, body: str) -> EmailTemplate:
        with get_session(self._engine) as session:
            now = datetime.now()
            t = EmailTemplate(name=name, subject=subject, body=body,
                              created_at=now, updated_at=now)
            session.add(t)
            session.flush()
            session.expunge_all()
            return t

    def update(self, template_id: int, name: str, subject: str, body: str) -> EmailTemplate:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            t.name = name
            t.subject = subject
            t.body = body
            t.updated_at = datetime.now()
            session.flush()
            session.expunge_all()
            return t

    def delete(self, template_id: int) -> None:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            if t:
                session.delete(t)

    def render(self, template: EmailTemplate, member: Member) -> tuple[str, str]:
        replacements = {
            "{事業所名}": member.org_name or "",
            "{代表者名}": member.rep_name or "",
            "{会員No.}": member.member_number or "",
            "{所属・役職}": member.dept_title or "",
        }
        subject = template.subject
        body = template.body
        for placeholder, value in replacements.items():
            subject = subject.replace(placeholder, value)
            body = body.replace(placeholder, value)
        return subject, body
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_template_service.py -v
```
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add app/services/template_service.py tests/test_template_service.py
git commit -m "feat: add email template service with placeholder rendering"
```

---

### Task 2: EmailService（Graph API・MSAL認証）

**Files:**
- Create: `app/services/email_service.py`

**Interfaces:**
- Produces:
  - `EmailService(config: AppConfig)`
  - `EmailService.get_token() -> str`（デバイスコードフロー、キャッシュあり）
  - `EmailService.send(to_address, subject, body, attachments) -> None`（失敗時は例外）
  - `EmailService.is_authenticated() -> bool`

- [ ] **Step 1: app/services/email_service.py を実装**

```python
# app/services/email_service.py
import base64
import json
import os
import requests
import msal


GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
SCOPES = ["Mail.Send"]
TOKEN_CACHE_FILE = os.path.join(os.path.expanduser("~"), ".rouho_token_cache.bin")


class EmailService:
    def __init__(self, config):
        self._config = config
        self._cache = msal.SerializableTokenCache()
        if os.path.exists(TOKEN_CACHE_FILE):
            with open(TOKEN_CACHE_FILE, "rb") as f:
                self._cache.deserialize(f.read())
        self._app = None

    def _get_app(self) -> msal.PublicClientApplication:
        if not self._app:
            self._app = msal.PublicClientApplication(
                self._config.m365_client_id,
                authority=f"https://login.microsoftonline.com/{self._config.m365_tenant_id}",
                token_cache=self._cache,
            )
        return self._app

    def _save_cache(self):
        if self._cache.has_state_changed:
            with open(TOKEN_CACHE_FILE, "wb") as f:
                f.write(self._cache.serialize())

    def get_token(self) -> str:
        app = self._get_app()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]

        # デバイスコードフロー
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"デバイスコードの取得に失敗しました: {flow.get('error_description')}")

        # ユーザーへの案内（呼び出し元がダイアログ表示を担当）
        raise DeviceCodeRequired(flow["message"], flow)

    def acquire_token_with_device_flow(self, flow: dict) -> str:
        app = self._get_app()
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"認証エラー: {result.get('error_description', '不明なエラー')}")
        self._save_cache()
        return result["access_token"]

    def is_authenticated(self) -> bool:
        app = self._get_app()
        return bool(app.get_accounts())

    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        attachments: list[dict] | None = None,
        token: str | None = None,
    ) -> None:
        if token is None:
            app = self._get_app()
            accounts = app.get_accounts()
            if not accounts:
                raise RuntimeError("未認証です。先にサインインしてください。")
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if not result or "access_token" not in result:
                raise RuntimeError("トークンの取得に失敗しました。再サインインしてください。")
            token = result["access_token"]

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to_address}}],
            },
            "saveToSentItems": "true",
        }

        if attachments:
            message["message"]["attachments"] = []
            for att in attachments:
                with open(att["path"], "rb") as f:
                    content = base64.b64encode(f.read()).decode("utf-8")
                message["message"]["attachments"].append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": content,
                })

        resp = requests.post(
            GRAPH_SEND_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=message,
            timeout=30,
        )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"送信エラー ({resp.status_code}): {resp.text[:200]}")


class DeviceCodeRequired(Exception):
    """デバイスコードフロー開始が必要な場合に発生"""
    def __init__(self, message: str, flow: dict):
        super().__init__(message)
        self.flow = flow
```

- [ ] **Step 2: コミット**

```bash
git add app/services/email_service.py
git commit -m "feat: add email service with MSAL device code flow"
```

---

### Task 3: SendJobService

**Files:**
- Create: `app/services/send_job_service.py`

**Interfaces:**
- Produces:
  - `SendJobService(engine)`
  - `SendJobService.create_job(name, template_id, staff_name) -> SendJob`
  - `SendJobService.execute_job(job_id, targets, email_svc, template_svc, attachments) -> dict`
  - `SendJobService.get_jobs() -> list[SendJob]`
  - `SendJobService.get_logs(job_id) -> list[SendLog]`

- [ ] **Step 1: app/services/send_job_service.py を実装**

```python
# app/services/send_job_service.py
from datetime import datetime
from app.database.connection import get_session
from app.database.models import SendJob, SendLog, Staff


class SendJobService:
    def __init__(self, engine):
        self._engine = engine

    def create_job(self, name: str, template_id: int, staff_name: str) -> SendJob:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            job = SendJob(
                name=name,
                template_id=template_id,
                staff_id=staff.id if staff else None,
                status="draft",
                created_at=datetime.now(),
            )
            session.add(job)
            session.flush()
            session.expunge_all()
            return job

    def execute_job(
        self,
        job_id: int,
        targets: list,  # list of Member
        email_svc,
        template_svc,
        attachments: list[dict] | None = None,
        progress_callback=None,
    ) -> dict:
        """
        targets: メールアドレスがある Member のリスト
        attachments: [{"path": str, "name": str}] の共通添付ファイルリスト
        progress_callback: fn(current, total) → UIのプログレスバー更新用
        """
        with get_session(self._engine) as session:
            job = session.get(SendJob, job_id)
            job.status = "sending"
            job.total_count = len(targets)
            job.success_count = 0
            job.error_count = 0

        results = {"success": 0, "error": 0, "skip": 0}

        # トークンを一度だけ取得
        from app.services.email_service import DeviceCodeRequired
        app_obj = email_svc._get_app()
        accounts = app_obj.get_accounts()
        if not accounts:
            raise RuntimeError("未認証です。先にサインインしてください。")
        token_result = app_obj.acquire_token_silent(
            ["Mail.Send"], account=accounts[0]
        )
        if not token_result or "access_token" not in token_result:
            raise RuntimeError("トークン取得失敗。再サインインしてください。")
        token = token_result["access_token"]

        with get_session(self._engine) as session:
            template = session.get(
                __import__("app.database.models", fromlist=["EmailTemplate"]).EmailTemplate,
                session.get(SendJob, job_id).template_id,
            )

        for idx, member in enumerate(targets):
            if progress_callback:
                progress_callback(idx + 1, len(targets))

            if not member.email:
                results["skip"] += 1
                self._log(job_id, member.id, "", "", "skip", "メールアドレスなし")
                continue

            try:
                subject, body = template_svc.render(template, member)
                email_svc.send(
                    to_address=member.email,
                    subject=subject,
                    body=body,
                    attachments=attachments,
                    token=token,
                )
                results["success"] += 1
                self._log(job_id, member.id, member.email, subject, "success", None)
            except Exception as e:
                results["error"] += 1
                self._log(job_id, member.id, member.email, "", "error", str(e)[:500])

        with get_session(self._engine) as session:
            job = session.get(SendJob, job_id)
            job.status = "done" if results["error"] == 0 else "error"
            job.success_count = results["success"]
            job.error_count = results["error"]
            job.sent_at = datetime.now()

        return results

    def _log(self, job_id, member_id, to_address, subject, status, error_msg):
        with get_session(self._engine) as session:
            session.add(SendLog(
                job_id=job_id,
                member_id=member_id,
                to_address=to_address,
                subject=subject,
                status=status,
                error_message=error_msg,
                sent_at=datetime.now() if status == "success" else None,
            ))

    def get_jobs(self) -> list[SendJob]:
        with get_session(self._engine) as session:
            jobs = (
                session.query(SendJob)
                .order_by(SendJob.created_at.desc())
                .all()
            )
            session.expunge_all()
            return jobs

    def get_logs(self, job_id: int) -> list[SendLog]:
        with get_session(self._engine) as session:
            logs = (
                session.query(SendLog)
                .filter_by(job_id=job_id)
                .all()
            )
            session.expunge_all()
            return logs
```

- [ ] **Step 2: コミット**

```bash
git add app/services/send_job_service.py
git commit -m "feat: add send job service"
```

---

### Task 4: メール送信タブ（ステップ形式）

**Files:**
- Modify: `app/ui/email_tab.py`
- Create: `app/ui/dialogs/template_edit_dialog.py`

**Interfaces:**
- Consumes: `EmailService`, `TemplateService`, `SendJobService`, `MemberService`

- [ ] **Step 1: template_edit_dialog.py を実装**

```python
# app/ui/dialogs/template_edit_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QTextEdit, QPushButton, QLabel, QMessageBox,
)
from app.services.template_service import TemplateService


class TemplateEditDialog(QDialog):
    def __init__(self, engine, template_id: int | None = None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._template_id = template_id
        self._svc = TemplateService(engine)
        self.saved = False
        self.setWindowTitle("テンプレート編集" if template_id else "テンプレート追加")
        self.resize(600, 480)
        self._build_ui()
        if template_id:
            self._load(template_id)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("テンプレート")
        fl = QFormLayout(grp)
        self._name_edit = QLineEdit()
        self._subject_edit = QLineEdit()
        self._body_edit = QTextEdit()
        fl.addRow("テンプレート名：", self._name_edit)
        fl.addRow("件名：", self._subject_edit)
        fl.addRow("本文：", self._body_edit)
        layout.addWidget(grp)

        hint = QLabel(
            "使用できるプレースホルダー：{事業所名} {代表者名} {会員No.} {所属・役職}"
        )
        hint.setStyleSheet("color:#666; font-size:11px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _load(self, template_id: int):
        t = self._svc.get(template_id)
        if t:
            self._name_edit.setText(t.name)
            self._subject_edit.setText(t.subject)
            self._body_edit.setPlainText(t.body)

    def _on_save(self):
        name = self._name_edit.text().strip()
        subject = self._subject_edit.text().strip()
        body = self._body_edit.toPlainText().strip()
        if not name or not subject or not body:
            QMessageBox.warning(self, "入力エラー", "テンプレート名・件名・本文は必須です。")
            return
        try:
            if self._template_id:
                self._svc.update(self._template_id, name, subject, body)
            else:
                self._svc.create(name, subject, body)
            self.saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

- [ ] **Step 2: app/ui/email_tab.py を実装**

```python
# app/ui/email_tab.py
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QPushButton, QComboBox,
    QTextEdit, QFileDialog, QMessageBox, QProgressBar, QSplitter,
    QHeaderView, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from app.services.member_service import MemberService, INS_TYPES
from app.services.template_service import TemplateService
from app.services.send_job_service import SendJobService
from app.services.email_service import EmailService, DeviceCodeRequired
from app.ui.dialogs.template_edit_dialog import TemplateEditDialog

BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}


class SendWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, job_svc, job_id, targets, email_svc, template_svc, attachments):
        super().__init__()
        self._job_svc = job_svc
        self._job_id = job_id
        self._targets = targets
        self._email_svc = email_svc
        self._template_svc = template_svc
        self._attachments = attachments

    def run(self):
        try:
            result = self._job_svc.execute_job(
                self._job_id, self._targets, self._email_svc,
                self._template_svc, self._attachments,
                progress_callback=lambda c, t: self.progress.emit(c, t),
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class EmailTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._member_svc = MemberService(engine)
        self._template_svc = TemplateService(engine)
        self._job_svc = SendJobService(engine)
        self._email_svc = EmailService(config)
        self._selected_members = []
        self._selected_template = None
        self._attachments = []
        self._build_ui()
        self._refresh_history()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上部：送信フォーム
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)

        # Step 1: 宛先選択
        step1 = QGroupBox("Step 1：宛先選択")
        s1_layout = QVBoxLayout(step1)
        kw_row = QHBoxLayout()
        self._kw_edit = QLineEdit()
        self._kw_edit.setPlaceholderText("事業所名・フリガナで検索")
        self._kw_edit.textChanged.connect(self._refresh_member_list)
        kw_row.addWidget(self._kw_edit)
        s1_layout.addLayout(kw_row)

        quick_row = QHBoxLayout()
        all_btn = QPushButton("全アクティブ会員を選択")
        all_btn.clicked.connect(self._on_select_all)
        tok_btn = QPushButton("特別加入のみ選択")
        tok_btn.clicked.connect(self._on_select_tokubetsu)
        quick_row.addWidget(all_btn)
        quick_row.addWidget(tok_btn)
        quick_row.addStretch()
        s1_layout.addLayout(quick_row)

        self._member_table = QTableWidget(0, 4)
        self._member_table.setHorizontalHeaderLabels(["選択", "会員No.", "事業所名", "メール"])
        self._member_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._member_table.setMaximumHeight(180)
        s1_layout.addWidget(self._member_table)
        self._selected_count_label = QLabel("選択中 0件（メール無し 0件はスキップ）")
        s1_layout.addWidget(self._selected_count_label)
        form_layout.addWidget(step1)

        # Step 2: テンプレート選択
        step2 = QGroupBox("Step 2：テンプレート選択")
        s2_layout = QHBoxLayout(step2)
        self._template_combo = QComboBox()
        self._template_combo.currentIndexChanged.connect(self._on_template_selected)
        s2_layout.addWidget(self._template_combo)
        add_tmpl_btn = QPushButton("新規")
        add_tmpl_btn.clicked.connect(lambda: self._on_edit_template(None))
        edit_tmpl_btn = QPushButton("編集")
        edit_tmpl_btn.clicked.connect(lambda: self._on_edit_template(
            self._template_combo.currentData()
        ))
        s2_layout.addWidget(add_tmpl_btn)
        s2_layout.addWidget(edit_tmpl_btn)
        form_layout.addWidget(step2)

        # Step 3: 添付ファイル
        step3 = QGroupBox("Step 3：添付ファイル（任意）")
        s3_layout = QHBoxLayout(step3)
        self._attach_label = QLabel("なし")
        add_att_btn = QPushButton("ファイル追加")
        add_att_btn.clicked.connect(self._on_add_attachment)
        clear_att_btn = QPushButton("クリア")
        clear_att_btn.clicked.connect(self._on_clear_attachment)
        s3_layout.addWidget(self._attach_label)
        s3_layout.addStretch()
        s3_layout.addWidget(add_att_btn)
        s3_layout.addWidget(clear_att_btn)
        form_layout.addWidget(step3)

        # Step 4: 送信
        step4 = QGroupBox("Step 4：送信")
        s4_layout = QVBoxLayout(step4)
        job_row = QHBoxLayout()
        job_row.addWidget(QLabel("ジョブ名："))
        self._job_name_edit = QLineEdit()
        self._job_name_edit.setPlaceholderText("例：2026年7月 特別加入者へのご案内")
        job_row.addWidget(self._job_name_edit)
        s4_layout.addLayout(job_row)

        btn_row = QHBoxLayout()
        auth_btn = QPushButton("Microsoft 365 サインイン")
        auth_btn.clicked.connect(self._on_auth)
        test_btn = QPushButton("テスト送信")
        test_btn.clicked.connect(self._on_test_send)
        send_btn = QPushButton("送信実行")
        send_btn.setStyleSheet("background:#2563eb; color:white; font-weight:bold;")
        send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(auth_btn)
        btn_row.addStretch()
        btn_row.addWidget(test_btn)
        btn_row.addWidget(send_btn)
        s4_layout.addLayout(btn_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.hide()
        s4_layout.addWidget(self._progress_bar)
        form_layout.addWidget(step4)
        splitter.addWidget(form_widget)

        # 下部：送信履歴
        history_widget = QWidget()
        h_layout = QVBoxLayout(history_widget)
        h_layout.addWidget(QLabel("送信履歴"))
        self._history_table = QTableWidget(0, 5)
        self._history_table.setHorizontalHeaderLabels(
            ["送信日", "操作者", "ジョブ名", "成功", "エラー"]
        )
        self._history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._history_table.setMaximumHeight(150)
        h_layout.addWidget(self._history_table)
        splitter.addWidget(history_widget)

        layout.addWidget(splitter)
        self._refresh_member_list()
        self._refresh_template_list()

    def _refresh_member_list(self):
        members = self._member_svc.search(
            keyword=self._kw_edit.text(), active_only=True
        )
        self._member_table.setRowCount(len(members))
        for row, m in enumerate(members):
            chk = QCheckBox()
            chk.stateChanged.connect(self._update_selected_count)
            self._member_table.setCellWidget(row, 0, chk)
            self._member_table.setItem(row, 1, QTableWidgetItem(m.member_number))
            self._member_table.setItem(row, 2, QTableWidgetItem(m.org_name))
            self._member_table.setItem(row, 3, QTableWidgetItem(m.email or "（なし）"))
        self._all_members = members
        self._update_selected_count()

    def _update_selected_count(self):
        checked = [
            self._all_members[r]
            for r in range(self._member_table.rowCount())
            if (w := self._member_table.cellWidget(r, 0)) and w.isChecked()
        ]
        no_email = sum(1 for m in checked if not m.email)
        self._selected_count_label.setText(
            f"選択中 {len(checked)}件（メール無し {no_email}件はスキップ）"
        )
        self._selected_members = checked

    def _on_select_all(self):
        for row in range(self._member_table.rowCount()):
            if w := self._member_table.cellWidget(row, 0):
                w.setChecked(True)

    def _on_select_tokubetsu(self):
        members = self._member_svc.search(tokubetsu_only=True, active_only=True)
        tok_ids = {m.id for m in members}
        for row, m in enumerate(self._all_members):
            if w := self._member_table.cellWidget(row, 0):
                w.setChecked(m.id in tok_ids)

    def _refresh_template_list(self):
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        self._template_combo.addItem("（テンプレートを選択）", None)
        for t in self._template_svc.get_all():
            self._template_combo.addItem(t.name, t.id)
        self._template_combo.blockSignals(False)

    def _on_template_selected(self):
        template_id = self._template_combo.currentData()
        if template_id:
            self._selected_template = self._template_svc.get(template_id)

    def _on_edit_template(self, template_id):
        dlg = TemplateEditDialog(self._engine, template_id, parent=self)
        if dlg.exec() == TemplateEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh_template_list()

    def _on_add_attachment(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添付ファイルを選択")
        if paths:
            for path in paths:
                self._attachments.append({"path": path, "name": os.path.basename(path)})
            names = ", ".join(a["name"] for a in self._attachments)
            self._attach_label.setText(names[:80])

    def _on_clear_attachment(self):
        self._attachments.clear()
        self._attach_label.setText("なし")

    def _on_auth(self):
        try:
            self._email_svc.get_token()
        except DeviceCodeRequired as e:
            # デバイスコードフローのメッセージを表示
            QMessageBox.information(self, "Microsoft サインイン", str(e))
            try:
                self._email_svc.acquire_token_with_device_flow(e.flow)
                QMessageBox.information(self, "完了", "サインインが完了しました。")
            except Exception as ex:
                QMessageBox.critical(self, "認証エラー", str(ex))
        except Exception as ex:
            QMessageBox.critical(self, "エラー", str(ex))

    def _on_test_send(self):
        if not self._selected_template:
            QMessageBox.warning(self, "エラー", "テンプレートを選択してください。")
            return
        test_addr = self._config.m365_test_address
        if not test_addr:
            QMessageBox.warning(self, "エラー", "設定タブでテスト送信先アドレスを登録してください。")
            return
        try:
            subject = self._selected_template.subject + "【テスト送信】"
            body = self._selected_template.body
            self._email_svc.send(test_addr, subject, body, self._attachments)
            QMessageBox.information(self, "完了", f"テスト送信しました。\n宛先: {test_addr}")
        except Exception as e:
            QMessageBox.critical(self, "送信エラー", str(e))

    def _on_send(self):
        if not self._selected_members:
            QMessageBox.warning(self, "エラー", "宛先を選択してください。")
            return
        if not self._selected_template:
            QMessageBox.warning(self, "エラー", "テンプレートを選択してください。")
            return
        job_name = self._job_name_edit.text().strip()
        if not job_name:
            QMessageBox.warning(self, "エラー", "ジョブ名を入力してください。")
            return
        reply = QMessageBox.question(
            self, "確認",
            f"{len(self._selected_members)}件にメールを送信します。よいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        job = self._job_svc.create_job(
            job_name, self._selected_template.id, self._config.last_staff_name
        )
        self._progress_bar.show()
        self._progress_bar.setRange(0, len(self._selected_members))

        self._worker = SendWorker(
            self._job_svc, job.id, self._selected_members,
            self._email_svc, self._template_svc, self._attachments,
        )
        self._worker.progress.connect(lambda c, t: self._progress_bar.setValue(c))
        self._worker.finished.connect(self._on_send_finished)
        self._worker.error.connect(lambda msg: QMessageBox.critical(self, "送信エラー", msg))
        self._worker.start()

    def _on_send_finished(self, result: dict):
        self._progress_bar.hide()
        QMessageBox.information(
            self, "送信完了",
            f"成功：{result['success']}件\nエラー：{result['error']}件\nスキップ：{result['skip']}件"
        )
        self._refresh_history()

    def _refresh_history(self):
        jobs = self._job_svc.get_jobs()
        self._history_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._history_table.setItem(row, 0, QTableWidgetItem(
                job.sent_at.strftime("%Y-%m-%d %H:%M") if job.sent_at else job.created_at.strftime("%Y-%m-%d")
            ))
            self._history_table.setItem(row, 1, QTableWidgetItem(""))
            self._history_table.setItem(row, 2, QTableWidgetItem(job.name))
            self._history_table.setItem(row, 3, QTableWidgetItem(str(job.success_count or 0)))
            self._history_table.setItem(row, 4, QTableWidgetItem(str(job.error_count or 0)))
```

- [ ] **Step 3: 設定タブにM365設定を追加**

`app/ui/settings_tab.py` の `_build_ui` 末尾に以下を追加：

```python
# M365設定
m365_group = QGroupBox("Microsoft 365設定")
m365_layout = QFormLayout(m365_group)
self._tenant_edit = QLineEdit(self._config.m365_tenant_id)
self._client_id_edit = QLineEdit(self._config.m365_client_id)
self._test_addr_edit = QLineEdit(self._config.m365_test_address)
save_m365_btn = QPushButton("保存")
save_m365_btn.clicked.connect(self._on_save_m365)
m365_layout.addRow("テナントID：", self._tenant_edit)
m365_layout.addRow("クライアントID：", self._client_id_edit)
m365_layout.addRow("テスト送信先：", self._test_addr_edit)
m365_layout.addRow("", save_m365_btn)
layout.addWidget(m365_group)
```

`_on_save_m365` メソッドを追加：

```python
def _on_save_m365(self):
    import os
    self._config.m365_tenant_id = self._tenant_edit.text().strip()
    self._config.m365_client_id = self._client_id_edit.text().strip()
    self._config.m365_test_address = self._test_addr_edit.text().strip()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app_config.json")
    self._config.save(os.path.normpath(config_path))
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.information(self, "保存", "Microsoft 365設定を保存しました。")
```

- [ ] **Step 4: 動作確認**

```
python main.py
```
確認項目：
- メール送信タブで会員選択 → テンプレート選択 → [Microsoft 365 サインイン] でブラウザが開くこと
- テスト送信ボタンで設定のアドレスにメールが届くこと

- [ ] **Step 5: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 6: コミット**

```bash
git add app/services/template_service.py app/services/email_service.py app/services/send_job_service.py app/ui/email_tab.py app/ui/dialogs/template_edit_dialog.py app/ui/settings_tab.py tests/test_template_service.py
git commit -m "feat: implement email sending tab with Graph API and template management"
```
