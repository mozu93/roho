from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.services.fee_service import DEBIT_FAILURE_REASONS, FeeService


class DebitResultDialog(QDialog):
    """不能先だけをチェックし、残りを入金済として期別に確定する画面。"""

    def __init__(self, engine, fiscal_year: int, parent=None):
        super().__init__(parent)
        self._svc = FeeService(engine)
        self._fiscal_year = fiscal_year
        self.setWindowTitle(f"{fiscal_year}年度 口座振替結果")
        self.resize(900, 650)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("対象期："))
        self._period = QComboBox()
        self._period.addItems(["1期", "2期"])
        self._period.currentTextChanged.connect(self._load)
        top.addWidget(self._period)
        top.addStretch()
        layout.addLayout(top)

        note = QLabel(
            "委託団体から不能連絡があった事業所だけ「不能」にチェックしてください。"
            "確定時、チェックのない事業所はすべて入金済になります。")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "不能", "管理No.", "事業所名", "不能理由",
            "引落不能を連絡済", "納入のお願い発送済",
        ])
        self._table.setColumnWidth(0, 60)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 260)
        self._table.setColumnWidth(3, 150)
        self._table.setColumnWidth(4, 150)
        self._table.setColumnWidth(5, 170)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("閉じる")
        cancel.clicked.connect(self.reject)
        save = QPushButton("不能先を登録し、その他を入金済にする")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _load(self):
        if not hasattr(self, "_table"):
            return
        records = self._svc.search(self._fiscal_year)
        existing = self._svc.get_debit_results(
            self._fiscal_year, self._period.currentText())
        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            current = existing.get(record.id, {})
            failed = bool(current) and not current["is_paid"]

            failure = QCheckBox()
            failure.setChecked(failed)
            self._table.setCellWidget(row, 0, failure)

            code = QTableWidgetItem(str(record.member.company_code or ""))
            code.setData(Qt.ItemDataRole.UserRole, record.id)
            code.setFlags(code.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 1, code)
            name = QTableWidgetItem(record.member.org_name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 2, name)

            reason = QComboBox()
            reason.addItems(DEBIT_FAILURE_REASONS)
            if current.get("failure_reason"):
                reason.setCurrentText(current["failure_reason"])
            self._table.setCellWidget(row, 3, reason)

            notified = QCheckBox()
            notified.setChecked(bool(current.get("notified_at")))
            self._table.setCellWidget(row, 4, notified)
            sent = QCheckBox()
            sent.setChecked(bool(current.get("notice_sent_at")))
            self._table.setCellWidget(row, 5, sent)

            def toggle(enabled, widgets=(reason, notified, sent)):
                for widget in widgets:
                    widget.setEnabled(enabled)

            failure.toggled.connect(toggle)
            toggle(failed)

    def _save(self):
        answer = QMessageBox.question(
            self, "口座振替結果の確定",
            f"{self._period.currentText()}の不能先を登録し、"
            "チェックのない事業所をすべて入金済にします。よろしいですか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        today = date.today()
        failures = {}
        for row in range(self._table.rowCount()):
            failed = self._table.cellWidget(row, 0)
            if not failed.isChecked():
                continue
            record_id = self._table.item(
                row, 1).data(Qt.ItemDataRole.UserRole)
            reason = self._table.cellWidget(row, 3)
            notified = self._table.cellWidget(row, 4)
            sent = self._table.cellWidget(row, 5)
            failures[record_id] = {
                "failure_reason": reason.currentText(),
                "notified_at": today if notified.isChecked() else None,
                "notice_sent_at": today if sent.isChecked() else None,
            }
        try:
            count = self._svc.confirm_debit_results(
                self._fiscal_year, self._period.currentText(),
                failures, confirmed_at=today)
        except ValueError as error:
            QMessageBox.warning(self, "入力エラー", str(error))
            return
        QMessageBox.information(
            self, "完了",
            f"{self._period.currentText()}を確定しました。"
            f"対象{count}件、不能{len(failures)}件です。")
        self.accept()
