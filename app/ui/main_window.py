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
from app.ui.notification_banner import NotificationBanner
from app.ui.update_banner import UpdateBanner
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

        # 新着バナー（ヘッダーとタブウィジェットの間）
        self._banner = NotificationBanner(self._engine, self._config)
        self._banner.navigate_to_member.connect(self._on_navigate_to_member)
        root.addWidget(self._banner)

        # アップデートバナー
        GITHUB_REPO = "mozu93/roho"
        self._update_banner = UpdateBanner(GITHUB_REPO, __version__)
        root.addWidget(self._update_banner)

        # タブウィジェット
        self._tabs = QTabWidget()
        self._tabs.addTab(MemberTab(self._engine, self._config), "名簿")
        self._tabs.addTab(WithdrawnTab(self._engine, self._config), "脱会済み")
        self._tabs.addTab(LabelTab(self._engine, self._config), "ラベル出力")
        self._tabs.addTab(EmailTab(self._engine, self._config), "メール送信")
        self._tabs.addTab(SettingsTab(self._engine, self._config, self._config_path), "設定")
        root.addWidget(self._tabs)

        self.statusBar().showMessage(f"v{__version__}")

    def _on_navigate_to_member(self, member_id: int, event_type: str, event_id: int):
        # 名簿タブ（インデックス0）に切り替え
        self._tabs.setCurrentIndex(0)
        if event_type == "activity":
            from app.ui.dialogs.activity_log_dialog import ActivityLogDialog
            from app.services.member_service import MemberService
            m = MemberService(self._engine).get(member_id)
            ActivityLogDialog(
                self._engine, member_id,
                self._config.last_staff_name,
                m.org_name if m else "",
                parent=self,
            ).exec()
        else:
            from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
            MemberHistoryDialog(self._engine, member_id, parent=self).exec()

    def _on_logout(self):
        self._config.last_staff_name = ""
        self._config.save(self._config_path)
        self._show_login_dialog()
        self._staff_label.setText(f"ログイン中：{self._current_staff}　さん")
        self._banner.refresh()
