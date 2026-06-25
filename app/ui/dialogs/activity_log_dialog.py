# app/ui/dialogs/activity_log_dialog.py
import html
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
                f"<b>{log.logged_at.strftime('%Y-%m-%d %H:%M')}</b>　{html.escape(log.logged_by)}　"
                f"<span style='color:#666'>[{html.escape(cat_names)}]</span>"
            )
            content = QLabel(log.content)
            content.setTextFormat(Qt.TextFormat.PlainText)
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
