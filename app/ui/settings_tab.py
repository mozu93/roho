# app/ui/settings_tab.py
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QMessageBox, QLabel, QTextEdit,
    QSplitter, QFileDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from app.database.connection import get_session
from app.database.models import Staff
from app.services.activity_service import ActivityService
from app.services.template_service import TemplateService
from app.services.email_service import EmailService, DeviceCodeRequired


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


class SettingsTab(QWidget):
    def __init__(self, engine, config, config_path: str = "", parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._act_svc = ActivityService(engine)
        self._tmpl_svc = TemplateService(engine)
        self._build_ui()
        self._refresh_staff()
        self._refresh_categories()
        self._refresh_templates()

    def _build_ui(self):
        f = QFont()
        f.setPointSize(11)
        self.setFont(f)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 左列：テンプレート管理 ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        lv.setSpacing(6)

        tmpl_group = QGroupBox("メールテンプレート管理")
        tg = QVBoxLayout(tmpl_group)
        tg.setSpacing(6)

        self._tmpl_list = QListWidget()
        self._tmpl_list.doubleClicked.connect(self._on_edit_template)
        tg.addWidget(self._tmpl_list, stretch=1)

        tmpl_btn_row = QHBoxLayout()
        tmpl_new_btn = QPushButton("新規")
        tmpl_new_btn.clicked.connect(self._on_new_template)
        tmpl_edit_btn = QPushButton("編集")
        tmpl_edit_btn.clicked.connect(self._on_edit_template)
        tmpl_del_btn = QPushButton("削除")
        tmpl_del_btn.clicked.connect(self._on_delete_template)
        tmpl_btn_row.addWidget(tmpl_new_btn)
        tmpl_btn_row.addWidget(tmpl_edit_btn)
        tmpl_btn_row.addWidget(tmpl_del_btn)
        tmpl_btn_row.addStretch()
        tg.addLayout(tmpl_btn_row)

        lv.addWidget(tmpl_group, stretch=1)

        # カテゴリ管理（左列下）
        cat_group = QGroupBox("対応カテゴリ管理")
        cg = QVBoxLayout(cat_group)
        cg.setSpacing(4)

        self._cat_list = QListWidget()
        self._cat_list.setMinimumHeight(160)
        cg.addWidget(self._cat_list, stretch=1)

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
        cg.addLayout(cat_row)

        lv.addWidget(cat_group)
        splitter.addWidget(left)

        # ── 右列：職員管理 / M365 ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(6)

        # 職員管理
        staff_group = QGroupBox("職員管理")
        sg = QVBoxLayout(staff_group)
        sg.setSpacing(4)

        self._staff_list = QListWidget()
        self._staff_list.setMaximumHeight(90)
        self._staff_list.currentItemChanged.connect(self._on_staff_selected)
        sg.addWidget(self._staff_list)

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
        sg.addLayout(add_row)

        sg.addWidget(QLabel("選択した職員の署名："))
        self._sig_edit = QTextEdit()
        self._sig_edit.setPlaceholderText("メール末尾に自動的に追加される署名を入力してください")
        sg.addWidget(self._sig_edit, stretch=1)

        sig_save_btn = QPushButton("署名を保存")
        sig_save_btn.clicked.connect(self._on_save_signature)
        sg.addWidget(sig_save_btn)

        rv.addWidget(staff_group, stretch=1)

        # データフォルダ設定
        data_group = QGroupBox("データフォルダ設定")
        dg = QVBoxLayout(data_group)
        dg.setSpacing(8)
        dg.setContentsMargins(10, 12, 10, 12)
        dg.addWidget(QLabel("DBファイルと自動バックアップの保存先フォルダ："))
        data_dir_row = QHBoxLayout()
        self._data_dir_edit = QLineEdit(self._config.data_dir)
        self._data_dir_edit.setPlaceholderText("空白の場合は設定ファイルと同フォルダ（ローカル）")
        browse_btn = QPushButton("参照...")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._on_browse_data_dir)
        data_dir_row.addWidget(self._data_dir_edit)
        data_dir_row.addWidget(browse_btn)
        dg.addLayout(data_dir_row)
        save_data_btn = QPushButton("保存（再起動後に反映）")
        save_data_btn.clicked.connect(self._on_save_data_dir)
        dg.addWidget(save_data_btn)
        rv.addWidget(data_group)

        # M365設定
        m365_group = QGroupBox("Microsoft 365設定")
        mg = QVBoxLayout(m365_group)
        mg.setSpacing(8)
        mg.setContentsMargins(10, 12, 10, 12)

        form = QFormLayout()
        form.setSpacing(8)
        self._tenant_edit = QLineEdit(self._config.m365_tenant_id)
        self._client_id_edit = QLineEdit(self._config.m365_client_id)
        self._test_addr_edit = QLineEdit(self._config.m365_test_address)
        form.addRow("テナントID：", self._tenant_edit)
        form.addRow("クライアントID：", self._client_id_edit)
        form.addRow("テスト送信先：", self._test_addr_edit)
        mg.addLayout(form)

        m365_btn_row = QHBoxLayout()
        save_m365_btn = QPushButton("設定を保存")
        save_m365_btn.clicked.connect(self._on_save_m365)
        auth_btn = QPushButton("Microsoft 365 サインイン")
        auth_btn.clicked.connect(self._on_auth)
        test_btn = QPushButton("テスト送信")
        test_btn.clicked.connect(self._on_test_send)
        m365_btn_row.addWidget(save_m365_btn)
        m365_btn_row.addStretch()
        m365_btn_row.addWidget(auth_btn)
        m365_btn_row.addWidget(test_btn)
        mg.addLayout(m365_btn_row)

        self._auth_status = QLabel("未サインイン")
        self._auth_status.setStyleSheet("color:#6B7280; font-size:9pt;")
        mg.addWidget(self._auth_status)
        self._update_auth_status()

        rv.addWidget(m365_group)
        splitter.addWidget(right)
        splitter.setSizes([420, 340])
        root.addWidget(splitter)

    # ── 職員管理 ──

    def _refresh_staff(self):
        self._staff_list.clear()
        with get_session(self._engine) as session:
            for s in session.query(Staff).order_by(Staff.id).all():
                status = "有効" if s.is_active else "無効"
                item = QListWidgetItem(f"{s.name}　[{status}]")
                item.setData(Qt.ItemDataRole.UserRole, s.id)
                self._staff_list.addItem(item)

    def _on_add_staff(self):
        name = self._staff_edit.text().strip()
        if not name:
            return
        with get_session(self._engine) as session:
            if session.query(Staff).filter_by(name=name).first():
                QMessageBox.warning(self, "エラー", f"「{name}」はすでに存在します。")
                return
            session.add(Staff(name=name))
        self._staff_edit.clear()
        self._refresh_staff()

    def _on_staff_selected(self, item):
        if not item:
            self._sig_edit.clear()
            return
        staff_id = item.data(Qt.ItemDataRole.UserRole)
        with get_session(self._engine) as session:
            s = session.get(Staff, staff_id)
            self._sig_edit.setPlainText(s.signature or "" if s else "")

    def _on_toggle_staff(self):
        item = self._staff_list.currentItem()
        if not item:
            return
        staff_id = item.data(Qt.ItemDataRole.UserRole)
        with get_session(self._engine) as session:
            s = session.get(Staff, staff_id)
            if s:
                s.is_active = not s.is_active
        self._refresh_staff()

    def _on_save_signature(self):
        item = self._staff_list.currentItem()
        if not item:
            QMessageBox.warning(self, "エラー", "職員を選択してください。")
            return
        staff_id = item.data(Qt.ItemDataRole.UserRole)
        with get_session(self._engine) as session:
            s = session.get(Staff, staff_id)
            if s:
                s.signature = self._sig_edit.toPlainText()
        QMessageBox.information(self, "保存", "署名を保存しました。")

    # ── テンプレート管理 ──

    def _refresh_templates(self):
        self._tmpl_list.clear()
        for t in self._tmpl_svc.get_all():
            item = QListWidgetItem(f"{t.name}　（件名：{t.subject}）")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self._tmpl_list.addItem(item)

    def _on_new_template(self):
        from app.ui.dialogs.template_edit_dialog import TemplateEditDialog
        dlg = TemplateEditDialog(self._engine, parent=self)
        dlg.exec()
        self._refresh_templates()

    def _on_edit_template(self):
        item = self._tmpl_list.currentItem()
        if not item:
            QMessageBox.information(self, "テンプレート編集", "編集するテンプレートを選択してください。")
            return
        from app.ui.dialogs.template_edit_dialog import TemplateEditDialog
        dlg = TemplateEditDialog(self._engine, template_id=item.data(Qt.ItemDataRole.UserRole), parent=self)
        dlg.exec()
        self._refresh_templates()

    def _on_delete_template(self):
        item = self._tmpl_list.currentItem()
        if not item:
            return
        reply = QMessageBox.question(
            self, "確認", f"「{item.text().split('　')[0]}」を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._tmpl_svc.delete(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_templates()

    # ── カテゴリ管理 ──

    def _refresh_categories(self):
        self._cat_list.clear()
        for cat in self._act_svc.get_categories():
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.id)
            self._cat_list.addItem(item)

    def _on_add_category(self):
        name = self._cat_edit.text().strip()
        if not name:
            return
        self._act_svc.add_category(name)
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
            self._act_svc.delete_category(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_categories()

    # ── データフォルダ設定 ──

    def _on_browse_data_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "データフォルダを選択", self._data_dir_edit.text() or ""
        )
        if folder:
            self._data_dir_edit.setText(folder)

    def _on_save_data_dir(self):
        import os
        new_dir = self._data_dir_edit.text().strip()
        if new_dir and not os.path.isdir(new_dir):
            QMessageBox.warning(self, "エラー",
                f"指定したフォルダが存在しません：\n{new_dir}\n\n先にフォルダを作成してください。")
            return
        self._config.data_dir = new_dir
        save_path = self._config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "app_config.json"
        )
        if self._config.save(os.path.normpath(save_path)):
            QMessageBox.information(self, "保存",
                "データフォルダを保存しました。\nアプリを再起動すると新しいフォルダが使われます。")
        else:
            QMessageBox.critical(self, "保存エラー", "設定ファイルの書き込みに失敗しました。")

    # ── M365設定・認証 ──

    def _on_save_m365(self):
        import os
        self._config.m365_tenant_id = self._tenant_edit.text().strip()
        self._config.m365_client_id = self._client_id_edit.text().strip()
        self._config.m365_test_address = self._test_addr_edit.text().strip()
        save_path = self._config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "app_config.json"
        )
        if self._config.save(os.path.normpath(save_path)):
            QMessageBox.information(self, "保存", "Microsoft 365設定を保存しました。")
        else:
            QMessageBox.critical(self, "保存エラー",
                "設定ファイルの書き込みに失敗しました。\n"
                "ファイルのアクセス権限を確認してください。")

    def _update_auth_status(self):
        svc = EmailService(self._config)
        if svc.is_authenticated():
            self._auth_status.setText("✓ サインイン済み")
            self._auth_status.setStyleSheet("color:#16A34A; font-size:9pt;")
        else:
            self._auth_status.setText("未サインイン")
            self._auth_status.setStyleSheet("color:#6B7280; font-size:9pt;")

    def _on_auth(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        email_svc = EmailService(self._config)
        try:
            email_svc.get_token()
            QMessageBox.information(self, "確認", "すでにサインイン済みです。")
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
            v.addWidget(QLabel("ブラウザが開きました。以下のコードを入力してサインインしてください："))
            code_lbl = QLabel(code)
            f = QFont(); f.setPointSize(22); f.setBold(True)
            code_lbl.setFont(f)
            code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            code_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            code_lbl.setStyleSheet(
                "background:#F3F4F6; border:1px solid #D1D5DB;"
                "border-radius:6px; padding:8px; letter-spacing:4px;")
            v.addWidget(code_lbl)
            url_lbl = QLabel(f'<a href="{url}">{url}</a>')
            url_lbl.setOpenExternalLinks(True)
            url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(url_lbl)
            wait = QLabel("サインインが完了すると自動的にこのダイアログが閉じます...")
            wait.setStyleSheet("color:#6B7280; font-size:9pt;")
            wait.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(wait)
            self._auth_dlg = dlg

            self._auth_worker = _AuthWorker(email_svc, flow)
            self._auth_worker.succeeded.connect(self._on_auth_success)
            self._auth_worker.failed.connect(self._on_auth_failed)
            self._auth_worker.start()
            dlg.exec()
        except Exception as ex:
            QMessageBox.critical(self, "エラー", str(ex))

    def reload_staff_settings(self):
        """ログアウト→ログイン後に呼び出し、M365認証状態と署名エリアをリセットする"""
        self._update_auth_status()
        self._staff_list.clearSelection()
        self._sig_edit.clear()

    def _on_auth_success(self):
        self._auth_worker.quit()
        self._auth_worker.wait()
        if hasattr(self, "_auth_dlg"):
            self._auth_dlg.accept()
        self._update_auth_status()
        QMessageBox.information(self, "完了", "Microsoft 365 サインインが完了しました。")

    def _on_auth_failed(self, msg: str):
        self._auth_worker.quit()
        self._auth_worker.wait()
        if hasattr(self, "_auth_dlg"):
            self._auth_dlg.reject()
        QMessageBox.critical(self, "認証エラー", msg)

    def _on_test_send(self):
        addr = self._test_addr_edit.text().strip()
        if not addr:
            QMessageBox.warning(self, "テスト送信", "テスト送信先メールアドレスを入力してください。")
            return
        email_svc = EmailService(self._config)
        try:
            token = email_svc.get_token_silent()
        except RuntimeError as e:
            QMessageBox.warning(self, "未サインイン", str(e))
            return
        try:
            email_svc.send(addr, "【テスト送信】労働保険名簿管理システム", "テスト送信です。", token=token)
            QMessageBox.information(self, "完了", f"{addr} へテスト送信しました。")
        except Exception as e:
            QMessageBox.critical(self, "送信エラー", str(e))
