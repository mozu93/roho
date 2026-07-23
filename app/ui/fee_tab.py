# app/ui/fee_tab.py
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QFileDialog, QTableView, QFrame,
    QMenu, QDialog, QGridLayout, QCheckBox, QApplication, QStyledItemDelegate,
)
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIntValidator
from app.services.fee_service import FeeService
from app.services.fee_export_service import FeeExportService
from app.services.activity_service import ActivityService
from app.services.member_service import INS_TYPES
from app.ui.dialogs.fee_edit_dialog import FeeEditDialog
from app.ui.dialogs.quick_premium_input_dialog import QuickPremiumInputDialog
from app.ui.dialogs.debit_result_dialog import DebitResultDialog
from app.ui.member_tab import _CheckHeader, _FrozenCheckDelegate, _FrozenItemDelegate

FILTERS = ["すべて", "未入力", "未入金", "入金済", "1期", "2期", "3期", "請求なし", "非会員", "督促中"]
BRANCH_COLS = ["枝番0", "枝番2", "枝番4", "枝番5", "枝番6"]
BRANCH_TYPES = ("ippan", "kensetsu_koyou", "ringyo", "kensetsu_genba", "kensetsu_jimusho")
PREMIUM_FIELDS = (
    "premium_branch_0", "premium_branch_2", "premium_branch_4",
    "premium_branch_5", "premium_branch_6",
)
PREMIUM_COLS = [f"概算保険料（{number}）" for number in ("0", "2", "4", "5", "6")]
BRANCH_PREMIUM_COLS = [
    column
    for pair in zip(BRANCH_COLS, PREMIUM_COLS)
    for column in pair
]
COLS = [
    "", "管理No.", "会員No.", "事業所名", "フリガナ", "所属・役職", "代表者名", "代表者フリガナ",
    "メール", "市外局番", "電話番号", "FAX市外局番", "FAX", "郵便番号", "住所",
    "郵送先郵便番号", "郵送先住所", "郵送先事業所名", "郵送先所属・役職名", "郵送先氏名",
    "雇用保険事業所番号",
] + BRANCH_PREMIUM_COLS + [
    "特別", "継続一括", "登録日", "最終更新日", "最終対応日", "メモ",
    "振込先金融機関", "振込先支店", "預金種目", "口座番号", "受取人名カナ",
    "会員区分", "概算保険料合計", "請求合計", "支払時期", "支払方法",
    "1期振替結果", "2期振替結果", "入金額", "入金日", "督促状況",
]
COL_INDEX = {name: index for index, name in enumerate(COLS)}
_COL_SELECT = COL_INDEX[""]
DEFAULT_HIDDEN_COLS = {
    "所属・役職", "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号",
    "FAX市外局番", "FAX", "郵便番号", "住所", "郵送先郵便番号", "郵送先住所",
    "郵送先事業所名", "郵送先所属・役職名", "郵送先氏名", "雇用保険事業所番号",
    "最終更新日", "最終対応日", "メモ", "振込先金融機関", "振込先支店",
    "預金種目", "口座番号", "受取人名カナ",
}
def _aggregate_sort_key(record):
    """年度更新タブと同じく、枝番の保険番号順で事業所を集約する。"""
    entries = {entry.ins_type: entry.ins_number for entry in record.member.insurance_entries}

    def key(ins_type):
        number = entries.get(ins_type) or ""
        try:
            return 0, int(number)
        except ValueError:
            return 1, number

    return tuple(key(ins_type) for ins_type in BRANCH_TYPES)


class FeeSortableTableWidgetItem(QTableWidgetItem):
    """数値列を数値順にし、空白は昇順・降順とも末尾に並べる。"""

    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        left = self.text().strip()
        right = other.text().strip()
        ascending = True
        table = self.tableWidget()
        if table:
            ascending = (
                table.horizontalHeader().sortIndicatorOrder()
                == Qt.SortOrder.AscendingOrder
            )
        if not left and not right:
            return False
        if not left:
            return not ascending
        if not right:
            return ascending
        try:
            return float(left.replace(",", "")) < float(right.replace(",", ""))
        except ValueError:
            return left < right


class _PremiumDelegate(QStyledItemDelegate):
    """概算保険料を数字だけで編集し、Enter後の下方向移動を通知する。"""
    enter_pressed = pyqtSignal(int, int)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(QIntValidator(0, 2_147_483_647, editor))
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        editor.returnPressed.connect(
            lambda e=editor, record_id=index.data(Qt.ItemDataRole.UserRole),
            column=index.column(): self._commit_and_advance(
                e, record_id, column))
        return editor

    def setEditorData(self, editor, index):
        editor.setText(str(index.data() or "").replace(",", ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text().strip())

    def _commit_and_advance(self, editor, record_id, column):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        QTimer.singleShot(
            0, lambda: self.enter_pressed.emit(record_id, column))


class FeeTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = FeeService(engine)
        self._activity_svc = ActivityService(engine)
        self._displayed_records = {}
        self._checked_ids: set[int] = set()
        self._last_checked_member_id: int = -1
        self._member_row_map: dict[int, int] = {}
        self._resizing_programmatically = False
        self._filling_table = False
        self._freeze_col = self._get_staff_setting("fee_freeze_col", -1)
        self._build_ui()
        self._apply_column_visibility()
        self._refresh_years()

    def _get_staff_setting(self, key: str, default=None):
        staff_name = self._config.last_staff_name
        return self._config.staff_settings.get(staff_name, {}).get(key, default)

    def _set_staff_setting(self, key: str, value):
        staff_name = self._config.last_staff_name
        if staff_name not in self._config.staff_settings:
            self._config.staff_settings[staff_name] = {}
        self._config.staff_settings[staff_name][key] = value
        if self._config_path:
            try:
                self._config.save(self._config_path)
            except Exception as error:
                print(f"Failed to save staff settings: {error}")

    def _build_ui(self):
        app = QApplication.instance()
        if app:
            font = QFont(app.font())
            font.setPointSize(font.pointSize() + 2)
            self.setFont(font)

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
        quick_input_btn = QPushButton("概算保険料を連続入力")
        quick_input_btn.clicked.connect(self._on_quick_premium_input)
        top_row.addWidget(quick_input_btn)
        debit_result_btn = QPushButton("口座振替結果（1期・2期）")
        debit_result_btn.clicked.connect(self._on_debit_results)
        top_row.addWidget(debit_result_btn)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        top_row.addWidget(export_btn)
        top_row.addStretch()
        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.clicked.connect(self._exec_column_menu)
        top_row.addWidget(col_setting_btn)
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
        self._check_header = _CheckHeader(self._table)
        self._check_header.toggled.connect(self._on_select_all)
        self._table.setHorizontalHeader(self._check_header)
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        header = self._check_header
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(True)
        header.setSortIndicatorShown(True)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        header.sectionResized.connect(self._on_column_resized)
        header.sectionMoved.connect(self._on_section_moved)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._premium_delegate = _PremiumDelegate(self._table)
        self._premium_delegate.enter_pressed.connect(self._edit_next_premium)
        for column_name in PREMIUM_COLS:
            self._table.setItemDelegateForColumn(
                COL_INDEX[column_name], self._premium_delegate)
        self._table.installEventFilter(self)
        layout.addWidget(self._table)

        self._frozen_view = QTableView(self._table)
        self._frozen_view.setModel(self._table.model())
        self._frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_view.verticalHeader().hide()
        self._frozen_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._frozen_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_view.setAlternatingRowColors(True)
        self._frozen_view.setFrameShape(QFrame.Shape.NoFrame)
        self._frozen_view.setSelectionModel(self._table.selectionModel())
        self._frozen_view.setItemDelegate(_FrozenItemDelegate(self._frozen_view))
        self._frozen_view.setItemDelegateForColumn(
            _COL_SELECT, _FrozenCheckDelegate(self._checked_ids, self._frozen_view))
        self._frozen_view.horizontalHeader().sectionClicked.connect(self._on_frozen_header_clicked)
        self._frozen_view.clicked.connect(self._on_frozen_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setVisible(False)
        self._table.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue)
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self._table.verticalScrollBar().setValue)

        button_row = QHBoxLayout()

        def separator():
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.VLine)
            frame.setFrameShadow(QFrame.Shadow.Sunken)
            return frame

        aggregate_btn = QPushButton("集約並び替え")
        aggregate_btn.clicked.connect(self._on_aggregate_sort)
        button_row.addWidget(aggregate_btn)
        button_row.addWidget(separator())

        button_row.addWidget(QLabel("選択："))
        self._filter_tokubetsu_chk = QCheckBox("特別加入")
        self._filter_tokubetsu_chk.stateChanged.connect(self._apply_selection_filters)
        button_row.addWidget(self._filter_tokubetsu_chk)
        self._filter_postal_chk = QCheckBox("郵送先あり")
        self._filter_postal_chk.stateChanged.connect(self._apply_selection_filters)
        button_row.addWidget(self._filter_postal_chk)
        button_row.addWidget(separator())

        label_btn = QPushButton("ラベル出力")
        label_btn.clicked.connect(self._on_label)
        button_row.addWidget(label_btn)
        reminder_email_btn = QPushButton("督促メール送信")
        reminder_email_btn.clicked.connect(self._on_compose_reminder_email)
        button_row.addWidget(reminder_email_btn)
        button_row.addStretch()
        activity_search_btn = QPushButton("対応履歴検索")
        activity_search_btn.clicked.connect(self._on_activity_search)
        button_row.addWidget(activity_search_btn)
        layout.addLayout(button_row)

        # 親のフォント継承だけに依存せず、操作部・一覧・固定列にも
        # 名簿・年度更新タブと同じ拡大フォントを明示的に適用する。
        for widget in self.findChildren(QWidget):
            widget.setFont(font)

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
        self._filling_table = True
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        if fiscal_year is None:
            self._table.setSortingEnabled(True)
            self._filling_table = False
            return
        keyword = self._search_edit.text().strip()
        status_filter = self._filter_combo.currentText()
        if status_filter == "すべて":
            status_filter = None
        records = self._svc.search(fiscal_year, keyword=keyword, status_filter=status_filter)
        debit_results = {
            period: self._svc.get_debit_results(fiscal_year, period)
            for period in ("1期", "2期")
        }
        if self._get_staff_setting("fee_aggregate_sort_active", False):
            records.sort(key=_aggregate_sort_key)
        self._displayed_records = {record.id: record for record in records}
        last_activity_map = self._activity_svc.get_last_logged_at_map(
            [record.member.id for record in records])
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            m = r.member
            check_container = QWidget()
            check_layout = QHBoxLayout(check_container)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check = QCheckBox()
            check.setChecked(m.id in self._checked_ids)
            check.stateChanged.connect(lambda state, member_id=m.id: self._on_check_changed(member_id, state))
            check_layout.addWidget(check)
            self._table.setCellWidget(row, _COL_SELECT, check_container)
            select_item = QTableWidgetItem()
            select_item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._table.setItem(row, _COL_SELECT, select_item)
            entries = {entry.ins_type: entry for entry in m.insurance_entries}
            active_accounts = [account for account in m.bank_accounts if account.is_enabled]
            separator = " ／ "
            account_types = {"1": "普通", "2": "当座", "4": "貯蓄"}
            values = {
                "管理No.": str(m.company_code or ""), "会員No.": m.member_number or "",
                "事業所名": m.org_name, "フリガナ": m.org_kana or "", "所属・役職": m.dept_title or "",
                "代表者名": m.rep_name or "", "代表者フリガナ": m.rep_kana or "", "メール": m.email or "",
                "市外局番": m.tel_area or "", "電話番号": m.tel or "", "FAX市外局番": m.fax_area or "",
                "FAX": m.fax or "", "郵便番号": m.postal_code or "", "住所": m.address or "",
                "郵送先郵便番号": m.postal_code_mail or "", "郵送先住所": m.address_mail or "",
                "郵送先事業所名": m.mail_org_name or "", "郵送先所属・役職名": m.mail_dept_title or "",
                "郵送先氏名": m.mail_person_name or "", "雇用保険事業所番号": m.employment_ins_no or "",
                "特別": "●" if any(entry.is_tokubetsu for entry in m.insurance_entries) else "",
                "継続一括": "●" if any(entry.is_ikkatsu for entry in m.insurance_entries) else "",
                "登録日": m.registered_date.strftime("%Y-%m-%d") if m.registered_date else "",
                "最終更新日": m.updated_at.strftime("%Y-%m-%d") if m.updated_at else "",
                "最終対応日": last_activity_map.get(m.id).strftime("%Y-%m-%d") if last_activity_map.get(m.id) else "",
                "メモ": m.note or "",
                "振込先金融機関": separator.join(f"{a.bank_name} ({a.bank_code})" for a in active_accounts),
                "振込先支店": separator.join(f"{a.branch_name} ({a.branch_code})" for a in active_accounts),
                "預金種目": separator.join(account_types.get(a.account_type, a.account_type) for a in active_accounts),
                "口座番号": separator.join(a.account_number for a in active_accounts),
                "受取人名カナ": separator.join(a.recipient_name_kana for a in active_accounts),
                "会員区分": "会員" if r.is_member_for_fee else "非会員",
                "概算保険料合計": f"{r.premium_total:,}", "請求合計": f"{r.total_amount:,}",
                "支払時期": r.final_payment_period or "", "支払方法": r.payment_method or "",
                "1期振替結果": self._format_debit_result(
                    debit_results["1期"].get(r.id)),
                "2期振替結果": self._format_debit_result(
                    debit_results["2期"].get(r.id)),
                "入金額": f"{r.paid_amount:,}" if r.paid_amount else "",
                "入金日": r.paid_at.strftime("%Y-%m-%d") if r.paid_at else "", "督促状況": r.reminder_status or "",
            }
            for ins_type, column_name in zip(BRANCH_TYPES, BRANCH_COLS):
                entry = entries.get(ins_type)
                values[column_name] = entry.ins_number if entry else ""
            for ins_type, field, column_name in zip(
                    BRANCH_TYPES, PREMIUM_FIELDS, PREMIUM_COLS):
                value = getattr(r, field)
                values[column_name] = f"{value:,}" if value else ""
            for col, column_name in enumerate(COLS):
                if col == _COL_SELECT:
                    continue
                value = values[column_name]
                item = FeeSortableTableWidgetItem(value)
                if column_name == "管理No.":
                    item.setData(Qt.ItemDataRole.UserRole, r.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column_name in PREMIUM_COLS:
                    branch_index = PREMIUM_COLS.index(column_name)
                    if BRANCH_TYPES[branch_index] in entries:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setData(Qt.ItemDataRole.UserRole, r.id)
                        item.setToolTip(
                            "クリックして入力。Enterで同じ枝番の次の事業所へ移動")
                    else:
                        item.setBackground(Qt.GlobalColor.lightGray)
                if column_name in PREMIUM_COLS + [
                        "概算保険料合計", "請求合計", "入金額"]:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._restore_table_settings()
        self._filling_table = False
        self._rebuild_member_row_map()
        all_checked = bool(records) and all(r.member.id in self._checked_ids for r in records)
        self._check_header.set_all_checked(all_checked)

    def _restore_table_settings(self):
        self._resizing_programmatically = True
        widths = self._get_staff_setting("fee_column_widths", {})
        for col in range(self._table.columnCount()):
            if str(col) in widths:
                self._table.setColumnWidth(col, int(widths[str(col)]))
            else:
                self._table.resizeColumnToContents(col)
        self._resizing_programmatically = False
        self._table.setSortingEnabled(True)
        sort_col = self._get_staff_setting("fee_sort_column", -1)
        if sort_col >= 0:
            order = Qt.SortOrder(self._get_staff_setting(
                "fee_sort_order", Qt.SortOrder.AscendingOrder.value))
            self._table.sortItems(sort_col, order)
            self._table.horizontalHeader().setSortIndicator(sort_col, order)
        self._update_frozen_view_geometry()

    # ── 列表示・並び替え・固定 ──

    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting("fee_hidden_columns", list(DEFAULT_HIDDEN_COLS))
        self._resizing_programmatically = True
        for index, column_name in enumerate(COLS):
            self._table.setColumnHidden(index, column_name in hidden_cols)
        order = self._get_staff_setting("fee_column_order")
        if order and len(order) == len(COLS):
            header = self._table.horizontalHeader()
            for visual, logical in enumerate(order):
                current = header.visualIndex(logical)
                if current != visual:
                    header.moveSection(current, visual)
        self._resizing_programmatically = False

    def _exec_column_menu(self, *_):
        dialog = QDialog(self)
        dialog.setWindowTitle("表示列選択")
        dialog.setMinimumWidth(320)
        outer = QVBoxLayout(dialog)
        hidden_cols = list(self._get_staff_setting("fee_hidden_columns", list(DEFAULT_HIDDEN_COLS)))
        half = (len(COLS) + 1) // 2
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        for row, (index, column_name) in enumerate(list(enumerate(COLS))[:half]):
            check = QCheckBox(column_name)
            check.setChecked(column_name not in hidden_cols)
            check.toggled.connect(lambda checked, col=index: self._toggle_column_visibility(col, checked))
            grid.addWidget(check, row, 0)
        for row, (index, column_name) in enumerate(list(enumerate(COLS))[half:]):
            check = QCheckBox(column_name)
            check.setChecked(column_name not in hidden_cols)
            check.toggled.connect(lambda checked, col=index: self._toggle_column_visibility(col, checked))
            grid.addWidget(check, row, 1)
        outer.addWidget(grid_widget)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("閉じる")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(close)
        outer.addLayout(buttons)
        dialog.exec()

    def _toggle_column_visibility(self, index: int, visible: bool):
        hidden_cols = list(self._get_staff_setting("fee_hidden_columns", list(DEFAULT_HIDDEN_COLS)))
        column_name = COLS[index]
        self._resizing_programmatically = True
        self._table.setColumnHidden(index, not visible)
        if visible:
            self._table.resizeColumnToContents(index)
            if column_name in hidden_cols:
                hidden_cols.remove(column_name)
        elif column_name not in hidden_cols:
            hidden_cols.append(column_name)
        self._resizing_programmatically = False
        self._set_staff_setting("fee_hidden_columns", hidden_cols)
        self._update_frozen_view_geometry()

    def _on_column_resized(self, logical_index: int, _old_size: int, new_size: int):
        if self._resizing_programmatically:
            return
        widths = dict(self._get_staff_setting("fee_column_widths", {}))
        widths[str(logical_index)] = new_size
        self._set_staff_setting("fee_column_widths", widths)
        self._update_frozen_view_geometry()

    def _on_section_moved(self, _logical: int, _old_visual: int, _new_visual: int):
        if self._resizing_programmatically:
            return
        header = self._table.horizontalHeader()
        order = [header.logicalIndex(visual) for visual in range(self._table.columnCount())]
        self._set_staff_setting("fee_column_order", order)

    def _on_sort_changed(self, logical_col: int, order):
        if logical_col < 0:
            return
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        self._set_staff_setting("fee_sort_column", logical_col)
        self._set_staff_setting("fee_sort_order", order.value)
        if not self._resizing_programmatically:
            self._set_staff_setting("fee_aggregate_sort_active", False)
        self._rebuild_member_row_map()

    def _show_column_menu(self, position):
        header = self._table.horizontalHeader()
        logical_col = header.logicalIndexAt(position)
        menu = QMenu(self)
        if 0 <= logical_col < len(COLS):
            menu.addAction(
                f"「{COLS[logical_col]}」列まで固定",
                lambda: self._set_freeze_col(logical_col),
            )
        if self._freeze_col >= 0:
            menu.addAction("列固定を解除", lambda: self._set_freeze_col(-1))
        menu.addSeparator()
        menu.addAction("表示列選択", self._exec_column_menu)
        menu.exec(header.mapToGlobal(position))

    def _set_freeze_col(self, column: int):
        self._freeze_col = column
        self._set_staff_setting("fee_freeze_col", column)
        self._update_frozen_view_geometry()

    def _update_frozen_view_geometry(self):
        if self._freeze_col < 0:
            self._frozen_view.setVisible(False)
            return
        frozen_width = 0
        for column in range(self._table.columnCount()):
            hidden = self._table.isColumnHidden(column) or column > self._freeze_col
            self._frozen_view.setColumnHidden(column, hidden)
            if not hidden:
                width = self._table.columnWidth(column)
                self._frozen_view.setColumnWidth(column, width)
                frozen_width += width
        self._frozen_view.horizontalHeader().setFixedHeight(
            self._table.horizontalHeader().height())
        for row in range(self._table.rowCount()):
            self._frozen_view.setRowHeight(row, self._table.rowHeight(row))
        frame_width = self._table.frameWidth()
        vertical_header_width = self._table.verticalHeader().width()
        self._frozen_view.setGeometry(
            frame_width + vertical_header_width, frame_width, frozen_width,
            self._table.height() - frame_width * 2,
        )
        self._frozen_view.setVisible(True)
        self._frozen_view.raise_()

    def eventFilter(self, object_, event):
        if object_ is self._table and event.type() == QEvent.Type.Resize:
            self._update_frozen_view_geometry()
        return super().eventFilter(object_, event)

    def _on_frozen_header_clicked(self, logical_col: int):
        header = self._table.horizontalHeader()
        if header.sortIndicatorSection() == logical_col:
            order = (Qt.SortOrder.DescendingOrder
                     if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
                     else Qt.SortOrder.AscendingOrder)
        else:
            order = Qt.SortOrder.AscendingOrder
        self._table.sortItems(logical_col, order)
        header.setSortIndicator(logical_col, order)

    # ── 督促メール対象の選択 ──

    def _on_select_all(self, checked: bool):
        if checked:
            self._checked_ids.update(record.member.id for record in self._displayed_records.values())
        else:
            self._checked_ids.difference_update(
                record.member.id for record in self._displayed_records.values())
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            checkbox = container.findChild(QCheckBox) if container else None
            if checkbox:
                checkbox.blockSignals(True)
                checkbox.setChecked(checked)
                checkbox.blockSignals(False)
        self._frozen_view.viewport().update()

    def _on_check_changed(self, member_id: int, state: int):
        checked = state == Qt.CheckState.Checked.value
        modifiers = QApplication.keyboardModifiers()
        if (modifiers & Qt.KeyboardModifier.ShiftModifier) and self._last_checked_member_id >= 0:
            start = self._find_row_by_member_id(self._last_checked_member_id)
            end = self._find_row_by_member_id(member_id)
            if start >= 0 and end >= 0:
                for row in range(min(start, end), max(start, end) + 1):
                    item = self._table.item(row, _COL_SELECT)
                    current_id = item.data(Qt.ItemDataRole.UserRole) if item else None
                    container = self._table.cellWidget(row, _COL_SELECT)
                    checkbox = container.findChild(QCheckBox) if container else None
                    if current_id is None or checkbox is None:
                        continue
                    checkbox.blockSignals(True)
                    checkbox.setChecked(checked)
                    checkbox.blockSignals(False)
                    if checked:
                        self._checked_ids.add(current_id)
                    else:
                        self._checked_ids.discard(current_id)
        elif checked:
            self._checked_ids.add(member_id)
        else:
            self._checked_ids.discard(member_id)
        self._last_checked_member_id = member_id
        all_checked = bool(self._displayed_records) and all(
            record.member.id in self._checked_ids for record in self._displayed_records.values())
        self._check_header.set_all_checked(all_checked)
        self._frozen_view.viewport().update()

    def _find_row_by_member_id(self, member_id: int) -> int:
        return self._member_row_map.get(member_id, -1)

    def _rebuild_member_row_map(self):
        self._member_row_map = {}
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_SELECT)
            member_id = item.data(Qt.ItemDataRole.UserRole) if item else None
            if member_id is not None:
                self._member_row_map[member_id] = row

    def _on_frozen_clicked(self, index):
        if index.column() == _COL_SELECT:
            member_id = index.data(Qt.ItemDataRole.UserRole)
            if member_id is not None:
                checked = member_id not in self._checked_ids
                self._on_check_changed(
                    member_id,
                    Qt.CheckState.Checked.value if checked else Qt.CheckState.Unchecked.value,
                )
        else:
            self._table.selectRow(index.row())

    def _apply_selection_filters(self):
        want_tokubetsu = self._filter_tokubetsu_chk.isChecked()
        want_postal = self._filter_postal_chk.isChecked()
        self._checked_ids.clear()
        if want_tokubetsu or want_postal:
            for record in self._displayed_records.values():
                member = record.member
                if want_tokubetsu and not any(
                    entry.is_tokubetsu for entry in member.insurance_entries
                ):
                    continue
                if want_postal and not (member.postal_code_mail or member.address_mail):
                    continue
                self._checked_ids.add(member.id)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_SELECT)
            member_id = item.data(Qt.ItemDataRole.UserRole) if item else None
            container = self._table.cellWidget(row, _COL_SELECT)
            checkbox = container.findChild(QCheckBox) if container else None
            if checkbox:
                checkbox.blockSignals(True)
                checkbox.setChecked(member_id in self._checked_ids)
                checkbox.blockSignals(False)
        all_checked = bool(self._displayed_records) and all(
            record.member.id in self._checked_ids for record in self._displayed_records.values())
        self._check_header.set_all_checked(all_checked)
        self._frozen_view.viewport().update()

    def _on_aggregate_sort(self):
        self._set_staff_setting("fee_sort_column", -1)
        self._set_staff_setting("fee_aggregate_sort_active", True)
        self._table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._refresh()

    def _on_label(self):
        from app.ui.dialogs.label_dialog import LabelDialog
        members = [
            record.member for record in self._displayed_records.values()
            if record.member.id in self._checked_ids
        ]
        if not members:
            QMessageBox.warning(
                self, "ラベル出力",
                "出力する事業所を選択してください（左端のチェックボックスで選択）。")
            return
        LabelDialog(self._engine, members, self._config, self._config_path, parent=self).exec()

    def _on_activity_search(self):
        from app.ui.dialogs.activity_search_dialog import ActivitySearchDialog
        ActivitySearchDialog(self._engine, parent=self).exec()

    def _on_compose_reminder_email(self):
        from app.ui.dialogs.compose_email_dialog import ComposeEmailDialog
        members = [
            record.member for record in self._displayed_records.values()
            if record.member.id in self._checked_ids
        ]
        if not members:
            QMessageBox.warning(
                self, "督促メール送信",
                "送信先を選択してください（左端のチェックボックスで選択）。")
            return
        ComposeEmailDialog(self._engine, self._config, members, parent=self).exec()

    def _on_frozen_double_clicked(self, index):
        self._table.selectRow(index.row())
        self._on_row_double_clicked(self._table.model().index(index.row(), 0))

    def _on_cell_clicked(self, row: int, column: int):
        if column not in {COL_INDEX[name] for name in PREMIUM_COLS}:
            return
        item = self._table.item(row, column)
        if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
            self._table.editItem(item)

    def _on_item_changed(self, item: QTableWidgetItem):
        premium_columns = {
            COL_INDEX[name]: field
            for name, field in zip(PREMIUM_COLS, PREMIUM_FIELDS)
        }
        if self._filling_table or item.column() not in premium_columns:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if not record_id:
            return
        raw_value = item.text().replace(",", "").strip()
        if raw_value and not raw_value.isdigit():
            QMessageBox.warning(
                self, "入力エラー", "概算保険料は0以上の整数で入力してください。")
            self._refresh()
            return
        value = int(raw_value) if raw_value else 0
        try:
            updated = self._svc.update(
                record_id, {premium_columns[item.column()]: value})
        except Exception as error:
            QMessageBox.critical(self, "保存エラー", str(error))
            self._refresh()
            return

        self._filling_table = True
        self._table.setSortingEnabled(False)
        item.setText(f"{value:,}" if value else "")
        self._table.item(
            item.row(), COL_INDEX["概算保険料合計"]).setText(
                f"{updated.premium_total:,}")
        self._table.item(item.row(), COL_INDEX["請求合計"]).setText(
            f"{updated.total_amount:,}")
        self._displayed_records[record_id] = updated
        self._table.setSortingEnabled(True)
        self._filling_table = False

    def _edit_next_premium(self, record_id: int, column: int):
        current_row = -1
        for row in range(self._table.rowCount()):
            item = self._table.item(row, column)
            if item and item.data(Qt.ItemDataRole.UserRole) == record_id:
                current_row = row
                break
        for row in range(current_row + 1, self._table.rowCount()):
            item = self._table.item(row, column)
            if item and item.flags() & Qt.ItemFlag.ItemIsEditable:
                self._table.setCurrentCell(row, column)
                self._table.scrollToItem(item)
                self._table.editItem(item)
                return

    def _on_row_double_clicked(self, index):
        if index.column() in {COL_INDEX[name] for name in PREMIUM_COLS}:
            return
        item = self._table.item(index.row(), COL_INDEX["管理No."])
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

    def _on_quick_premium_input(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に年度を選択または追加してください。")
            return
        record_ids = self._visible_unentered_record_ids()
        if not record_ids:
            QMessageBox.information(self, "概算保険料を連続入力", "未入力の事業所はありません。")
            return
        dialog = QuickPremiumInputDialog(
            self._engine, record_ids, parent=self,
            on_record_saved=self._refresh)
        dialog.exec()
        self._refresh()

    @staticmethod
    def _format_debit_result(result):
        if not result:
            return "未確認"
        if result["is_paid"]:
            return "入金済"
        progress = []
        if result.get("notified_at"):
            progress.append("連絡済")
        if result.get("notice_sent_at"):
            progress.append("発送済")
        suffix = f"・{'・'.join(progress)}" if progress else ""
        return f"不能（{result['failure_reason']}）{suffix}"

    def _on_debit_results(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(
                self, "確認", "先に年度を選択または追加してください。")
            return
        if DebitResultDialog(
                self._engine, fiscal_year, parent=self).exec():
            self._refresh()

    def _visible_unentered_record_ids(self) -> list[int]:
        """現在の一覧表示・並び替え順に、未入力レコードのIDを返す。"""
        record_ids = []
        record_id_column = COL_INDEX["管理No."]
        for row in range(self._table.rowCount()):
            item = self._table.item(row, record_id_column)
            record_id = item.data(Qt.ItemDataRole.UserRole) if item else None
            record = self._displayed_records.get(record_id)
            if record is not None and record.premium_total == 0:
                record_ids.append(record_id)
        return record_ids

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
