# app/ui/dialogs/member_edit_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QGroupBox, QComboBox,
    QPushButton, QScrollArea, QWidget, QLabel, QMessageBox,
)
from app.services.member_service import MemberService, INS_TYPES

INS_LABELS = {
    "ippan":            "一般・労＆雇（枝番0）",
    "kensetsu_koyou":   "建設業・他雇用（枝番2）",
    "ringyo":           "林業・労災（枝番4）",
    "kensetsu_genba":   "建設業・現場（枝番5）",
    "kensetsu_jimusho": "建設業・事務所（枝番6）",
}
BRANCH_NUMBERS = {
    "ippan": "0", "kensetsu_koyou": "2",
    "ringyo": "4", "kensetsu_genba": "5", "kensetsu_jimusho": "6",
}


class MemberEditDialog(QDialog):
    def __init__(self, engine, staff_name: str, member_id: int | None = None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self._member_id = member_id
        self._svc = MemberService(engine)
        self.saved = False
        self.setWindowTitle("編集" if member_id else "新規登録")
        self.setMinimumWidth(620)
        self.resize(640, 580)
        self._build_ui()
        if member_id:
            self._load_member(member_id)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)

        # 基本情報
        basic = QGroupBox("基本情報")
        fl = QFormLayout(basic)
        self._f_is_member = QComboBox()
        self._f_is_member.addItem("会員", True)
        self._f_is_member.addItem("非会員", False)
        self._f_member_number = QLineEdit()
        self._f_org_name = QLineEdit()
        self._f_org_kana = QLineEdit()
        self._f_dept_title = QLineEdit()
        self._f_rep_name = QLineEdit()
        self._f_rep_kana = QLineEdit()
        self._f_email = QLineEdit()
        self._f_tel_area = QLineEdit(); self._f_tel_area.setFixedWidth(60)
        self._f_tel = QLineEdit()
        self._f_fax_area = QLineEdit(); self._f_fax_area.setFixedWidth(60)
        self._f_fax = QLineEdit()
        self._f_postal_code = QLineEdit()
        self._f_address = QLineEdit()
        self._f_postal_code_mail = QLineEdit()
        self._f_address_mail = QLineEdit()
        self._f_addressee_mail = QLineEdit()
        self._f_employment_ins_no = QLineEdit()
        self._f_note = QTextEdit(); self._f_note.setFixedHeight(60)
        tel_row = QHBoxLayout()
        tel_row.addWidget(self._f_tel_area)
        tel_row.addWidget(QLabel("-"))
        tel_row.addWidget(self._f_tel)
        fax_row = QHBoxLayout()
        fax_row.addWidget(self._f_fax_area)
        fax_row.addWidget(QLabel("-"))
        fax_row.addWidget(self._f_fax)
        fl.addRow("種別*", self._f_is_member)
        fl.addRow("会員No.", self._f_member_number)
        fl.addRow("事業所名*", self._f_org_name)
        fl.addRow("フリガナ", self._f_org_kana)
        fl.addRow("所属・役職", self._f_dept_title)
        fl.addRow("代表者名", self._f_rep_name)
        fl.addRow("代表者フリガナ", self._f_rep_kana)
        fl.addRow("メール", self._f_email)
        fl.addRow("電話", tel_row)
        fl.addRow("FAX", fax_row)
        fl.addRow("郵便番号", self._f_postal_code)
        fl.addRow("住所", self._f_address)
        fl.addRow("郵送先郵便番号", self._f_postal_code_mail)
        fl.addRow("郵送先住所", self._f_address_mail)
        fl.addRow("郵送先宛名", self._f_addressee_mail)
        fl.addRow("雇用保険事業所番号", self._f_employment_ins_no)
        fl.addRow("メモ", self._f_note)
        form_layout.addWidget(basic)

        # 保険番号
        ins_group = QGroupBox("保険番号")
        ins_layout = QVBoxLayout(ins_group)
        self._ins_widgets = {}
        for ins_type in INS_TYPES:
            row = QHBoxLayout()
            chk = QCheckBox(INS_LABELS[ins_type])
            chk.setFixedWidth(220)
            num_edit = QLineEdit(); num_edit.setPlaceholderText("番号")
            tokubetsu_chk = QCheckBox("特別加入")
            ikkatsu_chk = QCheckBox("継続一括")
            row.addWidget(chk)
            row.addWidget(num_edit)
            row.addWidget(tokubetsu_chk)
            row.addWidget(ikkatsu_chk)
            ins_layout.addLayout(row)
            self._ins_widgets[ins_type] = (chk, num_edit, tokubetsu_chk, ikkatsu_chk)
            chk.toggled.connect(lambda checked, n=num_edit, t=tokubetsu_chk, k=ikkatsu_chk: (
                n.setEnabled(checked), t.setEnabled(checked), k.setEnabled(checked)
            ))
            num_edit.setEnabled(False); tokubetsu_chk.setEnabled(False); ikkatsu_chk.setEnabled(False)
        form_layout.addWidget(ins_group)

        # 変更理由
        self._reason_group = QGroupBox("変更理由（必須）")
        rl = QVBoxLayout(self._reason_group)
        self._f_reason = QLineEdit()
        self._f_reason.setPlaceholderText("例：住所変更、保険番号追加")
        rl.addWidget(self._f_reason)
        form_layout.addWidget(self._reason_group)

        # 新規作成時は変更理由を非表示
        if not self._member_id:
            self._reason_group.setVisible(False)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # ボタン
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

    def _load_member(self, member_id: int):
        m = self._svc.get(member_id)
        if not m:
            return
        idx = 0 if getattr(m, "is_member", True) else 1
        self._f_is_member.setCurrentIndex(idx)
        self._f_member_number.setText(m.member_number or "")
        self._f_org_name.setText(m.org_name or "")
        self._f_org_kana.setText(m.org_kana or "")
        self._f_dept_title.setText(m.dept_title or "")
        self._f_rep_name.setText(m.rep_name or "")
        self._f_rep_kana.setText(m.rep_kana or "")
        self._f_email.setText(m.email or "")
        self._f_tel_area.setText(m.tel_area or "")
        self._f_tel.setText(m.tel or "")
        self._f_fax_area.setText(m.fax_area or "")
        self._f_fax.setText(m.fax or "")
        self._f_postal_code.setText(m.postal_code or "")
        self._f_address.setText(m.address or "")
        self._f_postal_code_mail.setText(m.postal_code_mail or "")
        self._f_address_mail.setText(m.address_mail or "")
        self._f_addressee_mail.setText(m.addressee_mail or "")
        self._f_employment_ins_no.setText(m.employment_ins_no or "")
        self._f_note.setPlainText(m.note or "")
        for e in m.insurance_entries:
            if e.ins_type in self._ins_widgets:
                chk, num_edit, tok_chk, ika_chk = self._ins_widgets[e.ins_type]
                chk.setChecked(True)
                num_edit.setText(e.ins_number or "")
                tok_chk.setChecked(e.is_tokubetsu)
                ika_chk.setChecked(e.is_ikkatsu)

    def _collect_data(self) -> dict:
        entries = []
        for ins_type, (chk, num_edit, tok_chk, ika_chk) in self._ins_widgets.items():
            if chk.isChecked():
                entries.append({
                    "ins_type": ins_type,
                    "branch_number": BRANCH_NUMBERS[ins_type],
                    "ins_number": num_edit.text().strip(),
                    "is_tokubetsu": tok_chk.isChecked(),
                    "is_ikkatsu": ika_chk.isChecked(),
                })
        return {
            "is_member": self._f_is_member.currentData(),
            "member_number": self._f_member_number.text().strip() or None,
            "org_name": self._f_org_name.text().strip(),
            "org_kana": self._f_org_kana.text().strip(),
            "dept_title": self._f_dept_title.text().strip(),
            "rep_name": self._f_rep_name.text().strip(),
            "rep_kana": self._f_rep_kana.text().strip(),
            "email": self._f_email.text().strip(),
            "tel_area": self._f_tel_area.text().strip(),
            "tel": self._f_tel.text().strip(),
            "fax_area": self._f_fax_area.text().strip(),
            "fax": self._f_fax.text().strip(),
            "postal_code": self._f_postal_code.text().strip(),
            "address": self._f_address.text().strip(),
            "postal_code_mail": self._f_postal_code_mail.text().strip(),
            "address_mail": self._f_address_mail.text().strip(),
            "addressee_mail": self._f_addressee_mail.text().strip(),
            "employment_ins_no": self._f_employment_ins_no.text().strip(),
            "note": self._f_note.toPlainText().strip(),
            "insurance_entries": entries,
        }

    def _on_save(self):
        data = self._collect_data()
        if data["is_member"] and not data["member_number"]:
            QMessageBox.warning(self, "入力エラー", "会員の場合、会員No.は必須です。")
            return
        if not data["org_name"]:
            QMessageBox.warning(self, "入力エラー", "事業所名は必須です。")
            return
        try:
            if self._member_id:
                reason = self._f_reason.text().strip()
                if not reason:
                    QMessageBox.warning(self, "入力エラー", "変更理由を入力してください。")
                    return
                self._svc.update(self._member_id, data, reason, self._staff_name)
            else:
                self._svc.create(data, self._staff_name)
            self.saved = True
            self.accept()
        except Exception as e:
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError):
                QMessageBox.critical(self, "保存エラー", "同じ会員No.が既に存在します。別の会員No.を入力してください。")
            else:
                QMessageBox.critical(self, "保存エラー", str(e))
