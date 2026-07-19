# app/ui/renewal_tab.py
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QMenu, QDialog, QGridLayout, QCheckBox,
    QTableView, QFrame, QApplication,
)
from PyQt6.QtCore import Qt, QEvent
from app.services.renewal_service import RenewalService, OVERALL_STATUSES
from app.services.member_service import INS_TYPES
from app.services.activity_service import ActivityService
from app.ui.dialogs.renewal_edit_dialog import RenewalEditDialog, BRANCH_LABEL
from app.ui.member_tab import (
    SortableTableWidgetItem, _SelectionDelegate, _CheckHeader, _FrozenCheckDelegate,
)

FILTERS = ["すべて"] + OVERALL_STATUSES
BRANCH_SHORT_LABEL = {
    "ippan": "枝番0", "kensetsu_koyou": "枝番2", "ringyo": "枝番4",
    "kensetsu_genba": "枝番5", "kensetsu_jimusho": "枝番6",
}
_AC = Qt.AlignmentFlag.AlignCenter

COLS = [
    "",
    "管理No.", "会", "会員No.", "事業所名", "フリガナ", "所属・役職",
    "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
    "郵便番号", "住所", "郵送先郵便番号", "郵送先住所", "郵送先宛名", "雇用保険事業所番号",
] + [BRANCH_SHORT_LABEL[t] for t in INS_TYPES] + [
    "特別", "継続一括", "登録日", "最終更新日",
    "最終対応日（全体）", "メモ（全体）",
    "全体状況", "最終対応日（年度更新）", "備考（年度更新）",
]
_COL_SELECT = 0
BRANCH_COL_START = 20  # "枝番0" の列インデックス（チェックボックス+先頭19列: 管理No.〜雇用保険事業所番号）
_TAIL_START = BRANCH_COL_START + len(INS_TYPES)  # = 25: "特別" の列インデックス


def _aggregate_sort_key(r):
    """事業所が保有する枝番の保険番号を優先順位付き複数キーとして返す（数値は数値として比較）"""
    def _ins_key(ins_type):
        entry = next((e for e in r.member.insurance_entries if e.ins_type == ins_type), None)
        val = entry.ins_number if entry else ""
        try:
            return (0, int(val))
        except (ValueError, TypeError):
            return (1, val or "")
    return tuple(_ins_key(t) for t in INS_TYPES)


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
        self._resizing_programmatically = False
        self._records: list = []
        self._checked_ids: set[int] = set()
        self._last_checked_member_id: int = -1
        self._member_row_map: dict[int, int] = {}
        self._freeze_col: int = self._get_staff_setting("renewal_freeze_col", 0)
        self._build_ui()
        self._apply_column_visibility()
        self._refresh_years()

    # ── per-staff 設定ヘルパー ──

    def _get_staff_setting(self, key: str, default=None):
        name = self._config.last_staff_name
        return self._config.staff_settings.get(name, {}).get(key, default)

    def _set_staff_setting(self, key: str, value) -> None:
        name = self._config.last_staff_name
        if name not in self._config.staff_settings:
            self._config.staff_settings[name] = {}
        self._config.staff_settings[name][key] = value
        if self._config_path:
            try:
                self._config.save(self._config_path)
            except Exception as e:
                print(f"Failed to save staff settings: {e}")

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
        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.clicked.connect(self._exec_column_menu)
        top_row.addWidget(col_setting_btn)
        agg_btn = QPushButton("集約並び替え")
        agg_btn.clicked.connect(self._on_aggregate_sort)
        top_row.addWidget(agg_btn)
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
        self._check_header = _CheckHeader(self._table)
        self._check_header.toggled.connect(self._on_select_all)
        self._table.setHorizontalHeader(self._check_header)
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._check_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._check_header.setSectionsMovable(True)
        self._check_header.sortIndicatorChanged.connect(self._on_sort_changed)
        self._check_header.sectionResized.connect(self._on_column_resized)
        self._check_header.sectionMoved.connect(self._on_section_moved)
        self._check_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._check_header.customContextMenuRequested.connect(self._show_column_menu)
        self._check_header.setMinimumSectionSize(30)
        self._table.setItemDelegate(_SelectionDelegate(self._table))
        self._resizing_programmatically = True
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            self._table.setColumnWidth(col, 110)
            self._table.horizontalHeaderItem(col).setToolTip(BRANCH_LABEL[ins_type])
        self._resizing_programmatically = False
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

        # 列固定オーバーレイ
        self._frozen_view = QTableView(self._table)
        self._frozen_view.setModel(self._table.model())
        self._frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_view.verticalHeader().hide()
        self._frozen_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._frozen_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_view.setAlternatingRowColors(True)
        self._frozen_view.setFrameShape(QFrame.Shape.NoFrame)
        self._frozen_view.verticalHeader().setDefaultSectionSize(30)
        self._frozen_view.setItemDelegateForColumn(
            _COL_SELECT, _FrozenCheckDelegate(self._checked_ids, self._frozen_view))
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(self._on_frozen_header_clicked)
        self._frozen_view.clicked.connect(self._on_frozen_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setSelectionModel(self._table.selectionModel())
        self._frozen_view.setVisible(False)

        self._table.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue)
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self._table.verticalScrollBar().setValue)

        self._table.installEventFilter(self)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        label_btn = QPushButton("ラベル出力")
        label_btn.clicked.connect(self._on_label)
        btn_row.addWidget(label_btn)
        email_btn = QPushButton("メール送信")
        email_btn.clicked.connect(self._on_compose_email)
        btn_row.addWidget(email_btn)
        layout.addLayout(btn_row)

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
        if self._get_staff_setting("renewal_aggregate_sort_active", False):
            records.sort(key=_aggregate_sort_key)
        self._records = records
        member_ids = [r.member.id for r in records]
        self._last_activity_map = self._activity_svc.get_last_logged_at_map(member_ids)
        self._last_change_map = self._activity_svc.get_last_changed_at_map(member_ids)
        self._fill_table(records)

    def _fill_table(self, records):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            self._populate_row(row, r)

        self._resizing_programmatically = True
        saved_widths = self._get_staff_setting("renewal_column_widths", {})
        for i in range(self._table.columnCount()):
            if i == _COL_SELECT:
                self._table.setColumnWidth(i, 44)
            elif str(i) in saved_widths:
                self._table.setColumnWidth(i, int(saved_widths[str(i)]))
            else:
                self._table.resizeColumnToContents(i)
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            if str(col) not in saved_widths:
                self._table.setColumnWidth(col, 110)
        self._resizing_programmatically = False

        if self._get_staff_setting("renewal_aggregate_sort_active", False):
            self._resizing_programmatically = True
            self._table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            self._resizing_programmatically = False
            self._table.setSortingEnabled(True)
        else:
            saved_col = self._get_staff_setting("renewal_sort_column", -1)
            saved_ord = Qt.SortOrder(self._get_staff_setting(
                "renewal_sort_order", Qt.SortOrder.AscendingOrder.value))
            self._table.setSortingEnabled(True)
            if saved_col >= 0:
                self._resizing_programmatically = True
                self._table.horizontalHeader().setSortIndicator(saved_col, saved_ord)
                self._resizing_programmatically = False
        self._update_frozen_view_geometry()
        self._rebuild_member_row_map()

    def _on_aggregate_sort(self):
        self._records.sort(key=_aggregate_sort_key)
        self._set_staff_setting("renewal_aggregate_sort_active", True)
        self._fill_table(self._records)

    def _populate_row(self, row, r):
        m = r.member
        has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
        has_ikkatsu = any(e.is_ikkatsu for e in m.insurance_entries)

        chk_container = QWidget()
        chk_hbox = QHBoxLayout(chk_container)
        chk_hbox.setContentsMargins(0, 0, 0, 0)
        chk_hbox.setAlignment(_AC)
        chk = QCheckBox()
        chk.setChecked(m.id in self._checked_ids)
        chk.stateChanged.connect(lambda state, mid=m.id: self._on_check_changed(mid, state))
        chk_hbox.addWidget(chk)
        self._table.setCellWidget(row, _COL_SELECT, chk_container)
        sel_item = QTableWidgetItem()
        sel_item.setData(Qt.ItemDataRole.UserRole, m.id)
        self._table.setItem(row, _COL_SELECT, sel_item)

        code_item = SortableTableWidgetItem(str(m.company_code) if m.company_code else "")
        code_item.setData(Qt.ItemDataRole.UserRole, r.id)
        code_item.setTextAlignment(_AC)
        self._table.setItem(row, 1, code_item)

        mem_item = SortableTableWidgetItem("○" if getattr(m, "is_member", True) else "")
        mem_item.setTextAlignment(_AC)
        self._table.setItem(row, 2, mem_item)

        mno_item = SortableTableWidgetItem(m.member_number or "")
        mno_item.setTextAlignment(_AC)
        self._table.setItem(row, 3, mno_item)

        self._table.setItem(row, 4, SortableTableWidgetItem(m.org_name))
        self._table.setItem(row, 5, SortableTableWidgetItem(m.org_kana or ""))
        self._table.setItem(row, 6, SortableTableWidgetItem(m.dept_title or ""))
        self._table.setItem(row, 7, SortableTableWidgetItem(m.rep_name or ""))
        self._table.setItem(row, 8, SortableTableWidgetItem(m.rep_kana or ""))
        self._table.setItem(row, 9, SortableTableWidgetItem(m.email or ""))

        for delta, text in enumerate([
            m.tel_area or "", m.tel or "", m.fax_area or "", m.fax or "",
            m.postal_code or "", m.address or "",
            m.postal_code_mail or "", m.address_mail or "", m.addressee_mail or "",
            m.employment_ins_no or "",
        ]):
            item = SortableTableWidgetItem(text)
            item.setTextAlignment(_AC)
            self._table.setItem(row, 10 + delta, item)

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

    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        self._rebuild_member_row_map()
        if not self._resizing_programmatically and logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
            self._set_staff_setting("renewal_aggregate_sort_active", False)

    def _on_cell_clicked(self, row, col):
        if col < BRANCH_COL_START or col >= BRANCH_COL_START + len(INS_TYPES):
            return
        cell = self._table.item(row, col)
        id_item = self._table.item(row, 1)
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
        for i, rec in enumerate(self._records):
            if rec.id == renewal_id:
                self._records[i] = renewal
                break
        self._table.setSortingEnabled(False)
        self._populate_row(row, renewal)
        self._table.setSortingEnabled(True)
        self._rebuild_member_row_map()

    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 1)
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

    # ── 列表示・幅 ──

    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting("renewal_hidden_columns", [])
        self._resizing_programmatically = True
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)
        self._resizing_programmatically = False
        order = self._get_staff_setting("renewal_column_order")
        if order and len(order) == len(COLS):
            header = self._table.horizontalHeader()
            self._resizing_programmatically = True
            for visual, logical in enumerate(order):
                current = header.visualIndex(logical)
                if current != visual:
                    header.moveSection(current, visual)
            self._resizing_programmatically = False

    def _exec_column_menu(self, *_):
        dlg = QDialog(self)
        dlg.setWindowTitle("表示列選択")
        dlg.setMinimumWidth(320)

        hidden_cols = list(self._get_staff_setting("renewal_hidden_columns", []))

        outer = QVBoxLayout(dlg)
        items = [(i, col) for i, col in enumerate(COLS) if i != _COL_SELECT]
        half = (len(items) + 1) // 2

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)

        for r, (i, col) in enumerate(items[:half]):
            chk = QCheckBox(col or f"列{i}")
            chk.setChecked(COLS[i] not in hidden_cols)
            chk.toggled.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            grid.addWidget(chk, r, 0)

        for r, (i, col) in enumerate(items[half:]):
            chk = QCheckBox(col or f"列{i}")
            chk.setChecked(COLS[i] not in hidden_cols)
            chk.toggled.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            grid.addWidget(chk, r, 1)

        outer.addWidget(grid_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        dlg.exec()

    def _toggle_column_visibility(self, idx, visible):
        hidden = list(self._get_staff_setting("renewal_hidden_columns", []))
        if visible:
            self._resizing_programmatically = True
            self._table.showColumn(idx)
            self._table.resizeColumnToContents(idx)
            self._resizing_programmatically = False
            if COLS[idx] in hidden:
                hidden.remove(COLS[idx])
        else:
            self._resizing_programmatically = True
            self._table.hideColumn(idx)
            self._resizing_programmatically = False
            if COLS[idx] not in hidden:
                hidden.append(COLS[idx])
        self._set_staff_setting("renewal_hidden_columns", hidden)
        if self._freeze_col > 0:
            self._update_frozen_view_geometry()

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        if self._resizing_programmatically:
            return
        widths = dict(self._get_staff_setting("renewal_column_widths", {}))
        if new_size == 0:
            widths.pop(str(logical_index), None)
        else:
            widths[str(logical_index)] = new_size
        self._set_staff_setting("renewal_column_widths", widths)
        if self._freeze_col > 0 and logical_index <= self._freeze_col:
            self._update_frozen_view_geometry()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        if self._resizing_programmatically:
            return
        header = self._table.horizontalHeader()
        order = [header.logicalIndex(v) for v in range(self._table.columnCount())]
        self._set_staff_setting("renewal_column_order", order)

    # ── 列固定 ──

    def _set_freeze_col(self, col: int):
        self._freeze_col = col
        self._set_staff_setting("renewal_freeze_col", col)
        self._update_frozen_view_geometry()

    def _update_frozen_view_geometry(self):
        n = self._freeze_col
        table = self._table

        if n <= 0:
            self._frozen_view.setVisible(False)
            return

        frozen_width = 0
        for c in range(table.columnCount()):
            user_hidden = table.isColumnHidden(c)
            beyond_freeze = (c > n)
            self._frozen_view.setColumnHidden(c, beyond_freeze or user_hidden)
            if not beyond_freeze and not user_hidden:
                w = table.columnWidth(c)
                self._frozen_view.setColumnWidth(c, w)
                frozen_width += w

        hh_h = table.horizontalHeader().height()
        self._frozen_view.horizontalHeader().setFixedHeight(hh_h)

        for r in range(table.rowCount()):
            self._frozen_view.setRowHeight(r, table.rowHeight(r))

        vh_w = table.verticalHeader().width() if not table.verticalHeader().isHidden() else 0
        fw = table.frameWidth()
        self._frozen_view.setGeometry(
            fw + vh_w, fw,
            frozen_width,
            table.height() - fw * 2,
        )
        self._frozen_view.setVisible(True)
        self._frozen_view.raise_()

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() == QEvent.Type.Resize:
            self._update_frozen_view_geometry()
        return super().eventFilter(obj, event)

    def _on_frozen_header_clicked(self, logical_col: int):
        header = self._table.horizontalHeader()
        current_col = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()
        if current_col == logical_col:
            new_order = (Qt.SortOrder.DescendingOrder
                         if current_order == Qt.SortOrder.AscendingOrder
                         else Qt.SortOrder.AscendingOrder)
        else:
            new_order = Qt.SortOrder.AscendingOrder
        self._table.sortItems(logical_col, new_order)
        header.setSortIndicator(logical_col, new_order)
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, new_order)
        self._rebuild_member_row_map()

    def _on_frozen_double_clicked(self, index):
        self._table.selectRow(index.row())
        self._on_row_double_clicked(self._table.model().index(index.row(), 0))

    def _show_column_menu(self, pos):
        header = self._table.horizontalHeader()
        logical = header.logicalIndexAt(pos)
        menu = QMenu(self)
        if 0 < logical < len(COLS):
            col_name = COLS[logical]
            menu.addAction(
                f"「{col_name}」列まで固定",
                lambda: self._set_freeze_col(logical),
            )
        if self._freeze_col > 0:
            menu.addAction("列固定を解除", lambda: self._set_freeze_col(0))
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction("表示列選択", self._exec_column_menu)
        menu.exec(header.mapToGlobal(pos))

    # ── 選択（チェックボックス） ──

    def _on_select_all(self, checked: bool):
        if checked:
            for r in self._records:
                self._checked_ids.add(r.member.id)
        else:
            self._checked_ids.clear()
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            if container:
                chk = container.findChild(QCheckBox)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(checked)
                    chk.blockSignals(False)
        self._frozen_view.viewport().update()

    def _on_check_changed(self, member_id: int, state: int):
        new_checked = (state == Qt.CheckState.Checked.value)
        mods = QApplication.keyboardModifiers()

        if (mods & Qt.KeyboardModifier.ShiftModifier) and self._last_checked_member_id >= 0:
            start_row = self._find_row_by_member_id(self._last_checked_member_id)
            end_row = self._find_row_by_member_id(member_id)
            if start_row >= 0 and end_row >= 0:
                for r in range(min(start_row, end_row), max(start_row, end_row) + 1):
                    container = self._table.cellWidget(r, _COL_SELECT)
                    item = self._table.item(r, _COL_SELECT)
                    mid = item.data(Qt.ItemDataRole.UserRole) if item else None
                    if container and mid is not None:
                        chk = container.findChild(QCheckBox)
                        if chk:
                            chk.blockSignals(True)
                            chk.setChecked(new_checked)
                            chk.blockSignals(False)
                        if new_checked:
                            self._checked_ids.add(mid)
                        else:
                            self._checked_ids.discard(mid)
        else:
            if new_checked:
                self._checked_ids.add(member_id)
            else:
                self._checked_ids.discard(member_id)

        self._last_checked_member_id = member_id
        self._frozen_view.viewport().update()

    def _find_row_by_member_id(self, member_id: int) -> int:
        return self._member_row_map.get(member_id, -1)

    def _rebuild_member_row_map(self):
        self._member_row_map = {}
        for r in range(self._table.rowCount()):
            item = self._table.item(r, _COL_SELECT)
            if item:
                mid = item.data(Qt.ItemDataRole.UserRole)
                if mid is not None:
                    self._member_row_map[mid] = r

    def _on_frozen_clicked(self, index):
        row = index.row()
        col = index.column()
        if col == _COL_SELECT:
            mid = index.data(Qt.ItemDataRole.UserRole)
            if mid is not None:
                new_checked = mid not in self._checked_ids
                self._on_check_changed(
                    mid,
                    Qt.CheckState.Checked.value if new_checked else Qt.CheckState.Unchecked.value,
                )
        else:
            self._table.selectRow(row)

    # ── ラベル出力・メール送信 ──

    def _on_label(self):
        from app.ui.dialogs.label_dialog import LabelDialog
        members = [r.member for r in self._records if r.member.id in self._checked_ids]
        if not members:
            QMessageBox.warning(
                self, "ラベル出力", "出力する事業所を選択してください（左端のチェックボックスで選択）。")
            return
        LabelDialog(self._engine, members, parent=self).exec()

    def _on_compose_email(self):
        from app.ui.dialogs.compose_email_dialog import ComposeEmailDialog
        members = [r.member for r in self._records if r.member.id in self._checked_ids]
        if not members:
            QMessageBox.warning(self, "メール送信", "送信先を選択してください（左端のチェックボックスで選択）。")
            return
        ComposeEmailDialog(self._engine, self._config, members, parent=self).exec()
