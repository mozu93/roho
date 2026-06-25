# app/ui/settings_tab.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QMessageBox,
)
from app.database.connection import get_session
from app.database.models import Staff
from app.services.activity_service import ActivityService


class SettingsTab(QWidget):
    def __init__(self, engine, config, config_path: str = "", parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
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
            if session.query(Staff).filter_by(name=name).first():
                QMessageBox.warning(self, "エラー", f"「{name}」はすでに存在します。")
                return
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

    def _on_save_m365(self):
        import os
        self._config.m365_tenant_id = self._tenant_edit.text().strip()
        self._config.m365_client_id = self._client_id_edit.text().strip()
        self._config.m365_test_address = self._test_addr_edit.text().strip()
        save_path = self._config_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "app_config.json"
        )
        self._config.save(os.path.normpath(save_path))
        QMessageBox.information(self, "保存", "Microsoft 365設定を保存しました。")
