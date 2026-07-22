from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout,
    QLabel, QLineEdit, QMessageBox, QVBoxLayout, QPushButton, QHBoxLayout,
    QInputDialog,
)

from app.services.bank_account_service import BankAccountService, normalize_recipient_name
from app.services.bank_master_service import BankMasterService


class BankAccountDialog(QDialog):
    def __init__(self, engine, member_id: int, account_id: int | None = None, parent=None):
        super().__init__(parent)
        self._service = BankAccountService(engine)
        self._master_service = BankMasterService()
        self._member_id = member_id
        self._account_id = account_id
        self.saved = False
        self.setWindowTitle("振込先口座の編集" if account_id else "振込先口座の追加")
        self.setMinimumWidth(480)
        self._build_ui()
        if account_id:
            self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.bank_code = QLineEdit()
        self.bank_code.setPlaceholderText("銀行選択で自動入力")
        self.bank_name = QLineEdit()
        self.bank_name.setPlaceholderText("例：百五")
        self.branch_code = QLineEdit()
        self.branch_code.setPlaceholderText("支店選択で自動入力")
        self.branch_name = QLineEdit()
        self.branch_name.setPlaceholderText("例：旭が丘")
        self.account_type = QComboBox()
        self.account_type.addItem("普通", "1")
        self.account_type.addItem("当座", "2")
        self.account_type.addItem("貯蓄", "4")
        self.account_number = QLineEdit()
        self.recipient_name = QLineEdit()
        self.recipient_name.setPlaceholderText("例：ｶ)ｻﾝﾌﾟﾙ")
        self.normalized_preview = QLabel()
        self.normalized_preview.setStyleSheet("color: #666;")
        self.is_enabled = QCheckBox("使用可能")
        self.is_enabled.setChecked(True)

        for field, length in ((self.bank_code, 4), (self.branch_code, 3),
                              (self.account_number, 7)):
            field.setMaxLength(length)
            field.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]*")))

        bank_search_button = QPushButton("銀行を検索")
        bank_search_button.clicked.connect(self._search_bank)
        bank_row = QHBoxLayout()
        bank_row.addWidget(self.bank_name, 1)
        bank_row.addWidget(bank_search_button)
        branch_search_button = QPushButton("支店を検索")
        branch_search_button.clicked.connect(self._search_branch)
        branch_row = QHBoxLayout()
        branch_row.addWidget(self.branch_name, 1)
        branch_row.addWidget(branch_search_button)

        guide = QLabel(
            "銀行名・支店名の一部を入力して検索してください。\n"
            "選択するとコードが自動入力されます。"
        )
        guide.setWordWrap(True)
        guide.setStyleSheet("color: #4b5563; background: #f3f4f6; padding: 8px;")
        layout.addWidget(guide)
        form.addRow("金融機関名*", bank_row)
        form.addRow("金融機関コード", self.bank_code)
        form.addRow("支店名*", branch_row)
        form.addRow("支店コード", self.branch_code)
        form.addRow("預金種目*", self.account_type)
        form.addRow("口座番号*", self.account_number)
        form.addRow("受取人名カナ*", self.recipient_name)
        form.addRow("保存される表記", self.normalized_preview)
        form.addRow("使用可否", self.is_enabled)
        layout.addLayout(form)

        self.recipient_name.textChanged.connect(
            lambda text: self.normalized_preview.setText(normalize_recipient_name(text))
        )
        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_button = QPushButton("キャンセル")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("保存")
        save_button.setDefault(True)
        save_button.clicked.connect(self._save)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    @staticmethod
    def _display_name(item: dict) -> str:
        normalized = item.get("normalize") or {}
        return normalized.get("name") or item.get("name") or "名称不明"

    def _search_bank(self):
        try:
            results = self._master_service.search_banks(self.bank_name.text())
        except ValueError as exc:
            QMessageBox.warning(self, "銀行検索", str(exc))
            return
        except Exception:
            QMessageBox.warning(
                self, "銀行検索",
                "銀行情報を取得できませんでした。ネット接続を確認してください。\n"
                "接続できない場合は名称とコードを手入力できます。",
            )
            return
        if not results:
            QMessageBox.information(self, "銀行検索", "該当する金融機関がありません。")
            return
        labels = [f"{self._display_name(item)}（{item.get('code', '')}）" for item in results]
        selected, ok = QInputDialog.getItem(
            self, "銀行を選択", "金融機関", labels, 0, False
        )
        if ok:
            item = results[labels.index(selected)]
            self.bank_name.setText(self._display_name(item))
            self.bank_code.setText(str(item.get("code", "")).zfill(4))
            self.branch_name.clear()
            self.branch_code.clear()

    def _search_branch(self):
        try:
            results = self._master_service.search_branches(
                self.bank_code.text(), self.branch_name.text()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "支店検索", str(exc))
            return
        except Exception:
            QMessageBox.warning(
                self, "支店検索",
                "支店情報を取得できませんでした。ネット接続を確認してください。\n"
                "接続できない場合は名称とコードを手入力できます。",
            )
            return
        if not results:
            QMessageBox.information(self, "支店検索", "該当する支店がありません。")
            return
        labels = [f"{self._display_name(item)}（{item.get('code', '')}）" for item in results]
        selected, ok = QInputDialog.getItem(
            self, "支店を選択", "支店", labels, 0, False
        )
        if ok:
            item = results[labels.index(selected)]
            self.branch_name.setText(self._display_name(item))
            self.branch_code.setText(str(item.get("code", "")).zfill(3))

    def _data(self):
        return {
            "bank_code": self.bank_code.text(),
            "bank_name": self.bank_name.text(),
            "branch_code": self.branch_code.text(),
            "branch_name": self.branch_name.text(),
            "account_type": self.account_type.currentData(),
            "account_number": self.account_number.text(),
            "recipient_name_kana": self.recipient_name.text(),
            "is_enabled": self.is_enabled.isChecked(),
        }

    def _load(self):
        row = self._service.get(self._account_id)
        if not row or row.member_id != self._member_id:
            QMessageBox.warning(self, "読込エラー", "対象の振込先口座が見つかりません。")
            self.reject()
            return
        self.bank_code.setText(row.bank_code)
        self.bank_name.setText(row.bank_name)
        self.branch_code.setText(row.branch_code)
        self.branch_name.setText(row.branch_name)
        self.account_type.setCurrentIndex(self.account_type.findData(row.account_type))
        self.account_number.setText(row.account_number)
        self.recipient_name.setText(row.recipient_name_kana)
        self.is_enabled.setChecked(row.is_enabled)

    def _save(self):
        try:
            if self._account_id:
                self._service.update(self._account_id, self._data())
            else:
                self._service.create(self._member_id, self._data())
        except ValueError as exc:
            QMessageBox.warning(self, "入力エラー", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return
        self.saved = True
        self.accept()
