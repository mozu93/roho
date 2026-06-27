# app/ui/dialogs/withdraw_dialog.py
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDateEdit, QLineEdit, QPushButton, QMessageBox, QGroupBox, QLabel,
)
from PyQt6.QtCore import QDate
from app.services.member_service import MemberService


class WithdrawDialog(QDialog):
    def __init__(self, engine, staff_name: str, member_id: int, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self._member_id = member_id
        self._svc = MemberService(engine)
        self.withdrawn = False

        m = self._svc.get(member_id)
        self._org_name = m.org_name if m else ""
        self.setWindowTitle(f"委託解除 — {self._org_name}")
        self.setFixedSize(400, 230)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        target_lbl = QLabel(f"対象：{self._org_name}")
        target_lbl.setStyleSheet("font-weight: bold; color: #1e3a5f; padding: 4px 0;")
        layout.addWidget(target_lbl)

        grp = QGroupBox("委託解除情報を入力")
        fl = QFormLayout(grp)
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("委託解除理由を入力してください")
        fl.addRow("委託解除日：", self._date_edit)
        fl.addRow("委託解除理由：", self._reason_edit)
        layout.addWidget(grp)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("委託解除を実行")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_ok(self):
        reason = self._reason_edit.text().strip()
        if not reason:
            QMessageBox.warning(self, "入力エラー", "委託解除理由を入力してください。")
            return
        qd = self._date_edit.date()
        withdrawn_at = date(qd.year(), qd.month(), qd.day())
        reply = QMessageBox.question(
            self, "確認", f"「{self._org_name}」を委託解除してよいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._svc.withdraw(self._member_id, withdrawn_at, reason, self._staff_name)
            self.withdrawn = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
