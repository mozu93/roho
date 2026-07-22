from datetime import date, datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.refund_service import RefundService
from app.services.zengin_export_service import ZenginExportService
from app.services.pdf.refund_notice_pdf import generate_refund_notice_pdf
from app.ui.member_tab import _CheckHeader


COLS = ["", "管理No.", "会員No.", "事業所名", "還付金額", "振込先金融機関",
        "支店", "種目", "口座番号", "受取人名カナ", "全銀出力", "備考"]
FILTERS = ["すべて", "未入力", "振込対象", "口座未登録", "出力済"]


class RefundTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = RefundService(engine)
        self._records = {}
        self._checked_ids: set[int] = set()
        self._build_ui()
        self._refresh_years()

    def _build_ui(self):
        font = QFont(QApplication.instance().font())
        font.setPointSize(font.pointSize() + 2)
        self.setFont(font)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("年度："))
        self._year = QComboBox()
        self._year.currentIndexChanged.connect(self._refresh)
        top.addWidget(self._year)
        create = QPushButton("対象生成")
        create.clicked.connect(self._on_generate)
        top.addWidget(create)
        top.addStretch()
        layout.addLayout(top)

        search = QHBoxLayout()
        search.addWidget(QLabel("検索："))
        self._search = QLineEdit()
        self._search.setPlaceholderText("事業所名・会員No.・管理No.")
        self._search.textChanged.connect(self._refresh)
        search.addWidget(self._search)
        search.addWidget(QLabel("フィルタ："))
        self._filter = QComboBox()
        self._filter.addItems(FILTERS)
        self._filter.currentIndexChanged.connect(self._refresh)
        search.addWidget(self._filter)
        search.addStretch()
        layout.addLayout(search)

        self._table = QTableWidget(0, len(COLS))
        self._header = _CheckHeader(self._table)
        self._header.toggled.connect(self._on_select_all)
        self._table.setHorizontalHeader(self._header)
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._header.setSectionsMovable(True)
        self._table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        input_btn = QPushButton("還付金額を入力・編集")
        input_btn.clicked.connect(self._on_edit)
        buttons.addWidget(input_btn)
        label_btn = QPushButton("宛名ラベル出力")
        label_btn.clicked.connect(self._on_label)
        buttons.addWidget(label_btn)
        notice_btn = QPushButton("還付金振込通知書PDF")
        notice_btn.clicked.connect(self._on_notice)
        buttons.addWidget(notice_btn)
        zengin_btn = QPushButton("全銀振込データ出力")
        zengin_btn.clicked.connect(self._on_zengin)
        buttons.addWidget(zengin_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

    def _current_year(self):
        value = self._year.currentData()
        return int(value) if value is not None else None

    def _refresh_years(self):
        years = self._svc.list_years()
        self._year.blockSignals(True)
        self._year.clear()
        for year in years:
            self._year.addItem(f"{year}年度", year)
        self._year.blockSignals(False)
        self._refresh()

    def _on_generate(self):
        fiscal_year = self._current_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に手数料計算タブで年度を作成してください。")
            return
        count = self._svc.ensure_records(fiscal_year)
        QMessageBox.information(self, "対象生成", f"{count}件の還付金入力対象を追加しました。")
        self._refresh()

    def _refresh(self):
        fiscal_year = self._current_year()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        if fiscal_year is None:
            self._table.setSortingEnabled(True)
            return
        status = self._filter.currentText()
        rows = self._svc.list_records(
            fiscal_year, self._search.text().strip(), None if status == "すべて" else status)
        self._records = {record.id: record for record in rows}
        self._table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            member = record.member
            account = self._svc.account_for(record)
            container = QWidget()
            check_layout = QHBoxLayout(container)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check = QCheckBox()
            check.setChecked(record.id in self._checked_ids)
            check.stateChanged.connect(
                lambda state, rid=record.id, table_row=row: self._on_check_changed(rid, state, table_row))
            check_layout.addWidget(check)
            self._table.setCellWidget(row, 0, container)
            marker = QTableWidgetItem()
            marker.setData(Qt.ItemDataRole.UserRole, record.id)
            self._table.setItem(row, 0, marker)
            values = [
                str(member.company_code or ""), member.member_number or "", member.org_name,
                f"{record.refund_amount:,}" if record.refund_amount else "",
                f"{account.bank_name} ({account.bank_code})" if account else "未登録",
                f"{account.branch_name} ({account.branch_code})" if account else "",
                {"1": "普通", "2": "当座", "4": "貯蓄"}.get(account.account_type, "") if account else "",
                account.account_number if account else "", account.recipient_name_kana if account else "",
                record.exported_at.strftime("%Y-%m-%d") if record.exported_at else "", record.note or "",
            ]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                if col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                if col == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        self._table.setSortingEnabled(True)
        self._header.set_all_checked(bool(rows) and all(r.id in self._checked_ids for r in rows))

    def _selected_records(self, only_positive=False):
        rows = [r for r in self._records.values() if r.id in self._checked_ids]
        return [r for r in rows if r.refund_amount > 0] if only_positive else rows

    def _on_select_all(self, checked):
        visible = set(self._records)
        if checked:
            self._checked_ids.update(visible)
        else:
            self._checked_ids.difference_update(visible)
        self._refresh()

    def _on_check_changed(self, record_id, state, row=None):
        if state == Qt.CheckState.Checked.value:
            self._checked_ids.add(record_id)
        else:
            self._checked_ids.discard(record_id)
        if row is not None:
            self._table.selectRow(row)
        self._header.set_all_checked(bool(self._records) and all(rid in self._checked_ids for rid in self._records))

    def _current_record(self):
        row = self._table.currentRow()
        item = self._table.item(row, 0) if row >= 0 else None
        return self._records.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _on_edit(self, *_):
        record = self._current_record()
        if not record:
            checked = self._selected_records()
            if not checked:
                QMessageBox.information(self, "還付金額", "編集する事業所を選択してください。")
                return
            # チェック選択だけの場合は、表示順に連続して還付金を入力できる。
            updated = 0
            for target in checked:
                amount, ok = QInputDialog.getInt(
                    self, "還付金額",
                    f"{target.member.org_name} の還付金額（{updated + 1}/{len(checked)}）：",
                    target.refund_amount, 0, 999999999)
                if not ok:
                    break
                note, ok = QInputDialog.getText(
                    self, "備考", "備考（任意）：", text=target.note or "")
                if not ok:
                    break
                self._svc.update(target.id, amount, note)
                updated += 1
            if updated:
                self._refresh()
            return
        amount, ok = QInputDialog.getInt(self, "還付金額", f"{record.member.org_name} の還付金額：",
                                         record.refund_amount, 0, 999999999)
        if not ok:
            return
        note, ok = QInputDialog.getText(self, "備考", "備考（任意）：", text=record.note or "")
        if ok:
            self._svc.update(record.id, amount, note)
            self._refresh()

    def _on_label(self):
        records = self._selected_records(only_positive=True)
        if not records:
            QMessageBox.warning(self, "宛名ラベル出力", "還付金額が入力済みの事業所を選択してください。")
            return
        from app.ui.dialogs.label_dialog import LabelDialog
        LabelDialog(self._engine, [record.member for record in records], self._config,
                    self._config_path, parent=self).exec()

    def _on_notice(self):
        records = self._selected_records(only_positive=True)
        if not records:
            QMessageBox.warning(self, "振込通知書", "還付金額が入力済みの事業所を選択してください。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "還付金振込通知書PDF", "還付金振込通知書.pdf", "PDF (*.pdf)")
        if path:
            count = generate_refund_notice_pdf(records, path)
            QMessageBox.information(self, "完了", f"{count}件の振込通知書を出力しました。")

    def _on_zengin(self):
        fiscal_year = self._current_year()
        records = self._selected_records(only_positive=True)
        if fiscal_year is None or not records:
            QMessageBox.warning(self, "全銀振込データ", "還付金額が入力済みの事業所を選択してください。")
            return
        text, ok = QInputDialog.getText(self, "振込指定日", "振込指定日（YYYY-MM-DD）：", text=date.today().isoformat())
        if not ok:
            return
        try:
            transfer_date = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            QMessageBox.warning(self, "入力エラー", "YYYY-MM-DD形式で入力してください。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "全銀振込データ", "還付金振込.txt", "テキスト (*.txt)")
        if not path:
            return
        origin = {key: getattr(self._config, f"refund_origin_{key}") for key in (
            "bank_code", "bank_name", "branch_code", "branch_name", "account_type",
            "account_number", "account_name_kana")}
        try:
            count = ZenginExportService(self._engine).export(
                path, fiscal_year, [record.id for record in records], transfer_date, origin)
            QMessageBox.information(self, "完了", f"{count}件の全銀振込データを出力しました。")
            self._refresh()
        except Exception as error:
            QMessageBox.critical(self, "全銀振込データ", str(error))
