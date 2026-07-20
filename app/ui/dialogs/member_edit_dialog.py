# app/ui/dialogs/member_edit_dialog.py
import urllib.request
import json as _json
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QGroupBox, QComboBox,
    QPushButton, QScrollArea, QWidget, QLabel, QMessageBox, QDateEdit,
)
from PyQt6.QtCore import Qt, QDate
from app.services.member_service import MemberService, INS_TYPES
from app.utils.kana import to_halfwidth_kana

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
    def __init__(self, engine, staff_name: str, member_id: int | None = None,
                 show_withdraw_info: bool = False, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self._member_id = member_id
        self._show_withdraw_info = show_withdraw_info
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

        # 委託解除情報（委託解除タブからの表示時のみ）
        if self._show_withdraw_info:
            withdraw_group = QGroupBox("委託解除情報")
            wfl = QFormLayout(withdraw_group)
            self._f_withdrawn_at = QLabel()
            self._f_withdraw_reason = QLabel()
            self._f_withdraw_reason.setWordWrap(True)
            wfl.addRow("委託解除日", self._f_withdrawn_at)
            wfl.addRow("委託解除理由", self._f_withdraw_reason)
            form_layout.addWidget(withdraw_group)

        # 基本情報
        basic = QGroupBox("基本情報")
        fl = QFormLayout(basic)

        self._f_is_member = QComboBox()
        self._f_is_member.addItem("会員", True)
        self._f_is_member.addItem("非会員", False)
        self._f_registered_date = QDateEdit()
        self._f_registered_date.setCalendarPopup(True)
        self._f_registered_date.setDisplayFormat("yyyy-MM-dd")
        self._f_registered_date.setDate(QDate.currentDate())
        self._f_member_number = QLineEdit()
        self._f_org_name = QLineEdit()
        self._f_org_kana = QLineEdit()
        self._f_org_kana.setPlaceholderText("半角カタカナ（自動変換）")
        self._f_dept_title = QLineEdit()
        self._f_rep_name = QLineEdit()
        self._f_rep_kana = QLineEdit()
        self._f_rep_kana.setPlaceholderText("半角カタカナ（自動変換）")
        self._f_email = QLineEdit()

        # 電話（3分割: 市外局番 - 局番 - 番号）
        self._f_tel_area = QLineEdit()
        self._f_tel_area.setFixedWidth(55)
        self._f_tel_area.setPlaceholderText("059")
        self._f_tel_prefix = QLineEdit()
        self._f_tel_prefix.setFixedWidth(55)
        self._f_tel_prefix.setPlaceholderText("352")
        self._f_tel_number = QLineEdit()
        self._f_tel_number.setPlaceholderText("8192")
        tel_row = QHBoxLayout()
        tel_row.addWidget(self._f_tel_area)
        tel_row.addWidget(QLabel("-"))
        tel_row.addWidget(self._f_tel_prefix)
        tel_row.addWidget(QLabel("-"))
        tel_row.addWidget(self._f_tel_number)

        # FAX（3分割: 市外局番 - 局番 - 番号）
        self._f_fax_area = QLineEdit()
        self._f_fax_area.setFixedWidth(55)
        self._f_fax_area.setPlaceholderText("059")
        self._f_fax_prefix = QLineEdit()
        self._f_fax_prefix.setFixedWidth(55)
        self._f_fax_number = QLineEdit()
        fax_row = QHBoxLayout()
        fax_row.addWidget(self._f_fax_area)
        fax_row.addWidget(QLabel("-"))
        fax_row.addWidget(self._f_fax_prefix)
        fax_row.addWidget(QLabel("-"))
        fax_row.addWidget(self._f_fax_number)

        # 郵便番号（2分割: NNN - NNNN + 住所検索ボタン）
        self._f_postal_code_1 = QLineEdit()
        self._f_postal_code_1.setFixedWidth(42)
        self._f_postal_code_1.setMaxLength(3)
        self._f_postal_code_1.setPlaceholderText("514")
        self._f_postal_code_2 = QLineEdit()
        self._f_postal_code_2.setFixedWidth(50)
        self._f_postal_code_2.setMaxLength(4)
        self._f_postal_code_2.setPlaceholderText("0008")
        self._f_address = QLineEdit()
        self._f_address2 = QLineEdit()
        self._f_address2.setPlaceholderText("建物名・部屋番号等")
        pc_lookup_btn = QPushButton("住所検索")
        pc_lookup_btn.setFixedWidth(85)
        pc_lookup_btn.clicked.connect(
            lambda: self._lookup_address(
                self._f_postal_code_1, self._f_postal_code_2, self._f_address))
        pc_row = QHBoxLayout()
        pc_row.addWidget(self._f_postal_code_1)
        pc_row.addWidget(QLabel("-"))
        pc_row.addWidget(self._f_postal_code_2)
        pc_row.addWidget(pc_lookup_btn)
        pc_row.addStretch()

        # 郵送先郵便番号（2分割）
        self._f_postal_code_mail_1 = QLineEdit()
        self._f_postal_code_mail_1.setFixedWidth(42)
        self._f_postal_code_mail_1.setMaxLength(3)
        self._f_postal_code_mail_1.setPlaceholderText("514")
        self._f_postal_code_mail_2 = QLineEdit()
        self._f_postal_code_mail_2.setFixedWidth(50)
        self._f_postal_code_mail_2.setMaxLength(4)
        self._f_postal_code_mail_2.setPlaceholderText("0008")
        self._f_address_mail = QLineEdit()
        self._f_address_mail2 = QLineEdit()
        self._f_address_mail2.setPlaceholderText("建物名・部屋番号等")
        pcm_lookup_btn = QPushButton("住所検索")
        pcm_lookup_btn.setFixedWidth(85)
        pcm_lookup_btn.clicked.connect(
            lambda: self._lookup_address(
                self._f_postal_code_mail_1, self._f_postal_code_mail_2, self._f_address_mail))
        pcm_row = QHBoxLayout()
        pcm_row.addWidget(self._f_postal_code_mail_1)
        pcm_row.addWidget(QLabel("-"))
        pcm_row.addWidget(self._f_postal_code_mail_2)
        pcm_row.addWidget(pcm_lookup_btn)
        pcm_row.addStretch()

        self._f_mail_org_name = QLineEdit()
        self._f_mail_dept_title = QLineEdit()
        self._f_mail_person_name = QLineEdit()
        self._f_employment_ins_no = QLineEdit()
        self._f_note = QTextEdit()
        self._f_note.setFixedHeight(60)

        fl.addRow("種別*", self._f_is_member)
        fl.addRow("登録日", self._f_registered_date)
        fl.addRow("会員No.", self._f_member_number)
        fl.addRow("事業所名*", self._f_org_name)
        fl.addRow("フリガナ", self._f_org_kana)
        fl.addRow("所属・役職", self._f_dept_title)
        fl.addRow("代表者名", self._f_rep_name)
        fl.addRow("代表者フリガナ", self._f_rep_kana)
        fl.addRow("メール", self._f_email)
        fl.addRow("電話", tel_row)
        fl.addRow("FAX", fax_row)
        addr_layout = QVBoxLayout()
        addr_layout.setSpacing(3)
        addr_layout.addWidget(self._f_address)
        addr_layout.addWidget(self._f_address2)
        addr_mail_layout = QVBoxLayout()
        addr_mail_layout.setSpacing(3)
        addr_mail_layout.addWidget(self._f_address_mail)
        addr_mail_layout.addWidget(self._f_address_mail2)
        fl.addRow("郵便番号", pc_row)
        fl.addRow("住所", addr_layout)
        fl.addRow("郵送先郵便番号", pcm_row)
        fl.addRow("郵送先住所", addr_mail_layout)
        fl.addRow("郵送先事業所名", self._f_mail_org_name)
        fl.addRow("郵送先所属・役職名", self._f_mail_dept_title)
        fl.addRow("郵送先氏名", self._f_mail_person_name)
        fl.addRow("雇用保険事業所番号", self._f_employment_ins_no)
        fl.addRow("メモ", self._f_note)
        form_layout.addWidget(basic)

        # フリガナ自動変換（入力中にリアルタイムで半角カタカナへ）
        for field in (self._f_org_kana, self._f_rep_kana):
            def _make_kana_handler(f):
                def _handler(text):
                    converted = to_halfwidth_kana(text)
                    if converted != text:
                        f.blockSignals(True)
                        f.setText(converted)
                        f.setCursorPosition(len(converted))
                        f.blockSignals(False)
                return _handler
            field.textChanged.connect(_make_kana_handler(field))

        # 数字入力フィールドの半角変換ハンドラ（allow_hyphen=True でハイフンも許可）
        def _make_digit_handler(f, allow_hyphen=False):
            def _handler(text):
                result = []
                for c in text:
                    if '0' <= c <= '9':
                        result.append(c)
                    elif '０' <= c <= '９':
                        result.append(chr(ord(c) - 0xFEE0))
                    elif allow_hyphen and c == '-':
                        result.append(c)
                    elif allow_hyphen and c == '－':  # 全角ハイフン
                        result.append('-')
                converted = ''.join(result)
                if converted != text:
                    f.blockSignals(True)
                    f.setText(converted)
                    f.setCursorPosition(min(f.cursorPosition(), len(converted)))
                    f.blockSignals(False)
            return _handler

        # 数字のみ（ハイフンは画面上の区切り文字として表示するため入力不要）
        for _f in (
            self._f_tel_area, self._f_tel_prefix, self._f_tel_number,
            self._f_fax_area, self._f_fax_prefix, self._f_fax_number,
            self._f_postal_code_1, self._f_postal_code_2,
            self._f_postal_code_mail_1, self._f_postal_code_mail_2,
        ):
            _f.textChanged.connect(_make_digit_handler(_f))
        # 数字とハイフン
        for _f in (self._f_employment_ins_no,):
            _f.textChanged.connect(_make_digit_handler(_f, allow_hyphen=True))

        # 郵便番号 3桁入力後に自動で次フィールドへ移動
        self._f_postal_code_1.textChanged.connect(
            lambda t: self._f_postal_code_2.setFocus() if len(t) >= 3 else None)
        self._f_postal_code_mail_1.textChanged.connect(
            lambda t: self._f_postal_code_mail_2.setFocus() if len(t) >= 3 else None)

        # 保険番号
        ins_group = QGroupBox("保険番号")
        ins_layout = QVBoxLayout(ins_group)
        self._ins_widgets = {}
        for ins_type in INS_TYPES:
            row = QHBoxLayout()
            chk = QCheckBox(INS_LABELS[ins_type])
            chk.setFixedWidth(220)
            num_edit = QLineEdit()
            num_edit.setPlaceholderText("番号")
            num_edit.textChanged.connect(_make_digit_handler(num_edit, allow_hyphen=True))
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
            num_edit.setEnabled(False)
            tokubetsu_chk.setEnabled(False)
            ikkatsu_chk.setEnabled(False)
        form_layout.addWidget(ins_group)

        # 変更理由
        self._reason_group = QGroupBox("変更理由（省略可）")
        rl = QVBoxLayout(self._reason_group)
        self._f_reason = QLineEdit()
        self._f_reason.setPlaceholderText("例：住所変更、保険番号追加")
        rl.addWidget(self._f_reason)
        form_layout.addWidget(self._reason_group)

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

    # ── ユーティリティ ──────────────────────────────────────────────────────

    @staticmethod
    def _split_postal(raw: str) -> tuple[str, str]:
        """郵便番号を (上3桁, 下4桁) に分割"""
        digits = (raw or "").replace("-", "").strip()
        return digits[:3], digits[3:7]

    # ── データ入出力 ─────────────────────────────────────────────────────────

    def _load_member(self, member_id: int):
        m = self._svc.get(member_id)
        if not m:
            return
        if self._show_withdraw_info:
            self._f_withdrawn_at.setText(
                m.withdrawn_at.strftime("%Y-%m-%d") if m.withdrawn_at else "（未設定）")
            self._f_withdraw_reason.setText(m.withdraw_reason or "（未設定）")

        idx = 0 if getattr(m, "is_member", True) else 1
        self._f_is_member.setCurrentIndex(idx)
        if m.registered_date:
            self._f_registered_date.setDate(
                QDate(m.registered_date.year, m.registered_date.month, m.registered_date.day))
        self._f_member_number.setText(m.member_number or "")
        self._f_org_name.setText(m.org_name or "")
        self._f_org_kana.setText(m.org_kana or "")
        self._f_dept_title.setText(m.dept_title or "")
        self._f_rep_name.setText(m.rep_name or "")
        self._f_rep_kana.setText(m.rep_kana or "")
        self._f_email.setText(m.email or "")

        self._f_tel_area.setText(m.tel_area or "")
        _tel_parts = (m.tel or "").split("-", 1)
        self._f_tel_prefix.setText(_tel_parts[0])
        self._f_tel_number.setText(_tel_parts[1] if len(_tel_parts) > 1 else "")
        self._f_fax_area.setText(m.fax_area or "")
        _fax_parts = (m.fax or "").split("-", 1)
        self._f_fax_prefix.setText(_fax_parts[0])
        self._f_fax_number.setText(_fax_parts[1] if len(_fax_parts) > 1 else "")

        pc1, pc2 = self._split_postal(m.postal_code)
        self._f_postal_code_1.setText(pc1)
        self._f_postal_code_2.setText(pc2)
        addr_lines = (m.address or "").split("\n", 1)
        self._f_address.setText(addr_lines[0])
        self._f_address2.setText(addr_lines[1] if len(addr_lines) > 1 else "")

        pcm1, pcm2 = self._split_postal(m.postal_code_mail)
        self._f_postal_code_mail_1.setText(pcm1)
        self._f_postal_code_mail_2.setText(pcm2)
        addr_mail_lines = (m.address_mail or "").split("\n", 1)
        self._f_address_mail.setText(addr_mail_lines[0])
        self._f_address_mail2.setText(addr_mail_lines[1] if len(addr_mail_lines) > 1 else "")
        self._f_mail_org_name.setText(m.mail_org_name or "")
        self._f_mail_dept_title.setText(m.mail_dept_title or "")
        self._f_mail_person_name.setText(m.mail_person_name or "")
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
                    "ins_type":      ins_type,
                    "branch_number": BRANCH_NUMBERS[ins_type],
                    "ins_number":    num_edit.text().strip(),
                    "is_tokubetsu":  tok_chk.isChecked(),
                    "is_ikkatsu":    ika_chk.isChecked(),
                })

        pc1   = self._f_postal_code_1.text().strip()
        pc2   = self._f_postal_code_2.text().strip()
        pcm1  = self._f_postal_code_mail_1.text().strip()
        pcm2  = self._f_postal_code_mail_2.text().strip()

        return {
            "is_member":         self._f_is_member.currentData(),
            "registered_date":   self._f_registered_date.date().toPyDate(),
            "member_number":     self._f_member_number.text().strip() or None,
            "org_name":          self._f_org_name.text().strip(),
            "org_kana":          self._f_org_kana.text().strip(),
            "dept_title":        self._f_dept_title.text().strip(),
            "rep_name":          self._f_rep_name.text().strip(),
            "rep_kana":          self._f_rep_kana.text().strip(),
            "email":             self._f_email.text().strip(),
            "tel_area":          self._f_tel_area.text().strip(),
            "tel":               "-".join(x for x in [
                                     self._f_tel_prefix.text().strip(),
                                     self._f_tel_number.text().strip()] if x),
            "fax_area":          self._f_fax_area.text().strip(),
            "fax":               "-".join(x for x in [
                                     self._f_fax_prefix.text().strip(),
                                     self._f_fax_number.text().strip()] if x),
            "postal_code":       f"{pc1}-{pc2}" if pc1 and pc2 else (pc1 or ""),
            "address":           "\n".join(x for x in [
                                     self._f_address.text().strip(),
                                     self._f_address2.text().strip()] if x),
            "postal_code_mail":  f"{pcm1}-{pcm2}" if pcm1 and pcm2 else (pcm1 or ""),
            "address_mail":      "\n".join(x for x in [
                                     self._f_address_mail.text().strip(),
                                     self._f_address_mail2.text().strip()] if x),
            "mail_org_name":     self._f_mail_org_name.text().strip(),
            "mail_dept_title":   self._f_mail_dept_title.text().strip(),
            "mail_person_name":  self._f_mail_person_name.text().strip(),
            "employment_ins_no": self._f_employment_ins_no.text().strip(),
            "note":              self._f_note.toPlainText().strip(),
            "insurance_entries": entries,
        }

    # ── 住所検索 ─────────────────────────────────────────────────────────────

    def _lookup_address(self, pc1: QLineEdit, pc2: QLineEdit, addr_field: QLineEdit):
        zipcode = pc1.text().strip() + pc2.text().strip()
        if len(zipcode) != 7 or not zipcode.isdigit():
            QMessageBox.warning(self, "住所検索", "郵便番号を7桁の数字で入力してください。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            url = f"https://zipcloud.ibsnet.co.jp/api/search?zipcode={zipcode}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "住所検索エラー", f"住所を取得できませんでした。\n{e}")
            return
        QApplication.restoreOverrideCursor()
        results = data.get("results")
        if not results:
            QMessageBox.information(self, "住所検索", "該当する住所が見つかりませんでした。")
            return
        r = results[0]
        addr_field.setText(r.get("address1", "") + r.get("address2", "") + r.get("address3", ""))

    # ── 保存 ─────────────────────────────────────────────────────────────────

    def _on_save(self):
        data = self._collect_data()
        if data["is_member"] and not data["member_number"]:
            QMessageBox.warning(self, "入力エラー", "会員の場合、会員No.は必須です。")
            return
        if not data["org_name"]:
            QMessageBox.warning(self, "入力エラー", "事業所名は必須です。")
            return
        if data["member_number"]:
            dup = self._svc.find_by_member_number(data["member_number"])
            if dup and dup.id != self._member_id:
                QMessageBox.warning(
                    self, "入力エラー",
                    f"会員No.「{data['member_number']}」は既に「{dup.org_name}」で使用されています。",
                )
                return
        for entry in data["insurance_entries"]:
            if entry["ins_number"]:
                dup = self._svc.find_ins_number_conflict(
                    entry["branch_number"], entry["ins_number"],
                    exclude_member_id=self._member_id,
                )
                if dup:
                    QMessageBox.warning(
                        self, "入力エラー",
                        f"枝番「{entry['branch_number']}」の番号「{entry['ins_number']}」は"
                        f"既に「{dup.org_name}」で使用されています。",
                    )
                    return
        try:
            if self._member_id:
                reason = self._f_reason.text().strip()
                self._svc.update(self._member_id, data, reason, self._staff_name)
            else:
                self._svc.create(data, self._staff_name)
            self.saved = True
            self.accept()
        except Exception as e:
            from sqlalchemy.exc import IntegrityError
            if isinstance(e, IntegrityError):
                QMessageBox.critical(self, "保存エラー",
                    "同じ会員No.が既に存在します。別の会員No.を入力してください。")
            else:
                QMessageBox.critical(self, "保存エラー", str(e))
