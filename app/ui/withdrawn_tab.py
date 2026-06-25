from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView, QApplication,
)
from PyQt6.QtGui import QFont
from app.services.member_service import MemberService


class WithdrawnTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = MemberService(engine)
        self._members = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["脱会日", "会員No.", "事業所名", "脱会理由"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        layout.addWidget(self._table)
        btn_row = QHBoxLayout()
        reactivate_btn = QPushButton("再加入")
        reactivate_btn.clicked.connect(self._on_reactivate)
        btn_row.addStretch()
        btn_row.addWidget(reactivate_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        members = self._svc.search(inactive_only=True)
        self._members = members
        self._table.setRowCount(len(members))
        for row, m in enumerate(members):
            self._table.setItem(row, 0, QTableWidgetItem(
                m.withdrawn_at.strftime("%Y-%m-%d") if m.withdrawn_at else ""
            ))
            self._table.setItem(row, 1, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_name))
            self._table.setItem(row, 3, QTableWidgetItem(m.withdraw_reason or ""))

    def _on_reactivate(self):
        row = self._table.currentRow()
        if row < 0:
            return
        m = self._members[row]
        reply = QMessageBox.question(
            self, "確認", f"{m.org_name} を再加入しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._svc.reactivate(m.id, self._config.last_staff_name)
            self._refresh()
