import html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QHeaderView,
    QGroupBox, QScrollArea, QLabel, QMenu, QLineEdit, QCheckBox,
    QFrame, QDialog, QGridLayout, QApplication,
    QTableView, QAbstractItemView,
)
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtCore import Qt, QEvent, QTimer
from app.services.member_service import MemberService, INS_TYPES
from app.services.activity_service import ActivityService
from app.ui.member_tab import (
    SortableTableWidgetItem, _SelectionDelegate, _CheckHeader,
    _FrozenCheckDelegate,
)
from app.ui.dialogs.member_edit_dialog import MemberEditDialog

COLS = [
    "",                 # 0: checkbox
    "委託解除日",       # 1
    "委託解除理由",     # 2
    "No.", "会", "会員No.", "事業所名", "フリガナ", "所属・役職",
    "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
    "郵便番号", "住所",
    "郵送先郵便番号", "郵送先住所", "郵送先宛名", "雇用保険事業所番号",
    "0", "2", "4", "5", "6", "特別", "継続一括", "登録日", "最終対応日", "メモ",
]

_COL_SELECT       = 0
_COL_WITHDRAWN_AT = 1
_COL_REASON       = 2
_COL_OFFSET       = 3   # No. (company_code) の列インデックス

_AC = Qt.AlignmentFlag.AlignCenter


class WithdrawnTab(QWidget):
    def __init__(self, engine, config, config_path=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = MemberService(engine)
        self._activity_svc = ActivityService(engine)
        self._members = []
        self._checked_ids: set[int] = set()
        self._last_activity_map: dict = {}
        self._resizing_programmatically = False
        self._last_checked_member_id: int = -1
        self._freeze_col: int = self._get_staff_setting("withdrawn_freeze_col", 0)
        self._member_row_map: dict[int, int] = {}
        self._build_ui()
        self._apply_column_visibility()
        self._refresh()

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

    def reload_staff_settings(self):
        """ログアウト→ログイン後に呼び出し、列設定を切り替える"""
        # チェック状態をリセット（別職員のチェックが引き継がれないよう）
        self._checked_ids.clear()
        self._last_checked_member_id = -1
        self._check_header.set_all_checked(False)
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            if container:
                chk = container.findChild(QCheckBox)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)
        self._frozen_view.viewport().update()

        self._freeze_col = self._get_staff_setting("withdrawn_freeze_col", 0)
        self._apply_column_visibility()
        saved = self._get_staff_setting("withdrawn_column_widths", {})
        self._resizing_programmatically = True
        for i in range(self._table.columnCount()):
            if i == _COL_SELECT:
                self._table.setColumnWidth(i, 44)
            elif str(i) in saved:
                self._table.setColumnWidth(i, int(saved[str(i)]))
            else:
                self._table.resizeColumnToContents(i)
        self._resizing_programmatically = False
        self._update_frozen_view_geometry()

    # ── UI 構築 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 検索エリア
        search_row = QHBoxLayout()
        search_font = QFont(QApplication.instance().font())
        search_font.setPointSize(search_font.pointSize() + 2)

        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・代表者名・代表者フリガナ・住所・電話番号で検索")
        self._keyword_edit.textChanged.connect(self._refresh)
        self._keyword_edit.setFont(search_font)
        search_row.addWidget(self._keyword_edit)

        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.setFont(search_font)
        col_setting_btn.clicked.connect(self._exec_column_menu)
        search_row.addWidget(col_setting_btn)
        layout.addLayout(search_row)

        content_layout = QHBoxLayout()

        # 一覧テーブル
        self._table = QTableWidget(0, len(COLS))
        self._check_header = _CheckHeader(self._table)
        self._check_header.toggled.connect(self._on_select_all)
        self._table.setHorizontalHeader(self._check_header)
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._check_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._check_header.setSectionsMovable(True)
        self._check_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._check_header.customContextMenuRequested.connect(self._show_column_menu)
        self._check_header.sectionResized.connect(self._on_column_resized)
        self._check_header.sectionMoved.connect(self._on_section_moved)
        self._check_header.sortIndicatorChanged.connect(self._on_main_sort_changed)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._check_header.setMinimumSectionSize(30)
        self._table.setItemDelegate(_SelectionDelegate(self._table))
        self._table.itemDoubleClicked.connect(self._on_edit)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self._table, stretch=2)

        # 列固定オーバーレイ
        self._frozen_view = QTableView(self._table)
        self._frozen_view.setModel(self._table.model())
        self._frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_view.verticalHeader().hide()
        self._frozen_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self._frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._frozen_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_view.setFont(tbl_font)
        self._frozen_view.setAlternatingRowColors(True)
        self._frozen_view.setFrameShape(QFrame.Shape.NoFrame)
        self._frozen_view.horizontalHeader().setFont(tbl_font)
        self._frozen_view.verticalHeader().setDefaultSectionSize(30)
        self._frozen_view.setItemDelegateForColumn(
            _COL_SELECT, _FrozenCheckDelegate(self._checked_ids, self._frozen_view))
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(
            self._on_frozen_header_clicked)
        self._frozen_view.clicked.connect(self._on_frozen_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frozen_view.customContextMenuRequested.connect(self._on_frozen_context_menu)
        self._frozen_view.setVisible(False)

        # 縦スクロール同期
        self._table.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue)
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self._table.verticalScrollBar().setValue)

        self._table.installEventFilter(self)

        # 対応履歴パネル
        self._activity_panel = QGroupBox("対応履歴")
        self._activity_panel.setFixedWidth(380)
        panel_layout = QVBoxLayout(self._activity_panel)

        self._placeholder_label = QLabel("一覧から会員を選択してください。")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._placeholder_label)

        self._log_scroll = QScrollArea()
        self._log_scroll.setWidgetResizable(True)
        self._log_container = QWidget()
        self._log_vbox = QVBoxLayout(self._log_container)
        self._log_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._log_scroll.setWidget(self._log_container)
        panel_layout.addWidget(self._log_scroll)
        self._log_scroll.setVisible(False)

        content_layout.addWidget(self._activity_panel)
        layout.addLayout(content_layout)

        # ボタン行
        def _sep():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFrameShadow(QFrame.Shadow.Sunken)
            return f

        btn_row = QHBoxLayout()

        agg_btn = QPushButton("集約並び替え")
        agg_btn.clicked.connect(self._on_aggregate_sort)
        btn_row.addWidget(agg_btn)

        btn_row.addWidget(_sep())

        btn_row.addWidget(QLabel("選択:"))
        self._filter_tokubetsu_chk = QCheckBox("特別加入")
        self._filter_tokubetsu_chk.stateChanged.connect(self._apply_selection_filters)
        btn_row.addWidget(self._filter_tokubetsu_chk)
        self._filter_postal_chk = QCheckBox("郵送先あり")
        self._filter_postal_chk.stateChanged.connect(self._apply_selection_filters)
        btn_row.addWidget(self._filter_postal_chk)

        btn_row.addWidget(_sep())

        label_btn = QPushButton("ラベル出力")
        label_btn.clicked.connect(self._on_label)
        btn_row.addWidget(label_btn)

        email_btn = QPushButton("メール送信")
        email_btn.clicked.connect(self._on_compose_email)
        btn_row.addWidget(email_btn)

        btn_row.addStretch()

        reactivate_btn = QPushButton("委託解除を取消")
        reactivate_btn.clicked.connect(self._on_reactivate)
        btn_row.addWidget(reactivate_btn)

        self._activity_toggle_btn = QPushButton("対応履歴 ≪")
        self._activity_toggle_btn.clicked.connect(self._on_toggle_activity_panel)
        btn_row.addWidget(self._activity_toggle_btn)

        layout.addLayout(btn_row)

    # ── データ取得・描画 ──

    def _refresh(self):
        members = self._svc.search(
            keyword=self._keyword_edit.text(),
            inactive_only=True,
        )
        self._members = members
        member_ids = [m.id for m in members]
        self._last_activity_map = self._activity_svc.get_last_logged_at_map(member_ids)
        self._fill_table(members)

    def _fill_table(self, members):
        self._member_row_map = {}
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(members))

        for row, m in enumerate(members):
            self._member_row_map[m.id] = row
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            has_ikkatsu   = any(e.is_ikkatsu   for e in m.insurance_entries)

            # チェックボックス列（中央ぞろえ）
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

            # 委託解除固有列
            wd = SortableTableWidgetItem(
                m.withdrawn_at.strftime("%Y-%m-%d") if m.withdrawn_at else ""
            )
            wd.setTextAlignment(_AC)
            self._table.setItem(row, _COL_WITHDRAWN_AT, wd)
            self._table.setItem(row, _COL_REASON,
                                SortableTableWidgetItem(m.withdraw_reason or ""))

            # 共通列
            o = _COL_OFFSET
            code_item = SortableTableWidgetItem(str(m.company_code) if m.company_code else "")
            code_item.setData(Qt.ItemDataRole.UserRole, m.id)
            code_item.setTextAlignment(_AC)
            self._table.setItem(row, o + 0, code_item)

            mem_item = SortableTableWidgetItem("○" if getattr(m, "is_member", True) else "")
            mem_item.setTextAlignment(_AC)
            self._table.setItem(row, o + 1, mem_item)

            mno_item = SortableTableWidgetItem(m.member_number or "")
            mno_item.setTextAlignment(_AC)
            self._table.setItem(row, o + 2, mno_item)

            self._table.setItem(row, o + 3, SortableTableWidgetItem(m.org_name))
            self._table.setItem(row, o + 4, SortableTableWidgetItem(m.org_kana or ""))
            self._table.setItem(row, o + 5, SortableTableWidgetItem(m.dept_title or ""))
            self._table.setItem(row, o + 6, SortableTableWidgetItem(m.rep_name or ""))
            self._table.setItem(row, o + 7, SortableTableWidgetItem(m.rep_kana or ""))
            self._table.setItem(row, o + 8, SortableTableWidgetItem(m.email or ""))

            # 市外局番(o+9) / 電話番号(o+10) / FAX市外局番(o+11) / FAX(o+12)
            for delta, text in enumerate([
                m.tel_area or "",
                m.tel or "",
                m.fax_area or "",
                m.fax or "",
                m.postal_code or "",
                m.address or "",
                m.postal_code_mail or "",
                m.address_mail or "",
                m.addressee_mail or "",
                m.employment_ins_no or "",
            ]):
                item = SortableTableWidgetItem(text)
                item.setTextAlignment(_AC)
                self._table.setItem(row, o + 9 + delta, item)

            ins_map = {e.ins_type: e for e in m.insurance_entries}
            for col_idx, ins_type in enumerate(INS_TYPES):
                entry = ins_map.get(ins_type)
                item = SortableTableWidgetItem(entry.ins_number if entry else "")
                item.setTextAlignment(_AC)
                if entry:
                    if entry.is_tokubetsu and entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(216, 180, 254)))
                    elif entry.is_tokubetsu:
                        item.setBackground(QBrush(QColor(226, 240, 217)))
                    elif entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(255, 224, 178)))
                self._table.setItem(row, o + 19 + col_idx, item)

            toku = SortableTableWidgetItem("●" if has_tokubetsu else "")
            toku.setTextAlignment(_AC)
            self._table.setItem(row, o + 24, toku)

            ikk = SortableTableWidgetItem("●" if has_ikkatsu else "")
            ikk.setTextAlignment(_AC)
            self._table.setItem(row, o + 25, ikk)

            reg_item = SortableTableWidgetItem(
                m.registered_date.strftime("%Y-%m-%d") if m.registered_date else ""
            )
            reg_item.setTextAlignment(_AC)
            self._table.setItem(row, o + 26, reg_item)

            last_act = self._last_activity_map.get(m.id)
            act_item = SortableTableWidgetItem(
                last_act.strftime("%Y-%m-%d") if last_act else ""
            )
            act_item.setTextAlignment(_AC)
            self._table.setItem(row, o + 27, act_item)

            self._table.setItem(row, o + 28, SortableTableWidgetItem(m.note or ""))

        # 列幅適用
        self._resizing_programmatically = True
        saved = self._get_staff_setting("withdrawn_column_widths", {})
        for i in range(self._table.columnCount()):
            if i == _COL_SELECT:
                self._table.setColumnWidth(i, 44)
            elif str(i) in saved:
                self._table.setColumnWidth(i, int(saved[str(i)]))
            else:
                self._table.resizeColumnToContents(i)
        self._resizing_programmatically = False

        self._table.setSortingEnabled(True)
        self._update_frozen_view_geometry()
        QTimer.singleShot(0, self._update_frozen_view_geometry)

    # ── 選択・チェック ──

    def _selected_member(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, _COL_OFFSET)
        if not item:
            return None
        return next((x for x in self._members if x.id == item.data(Qt.ItemDataRole.UserRole)), None)

    def _on_select_all(self, checked: bool):
        if checked:
            for m in self._members:
                self._checked_ids.add(m.id)
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

    def _apply_selection_filters(self):
        want_tokubetsu = self._filter_tokubetsu_chk.isChecked()
        want_postal    = self._filter_postal_chk.isChecked()

        self._checked_ids.clear()
        if want_tokubetsu or want_postal:
            for m in self._members:
                if want_tokubetsu and not any(e.is_tokubetsu for e in m.insurance_entries):
                    continue
                if want_postal and not m.postal_code_mail:
                    continue
                self._checked_ids.add(m.id)

        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            if container:
                chk = container.findChild(QCheckBox)
                item = self._table.item(row, _COL_OFFSET)
                mid = item.data(Qt.ItemDataRole.UserRole) if item else None
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(mid in self._checked_ids)
                    chk.blockSignals(False)

        all_on = bool(self._checked_ids) and len(self._checked_ids) == len(self._members)
        self._check_header.set_all_checked(all_on)
        self._frozen_view.viewport().update()

    def _on_check_changed(self, member_id: int, state: int):
        new_checked = (state == Qt.CheckState.Checked.value)
        mods = QApplication.keyboardModifiers()

        if (mods & Qt.KeyboardModifier.ShiftModifier) and self._last_checked_member_id >= 0:
            start_row = self._find_row_by_member_id(self._last_checked_member_id)
            end_row   = self._find_row_by_member_id(member_id)
            if start_row >= 0 and end_row >= 0:
                for r in range(min(start_row, end_row), max(start_row, end_row) + 1):
                    container = self._table.cellWidget(r, _COL_SELECT)
                    item = self._table.item(r, _COL_OFFSET)
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
        all_on = bool(self._members) and all(m.id in self._checked_ids for m in self._members)
        self._check_header.set_all_checked(all_on)
        self._frozen_view.viewport().update()

    def _find_row_by_member_id(self, member_id: int) -> int:
        return self._member_row_map.get(member_id, -1)

    def _set_freeze_col(self, col: int):
        self._freeze_col = col
        self._set_staff_setting("withdrawn_freeze_col", col)
        self._update_frozen_view_geometry()

    def _update_frozen_view_geometry(self):
        n = self._freeze_col
        table = self._table

        if n <= 0:
            self._frozen_view.setVisible(False)
            return

        frozen_width = 0
        col_count = table.columnCount()
        for c in range(col_count):
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

    def _rebuild_member_row_map(self):
        self._member_row_map = {}
        for r in range(self._table.rowCount()):
            item = self._table.item(r, _COL_OFFSET)
            if item:
                mid = item.data(Qt.ItemDataRole.UserRole)
                if mid is not None:
                    self._member_row_map[mid] = r

    def _on_frozen_header_clicked(self, logical_col: int):
        current_col = self._check_header.sortIndicatorSection()
        current_order = self._check_header.sortIndicatorOrder()
        if current_col == logical_col:
            new_order = (Qt.SortOrder.DescendingOrder
                         if current_order == Qt.SortOrder.AscendingOrder
                         else Qt.SortOrder.AscendingOrder)
        else:
            new_order = Qt.SortOrder.AscendingOrder
        self._table.sortItems(logical_col, new_order)
        self._check_header.setSortIndicator(logical_col, new_order)
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, new_order)
        self._rebuild_member_row_map()

    def _on_main_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        self._rebuild_member_row_map()

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

    def _on_frozen_double_clicked(self, index):
        if index.column() != _COL_SELECT:
            self._table.selectRow(index.row())
            self._on_edit()

    def _on_frozen_context_menu(self, pos):
        index = self._frozen_view.indexAt(pos)
        if index.isValid():
            self._table.selectRow(index.row())
        if not self._selected_member():
            return
        menu = QMenu(self)
        menu.addAction("編集",  self._on_edit)
        menu.addAction("再加入", self._on_reactivate)
        menu.exec(self._frozen_view.viewport().mapToGlobal(pos))

    # ── コンテキストメニュー ──

    def _on_context_menu(self, pos):
        if not self._selected_member():
            return
        menu = QMenu(self)
        menu.addAction("編集",  self._on_edit)
        menu.addAction("再加入", self._on_reactivate)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── アクション ──

    def _on_aggregate_sort(self):
        def _ins_key(m, ins_type):
            entry = next((e for e in m.insurance_entries if e.ins_type == ins_type), None)
            val = entry.ins_number if entry else ""
            try:
                return (0, int(val))
            except (ValueError, TypeError):
                return (1, val or "")

        self._members.sort(key=lambda m: (
            _ins_key(m, "ippan"),
            _ins_key(m, "kensetsu_koyou"),
            _ins_key(m, "ringyo"),
            _ins_key(m, "kensetsu_genba"),
            _ins_key(m, "kensetsu_jimusho"),
        ))
        self._fill_table(self._members)

    def _on_label(self):
        from app.ui.dialogs.label_dialog import LabelDialog
        members = [m for m in self._members if m.id in self._checked_ids]
        if not members:
            QMessageBox.warning(self, "ラベル出力",
                "出力する会員を選択してください（左端のチェックボックスで選択）。")
            return
        LabelDialog(self._engine, members, parent=self).exec()

    def _on_compose_email(self):
        from app.ui.dialogs.compose_email_dialog import ComposeEmailDialog
        members = [m for m in self._members if m.id in self._checked_ids]
        if not members:
            QMessageBox.warning(self, "メール送信", "送信先を選択してください（左端のチェックボックスで選択）。")
            return
        ComposeEmailDialog(self._engine, self._config, members, parent=self).exec()

    def _on_edit(self):
        m = self._selected_member()
        if not m:
            return
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, m.id,
                               show_withdraw_info=True, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_reactivate(self):
        m = self._selected_member()
        if not m:
            QMessageBox.information(self, "委託解除を取消", "一覧から会員を選択してください。")
            return
        reply = QMessageBox.warning(
            self, "委託解除を取消",
            f"「{m.org_name}」の委託解除を取消し、名簿に戻します。\n\nよいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._svc.undo_withdraw(m.id, self._config.last_staff_name)
            QMessageBox.information(self, "完了", f"「{m.org_name}」を名簿に戻しました。")
            self._refresh()

    def _on_toggle_activity_panel(self):
        visible = not self._activity_panel.isVisible()
        self._activity_panel.setVisible(visible)
        self._activity_toggle_btn.setText("対応履歴 ≪" if visible else "対応履歴 ≫")

    # ── 対応履歴パネル ──

    def _on_selection_changed(self):
        m = self._selected_member()
        if not m:
            self._placeholder_label.setVisible(True)
            self._log_scroll.setVisible(False)
            self._activity_panel.setTitle("対応履歴")
            return
        self._placeholder_label.setVisible(False)
        self._log_scroll.setVisible(True)
        self._activity_panel.setTitle(f"対応履歴 - {m.org_name}")
        self._load_activity_logs(m.id)

    def _load_activity_logs(self, member_id):
        while self._log_vbox.count():
            item = self._log_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        logs = self._activity_svc.get_logs(member_id)
        for log in logs:
            cat_names = "・".join(c.name for c in log.categories) if log.categories else "カテゴリなし"
            entry = QWidget()
            entry.setStyleSheet("border:1px solid #ddd; border-radius:4px; padding:4px; margin:2px;")
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(6, 4, 6, 4)
            header_lbl = QLabel(
                f"<b>{log.logged_at.strftime('%Y-%m-%d %H:%M')}</b>　{html.escape(log.logged_by)}　"
                f"<span style='color:#666'>[{html.escape(cat_names)}]</span>"
            )
            content_lbl = QLabel(log.content)
            content_lbl.setTextFormat(Qt.TextFormat.PlainText)
            content_lbl.setWordWrap(True)
            entry_layout.addWidget(header_lbl)
            entry_layout.addWidget(content_lbl)
            self._log_vbox.addWidget(entry)

        if not logs:
            self._log_vbox.addWidget(QLabel("対応履歴はありません。"))

    # ── 列表示・幅・順序 ──

    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting(
            "withdrawn_hidden_columns",
            list(self._config.withdrawn_hidden_columns),
        )
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)
        # 列順を復元
        order = self._get_staff_setting("withdrawn_column_order")
        if order and len(order) == len(COLS):
            self._resizing_programmatically = True
            for visual, logical in enumerate(order):
                current = self._check_header.visualIndex(logical)
                if current != visual:
                    self._check_header.moveSection(current, visual)
            self._resizing_programmatically = False

    def _show_column_menu(self, pos):
        logical = self._check_header.logicalIndexAt(pos)
        menu = QMenu(self)
        if logical > 0 and logical < len(COLS):
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
        menu.exec(self._check_header.mapToGlobal(pos))

    def _exec_column_menu(self, *_):
        dlg = QDialog(self)
        dlg.setWindowTitle("表示列選択")
        dlg.setMinimumWidth(320)

        hidden_cols = list(self._get_staff_setting(
            "withdrawn_hidden_columns", list(self._config.withdrawn_hidden_columns)))

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
        hidden = list(self._get_staff_setting(
            "withdrawn_hidden_columns",
            list(self._config.withdrawn_hidden_columns),
        ))
        if visible:
            self._table.showColumn(idx)
            self._resizing_programmatically = True
            self._table.resizeColumnToContents(idx)
            self._resizing_programmatically = False
            if COLS[idx] in hidden:
                hidden.remove(COLS[idx])
        else:
            self._table.hideColumn(idx)
            if COLS[idx] not in hidden:
                hidden.append(COLS[idx])
        self._set_staff_setting("withdrawn_hidden_columns", hidden)
        if self._freeze_col > 0:
            self._update_frozen_view_geometry()

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        if self._resizing_programmatically:
            return
        widths = dict(self._get_staff_setting("withdrawn_column_widths", {}))
        if new_size == 0:
            widths.pop(str(logical_index), None)
        else:
            widths[str(logical_index)] = new_size
        self._set_staff_setting("withdrawn_column_widths", widths)
        if self._freeze_col > 0 and logical_index <= self._freeze_col:
            self._update_frozen_view_geometry()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        if self._resizing_programmatically:
            return
        col0_visual = self._check_header.visualIndex(_COL_SELECT)
        if col0_visual != 0:
            self._resizing_programmatically = True
            self._check_header.moveSection(col0_visual, 0)
            self._resizing_programmatically = False
            return
        order = [self._check_header.logicalIndex(v)
                 for v in range(self._table.columnCount())]
        self._set_staff_setting("withdrawn_column_order", order)

    def jump_to_member(self, member_id: int):
        self._refresh()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_OFFSET)
            if item and item.data(Qt.ItemDataRole.UserRole) == member_id:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return
