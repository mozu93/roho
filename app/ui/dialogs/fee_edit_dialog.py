# app/ui/dialogs/fee_edit_dialog.py
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QWidget,
    QLabel, QComboBox, QCheckBox, QLineEdit, QDateEdit, QTextEdit,
    QPushButton, QGroupBox, QMessageBox,
)
from PyQt6.QtCore import QDate
from app.services.fee_service import (
    FeeService, calculate_fee, determine_payment_period,
    PAYMENT_METHODS, PAYMENT_PERIODS, REMINDER_STATUSES,
)
from app.services.member_service import MemberService, INS_TYPES

BRANCH_FIELD = {
    "ippan": "premium_branch_0", "kensetsu_koyou": "premium_branch_2",
    "ringyo": "premium_branch_4", "kensetsu_genba": "premium_branch_5",
    "kensetsu_jimusho": "premium_branch_6",
}
BRANCH_LABEL = {
    "ippan": "枝番0（一般・労災＆雇用）", "kensetsu_koyou": "枝番2（建設業・他雇用）",
    "ringyo": "枝番4（林業・労災）", "kensetsu_genba": "枝番5（建設業・現場）",
    "kensetsu_jimusho": "枝番6（建設業・事務所）",
}


def _make_digit_handler(field):
    def _handler(text):
        converted = "".join(c for c in text if c.isdigit())
        if converted != text:
            field.blockSignals(True)
            field.setText(converted)
            field.setCursorPosition(len(converted))
            field.blockSignals(False)
    return _handler


class FeeEditDialog(QDialog):
    def __init__(self, engine, record_id: int, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._record_id = record_id
        self._svc = FeeService(engine)
        self._member_svc = MemberService(engine)
        self.saved = False

        self._record = self._svc.get(record_id)
        if self._record is None:
            raise ValueError(f"手数料レコードID {record_id} が見つかりません。")
        self._member = self._member_svc.get(self._record.member_id)
        self.setWindowTitle(f"手数料計算 — {self._member.org_name}")
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

        member_group = QGroupBox("会員区分")
        mfl = QFormLayout(member_group)
        mfl.addRow(QLabel(f"名簿の会員区分：{'会員' if self._member.is_member else '非会員'}"))
        self._f_override = QCheckBox("名簿と異なる区分に上書きする")
        self._f_is_member = QComboBox()
        self._f_is_member.addItem("会員", True)
        self._f_is_member.addItem("非会員", False)
        self._f_is_member.setEnabled(False)
        self._f_override_reason = QLineEdit()
        self._f_override_reason.setEnabled(False)
        self._f_override.toggled.connect(self._f_is_member.setEnabled)
        self._f_override.toggled.connect(self._f_override_reason.setEnabled)
        self._f_override.toggled.connect(self._recalculate)
        self._f_is_member.currentIndexChanged.connect(self._recalculate)
        mfl.addRow(self._f_override)
        mfl.addRow("上書き区分", self._f_is_member)
        mfl.addRow("上書き理由", self._f_override_reason)
        form_layout.addWidget(member_group)

        premium_group = QGroupBox("枝番別概算保険料（空欄は0円）")
        pfl = QFormLayout(premium_group)
        self._premium_fields = {}
        member_ins_types = {e.ins_type for e in self._member.insurance_entries}
        for ins_type in INS_TYPES:
            edit = QLineEdit()
            edit.setEnabled(ins_type in member_ins_types)
            edit.textChanged.connect(_make_digit_handler(edit))
            edit.textChanged.connect(self._recalculate)
            pfl.addRow(BRANCH_LABEL[ins_type], edit)
            self._premium_fields[ins_type] = edit
        form_layout.addWidget(premium_group)

        result_group = QGroupBox("計算結果（自動計算・編集不可）")
        rfl = QFormLayout(result_group)
        self._r_premium_total = QLabel("0円")
        self._r_five_percent = QLabel("0円")
        self._r_fee_without_tax = QLabel("0円")
        self._r_tax = QLabel("0円")
        self._r_total = QLabel("0円")
        rfl.addRow("概算保険料合計", self._r_premium_total)
        rfl.addRow("5%計算額", self._r_five_percent)
        rfl.addRow("税抜手数料", self._r_fee_without_tax)
        rfl.addRow("消費税", self._r_tax)
        rfl.addRow("請求合計", self._r_total)
        form_layout.addWidget(result_group)

        payment_group = QGroupBox("支払時期・支払方法")
        pyfl = QFormLayout(payment_group)
        self._f_lump_sum = QCheckBox("保険料を一括で支払う事業所")
        self._f_lump_sum.toggled.connect(self._recalculate)
        self._f_entrust_month = QDateEdit()
        self._f_entrust_month.setCalendarPopup(True)
        self._f_entrust_month.setDisplayFormat("yyyy-MM-dd")
        self._f_entrust_month.dateChanged.connect(self._recalculate)
        self._r_auto_period = QLabel("-")
        self._f_final_period = QComboBox()
        self._f_final_period.addItems(PAYMENT_PERIODS)
        self._f_period_reason = QLineEdit()
        self._f_period_reason.setPlaceholderText("自動判定と異なる場合は必須")
        self._f_payment_method = QComboBox()
        self._f_payment_method.addItems(PAYMENT_METHODS)
        pyfl.addRow(self._f_lump_sum)
        pyfl.addRow("委託開始年月", self._f_entrust_month)
        pyfl.addRow("自動判定支払時期", self._r_auto_period)
        pyfl.addRow("確定支払時期", self._f_final_period)
        pyfl.addRow("変更理由", self._f_period_reason)
        pyfl.addRow("支払方法", self._f_payment_method)
        form_layout.addWidget(payment_group)

        pay_group = QGroupBox("入金・督促")
        payfl = QFormLayout(pay_group)
        self._f_paid_amount = QLineEdit()
        self._f_paid_amount.textChanged.connect(_make_digit_handler(self._f_paid_amount))
        self._f_has_paid = QCheckBox("入金あり")
        self._f_paid_at = QDateEdit(QDate.currentDate())
        self._f_paid_at.setCalendarPopup(True)
        self._f_paid_at.setEnabled(False)
        self._f_has_paid.toggled.connect(self._f_paid_at.setEnabled)
        self._f_reminder_status = QComboBox()
        self._f_reminder_status.addItems(REMINDER_STATUSES)
        self._f_note = QTextEdit()
        self._f_note.setFixedHeight(60)
        payfl.addRow("入金額", self._f_paid_amount)
        payfl.addRow(self._f_has_paid)
        payfl.addRow("入金日", self._f_paid_at)
        payfl.addRow("督促状況", self._f_reminder_status)
        payfl.addRow("備考", self._f_note)
        form_layout.addWidget(pay_group)

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
        r = self._record
        if r.is_member_for_fee != self._member.is_member:
            self._f_override.setChecked(True)
        idx = self._f_is_member.findData(r.is_member_for_fee)
        self._f_is_member.setCurrentIndex(idx if idx >= 0 else 0)
        self._f_override_reason.setText(r.member_override_reason or "")

        for ins_type, field in self._premium_fields.items():
            value = getattr(r, BRANCH_FIELD[ins_type])
            field.setText(str(value) if value else "")

        self._f_lump_sum.setChecked(r.is_lump_sum_payment)
        if r.entrust_start_month:
            self._f_entrust_month.setDate(QDate(
                r.entrust_start_month.year, r.entrust_start_month.month,
                r.entrust_start_month.day))
        idx = self._f_final_period.findText(r.final_payment_period or "2期")
        self._f_final_period.setCurrentIndex(idx if idx >= 0 else 1)
        self._f_period_reason.setText(r.payment_period_override_reason or "")
        idx = self._f_payment_method.findText(r.payment_method or "")
        if idx >= 0:
            self._f_payment_method.setCurrentIndex(idx)

        self._f_paid_amount.setText(str(r.paid_amount) if r.paid_amount else "")
        if r.paid_at:
            self._f_has_paid.setChecked(True)
            self._f_paid_at.setDate(QDate(r.paid_at.year, r.paid_at.month, r.paid_at.day))
        idx = self._f_reminder_status.findText(r.reminder_status or "未督促")
        self._f_reminder_status.setCurrentIndex(idx if idx >= 0 else 0)
        self._f_note.setPlainText(r.note or "")

        self._recalculate()

    def _current_premiums(self) -> dict:
        result = {}
        for ins_type, field in self._premium_fields.items():
            text = field.text().strip()
            key = BRANCH_FIELD[ins_type].replace("premium_", "")
            result[key] = int(text) if text else 0
        return result

    def _recalculate(self):
        rule = self._svc.get_or_create_rule(self._record.fiscal_year)
        is_member = self._f_is_member.currentData() if self._f_override.isChecked() \
            else self._member.is_member
        calc = calculate_fee(self._current_premiums(), is_member, rule)
        self._r_premium_total.setText(f"{calc['premium_total']:,}円")
        self._r_five_percent.setText(f"{calc['five_percent_amount']:,}円")
        self._r_fee_without_tax.setText(f"{calc['fee_without_tax']:,}円")
        self._r_tax.setText(f"{calc['tax_amount']:,}円")
        self._r_total.setText(f"{calc['total_amount']:,}円")

        qd = self._f_entrust_month.date()
        entrust = date(qd.year(), qd.month(), qd.day())
        auto_period = determine_payment_period(
            self._record.fiscal_year, self._f_lump_sum.isChecked(), entrust)
        self._r_auto_period.setText(auto_period)

    def _on_save(self):
        is_member = self._f_is_member.currentData() if self._f_override.isChecked() \
            else self._member.is_member
        override_reason = self._f_override_reason.text().strip()
        if self._f_override.isChecked() and not override_reason:
            QMessageBox.warning(self, "入力エラー", "会員区分の上書き理由を入力してください。")
            return

        qd = self._f_entrust_month.date()
        entrust = date(qd.year(), qd.month(), qd.day())

        paid_amount_text = self._f_paid_amount.text().strip()
        paid_amount = int(paid_amount_text) if paid_amount_text else None
        paid_at = None
        if self._f_has_paid.isChecked():
            qd2 = self._f_paid_at.date()
            paid_at = date(qd2.year(), qd2.month(), qd2.day())

        premiums = self._current_premiums()
        data = {
            "is_member_for_fee": is_member,
            "member_override_reason": override_reason if self._f_override.isChecked() else None,
            "premium_branch_0": premiums["branch_0"],
            "premium_branch_2": premiums["branch_2"],
            "premium_branch_4": premiums["branch_4"],
            "premium_branch_5": premiums["branch_5"],
            "premium_branch_6": premiums["branch_6"],
            "is_lump_sum_payment": self._f_lump_sum.isChecked(),
            "entrust_start_month": entrust,
            "final_payment_period": self._f_final_period.currentText(),
            "payment_period_override_reason": self._f_period_reason.text().strip(),
            "payment_method": self._f_payment_method.currentText(),
            "paid_amount": paid_amount,
            "paid_at": paid_at,
            "reminder_status": self._f_reminder_status.currentText(),
            "note": self._f_note.toPlainText(),
        }
        try:
            self._svc.update(self._record_id, data)
            self.saved = True
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", str(e))
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
