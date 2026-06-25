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
        send_btn.setObjectName("sendButton")
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
