# app/ui/dialogs/member_history_dialog.py
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QTextEdit, QLabel, QPushButton, QSplitter,
)
from PyQt6.QtCore import Qt
from app.services.member_service import MemberService


class MemberHistoryDialog(QDialog):
    def __init__(self, engine, member_id: int, parent=None):
        super().__init__(parent)
        self._svc = MemberService(engine)
        self._member_id = member_id
        self.setWindowTitle("変更履歴")
        self.resize(700, 450)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["変更日時", "担当者", "変更理由"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_select)
        splitter.addWidget(self._table)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("行を選択すると変更前データを表示します")
        splitter.addWidget(self._detail)
        layout.addWidget(splitter)

        btn = QPushButton("閉じる")
        btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _load(self):
        self._changes = self._svc.get_changes(self._member_id)
        self._table.setRowCount(len(self._changes))
        for row, c in enumerate(self._changes):
            self._table.setItem(row, 0, QTableWidgetItem(c.changed_at.strftime("%Y-%m-%d %H:%M")))
            self._table.setItem(row, 1, QTableWidgetItem(c.changed_by))
            self._table.setItem(row, 2, QTableWidgetItem(c.change_reason))

    def _on_select(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        change = self._changes[row]
        try:
            data = json.loads(change.snapshot)
            self._detail.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            self._detail.setPlainText(change.snapshot)
