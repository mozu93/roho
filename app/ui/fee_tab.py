# app/ui/fee_tab.py
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QFileDialog,
)
from PyQt6.QtCore import Qt
from app.services.fee_service import FeeService
from app.services.fee_export_service import FeeExportService
from app.ui.dialogs.fee_edit_dialog import FeeEditDialog

FILTERS = ["すべて", "未入力", "未入金", "入金済", "1期", "2期", "3期", "請求なし", "非会員", "督促中"]
COLS = ["管理No.", "会員No.", "事業所名", "会員区分", "概算保険料合計", "請求合計",
        "支払時期", "支払方法", "入金額", "入金日", "督促状況"]


class FeeTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = FeeService(engine)
        self._build_ui()
        self._refresh_years()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("年度："))
        self._year_combo = QComboBox()
        self._year_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._year_combo)
        add_year_btn = QPushButton("新年度追加")
        add_year_btn.clicked.connect(self._on_add_year)
        top_row.addWidget(add_year_btn)
        gen_btn = QPushButton("対象生成")
        gen_btn.clicked.connect(self._on_generate)
        top_row.addWidget(gen_btn)
        recalc_btn = QPushButton("再計算")
        recalc_btn.clicked.connect(self._on_recalculate)
        top_row.addWidget(recalc_btn)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        top_row.addWidget(export_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("検索："))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("事業所名・会員No.・管理No.")
        self._search_edit.textChanged.connect(self._refresh)
        search_row.addWidget(self._search_edit)
        search_row.addWidget(QLabel("フィルタ："))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(FILTERS)
        self._filter_combo.currentIndexChanged.connect(self._refresh)
        search_row.addWidget(self._filter_combo)
        search_row.addStretch()
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)

    def _current_fiscal_year(self):
        data = self._year_combo.currentData()
        return int(data) if data is not None else None

    def _refresh_years(self):
        years = self._svc.list_years()
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        for y in years:
            self._year_combo.addItem(f"{y}年度", y)
        self._year_combo.blockSignals(False)
        self._refresh()

    def _refresh(self):
        fiscal_year = self._current_fiscal_year()
        self._table.setRowCount(0)
        if fiscal_year is None:
            return
        keyword = self._search_edit.text().strip()
        status_filter = self._filter_combo.currentText()
        if status_filter == "すべて":
            status_filter = None
        records = self._svc.search(fiscal_year, keyword=keyword, status_filter=status_filter)
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            m = r.member
            values = [
                str(m.company_code or ""),
                m.member_number or "",
                m.org_name,
                "会員" if r.is_member_for_fee else "非会員",
                f"{r.premium_total:,}",
                f"{r.total_amount:,}",
                r.final_payment_period or "",
                r.payment_method or "",
                f"{r.paid_amount:,}" if r.paid_amount else "",
                r.paid_at.strftime("%Y-%m-%d") if r.paid_at else "",
                r.reminder_status or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, r.id)
                self._table.setItem(row, col, item)

    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 0)
        if not item:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        dlg = FeeEditDialog(self._engine, record_id, parent=self)
        if dlg.exec():
            self._refresh()

    def _on_add_year(self):
        year, ok = QInputDialog.getInt(
            self, "新年度追加", "西暦年度を入力してください（例：2026）",
            datetime.now().year, 2000, 2100)
        if not ok:
            return
        self._svc.get_or_create_rule(year)
        self._refresh_years()
        idx = self._year_combo.findData(year)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)

    def _on_generate(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に年度を選択または追加してください。")
            return
        added = self._svc.generate_records(fiscal_year)
        QMessageBox.information(self, "対象生成", f"{added}件のレコードを追加しました。")
        self._refresh()

    def _on_recalculate(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            return
        count = self._svc.recalculate_all(fiscal_year)
        QMessageBox.information(self, "再計算", f"{count}件を再計算しました。")
        self._refresh()

    def _on_export(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に年度を選択または追加してください。")
            return
        default_name = f"手数料計算_{fiscal_year}年度.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Excel出力", default_name, "Excel (*.xlsx)")
        if not path:
            return
        try:
            count = FeeExportService(self._engine).export_excel(fiscal_year, path)
            QMessageBox.information(self, "完了", f"{count}件を出力しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
