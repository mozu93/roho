from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.services.backup_service import BackupService


class BackupRestoreDialog(QDialog):
    def __init__(self, backup_service: BackupService, engine, parent=None):
        super().__init__(parent)
        self._svc = backup_service
        self._engine = engine
        self.restored = False
        self.setWindowTitle("バックアップから復元")
        self.setMinimumWidth(500)
        self.setMaximumHeight(560)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            "復元するバックアップを選択してください。\n"
            "※ 現在のデータは上書きされます。復元後、アプリが終了します。"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "color:#92400e; background:#fef9c3; padding:8px; border-radius:4px;"
        )
        layout.addWidget(info)

        backups = self._svc.list_backups()

        if not backups:
            layout.addWidget(QLabel("バックアップが見つかりません。"))
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)

            list_widget = QWidget()
            list_layout = QVBoxLayout(list_widget)
            list_layout.setContentsMargins(0, 0, 0, 0)
            list_layout.setSpacing(0)

            for i, b in enumerate(backups):
                row = QWidget()
                row_h = QHBoxLayout(row)
                row_h.setContentsMargins(4, 8, 4, 8)

                lbl = QLabel(
                    f"<b>{b['date'].strftime('%Y-%m-%d')}</b>"
                    f"　<span style='color:#555;'>（{b['age_label']}・{b['size_kb']} KB）</span>"
                )
                lbl.setTextFormat(Qt.TextFormat.RichText)

                restore_btn = QPushButton("復元")
                restore_btn.setFixedWidth(64)
                restore_btn.clicked.connect(
                    lambda _, p=b["path"], d=b["date"]: self._on_restore(p, d)
                )

                row_h.addWidget(lbl, 1)
                row_h.addWidget(restore_btn)
                list_layout.addWidget(row)

                if i < len(backups) - 1:
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.HLine)
                    list_layout.addWidget(line)

            list_layout.addStretch()
            scroll.setWidget(list_widget)
            layout.addWidget(scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_restore(self, backup_path: str, backup_date):
        ret = QMessageBox.warning(
            self,
            "復元の確認",
            f"{backup_date.strftime('%Y-%m-%d')} のバックアップから復元しますか？\n\n"
            "現在のデータは上書きされます。\n"
            "復元後、アプリが終了します。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if ret != QMessageBox.StandardButton.Ok:
            return

        try:
            self._svc.restore(backup_path, self._engine)
            QMessageBox.information(
                self, "復元完了",
                "復元が完了しました。アプリを終了します。\n"
                "再起動してご利用ください。"
            )
            self.restored = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "復元エラー", str(e))
