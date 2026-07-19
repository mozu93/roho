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
from app.services.activity_service import ActivityService
from app.ui.dialogs.renewal_edit_dialog import RenewalEditDialog, BRANCH_LABEL
from app.ui.member_tab import SortableTableWidgetItem

FILTERS = ["すべて"] + OVERALL_STATUSES
BRANCH_SHORT_LABEL = {
    "ippan": "枝番0", "kensetsu_koyou": "枝番2", "ringyo": "枝番4",
    "kensetsu_genba": "枝番5", "kensetsu_jimusho": "枝番6",
}
_AC = Qt.AlignmentFlag.AlignCenter

COLS = [
    "管理No.", "会", "会員No.", "事業所名", "フリガナ", "所属・役職",
    "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
    "郵便番号", "住所", "郵送先郵便番号", "郵送先住所", "郵送先宛名", "雇用保険事業所番号",
] + [BRANCH_SHORT_LABEL[t] for t in INS_TYPES] + [
    "特別", "継続一括", "登録日", "最終更新日",
    "最終対応日（全体）", "メモ（全体）",
    "全体状況", "最終対応日（年度更新）", "備考（年度更新）",
]
BRANCH_COL_START = 19  # "枝番0" の列インデックス（先頭19列: 管理No.〜雇用保険事業所番号）
_TAIL_START = BRANCH_COL_START + len(INS_TYPES)  # = 24: "特別" の列インデックス


class RenewalTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = RenewalService(engine)
        self._activity_svc = ActivityService(engine)
        self._last_activity_map: dict = {}
        self._last_change_map: dict = {}
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
        self._table.setObjectName("renewalTable")
        self._table.setStyleSheet(
            "QTableWidget#renewalTable::item:hover { background: #ffe4ec; color: #1a1a1a; }"
        )
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            self._table.setColumnWidth(col, 110)
            self._table.horizontalHeaderItem(col).setToolTip(BRANCH_LABEL[ins_type])
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.cellClicked.connect(self._on_cell_clicked)
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
        member_ids = [r.member.id for r in records]
        self._last_activity_map = self._activity_svc.get_last_logged_at_map(member_ids)
        self._last_change_map = self._activity_svc.get_last_changed_at_map(member_ids)
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            self._populate_row(row, r)

    def _populate_row(self, row, r):
        m = r.member
        has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
        has_ikkatsu = any(e.is_ikkatsu for e in m.insurance_entries)

        code_item = SortableTableWidgetItem(str(m.company_code) if m.company_code else "")
        code_item.setData(Qt.ItemDataRole.UserRole, r.id)
        code_item.setTextAlignment(_AC)
        self._table.setItem(row, 0, code_item)

        mem_item = SortableTableWidgetItem("○" if getattr(m, "is_member", True) else "")
        mem_item.setTextAlignment(_AC)
        self._table.setItem(row, 1, mem_item)

        mno_item = SortableTableWidgetItem(m.member_number or "")
        mno_item.setTextAlignment(_AC)
        self._table.setItem(row, 2, mno_item)

        self._table.setItem(row, 3, SortableTableWidgetItem(m.org_name))
        self._table.setItem(row, 4, SortableTableWidgetItem(m.org_kana or ""))
        self._table.setItem(row, 5, SortableTableWidgetItem(m.dept_title or ""))
        self._table.setItem(row, 6, SortableTableWidgetItem(m.rep_name or ""))
        self._table.setItem(row, 7, SortableTableWidgetItem(m.rep_kana or ""))
        self._table.setItem(row, 8, SortableTableWidgetItem(m.email or ""))

        for delta, text in enumerate([
            m.tel_area or "", m.tel or "", m.fax_area or "", m.fax or "",
            m.postal_code or "", m.address or "",
            m.postal_code_mail or "", m.address_mail or "", m.addressee_mail or "",
            m.employment_ins_no or "",
        ]):
            item = SortableTableWidgetItem(text)
            item.setTextAlignment(_AC)
            self._table.setItem(row, 9 + delta, item)

        items_by_type = {i.branch_type: i for i in r.items}
        ins_number_by_type = {e.ins_type: e.ins_number for e in m.insurance_entries}
        for i, branch_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            renewal_item = items_by_type.get(branch_type)
            if renewal_item is None:
                cell = SortableTableWidgetItem("－")
                cell.setData(Qt.ItemDataRole.UserRole, None)
            else:
                status_text = renewal_item.submission_status
                if renewal_item.submission_status == "提出済" and renewal_item.confirmed_at:
                    status_text = f"提出済 {renewal_item.confirmed_at.strftime('%m-%d')}"
                ins_number = ins_number_by_type.get(branch_type)
                text = f"{ins_number} {status_text}" if ins_number else status_text
                cell = SortableTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, (branch_type, renewal_item.submission_status))
            cell.setTextAlignment(_AC)
            self._table.setItem(row, col, cell)

        toku_item = SortableTableWidgetItem("●" if has_tokubetsu else "")
        toku_item.setTextAlignment(_AC)
        self._table.setItem(row, _TAIL_START + 0, toku_item)

        ikk_item = SortableTableWidgetItem("●" if has_ikkatsu else "")
        ikk_item.setTextAlignment(_AC)
        self._table.setItem(row, _TAIL_START + 1, ikk_item)

        reg_item = SortableTableWidgetItem(
            m.registered_date.strftime("%Y-%m-%d") if m.registered_date else "")
        reg_item.setTextAlignment(_AC)
        self._table.setItem(row, _TAIL_START + 2, reg_item)

        change_dt = self._last_change_map.get(m.id)
        change_item = SortableTableWidgetItem(change_dt.strftime("%Y-%m-%d") if change_dt else "")
        change_item.setTextAlignment(_AC)
        self._table.setItem(row, _TAIL_START + 3, change_item)

        last_dt = self._last_activity_map.get(m.id)
        last_item = SortableTableWidgetItem(last_dt.strftime("%Y-%m-%d") if last_dt else "")
        last_item.setTextAlignment(_AC)
        self._table.setItem(row, _TAIL_START + 4, last_item)

        self._table.setItem(row, _TAIL_START + 5, SortableTableWidgetItem(m.note or ""))

        self._table.setItem(row, _TAIL_START + 6, SortableTableWidgetItem(r.overall_status or ""))
        self._table.setItem(row, _TAIL_START + 7, SortableTableWidgetItem(
            r.last_contacted_at.strftime("%Y-%m-%d") if r.last_contacted_at else ""))
        self._table.setItem(row, _TAIL_START + 8, SortableTableWidgetItem((r.note or "")[:30]))

    def _on_cell_clicked(self, row, col):
        if col < BRANCH_COL_START or col >= BRANCH_COL_START + len(INS_TYPES):
            return
        cell = self._table.item(row, col)
        id_item = self._table.item(row, 0)
        if cell is None or id_item is None:
            return
        data = cell.data(Qt.ItemDataRole.UserRole)
        if data is None:
            return
        branch_type, status = data
        if status not in ("未提出", "提出済"):
            return
        renewal_id = id_item.data(Qt.ItemDataRole.UserRole)
        renewal = self._svc.toggle_item(renewal_id, branch_type)
        self._populate_row(row, renewal)

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
