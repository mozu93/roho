import os
import webbrowser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QComboBox,
    QFileDialog, QMessageBox, QCheckBox, QWidget, QFormLayout,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from app.database.connection import get_session
from app.database.models import Staff
from app.services.template_service import TemplateService
from app.services.email_service import EmailService, DeviceCodeRequired


_PLACEHOLDERS = ["{事業所名}", "{所属・役職}", "{代表者名}", "{会員No.}"]


class _SendWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)

    def __init__(self, email_svc, token, messages: list, attachments: list):
        super().__init__()
        self._email_svc = email_svc
        self._token = token
        self._messages = messages
        self._attachments = attachments

    def run(self):
        errors = []
        total = len(self._messages)
        for i, (m, subj, body) in enumerate(self._messages, 1):
            try:
                self._email_svc.send(
                    m.email, subj, body,
                    self._attachments or None,
                    self._token,
                )
            except Exception as e:
                errors.append(f"{m.org_name}：{e}")
            self.progress.emit(i, total)
        self.finished.emit(errors)


class _AuthWorker(QThread):
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, email_svc, flow):
        super().__init__()
        self._email_svc = email_svc
        self._flow = flow

    def run(self):
        try:
            self._email_svc.acquire_token_with_device_flow(self._flow)
            self.succeeded.emit()
        except Exception as e:
            self.failed.emit(str(e))


class ComposeEmailDialog(QDialog):
    def __init__(self, engine, config, members: list, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._members = members
        self._attachments: list[dict] = []
        self._svc = TemplateService(engine)
        self.setWindowTitle(f"メール作成　（{len(members)}件）")
        self.resize(860, 560)
        self._build_ui()
        self._refresh_templates()
        self._load_signature_preview()

    # ── UI 構築 ──

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ── 左右2カラム ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 左ペイン：送信先テーブル ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        lv.setSpacing(4)
        lv.addWidget(QLabel(f"送信先　{len(self._members)}件："))

        self._chk_widgets: list[QCheckBox] = []
        self._recv_table = QTableWidget(len(self._members), 3)
        self._recv_table.setHorizontalHeaderLabels(["", "事業所名", "メールアドレス"])
        self._recv_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._recv_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._recv_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._recv_table.setColumnWidth(0, 30)
        self._recv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._recv_table.setAlternatingRowColors(True)
        from PyQt6.QtGui import QColor
        for r, m in enumerate(self._members):
            chk = QCheckBox()
            chk.setChecked(bool(m.email))
            chk.setEnabled(bool(m.email))
            self._chk_widgets.append(chk)
            container = QWidget()
            hb = QHBoxLayout(container)
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hb.addWidget(chk)
            self._recv_table.setCellWidget(r, 0, container)
            self._recv_table.setItem(r, 1, QTableWidgetItem(m.org_name))
            addr_item = QTableWidgetItem(m.email or "メールなし")
            if not m.email:
                addr_item.setForeground(QColor(150, 150, 150))
            self._recv_table.setItem(r, 2, addr_item)
        lv.addWidget(self._recv_table)

        # 全選択/解除
        sel_row = QHBoxLayout()
        all_btn = QPushButton("全選択")
        all_btn.clicked.connect(lambda: self._set_all_checked(True))
        none_btn = QPushButton("全解除")
        none_btn.clicked.connect(lambda: self._set_all_checked(False))
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        lv.addLayout(sel_row)

        splitter.addWidget(left)

        # ── 右ペイン：メール入力 ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(6)

        # テンプレート選択
        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("テンプレート："))
        self._template_combo = QComboBox()
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        tmpl_row.addWidget(self._template_combo, stretch=1)
        clear_btn = QPushButton("クリア")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._on_clear_body)
        tmpl_row.addWidget(clear_btn)
        rv.addLayout(tmpl_row)

        # 件名
        subj_row = QHBoxLayout()
        subj_row.addWidget(QLabel("件名："))
        self._subject_edit = QLineEdit()
        subj_row.addWidget(self._subject_edit)
        rv.addLayout(subj_row)

        # 本文 + プレースホルダー挿入ボタン
        body_label_row = QHBoxLayout()
        body_label_row.addWidget(QLabel("本文："))
        body_label_row.addStretch()
        body_label_row.addWidget(QLabel("挿入："))
        for ph in _PLACEHOLDERS:
            btn = QPushButton(ph)
            btn.setFixedHeight(22)
            btn.setStyleSheet("font-size:9pt; padding:0 4px;")
            btn.clicked.connect(lambda _, p=ph: self._insert_placeholder(p))
            body_label_row.addWidget(btn)
        rv.addLayout(body_label_row)

        self._body_edit = QTextEdit()
        rv.addWidget(self._body_edit, stretch=1)

        # 署名プレビュー
        self._sig_label = QLabel("署名：（設定タブで登録）")
        self._sig_label.setStyleSheet(
            "color:#374151; font-size:9pt; background:#F9FAFB;"
            "border:1px solid #E5E7EB; padding:4px; border-radius:4px;")
        self._sig_label.setWordWrap(True)
        self._sig_label.setMaximumHeight(50)
        rv.addWidget(self._sig_label)

        # 添付ファイル
        att_row = QHBoxLayout()
        att_row.addWidget(QLabel("添付："))
        self._attach_label = QLabel("なし")
        att_row.addWidget(self._attach_label, stretch=1)
        add_att_btn = QPushButton("ファイル追加")
        add_att_btn.clicked.connect(self._on_add_attachment)
        clr_att_btn = QPushButton("クリア")
        clr_att_btn.clicked.connect(self._on_clear_attachment)
        att_row.addWidget(add_att_btn)
        att_row.addWidget(clr_att_btn)
        rv.addLayout(att_row)

        splitter.addWidget(right)
        splitter.setSizes([280, 560])
        root.addWidget(splitter, stretch=1)

        # ── 進捗バー ──
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

        # ── ボタン行（全幅）──
        btn_row = QHBoxLayout()
        self._cancel_btn = QPushButton("キャンセル")
        self._cancel_btn.clicked.connect(self.reject)
        preview_btn = QPushButton("プレビュー")
        preview_btn.clicked.connect(self._on_preview)
        self._send_btn = QPushButton("送信実行")
        self._send_btn.setDefault(True)
        self._send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(self._send_btn)
        root.addLayout(btn_row)

    # ── 初期化 ──

    def _refresh_templates(self):
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        self._template_combo.addItem("（手入力）", None)
        for t in self._svc.get_all():
            self._template_combo.addItem(t.name, t.id)
        self._template_combo.blockSignals(False)

    def _load_signature_preview(self):
        sig = self._get_staff_signature()
        if sig:
            preview = sig[:120] + ("…" if len(sig) > 120 else "")
            self._sig_label.setText(f"署名（自動付加）：\n{preview}")
        else:
            self._sig_label.setText("署名：未登録（設定タブ → 職員管理 で登録できます）")

    # ── イベント ──

    def _insert_placeholder(self, placeholder: str):
        if self._subject_edit.hasFocus():
            self._subject_edit.insert(placeholder)
        else:
            self._body_edit.insertPlainText(placeholder)
            self._body_edit.setFocus()

    def _on_template_changed(self, idx):
        tid = self._template_combo.currentData()
        if not tid:
            return
        t = self._svc.get(tid)
        if t:
            self._subject_edit.setText(t.subject)
            self._body_edit.setPlainText(t.body)

    def _on_clear_body(self):
        self._template_combo.blockSignals(True)
        self._template_combo.setCurrentIndex(0)
        self._template_combo.blockSignals(False)
        self._subject_edit.clear()
        self._body_edit.clear()

    def _on_add_attachment(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添付ファイルを選択")
        for p in paths:
            self._attachments.append({"path": p, "name": os.path.basename(p)})
        self._attach_label.setText(
            ", ".join(a["name"] for a in self._attachments)[:80] if self._attachments else "なし"
        )

    def _on_clear_attachment(self):
        self._attachments.clear()
        self._attach_label.setText("なし")

    def _on_preview(self):
        targets = self._checked_members_with_email()
        if not targets:
            QMessageBox.information(self, "プレビュー", "メールアドレスのある宛先がありません。")
            return
        m = targets[0]
        subj, body = self._render(m, self._subject_edit.text(), self._body_edit.toPlainText())
        sig = self._get_staff_signature()
        if sig:
            body += f"\n\n{sig}"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"プレビュー　{m.org_name}（{m.email}）")
        dlg.resize(620, 480)
        v = QVBoxLayout(dlg)

        fl = QFormLayout()
        fl.addRow("宛先：", QLabel(f"{m.org_name}　{m.email}"))
        fl.addRow("件名：", QLabel(subj))
        v.addLayout(fl)

        v.addWidget(QLabel("本文："))
        body_view = QTextEdit()
        body_view.setPlainText(body)
        body_view.setReadOnly(True)
        v.addWidget(body_view)

        if len(targets) > 1:
            note = QLabel(f"※ 表示は1件目のプレビューです。残り {len(targets)-1}件も同様に送信されます。")
            note.setStyleSheet("color:#6B7280; font-size:9pt;")
            v.addWidget(note)

        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(dlg.accept)
        br = QHBoxLayout()
        br.addStretch()
        br.addWidget(close_btn)
        v.addLayout(br)
        dlg.exec()

    def _on_send(self):
        import re
        subject = self._subject_edit.text().strip()
        body_tmpl = self._body_edit.toPlainText()
        if not subject:
            QMessageBox.warning(self, "入力エラー", "件名を入力してください。")
            return
        if not body_tmpl.strip():
            QMessageBox.warning(self, "入力エラー", "本文を入力してください。")
            return

        # 未置換プレースホルダーの検出（自動置換される4種以外が残っていれば警告）
        _known_ph = {"{事業所名}", "{代表者名}", "{所属・役職}", "{会員No.}"}
        _found_ph = set(re.findall(r'\{[^}]+\}', subject + "\n" + body_tmpl))
        _unknown_ph = _found_ph - _known_ph
        if _unknown_ph:
            ret = QMessageBox.warning(
                self, "未知のプレースホルダー",
                "件名・本文に自動置換されないプレースホルダーがあります：\n"
                f"{', '.join(sorted(_unknown_ph))}\n\n"
                "そのまま全宛先に送信されます。続行しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        # 添付ファイルの存在確認
        missing = [a["name"] for a in self._attachments if not os.path.exists(a["path"])]
        if missing:
            QMessageBox.warning(
                self, "添付ファイルエラー",
                "以下の添付ファイルが見つかりません：\n" + "\n".join(missing),
            )
            return

        targets = self._checked_members_with_email()
        no_email = [m for m in self._get_checked_members() if not m.email]
        if not targets:
            QMessageBox.warning(self, "エラー", "送信先にメールアドレスのある宛先がありません。")
            return

        msg = f"{len(targets)}件にメールを送信します。"
        if no_email:
            msg += f"\n（メールアドレスなし {len(no_email)}件はスキップ）"
        reply = QMessageBox.question(
            self, "送信確認", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        email_svc = EmailService(self._config)
        try:
            token = email_svc.get_token_silent()
        except RuntimeError:
            # 未認証 → このダイアログを閉じずにインラインでサインイン
            self._start_inline_auth(email_svc, targets, subject, body_tmpl)
            return

        self._do_send(email_svc, token, targets, subject, body_tmpl)

    # ── インライン認証 ──

    def _start_inline_auth(self, email_svc, targets, subject, body_tmpl):
        try:
            email_svc.get_token()  # DeviceCodeRequired を発生させる
        except DeviceCodeRequired as e:
            flow = e.flow
            url  = flow.get("verification_uri", "https://microsoft.com/devicelogin")
            code = flow.get("user_code", "")
            webbrowser.open(url)

            dlg = QDialog(self)
            dlg.setWindowTitle("Microsoft 365 サインイン")
            dlg.setFixedWidth(460)
            v = QVBoxLayout(dlg)
            v.setSpacing(10)

            v.addWidget(QLabel(
                "未サインインのため、このままサインインします。\n"
                "ブラウザで以下のコードを入力してください："
            ))

            code_lbl = QLabel(code)
            f = QFont()
            f.setPointSize(22)
            f.setBold(True)
            code_lbl.setFont(f)
            code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            code_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            code_lbl.setStyleSheet(
                "background:#F3F4F6; border:1px solid #D1D5DB;"
                "border-radius:6px; padding:8px; letter-spacing:4px;")
            v.addWidget(code_lbl)

            url_lbl = QLabel(f'<a href="{url}">{url}</a>')
            url_lbl.setOpenExternalLinks(True)
            url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(url_lbl)

            wait_lbl = QLabel("サインインが完了すると自動的にメール送信を開始します...")
            wait_lbl.setStyleSheet("color:#6B7280; font-size:9pt;")
            wait_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(wait_lbl)

            cancel_btn = QPushButton("キャンセル")
            cancel_btn.clicked.connect(dlg.reject)
            br = QHBoxLayout()
            br.addStretch()
            br.addWidget(cancel_btn)
            v.addLayout(br)

            self._pending = (email_svc, targets, subject, body_tmpl)
            self._auth_aborted = False
            dlg.rejected.connect(lambda: setattr(self, "_auth_aborted", True))

            self._auth_worker = _AuthWorker(email_svc, flow)
            self._auth_worker.succeeded.connect(
                lambda: self._on_inline_auth_success(dlg))
            self._auth_worker.failed.connect(
                lambda msg: self._on_inline_auth_failed(dlg, msg))
            self._auth_worker.start()
            dlg.exec()
        except Exception as ex:
            QMessageBox.critical(self, "エラー", str(ex))

    def _on_inline_auth_success(self, dlg):
        self._auth_worker.quit()
        self._auth_worker.wait()
        dlg.accept()
        if self._auth_aborted:
            return
        email_svc, targets, subject, body_tmpl = self._pending
        try:
            token = email_svc.get_token_silent()
        except RuntimeError as e:
            QMessageBox.critical(self, "認証エラー", str(e))
            return
        self._do_send(email_svc, token, targets, subject, body_tmpl)

    def _on_inline_auth_failed(self, dlg, msg: str):
        self._auth_worker.quit()
        self._auth_worker.wait()
        dlg.reject()
        QMessageBox.critical(self, "認証エラー", msg)

    # ── 送信本体 ──

    def _do_send(self, email_svc, token, targets, subject, body_tmpl):
        sig = self._get_staff_signature()
        messages = []
        for m in targets:
            subj, body = self._render(m, subject, body_tmpl)
            if sig:
                body += f"\n\n{sig}"
            messages.append((m, subj, body))

        self._progress.setRange(0, len(messages))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._send_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

        self._send_worker = _SendWorker(email_svc, token, messages, self._attachments)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.finished.connect(self._on_send_finished)
        self._send_worker.start()

    def _on_send_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._progress.setFormat(f"送信中… {current}/{total}")

    def _on_send_finished(self, errors: list):
        self._send_worker.quit()
        self._send_worker.wait()
        self._progress.setVisible(False)
        self._send_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        if errors:
            QMessageBox.warning(self, "送信エラー", "\n".join(errors))
        else:
            QMessageBox.information(self, "完了", "送信が完了しました。")
            self.accept()

    def closeEvent(self, event):
        if hasattr(self, "_send_worker") and self._send_worker.isRunning():
            self._send_worker.quit()
            self._send_worker.wait()
        if hasattr(self, "_auth_worker") and self._auth_worker.isRunning():
            self._auth_worker.quit()
            self._auth_worker.wait()
        super().closeEvent(event)

    # ── ヘルパー ──

    def _get_checked_members(self) -> list:
        return [m for m, chk in zip(self._members, self._chk_widgets) if chk.isChecked()]

    def _set_all_checked(self, checked: bool):
        for m, chk in zip(self._members, self._chk_widgets):
            if m.email:
                chk.setChecked(checked)

    def _checked_members_with_email(self) -> list:
        return [m for m in self._get_checked_members() if m.email]

    def _render(self, member, subject: str, body: str) -> tuple[str, str]:
        replacements = {
            "{事業所名}":   member.org_name or "",
            "{代表者名}":   member.rep_name or "",
            "{所属・役職}": member.dept_title or "",
            "{会員No.}":   member.member_number or "",
        }
        for k, v in replacements.items():
            subject = subject.replace(k, v)
            body    = body.replace(k, v)
        return subject, body

    def _get_staff_signature(self) -> str:
        name = self._config.last_staff_name
        with get_session(self._engine) as session:
            s = session.query(Staff).filter_by(name=name).first()
            return (s.signature or "") if s else ""
