# app/ui/dialogs/renewal_edit_dialog.py
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QWidget,
    QLabel, QComboBox, QCheckBox, QDateEdit, QTextEdit,
    QPushButton, QGroupBox, QMessageBox,
)
from PyQt6.QtCore import QDate
from app.services.renewal_service import (
    RenewalService, compute_overall_status, SUBMISSION_STATUSES, OVERALL_STATUSES,
)
from app.services.member_service import MemberService, INS_TYPES

BRANCH_LABEL = {
    "ippan": "枝番0（一般・労災＆雇用）", "kensetsu_koyou": "枝番2（建設業・他雇用）",
    "ringyo": "枝番4（林業・労災）", "kensetsu_genba": "枝番5（建設業・現場）",
    "kensetsu_jimusho": "枝番6（建設業・事務所）",
}
EDITABLE_SUBMISSION_STATUSES = [
    status for status in SUBMISSION_STATUSES if status != "対象外"
]


class RenewalEditDialog(QDialog):
    def __init__(self, engine, renewal_id: int, staff_name: str, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._renewal_id = renewal_id
        self._staff_name = staff_name
        self._svc = RenewalService(engine)
        self._member_svc = MemberService(engine)
        self.saved = False

        self._renewal = self._svc.get(renewal_id)
        if self._renewal is None:
            raise ValueError(f"年度更新レコードID {renewal_id} が見つかりません。")
        self._member = self._member_svc.get(self._renewal.member_id)
        self.setWindowTitle(f"年度更新 — {self._member.org_name}")
        self.setMinimumWidth(700)
        self.resize(700, 580)
        self._build_ui()
        self._load()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)

        item_group = QGroupBox("枝番別提出状況")
        ifl = QFormLayout(item_group)
        self._status_fields = {}
        self._confirmed_fields = {}
        insurance_entries = {
            entry.ins_type: entry for entry in self._member.insurance_entries
        }
        for ins_type in INS_TYPES:
            entry = insurance_entries.get(ins_type)
            if entry is None:
                continue
            status_combo = QComboBox()
            status_combo.addItems(EDITABLE_SUBMISSION_STATUSES)
            status_combo.currentIndexChanged.connect(self._recalculate)

            confirmed_edit = QDateEdit(QDate.currentDate())
            confirmed_edit.setCalendarPopup(True)
            confirmed_edit.setDisplayFormat("yyyy-MM-dd")

            row = QHBoxLayout()
            row.addWidget(status_combo)
            row.addWidget(confirmed_edit)
            wrapper = QWidget()
            wrapper.setLayout(row)
            label = BRANCH_LABEL[ins_type]
            if entry.ins_number:
                label = f"{label}（番号: {entry.ins_number}）"
            ifl.addRow(label, wrapper)

            self._status_fields[ins_type] = status_combo
            self._confirmed_fields[ins_type] = confirmed_edit
        form_layout.addWidget(item_group)

        overall_group = QGroupBox("全体状況")
        ofl = QFormLayout(overall_group)
        self._r_auto_status = QLabel("-")
        self._f_manual = QCheckBox("手動指定する")
        self._f_overall_status = QComboBox()
        self._f_overall_status.addItems(OVERALL_STATUSES)
        self._f_overall_status.setEnabled(False)
        self._f_manual.toggled.connect(self._f_overall_status.setEnabled)
        self._f_manual.toggled.connect(self._recalculate)
        ofl.addRow("自動判定結果", self._r_auto_status)
        ofl.addRow(self._f_manual)
        ofl.addRow("全体状況", self._f_overall_status)
        form_layout.addWidget(overall_group)

        note_group = QGroupBox("メモ（年度更新）")
        note_layout = QVBoxLayout(note_group)
        self._f_note = QTextEdit()
        self._f_note.setMinimumHeight(140)
        note_layout.addWidget(self._f_note, 1)
        form_layout.addWidget(note_group)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    def _load(self):
        r = self._renewal
        for item in r.items:
            if item.branch_type not in self._status_fields:
                continue
            idx = self._status_fields[item.branch_type].findText(item.submission_status)
            self._status_fields[item.branch_type].setCurrentIndex(idx if idx >= 0 else 0)
            if item.confirmed_at:
                self._confirmed_fields[item.branch_type].setDate(QDate(
                    item.confirmed_at.year, item.confirmed_at.month, item.confirmed_at.day))

        if r.overall_status_manual:
            self._f_manual.setChecked(True)
            idx = self._f_overall_status.findText(r.overall_status)
            self._f_overall_status.setCurrentIndex(idx if idx >= 0 else 0)

        self._f_note.setPlainText(r.note or "")

        self._recalculate()

    def _recalculate(self):
        statuses = [combo.currentText() for combo in self._status_fields.values()]
        auto_status = compute_overall_status(statuses)
        self._r_auto_status.setText(auto_status)
        if not self._f_manual.isChecked():
            idx = self._f_overall_status.findText(auto_status)
            self._f_overall_status.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_save(self):
        items_data = {}
        tracked_change = False
        existing_items = {item.branch_type: item for item in self._renewal.items}
        for ins_type, combo in self._status_fields.items():
            qd = self._confirmed_fields[ins_type].date()
            confirmed_at = date(qd.year(), qd.month(), qd.day())
            existing_item = existing_items.get(ins_type)
            if (existing_item is None
                    or combo.currentText() != existing_item.submission_status
                    or confirmed_at != existing_item.confirmed_at):
                tracked_change = True
            items_data[ins_type] = {
                "submission_status": combo.currentText(),
                "confirmed_at": confirmed_at,
            }

        note = self._f_note.toPlainText()
        last_contacted = self._renewal.last_contacted_at
        manual = self._f_manual.isChecked()
        if (note != (self._renewal.note or "")
                or tracked_change
                or manual != self._renewal.overall_status_manual
                or (manual and self._f_overall_status.currentText() != self._renewal.overall_status)):
            last_contacted = date.today()

        renewal_data = {
            "overall_status_manual": manual,
            "overall_status": self._f_overall_status.currentText() if manual else None,
            "last_contacted_at": last_contacted,
            "note": note,
        }
        try:
            self._svc.update(self._renewal_id, items_data, renewal_data)
            self.saved = True
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", str(e))
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
