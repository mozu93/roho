# app/ui/renewal_tab.py
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog,
)
from PyQt6.QtCore import Qt
from app.services.renewal_service import RenewalService, OVERALL_STATUSES
from app.services.member_service import INS_TYPES
from app.ui.dialogs.renewal_edit_dialog import RenewalEditDialog, BRANCH_LABEL

FILTERS = ["すべて"] + OVERALL_STATUSES
BRANCH_SHORT_LABEL = {
    "ippan": "枝番0", "kensetsu_koyou": "枝番2", "ringyo": "枝番4",
    "kensetsu_genba": "枝番5", "kensetsu_jimusho": "枝番6",
}
BRANCH_COL_START = 3
COLS = (
    ["管理No.", "会員No.", "事業所名"]
    + [BRANCH_SHORT_LABEL[t] for t in INS_TYPES]
    + ["全体状況", "最終対応日", "備考"]
)


class RenewalTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = RenewalService(engine)
        self._build_ui()
        self._refresh_years()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("年度："))
        self._year_combo = QComboBox()
        self._year_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._year_combo)
        gen_btn = QPushButton("対象生成")
        gen_btn.clicked.connect(self._on_generate)
        top_row.addWidget(gen_btn)
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
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            self._table.setColumnWidth(col, 70)
            self._table.horizontalHeaderItem(col).setToolTip(BRANCH_LABEL[ins_type])
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
            self._populate_row(row, r)

    def _populate_row(self, row, r):
        m = r.member
        head_values = [str(m.company_code or ""), m.member_number or "", m.org_name]
        for col, value in enumerate(head_values):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, r.id)
            self._table.setItem(row, col, item)

        items_by_type = {i.branch_type: i for i in r.items}
        for i, branch_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            renewal_item = items_by_type.get(branch_type)
            if renewal_item is None:
                cell = QTableWidgetItem("－")
                cell.setData(Qt.ItemDataRole.UserRole, None)
            else:
                text = renewal_item.submission_status
                if renewal_item.submission_status == "提出済" and renewal_item.confirmed_at:
                    text = f"提出済 {renewal_item.confirmed_at.strftime('%m-%d')}"
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, (branch_type, renewal_item.submission_status))
            self._table.setItem(row, col, cell)

        tail_start = BRANCH_COL_START + len(INS_TYPES)
        tail_values = [
            r.overall_status or "",
            r.last_contacted_at.strftime("%Y-%m-%d") if r.last_contacted_at else "",
            (r.note or "")[:30],
        ]
        for offset, value in enumerate(tail_values):
            self._table.setItem(row, tail_start + offset, QTableWidgetItem(value))

    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 0)
        if not item:
            return
        renewal_id = item.data(Qt.ItemDataRole.UserRole)
        dlg = RenewalEditDialog(self._engine, renewal_id, self._config.last_staff_name, parent=self)
        if dlg.exec():
            self._refresh()

    def _on_generate(self):
        year, ok = QInputDialog.getInt(
            self, "対象生成", "西暦年度を入力してください（例：2026）",
            self._current_fiscal_year() or datetime.now().year, 2000, 2100)
        if not ok:
            return
        added = self._svc.generate_records(year)
        QMessageBox.information(self, "対象生成", f"{added}件のレコードを追加しました。")
        self._refresh_years()
        idx = self._year_combo.findData(year)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)
