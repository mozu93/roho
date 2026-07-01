import html
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QTableView, QAbstractItemView,
    QPushButton, QLabel, QHeaderView, QMenu, QFrame,
    QGroupBox, QScrollArea, QTextEdit, QMessageBox,
    QComboBox, QStyledItemDelegate, QStyle, QStyleOptionButton,
    QDialog, QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QEvent, QTimer
from PyQt6.QtGui import QAction, QColor, QBrush, QFont, QPalette
from PyQt6.QtWidgets import QApplication
from app.services.member_service import MemberService, INS_TYPES
from app.services.activity_service import ActivityService
from app.ui.dialogs.member_edit_dialog import MemberEditDialog
from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
from app.ui.dialogs.withdraw_dialog import WithdrawDialog
from app.ui.dialogs.import_dialog import ImportDialog
from app.ui.dialogs.activity_search_dialog import ActivitySearchDialog


class _FrozenCheckDelegate(QStyledItemDelegate):
    """固定列オーバーレイ内のチェックボックスを描画するデリゲート"""
    def __init__(self, checked_ids: set, parent=None):
        super().__init__(parent)
        self._checked_ids = checked_ids

    def paint(self, painter, option, index):
        mid = index.data(Qt.ItemDataRole.UserRole)
        if mid is None:
            super().paint(painter, option, index)
            return
        checked = mid in self._checked_ids
        opt = QStyleOptionButton()
        sz = 16
        opt.rect = QRect(
            option.rect.x() + (option.rect.width() - sz) // 2,
            option.rect.y() + (option.rect.height() - sz) // 2,
            sz, sz,
        )
        opt.state = (
            QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off
        ) | QStyle.StateFlag.State_Enabled
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox, opt, painter)


class _FrozenItemDelegate(QStyledItemDelegate):
    """凍結ビュー用: 選択行を薄い青で強調し、文字を太字で描画するデリゲート"""
    _SEL_BG = QColor(200, 225, 248)  # 薄い青（枝番色が透けて見えるよう薄く）

    def paint(self, painter, option, index):
        # ホバーを無効化（メインテーブルとの色差を防ぐ）
        option.state &= ~QStyle.StateFlag.State_MouseOver

        if option.state & QStyle.StateFlag.State_Selected:
            # Windows ネイティブ描画より先に薄い青を塗る
            painter.fillRect(option.rect, self._SEL_BG)
            # 選択フラグを外してテキスト・アイコンのみ描画（太字・元の文字色）
            option.state &= ~QStyle.StateFlag.State_Selected
            option.backgroundBrush = QBrush(self._SEL_BG)
            option.font.setBold(True)

        super().paint(painter, option, index)


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)

        self_text = self.text()
        other_text = other.text()

        if not self_text and not other_text:
            return False

        table = self.tableWidget()
        is_ascending = True
        if table:
            header = table.horizontalHeader()
            is_ascending = (header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder)

        if not self_text:
            return not is_ascending
        if not other_text:
            return is_ascending

        try:
            return float(self_text) < float(other_text)
        except ValueError:
            pass

        return self_text < other_text


class _SelectionDelegate(QStyledItemDelegate):
    """選択行のセル色を保持しつつ半透明オーバーレイで選択を表現するデリゲート"""
    _OVERLAY = QColor(37, 99, 235, 30)  # primary blue ~12% opacity

    def paint(self, painter, option, index):
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            bg = index.data(Qt.ItemDataRole.BackgroundRole)
            if bg and isinstance(bg, QBrush) and bg.color().isValid():
                painter.fillRect(option.rect, bg)
            elif index.row() % 2:
                painter.fillRect(option.rect, option.palette.alternateBase())
            else:
                painter.fillRect(option.rect, option.palette.base())
            painter.fillRect(option.rect, self._OVERLAY)
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if text:
                font = QFont(option.font)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(15, 23, 42))
                raw_align = index.data(Qt.ItemDataRole.TextAlignmentRole)
                align = Qt.AlignmentFlag(int(raw_align)) if raw_align is not None \
                    else Qt.AlignmentFlag.AlignLeft
                if not (align & Qt.AlignmentFlag.AlignVertical_Mask):
                    align |= Qt.AlignmentFlag.AlignVCenter
                painter.drawText(
                    option.rect.adjusted(4, 0, -4, 0),
                    align,
                    str(text),
                )
            painter.restore()
        else:
            super().paint(painter, option, index)


class _CheckHeader(QHeaderView):
    """列0ヘッダーにチェックボックスを描画し、クリックで全選択/解除を通知する"""
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._all_checked = False
        self.setSectionsClickable(True)

    def set_all_checked(self, checked: bool):
        if self._all_checked != checked:
            self._all_checked = checked
            self.viewport().update()

    def paintSection(self, painter, rect, logical_index: int):
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()
        if logical_index == 0:
            size = 16
            opt = QStyleOptionButton()
            opt.rect = QRect(
                rect.x() + (rect.width() - size) // 2,
                rect.y() + (rect.height() - size) // 2,
                size, size,
            )
            opt.state = (QStyle.StateFlag.State_Enabled |
                         (QStyle.StateFlag.State_On if self._all_checked
                          else QStyle.StateFlag.State_Off))
            self.style().drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorCheckBox, opt, painter
            )

    def mousePressEvent(self, event):
        logical = self.logicalIndexAt(event.pos())
        if logical == 0:
            self._all_checked = not self._all_checked
            self.viewport().update()
            self.toggled.emit(self._all_checked)
        else:
            super().mousePressEvent(event)


BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}
COLS = [
    "",
    "No.", "会", "会員No.", "事業所名", "フリガナ", "所属・役職",
    "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
    "郵便番号", "住所",
    "郵送先郵便番号", "郵送先住所", "郵送先宛名", "雇用保険事業所番号",
    "0", "2", "4", "5", "6", "特別", "継続一括", "登録日", "最終更新日", "最終対応日", "メモ"
]
# 列インデックス定数
_COL_SELECT = 0
_COL_COMPANY_CODE = 1
_COL_IS_MEMBER = 2
_COL_MEMBER_NUMBER = 3
_COL_ORG_NAME = 4


class MemberTab(QWidget):
    jump_to_withdrawn = pyqtSignal(int)  # 委託解除タブへ移動リクエスト

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
        self._last_change_map: dict = {}
        self._resizing_programmatically = False
        self._last_checked_member_id: int = -1
        self._freeze_col: int = self._get_staff_setting("freeze_col", 0)
        self._member_row_map: dict[int, int] = {}
        self._pending_member_id: int | None = None
        self._activity_load_timer = QTimer(self)
        self._activity_load_timer.setSingleShot(True)
        self._activity_load_timer.setInterval(80)
        self._activity_load_timer.timeout.connect(self._deferred_load_activity)
        self._build_ui()
        self._apply_column_visibility()
        self._refresh()

    # ── 個人別設定ヘルパー ──

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

        self._freeze_col = self._get_staff_setting("freeze_col", 0)
        self._apply_column_visibility()
        saved = self._get_staff_setting("column_widths",
                self._config.member_column_widths)
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

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 検索エリア
        search_row = QHBoxLayout()
        search_font = QFont(QApplication.instance().font())
        search_font.setPointSize(search_font.pointSize() + 2)

        add_btn = QPushButton("追加")
        add_btn.setFont(search_font)
        add_btn.clicked.connect(self._on_add)
        search_row.addWidget(add_btn)

        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・住所・電話番号で検索")
        self._keyword_edit.textChanged.connect(self._refresh)
        self._keyword_edit.setFont(search_font)
        search_row.addWidget(self._keyword_edit)

        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.setFont(search_font)
        col_setting_btn.clicked.connect(self._on_show_column_menu_btn)
        search_row.addWidget(col_setting_btn)

        layout.addLayout(search_row)


        # 中央の分割エリア（テーブルと対応履歴パネル）
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
        self._table.itemDoubleClicked.connect(self._on_edit)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        self._table.setColumnWidth(_COL_SELECT, 44)
        self._table.setItemDelegate(_SelectionDelegate(self._table))
        content_layout.addWidget(self._table, stretch=2)

        # 列固定オーバーレイ（_tableと同じモデルを共有するQTableView）
        self._frozen_view = QTableView(self._table)
        self._frozen_view.setModel(self._table.model())
        self._frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_view.verticalHeader().hide()
        self._frozen_view.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self._frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._frozen_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_view.setFont(tbl_font)
        self._frozen_view.setAlternatingRowColors(True)
        self._frozen_view.setFrameShape(QFrame.Shape.NoFrame)
        self._frozen_view.horizontalHeader().setFont(tbl_font)
        self._frozen_view.verticalHeader().setDefaultSectionSize(30)
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(
            self._on_frozen_header_clicked)
        self._frozen_view.clicked.connect(self._on_frozen_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frozen_view.customContextMenuRequested.connect(self._on_frozen_context_menu)
        # 選択モデルをメインテーブルと共有（凍結列にも選択ハイライトを同期）
        self._frozen_view.setSelectionModel(self._table.selectionModel())

        # 凍結ビュー: 選択行の文字を太字にするデリゲート（全列）を設定してから
        # チェックボックス列のみ上書き（setItemDelegate は列別設定を消去するため順序が重要）
        self._frozen_view.setItemDelegate(_FrozenItemDelegate(self._frozen_view))
        self._frozen_view.setItemDelegateForColumn(
            _COL_SELECT, _FrozenCheckDelegate(self._checked_ids, self._frozen_view))

        # メインテーブルの選択変更時に凍結ビューを再描画（非凍結列クリック時の同期）
        self._table.selectionModel().selectionChanged.connect(
            lambda *_: self._frozen_view.viewport().update()
        )

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

        # プレースホルダー（未選択時）
        self._placeholder_label = QLabel("名簿から会員を選択してください。")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._placeholder_label)

        # 対応履歴のコンテンツ（選択時に表示）
        self._activity_content = QWidget()
        content_vbox = QVBoxLayout(self._activity_content)
        content_vbox.setContentsMargins(0, 0, 0, 0)

        # 新規メモ入力エリア
        input_group = QGroupBox("新規対応メモを追加")
        input_layout = QVBoxLayout(input_group)

        # カテゴリ選択
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("カテゴリ："))
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("カテゴリなし", None)
        for cat in self._activity_svc.get_categories():
            self._cat_combo.addItem(cat.name, cat.id)
        cat_row.addWidget(self._cat_combo)
        cat_row.addStretch()
        input_layout.addLayout(cat_row)

        # テキスト入力
        self._content_edit = QTextEdit()
        self._content_edit.setFixedHeight(160)
        self._content_edit.setPlaceholderText("対応内容を入力してください")
        input_layout.addWidget(self._content_edit)

        # 保存ボタン
        save_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save_activity)
        save_row.addStretch()
        save_row.addWidget(save_btn)
        input_layout.addLayout(save_row)

        content_vbox.addWidget(input_group, stretch=1)

        # 履歴表示エリア
        log_scroll = QScrollArea()
        log_scroll.setWidgetResizable(True)
        log_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._log_container = QWidget()
        self._log_vbox = QVBoxLayout(self._log_container)
        self._log_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._log_vbox.setContentsMargins(0, 0, 0, 0)
        self._log_vbox.setSpacing(0)
        log_scroll.setWidget(self._log_container)
        content_vbox.addWidget(log_scroll, stretch=2)
        panel_layout.addWidget(self._activity_content)

        # 初期状態は非表示
        self._activity_content.setVisible(False)

        content_layout.addWidget(self._activity_panel)
        layout.addLayout(content_layout)

        # ボタン行
        btn_row = QHBoxLayout()

        def _sep():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFrameShadow(QFrame.Shadow.Sunken)
            return f

        # ── 並び替えグループ ──
        agg_btn = QPushButton("集約並び替え")
        agg_btn.clicked.connect(self._on_aggregate_sort)
        btn_row.addWidget(agg_btn)

        btn_row.addWidget(_sep())

        # ── 選択フィルタ（チェックボックス）──
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

        # ── 対応履歴グループ（右端）──
        activity_search_btn = QPushButton("対応履歴検索")
        activity_search_btn.clicked.connect(self._on_activity_search)
        self._activity_toggle_btn = QPushButton("対応履歴 ≪")
        self._activity_toggle_btn.clicked.connect(self._on_toggle_activity_panel)
        btn_row.addWidget(activity_search_btn)
        btn_row.addWidget(self._activity_toggle_btn)

        layout.addLayout(btn_row)

    def _refresh(self):
        members = self._svc.search(
            keyword=self._keyword_edit.text(),
            active_only=True,
        )
        self._members = members
        member_ids = [m.id for m in members]
        self._last_activity_map = self._activity_svc.get_last_logged_at_map(member_ids)
        self._last_change_map = self._activity_svc.get_last_changed_at_map(member_ids)
        self._fill_table(members)

    def _fill_table(self, members):
        self._member_row_map = {}
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(members))
        _one_year_ago = datetime.now() - timedelta(days=365)
        for row, m in enumerate(members):
            self._member_row_map[m.id] = row
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            has_ikkatsu = any(e.is_ikkatsu for e in m.insurance_entries)

            # 選択チェックボックス列（コンテナで中央ぞろえ）
            chk_container = QWidget()
            chk_hbox = QHBoxLayout(chk_container)
            chk_hbox.setContentsMargins(0, 0, 0, 0)
            chk_hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(m.id in self._checked_ids)
            chk.stateChanged.connect(lambda state, mid=m.id: self._on_check_changed(mid, state))
            chk_hbox.addWidget(chk)
            self._table.setCellWidget(row, _COL_SELECT, chk_container)
            # オーバーレイ用にモデルアイテムも設定（UserRoleにmember_id格納）
            sel_item = QTableWidgetItem()
            sel_item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._table.setItem(row, _COL_SELECT, sel_item)

            code_item = SortableTableWidgetItem(str(m.company_code) if m.company_code else "")
            code_item.setData(Qt.ItemDataRole.UserRole, m.id)
            code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            last_change = self._last_change_map.get(m.id)
            if last_change and last_change >= _one_year_ago:
                code_item.setForeground(QBrush(QColor(210, 70, 70)))
            self._table.setItem(row, _COL_COMPANY_CODE, code_item)
            is_mem = getattr(m, "is_member", True)
            mem_item = SortableTableWidgetItem("○" if is_mem else "")
            mem_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_IS_MEMBER, mem_item)
            member_no_item = SortableTableWidgetItem(m.member_number or "")
            member_no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_MEMBER_NUMBER, member_no_item)
            self._table.setItem(row, _COL_ORG_NAME, SortableTableWidgetItem(m.org_name))
            self._table.setItem(row, 5, SortableTableWidgetItem(m.org_kana or ""))
            self._table.setItem(row, 6, SortableTableWidgetItem(m.dept_title or ""))
            self._table.setItem(row, 7, SortableTableWidgetItem(m.rep_name or ""))
            self._table.setItem(row, 8, SortableTableWidgetItem(m.rep_kana or ""))
            self._table.setItem(row, 9, SortableTableWidgetItem(m.email or ""))
            _ac = Qt.AlignmentFlag.AlignCenter
            # 市外局番(10) / 電話番号(11) / FAX市外局番(12) / FAX(13)
            tel_area_item = SortableTableWidgetItem(m.tel_area or "")
            tel_area_item.setTextAlignment(_ac)
            self._table.setItem(row, 10, tel_area_item)
            tel_item = SortableTableWidgetItem(m.tel or "")
            tel_item.setTextAlignment(_ac)
            self._table.setItem(row, 11, tel_item)
            fax_area_item = SortableTableWidgetItem(m.fax_area or "")
            fax_area_item.setTextAlignment(_ac)
            self._table.setItem(row, 12, fax_area_item)
            fax_item = SortableTableWidgetItem(m.fax or "")
            fax_item.setTextAlignment(_ac)
            self._table.setItem(row, 13, fax_item)
            postal_item = SortableTableWidgetItem(m.postal_code or "")
            postal_item.setTextAlignment(_ac)
            self._table.setItem(row, 14, postal_item)
            self._table.setItem(row, 15, SortableTableWidgetItem(m.address or ""))
            self._table.setItem(row, 16, SortableTableWidgetItem(m.postal_code_mail or ""))
            self._table.setItem(row, 17, SortableTableWidgetItem(m.address_mail or ""))
            self._table.setItem(row, 18, SortableTableWidgetItem(m.addressee_mail or ""))
            emp_item = SortableTableWidgetItem(m.employment_ins_no or "")
            emp_item.setTextAlignment(_ac)
            self._table.setItem(row, 19, emp_item)
            ins_map = {e.ins_type: e for e in m.insurance_entries}
            for col_idx, ins_type in enumerate(INS_TYPES):
                entry = ins_map.get(ins_type)
                val = entry.ins_number if entry else ""
                item = SortableTableWidgetItem(val)
                item.setTextAlignment(_ac)
                if entry:
                    if entry.is_tokubetsu and entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(216, 180, 254)))
                    elif entry.is_tokubetsu:
                        item.setBackground(QBrush(QColor(226, 240, 217)))
                    elif entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(255, 224, 178)))
                self._table.setItem(row, 20 + col_idx, item)
            toku_item = SortableTableWidgetItem("●" if has_tokubetsu else "")
            toku_item.setTextAlignment(_ac)
            self._table.setItem(row, 25, toku_item)
            ikk_item = SortableTableWidgetItem("●" if has_ikkatsu else "")
            ikk_item.setTextAlignment(_ac)
            self._table.setItem(row, 26, ikk_item)
            reg_item = SortableTableWidgetItem(
                m.registered_date.strftime("%Y-%m-%d") if m.registered_date else ""
            )
            reg_item.setTextAlignment(_ac)
            self._table.setItem(row, 27, reg_item)
            change_dt = self._last_change_map.get(m.id)
            change_item = SortableTableWidgetItem(
                change_dt.strftime("%Y-%m-%d") if change_dt else ""
            )
            change_item.setTextAlignment(_ac)
            self._table.setItem(row, 28, change_item)
            last_dt = self._last_activity_map.get(m.id)
            last_item = SortableTableWidgetItem(
                last_dt.strftime("%Y-%m-%d") if last_dt else ""
            )
            last_item.setTextAlignment(_ac)
            self._table.setItem(row, 29, last_item)
            self._table.setItem(row, 30, SortableTableWidgetItem(m.note or ""))
        self._table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._table.setSortingEnabled(True)
        self._resizing_programmatically = True
        saved = self._get_staff_setting("column_widths",
                self._config.member_column_widths)
        for i in range(self._table.columnCount()):
            if i == _COL_SELECT:
                self._table.setColumnWidth(i, 44)
            elif str(i) in saved:
                self._table.setColumnWidth(i, saved[str(i)])
            else:
                self._table.resizeColumnToContents(i)
        self._resizing_programmatically = False
        self._update_frozen_view_geometry()
        QTimer.singleShot(0, self._update_frozen_view_geometry)

    def _on_select_all(self, checked: bool):
        self._checked_ids.clear()
        if checked:
            for m in self._members:
                self._checked_ids.add(m.id)
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            if container:
                chk = container.findChild(QCheckBox)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(checked)
                    chk.blockSignals(False)
        self._frozen_view.viewport().update()

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

    def _on_select_tokubetsu(self):
        self._checked_ids.clear()
        for m in self._members:
            if any(e.is_tokubetsu for e in m.insurance_entries):
                self._checked_ids.add(m.id)
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_SELECT)
            if container:
                chk = container.findChild(QCheckBox)
                item = self._table.item(row, _COL_COMPANY_CODE)
                mid = item.data(Qt.ItemDataRole.UserRole) if item else None
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(mid in self._checked_ids)
                    chk.blockSignals(False)
        all_on = bool(self._checked_ids) and len(self._checked_ids) == len(self._members)
        self._check_header.set_all_checked(all_on)
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
                item = self._table.item(row, _COL_COMPANY_CODE)
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
                    item = self._table.item(r, _COL_COMPANY_CODE)
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
        self._set_staff_setting("freeze_col", col)
        self._update_frozen_view_geometry()

    def _update_frozen_view_geometry(self):
        """固定列オーバーレイの表示・位置・列設定を更新する"""
        if not hasattr(self, '_frozen_view'):
            return
        n = self._freeze_col
        table = self._table

        if n <= 0:
            self._frozen_view.setVisible(False)
            return

        # 固定ビューでの列表示制御（固定範囲内のみ表示、ユーザーの非表示設定を尊重）
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

        # ヘッダー高さを揃える
        hh_h = table.horizontalHeader().height()
        self._frozen_view.horizontalHeader().setFixedHeight(hh_h)

        # 行高さを同期
        for r in range(table.rowCount()):
            self._frozen_view.setRowHeight(r, table.rowHeight(r))

        # 位置: _table ウィジェット内の左上から
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
        """ソート後など行順変化時に _member_row_map を再構築する"""
        self._member_row_map = {}
        for r in range(self._table.rowCount()):
            item = self._table.item(r, _COL_COMPANY_CODE)
            if item:
                mid = item.data(Qt.ItemDataRole.UserRole)
                if mid is not None:
                    self._member_row_map[mid] = r

    def _on_frozen_header_clicked(self, logical_col: int):
        """固定列ヘッダークリックで _table をソートする"""
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
        """メインヘッダーでのソート変更を固定ビューのインジケーターに反映する"""
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        self._rebuild_member_row_map()

    def _on_frozen_clicked(self, index):
        """固定オーバーレイのクリック処理"""
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
            # QTableWidget.currentRow() が確実に更新されるよう明示的に設定
            self._table.setCurrentCell(index.row(), _COL_COMPANY_CODE)

    def _on_frozen_double_clicked(self, index):
        if index.column() != _COL_SELECT:
            self._table.setCurrentCell(index.row(), _COL_COMPANY_CODE)
            self._on_edit()

    def _on_frozen_context_menu(self, pos):
        index = self._frozen_view.indexAt(pos)
        if index.isValid():
            self._table.setCurrentCell(index.row(), _COL_COMPANY_CODE)
        if not self._selected_member():
            return
        menu = QMenu(self)
        menu.addAction("編集",    self._on_edit)
        menu.addAction("変更履歴", self._on_history)
        menu.addAction("委託解除", self._on_withdraw)
        menu.addSeparator()
        menu.addAction("削除",    self._on_delete)
        menu.exec(self._frozen_view.viewport().mapToGlobal(pos))

    def _selected_member(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, _COL_COMPANY_CODE)
        if not item:
            return None
        member_id = item.data(Qt.ItemDataRole.UserRole)
        for m in self._members:
            if m.id == member_id:
                return m
        return None

    def _on_context_menu(self, pos):
        if not self._selected_member():
            return
        menu = QMenu(self)
        menu.addAction("編集",    self._on_edit)
        menu.addAction("変更履歴", self._on_history)
        menu.addAction("委託解除", self._on_withdraw)
        menu.addSeparator()
        menu.addAction("削除",    self._on_delete)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_add(self):
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_edit(self):
        m = self._selected_member()
        if not m:
            return
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_withdraw(self):
        m = self._selected_member()
        if not m:
            return
        dlg = WithdrawDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == WithdrawDialog.DialogCode.Accepted and dlg.withdrawn:
            self._refresh()

    def _on_delete(self):
        m = self._selected_member()
        if not m:
            return
        ret = QMessageBox.warning(
            self, "削除の確認",
            f"「{m.org_name}」を完全に削除しますか？\n\n"
            "変更履歴・対応履歴を含むすべてのデータが削除されます。\n"
            "この操作は取り消せません。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ret == QMessageBox.StandardButton.Ok:
            self._svc.delete(m.id)
            self._refresh()

    def _on_history(self):
        m = self._selected_member()
        if not m:
            return
        MemberHistoryDialog(self._engine, m.id, parent=self).exec()

    def _on_selection_changed(self):
        m = self._selected_member()
        if not m:
            self._activity_load_timer.stop()
            self._pending_member_id = None
            self._placeholder_label.setVisible(True)
            self._activity_content.setVisible(False)
            self._activity_panel.setTitle("対応履歴")
            return

        self._placeholder_label.setVisible(False)
        self._activity_content.setVisible(True)
        self._activity_panel.setTitle(f"対応履歴 - {m.org_name}")
        self._pending_member_id = m.id
        self._activity_load_timer.start()  # 80ms デバウンス（連続クリック対策）

    def _deferred_load_activity(self):
        if self._pending_member_id is not None:
            self._load_activity_logs(self._pending_member_id)

    def _load_activity_logs(self, member_id):
        # 既存ウィジェットを即時削除
        while self._log_vbox.count():
            item = self._log_vbox.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        logs = self._activity_svc.get_logs(member_id)
        for log in logs:
            cat_names = "・".join(c.name for c in log.categories) if log.categories else "カテゴリなし"
            entry = QWidget()
            entry.setStyleSheet("background: white; border-bottom: 1px solid #e0e0e0;")
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(8, 8, 8, 8)
            header_row = QHBoxLayout()
            header = QLabel(
                f"<b>{log.logged_at.strftime('%Y-%m-%d %H:%M')}</b>　{html.escape(log.logged_by)}　"
                f"<span style='color:#666'>[{html.escape(cat_names)}]</span>"
            )
            header_row.addWidget(header)
            header_row.addStretch()
            del_btn = QPushButton("削除")
            del_btn.setFixedWidth(50)
            del_btn.clicked.connect(lambda _, log_id=log.id: self._on_delete_activity_log(log_id))
            header_row.addWidget(del_btn)
            content = QLabel(log.content)
            content.setTextFormat(Qt.TextFormat.PlainText)
            content.setWordWrap(True)
            entry_layout.addLayout(header_row)
            entry_layout.addWidget(content)
            self._log_vbox.addWidget(entry)

        if not logs:
            self._log_vbox.addWidget(QLabel("対応履歴はありません。"))

    def _on_delete_activity_log(self, log_id: int):
        reply = QMessageBox.question(
            self, "確認", "この対応履歴を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._activity_svc.delete_log(log_id)
        m = self._selected_member()
        saved_id = m.id if m else None
        self._refresh()  # 最終対応日更新のため
        if saved_id is not None:
            # refresh後も同じ行を選択し直す（ソート等で行位置が変わる場合に対応）
            for row in range(self._table.rowCount()):
                item = self._table.item(row, _COL_COMPANY_CODE)
                if item and item.data(Qt.ItemDataRole.UserRole) == saved_id:
                    self._table.selectRow(row)
                    break

    def refresh_categories(self):
        current_id = self._cat_combo.currentData()
        self._cat_combo.clear()
        self._cat_combo.addItem("カテゴリなし", None)
        for cat in self._activity_svc.get_categories():
            self._cat_combo.addItem(cat.name, cat.id)
        # 選択を復元（削除されていれば先頭に戻す）
        for i in range(self._cat_combo.count()):
            if self._cat_combo.itemData(i) == current_id:
                self._cat_combo.setCurrentIndex(i)
                break

    def _on_save_activity(self):
        m = self._selected_member()
        if not m:
            return
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "入力エラー", "内容を入力してください。")
            return
        cat_id = self._cat_combo.currentData()
        cat_ids = [cat_id] if cat_id is not None else []
        try:
            self._activity_svc.add_log(m.id, content, cat_ids, self._config.last_staff_name)
            self._content_edit.clear()
            self._cat_combo.setCurrentIndex(0)
            saved_id = m.id
            self._refresh()  # 最終対応日更新のため
            # refresh後も同じ行を選択し直す（ソート等で行位置が変わる場合に対応）
            for row in range(self._table.rowCount()):
                item = self._table.item(row, _COL_COMPANY_CODE)
                if item and item.data(Qt.ItemDataRole.UserRole) == saved_id:
                    self._table.selectRow(row)
                    break
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))

    def _on_import(self):
        dlg = ImportDialog(self._engine, self._config.last_staff_name, parent=self)
        if dlg.exec() == ImportDialog.DialogCode.Accepted:
            self._refresh()

    def _apply_column_visibility(self):
        # per-staff設定、なければグローバル設定にフォールバック
        hidden_cols = self._get_staff_setting("hidden_columns",
                      list(self._config.hidden_columns))
        for i, col in enumerate(COLS[1:], start=1):  # 選択列(0)は常に表示
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)
        # 列順を復元
        order = self._get_staff_setting("column_order")
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

    def _on_show_column_menu_btn(self):
        self._exec_column_menu()

    def _exec_column_menu(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("表示列選択")
        dlg.setMinimumWidth(320)

        outer = QVBoxLayout(dlg)

        # ユーザー設定から表示状態を取得（固定列は _table で非表示になっていないため）
        hidden_cols = list(self._get_staff_setting(
            "hidden_columns", list(self._config.hidden_columns)))

        items = [(i, col) for i, col in enumerate(COLS[1:], start=1)]
        half = (len(items) + 1) // 2

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)

        for row, (i, col) in enumerate(items[:half]):
            chk = QCheckBox(col or f"列{i}")
            chk.setChecked(COLS[i] not in hidden_cols)
            chk.toggled.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            grid.addWidget(chk, row, 0)

        for row, (i, col) in enumerate(items[half:]):
            chk = QCheckBox(col or f"列{i}")
            chk.setChecked(COLS[i] not in hidden_cols)
            chk.toggled.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            grid.addWidget(chk, row, 1)

        outer.addWidget(grid_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        dlg.exec()

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        if self._resizing_programmatically:
            return
        widths = dict(self._get_staff_setting("column_widths", {}))
        if new_size == 0:
            widths.pop(str(logical_index), None)
        else:
            widths[str(logical_index)] = new_size
        self._set_staff_setting("column_widths", widths)
        if self._freeze_col > 0 and logical_index <= self._freeze_col:
            self._update_frozen_view_geometry()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        if self._resizing_programmatically:
            return
        # チェックボックス列は常に先頭に固定
        col0_visual = self._check_header.visualIndex(_COL_SELECT)
        if col0_visual != 0:
            self._resizing_programmatically = True
            self._check_header.moveSection(col0_visual, 0)
            self._resizing_programmatically = False
            return
        order = [self._check_header.logicalIndex(v)
                 for v in range(self._table.columnCount())]
        self._set_staff_setting("column_order", order)

    def _toggle_column_visibility(self, idx, visible):
        hidden = list(self._get_staff_setting("hidden_columns",
                      list(self._config.hidden_columns)))
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
        self._set_staff_setting("hidden_columns", hidden)
        if self._freeze_col > 0:
            self._update_frozen_view_geometry()

    def _on_label(self):
        from app.ui.dialogs.label_dialog import LabelDialog
        members = [m for m in self._members if m.id in self._checked_ids]
        if not members:
            QMessageBox.warning(self, "ラベル出力", "出力する会員を選択してください（左端のチェックボックスで選択）。")
            return
        LabelDialog(self._engine, members, parent=self).exec()

    def _on_compose_email(self):
        from app.ui.dialogs.compose_email_dialog import ComposeEmailDialog
        members = [m for m in self._members if m.id in self._checked_ids]
        if not members:
            QMessageBox.warning(self, "メール送信", "送信先を選択してください（左端のチェックボックスで選択）。")
            return
        ComposeEmailDialog(self._engine, self._config, members, parent=self).exec()

    def _on_toggle_activity_panel(self):
        visible = not self._activity_panel.isVisible()
        self._activity_panel.setVisible(visible)
        self._activity_toggle_btn.setText("対応履歴 ≪" if visible else "対応履歴 ≫")

    def _on_activity_search(self):
        dlg = ActivitySearchDialog(self._engine, parent=self)
        dlg.member_selected.connect(self._jump_to_member)
        dlg.withdrawn_member_selected.connect(self.jump_to_withdrawn.emit)
        dlg.exec()

    def _jump_to_member(self, member_id: int):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == member_id:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return
        # 現在の検索条件でヒットしない場合は条件をリセットして再検索
        self._keyword_edit.clear()
        self._refresh()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == member_id:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return

    def _on_export(self):
        from PyQt6.QtWidgets import QFileDialog
        from app.services.import_service import ExportService
        path, _ = QFileDialog.getSaveFileName(self, "Excel出力", "加入者名簿.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            ExportService(self._engine).export_excel(self._members, path)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "完了", f"{len(self._members)}件を出力しました。")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "エラー", str(e))
