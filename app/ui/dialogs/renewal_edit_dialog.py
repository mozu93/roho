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
        self._has_confirmed_fields = {}
        self._confirmed_fields = {}
        member_ins_types = {e.ins_type for e in self._member.insurance_entries}
        for ins_type in INS_TYPES:
            if ins_type not in member_ins_types:
                continue
            status_combo = QComboBox()
            status_combo.addItems(SUBMISSION_STATUSES)
            status_combo.currentIndexChanged.connect(self._recalculate)

            has_confirmed = QCheckBox("確認日あり")
            confirmed_edit = QDateEdit(QDate.currentDate())
            confirmed_edit.setCalendarPopup(True)
            confirmed_edit.setDisplayFormat("yyyy-MM-dd")
            confirmed_edit.setEnabled(False)
            has_confirmed.toggled.connect(confirmed_edit.setEnabled)

            row = QHBoxLayout()
            row.addWidget(status_combo)
            row.addWidget(has_confirmed)
            row.addWidget(confirmed_edit)
            wrapper = QWidget()
            wrapper.setLayout(row)
            ifl.addRow(BRANCH_LABEL[ins_type], wrapper)

            self._status_fields[ins_type] = status_combo
            self._has_confirmed_fields[ins_type] = has_confirmed
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

        contact_group = QGroupBox("対応記録")
        cfl = QFormLayout(contact_group)
        self._f_has_contact = QCheckBox("最終対応日あり")
        self._f_last_contacted = QDateEdit(QDate.currentDate())
        self._f_last_contacted.setCalendarPopup(True)
        self._f_last_contacted.setEnabled(False)
        self._f_has_contact.toggled.connect(self._f_last_contacted.setEnabled)
        self._f_note = QTextEdit()
        self._f_note.setFixedHeight(60)
        activity_btn = QPushButton("対応履歴")
        activity_btn.clicked.connect(self._on_open_activity_log)
        cfl.addRow(self._f_has_contact)
        cfl.addRow("最終対応日", self._f_last_contacted)
        cfl.addRow("メモ", self._f_note)
        cfl.addRow(activity_btn)
        form_layout.addWidget(contact_group)

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
                self._has_confirmed_fields[item.branch_type].setChecked(True)
                self._confirmed_fields[item.branch_type].setDate(QDate(
                    item.confirmed_at.year, item.confirmed_at.month, item.confirmed_at.day))

        if r.overall_status_manual:
            self._f_manual.setChecked(True)
            idx = self._f_overall_status.findText(r.overall_status)
            self._f_overall_status.setCurrentIndex(idx if idx >= 0 else 0)

        if r.last_contacted_at:
            self._f_has_contact.setChecked(True)
            self._f_last_contacted.setDate(QDate(
                r.last_contacted_at.year, r.last_contacted_at.month, r.last_contacted_at.day))
        self._f_note.setPlainText(r.note or "")

        self._recalculate()

    def _recalculate(self):
        statuses = [combo.currentText() for combo in self._status_fields.values()]
        auto_status = compute_overall_status(statuses)
        self._r_auto_status.setText(auto_status)
        if not self._f_manual.isChecked():
            idx = self._f_overall_status.findText(auto_status)
            self._f_overall_status.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_open_activity_log(self):
        from app.ui.dialogs.activity_log_dialog import ActivityLogDialog
        from app.services.activity_service import ActivityService
        ActivityService(self._engine).get_or_create_category("年度更新について")
        ActivityLogDialog(
            self._engine, self._member.id, self._staff_name,
            self._member.org_name, parent=self,
            default_category_name="年度更新について",
        ).exec()

    def _on_save(self):
        items_data = {}
        for ins_type, combo in self._status_fields.items():
            confirmed_at = None
            if self._has_confirmed_fields[ins_type].isChecked():
                qd = self._confirmed_fields[ins_type].date()
                confirmed_at = date(qd.year(), qd.month(), qd.day())
            items_data[ins_type] = {
                "submission_status": combo.currentText(),
                "confirmed_at": confirmed_at,
            }

        last_contacted = None
        if self._f_has_contact.isChecked():
            qd2 = self._f_last_contacted.date()
            last_contacted = date(qd2.year(), qd2.month(), qd2.day())

        renewal_data = {
            "overall_status_manual": self._f_manual.isChecked(),
            "overall_status": self._f_overall_status.currentText() if self._f_manual.isChecked() else None,
            "last_contacted_at": last_contacted,
            "note": self._f_note.toPlainText(),
        }
        try:
            self._svc.update(self._renewal_id, items_data, renewal_data)
            self.saved = True
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", str(e))
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
