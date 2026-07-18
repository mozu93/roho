import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from app.utils.app_config import AppConfig
from app.database.connection import get_engine
from app.ui.dialogs.staff_login_dialog import StaffLoginDialog
from app.ui.member_tab import MemberTab
from app.ui.withdrawn_tab import WithdrawnTab
from app.ui.renewal_tab import RenewalTab
from app.ui.fee_tab import FeeTab
from app.ui.settings_tab import SettingsTab
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
        self._maybe_first_launch_setup()
        self._init_db()
        self._init_backup()
        self._ensure_login()
        self._build_ui()
        self._restore_geometry()
        QTimer.singleShot(200, self._show_notifications)

    def _maybe_first_launch_setup(self):
        """設定ファイルが存在しない（初回起動）場合にデータフォルダ選択を促す。"""
        if os.path.exists(self._config_path):
            return
        from app.ui.dialogs.first_launch_dialog import FirstLaunchDialog
        dlg = FirstLaunchDialog()
        if dlg.exec() != FirstLaunchDialog.DialogCode.Accepted:
            raise SystemExit(0)
        if dlg.selected_dir:
            self._config.data_dir = dlg.selected_dir
        self._config.save(self._config_path)

    def _effective_data_dir(self) -> str:
        """データフォルダのパスを返す（data_dir → db_path のフォルダ → config と同フォルダ の優先順）"""
        if self._config.data_dir:
            return self._config.data_dir
        if self._config.db_path:
            return os.path.dirname(self._config.db_path)
        return os.path.dirname(self._config_path)

    def _init_db(self):
        data_dir = self._effective_data_dir()
        db_path = os.path.join(data_dir, "rouho.db")
        self._engine = get_engine(db_path)
        self._db_path = db_path

    def _init_backup(self):
        from app.services.backup_service import BackupService
        backup_dir = os.path.join(self._effective_data_dir(), "backups")
        self._backup_svc = BackupService(self._db_path, backup_dir)
        self._backup_svc.run_if_needed()

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
            if not self._config.save(self._config_path):
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "設定保存エラー",
                    "ログイン情報の保存に失敗しました。\n"
                    "次回起動時にログイン選択が再表示される場合があります。"
                )
        else:
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

        # アップデートバナー
        GITHUB_REPO = "mozu93/roho"
        self._update_banner = UpdateBanner(GITHUB_REPO, __version__)
        root.addWidget(self._update_banner)

        # タブウィジェット
        self._tabs = QTabWidget()
        self._member_tab = MemberTab(self._engine, self._config, self._config_path)
        self._member_tab.jump_to_withdrawn.connect(self._on_jump_to_withdrawn)
        self._tabs.addTab(self._member_tab, "名簿")
        self._withdrawn_tab = WithdrawnTab(self._engine, self._config, self._config_path)
        self._tabs.addTab(self._withdrawn_tab, "委託解除済")
        self._renewal_tab = RenewalTab(self._engine, self._config, self._config_path)
        self._tabs.addTab(self._renewal_tab, "年度更新")
        self._fee_tab = FeeTab(self._engine, self._config, self._config_path)
        self._tabs.addTab(self._fee_tab, "手数料計算")
        self._settings_tab = SettingsTab(self._engine, self._config, self._config_path)
        self._tabs.addTab(self._settings_tab, "設定")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        self.statusBar().showMessage(f"v{__version__}")

        # メニューバー
        file_menu = self.menuBar().addMenu("ファイル")
        file_menu.addAction("Excelインポート", self._member_tab._on_import)
        file_menu.addAction("Excel出力",      self._member_tab._on_export)
        file_menu.addSeparator()
        file_menu.addAction("バックアップから復元", self._on_restore_backup)
        file_menu.addSeparator()
        file_menu.addAction("ユーザーマニュアル",  lambda: self._open_manual("user.html"))
        file_menu.addAction("管理者マニュアル",    lambda: self._open_manual("admin.html"))
        file_menu.addSeparator()
        file_menu.addAction("バージョン情報",      self._on_about)

    def _on_tab_changed(self, index: int):
        widget = self._tabs.widget(index)
        if widget is self._withdrawn_tab:
            self._withdrawn_tab._refresh()
        elif widget is self._member_tab:
            self._member_tab._refresh()
            self._member_tab.refresh_categories()
        elif widget is self._fee_tab:
            self._fee_tab._refresh()
        elif widget is self._renewal_tab:
            self._renewal_tab._refresh()

    def _on_navigate_to_member(self, member_id: int, event_type: str, event_id: int):
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
                readonly=True,
            ).exec()
        else:
            from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
            MemberHistoryDialog(self._engine, member_id, parent=self).exec()

    def _on_jump_to_withdrawn(self, member_id: int):
        self._tabs.setCurrentIndex(1)
        self._withdrawn_tab.jump_to_member(member_id)

    def _show_notifications(self):
        from app.services.activity_service import ActivityService
        from app.ui.dialogs.notification_dialog import NotificationDialog
        items = ActivityService(self._engine).get_unread(self._config.last_staff_name)
        if not items:
            return
        dlg = NotificationDialog(items, self._engine, self._config, parent=self)
        dlg.navigate_to_member.connect(self._on_navigate_to_member)
        dlg.exec()

    def _open_manual(self, filename: str):
        import sys
        import webbrowser
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..")
        path = os.path.normpath(os.path.join(base, "assets", "manuals", filename))
        webbrowser.open(f"file:///{path}")

    def _on_about(self):
        from app.ui.dialogs.about_dialog import AboutDialog
        AboutDialog(parent=self).exec()

    def _on_restore_backup(self):
        from app.ui.dialogs.backup_restore_dialog import BackupRestoreDialog
        dlg = BackupRestoreDialog(self._backup_svc, self._engine, parent=self)
        dlg.exec()
        if dlg.restored:
            self.close()

    def _restore_geometry(self):
        geo = self._config.window_geometry
        if not geo:
            return
        w = max(700, geo.get("w", 780))
        h = max(500, geo.get("h", 720))
        x = geo.get("x", 100)
        y = geo.get("y", 100)
        # ウィンドウ中心がいずれかのスクリーン内に収まるか確認
        from PyQt6.QtWidgets import QApplication
        cx, cy = x + w // 2, y + h // 2
        on_screen = any(s.geometry().contains(cx, cy) for s in QApplication.screens())
        if not on_screen:
            primary = QApplication.primaryScreen().availableGeometry()
            x = (primary.width() - w) // 2
            y = (primary.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def closeEvent(self, event):
        # 再入防止: Qt が複数回 closeEvent を発行する場合に備える
        if getattr(self, "_closing", False):
            event.accept()
            return
        self._closing = True
        event.accept()

        # ウィンドウ位置を保存
        try:
            geo = self.geometry()
            self._config.window_geometry = {
                "x": geo.x(), "y": geo.y(),
                "w": geo.width(), "h": geo.height(),
            }
            self._config.save(self._config_path)
        except Exception:
            pass

        # バックグラウンドスレッドを順次停止
        # (QThread デストラクタが実行中スレッドを待ち続けるのを防ぐ)
        for widget_attr in ("_update_banner", "_settings_tab"):
            widget = getattr(self, widget_attr, None)
            if widget and hasattr(widget, "stop_threads"):
                try:
                    widget.stop_threads()
                except Exception:
                    pass

        # タブ内のスレッドも停止
        tabs = getattr(self, "_tabs", None)
        if tabs:
            for i in range(tabs.count()):
                w = tabs.widget(i)
                if w and hasattr(w, "stop_threads"):
                    try:
                        w.stop_threads()
                    except Exception:
                        pass

        # SQLAlchemy 接続プールを解放 (WAL ファイルの適切な後処理)
        try:
            if self._engine:
                self._engine.dispose()
        except Exception:
            pass

        # プロセスを強制終了
        # TerminateProcess は ExitProcess と違い DLL ローダーロックの影響を受けず
        # ブロッキング中のスレッドがあっても即時終了できる
        import sys as _sys
        import os as _os
        if _sys.platform == "win32":
            import ctypes as _ctypes
            _ctypes.windll.kernel32.TerminateProcess(
                _ctypes.windll.kernel32.GetCurrentProcess(), 0
            )
        _os._exit(0)

    def _on_logout(self):
        self._config.last_staff_name = ""
        self._config.save(self._config_path)
        self.close()
