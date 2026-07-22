from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from app.services.fee_service import FeeService, calculate_fee
from app.services.member_service import INS_TYPES, MemberService


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


class QuickPremiumInputDialog(QDialog):
    """紙面を見ながら概算保険料だけを連続入力するための画面。"""

    def __init__(self, engine, record_ids: list[int], parent=None, on_record_saved=None):
        super().__init__(parent)
        if not record_ids:
            raise ValueError("入力対象の手数料レコードがありません。")
        self._svc = FeeService(engine)
        self._member_svc = MemberService(engine)
        self._record_ids = record_ids
        self._index = 0
        self._fields = {}
        self._on_record_saved = on_record_saved

        self.setWindowTitle("概算保険料を連続入力")
        self.setMinimumWidth(660)
        self._build_ui()
        self._load_current()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._progress = QLabel()
        self._progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._progress)
        self._save_status = QLabel()
        self._save_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._save_status.setStyleSheet("color: #16803c; font-weight: bold;")
        layout.addWidget(self._save_status)

        self._office_name = QLabel()
        self._office_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._office_name.setStyleSheet("font-size: 18pt; font-weight: bold;")
        layout.addWidget(self._office_name)
        self._office_detail = QLabel()
        self._office_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._office_detail)

        premium_group = QGroupBox("枝番別概算保険料（円）")
        self._premium_layout = QFormLayout(premium_group)
        layout.addWidget(premium_group)

        result_group = QGroupBox("自動計算結果")
        result_layout = QFormLayout(result_group)
        self._premium_total = QLabel()
        self._billing_total = QLabel()
        result_layout.addRow("概算保険料合計", self._premium_total)
        result_layout.addRow("請求合計", self._billing_total)
        layout.addWidget(result_group)

        buttons = QHBoxLayout()
        self._previous_btn = QPushButton("前へ")
        self._previous_btn.clicked.connect(self._on_previous)
        skip_btn = QPushButton("保留して次へ")
        skip_btn.clicked.connect(self._on_skip)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.reject)
        self._save_next_btn = QPushButton("保存して次へ")
        self._save_next_btn.clicked.connect(self._on_save_next)
        # 金額欄の Enter は枝番移動だけに使う。いずれの操作ボタンも
        # ダイアログの既定ボタンにはしない。
        for button in (self._previous_btn, skip_btn, close_btn, self._save_next_btn):
            button.setAutoDefault(False)
            button.setDefault(False)
        buttons.addWidget(self._previous_btn)
        buttons.addWidget(skip_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        buttons.addWidget(self._save_next_btn)
        layout.addLayout(buttons)

    def _clear_fields(self):
        while self._premium_layout.rowCount():
            self._premium_layout.removeRow(0)
        self._fields = {}

    def _load_current(self, saved_message: str = ""):
        self._record = self._svc.get(self._record_ids[self._index])
        self._member = self._member_svc.get(self._record.member_id)
        self._save_status.setText(saved_message)
        self._progress.setText(f"{self._index + 1} 件目 / {len(self._record_ids)} 件")
        self._office_name.setText(self._member.org_name)
        self._office_detail.setText(
            f"管理No. {self._member.company_code or ''}　会員No. {self._member.member_number or ''}")
        self._previous_btn.setEnabled(self._index > 0)
        self._save_next_btn.setText(
            "保存して完了" if self._index == len(self._record_ids) - 1 else "保存して次へ")

        self._clear_fields()
        entries = {entry.ins_type: entry for entry in self._member.insurance_entries}
        for ins_type in INS_TYPES:
            entry = entries.get(ins_type)
            if entry is None:
                continue
            label = BRANCH_LABEL[ins_type]
            if entry.ins_number:
                label += f"（番号: {entry.ins_number}）"
            field = QLineEdit()
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
            value = getattr(self._record, BRANCH_FIELD[ins_type])
            field.setText(str(value) if value else "")
            field.textChanged.connect(lambda text, widget=field: self._sanitize_and_recalculate(widget, text))
            field.returnPressed.connect(lambda t=ins_type: self._focus_next(t))
            self._premium_layout.addRow(label, field)
            self._fields[ins_type] = field

        self._recalculate()
        if self._fields:
            next(iter(self._fields.values())).setFocus()

    def _sanitize_and_recalculate(self, field, text):
        digits = "".join(char for char in text if char.isdigit())
        if digits != text:
            field.blockSignals(True)
            field.setText(digits)
            field.setCursorPosition(len(digits))
            field.blockSignals(False)
        self._recalculate()

    def _premiums(self) -> dict:
        premiums = {}
        for ins_type in INS_TYPES:
            field = self._fields.get(ins_type)
            key = BRANCH_FIELD[ins_type].replace("premium_", "")
            premiums[key] = int(field.text()) if field and field.text() else 0
        return premiums

    def _recalculate(self):
        rule = self._svc.get_or_create_rule(self._record.fiscal_year)
        calc = calculate_fee(self._premiums(), self._record.is_member_for_fee, rule)
        self._premium_total.setText(f"{calc['premium_total']:,} 円")
        self._billing_total.setText(f"{calc['total_amount']:,} 円")

    def _focus_next(self, ins_type):
        field_names = list(self._fields)
        index = field_names.index(ins_type)
        if index + 1 < len(field_names):
            self._fields[field_names[index + 1]].setFocus()
            self._fields[field_names[index + 1]].selectAll()
        else:
            # returnPressed の処理中に入力欄を破棄すると不安定になるため、
            # イベントが完了してから保存・次画面への遷移を行う。
            QTimer.singleShot(0, self._on_save_next)

    def _save_current(self) -> bool:
        premiums = self._premiums()
        data = {
            BRANCH_FIELD[ins_type]: premiums[BRANCH_FIELD[ins_type].replace("premium_", "")]
            for ins_type in INS_TYPES
        }
        try:
            self._svc.update(self._record.id, data)
            if self._on_record_saved:
                self._on_record_saved()
            return True
        except ValueError as error:
            QMessageBox.warning(self, "入力エラー", str(error))
        except Exception as error:
            QMessageBox.critical(self, "エラー", str(error))
        return False

    def _on_save_next(self):
        if not self._save_current():
            return
        if self._index == len(self._record_ids) - 1:
            self.accept()
            return
        self._index += 1
        self._load_current("保存しました")

    def _on_skip(self):
        if self._index == len(self._record_ids) - 1:
            self.accept()
            return
        self._index += 1
        self._load_current()

    def _on_previous(self):
        if self._index == 0:
            return
        self._index -= 1
        self._load_current()
