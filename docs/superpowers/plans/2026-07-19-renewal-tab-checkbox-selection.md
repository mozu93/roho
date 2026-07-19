# 年度更新タブ チェックボックス選択列・ラベル出力・メール送信 実装計画（サブプロジェクト③）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 年度更新タブの一覧にチェックボックス選択列（全選択ヘッダー・シフトクリック範囲選択・列固定オーバーレイ連携）を追加し、選択した事業所へラベル出力・メール送信できるようにする。

**Architecture:** `withdrawn_tab.py`のチェックボックス選択・シフトクリック範囲選択・ラベル出力・メール送信部分を実装テンプレートとして踏襲する。`member_tab.py`の共有クラス`_CheckHeader`（ヘッダーの全選択チェックボックス）・`_FrozenCheckDelegate`（列固定オーバーレイのチェックボックス描画）を追加でインポートする。チェックボックス列を列0に挿入するため、既存の33列は全て+1インデックスがずれる。

**Tech Stack:** Python 3.11+ / PyQt6（DB変更なし）

## Global Constraints

- `app/database/models.py`・`app/utils/app_config.py`・`app/ui/dialogs/label_dialog.py`・`app/ui/dialogs/compose_email_dialog.py`への変更は行わない（既存ダイアログをそのまま呼び出す）
- 選択状態は`Member.id`の集合（`self._checked_ids: set[int]`）で管理する。検索・フィルタ・年度切替をまたいでも保持する
- チェックボックス列（列0）は「表示列選択」ダイアログの対象外（常に表示）、「列固定」メニューの対象外（`freeze_col <= 0`が固定なしを表す番兵のため）とする
- 「管理No.」列（新しい列1）は引き続き`AnnualRenewal.id`をUserRoleに保持し、既存の枝番トグル・編集ダイアログ機能はそのまま動作させる
- 参照設計書: `docs/superpowers/specs/2026-07-19-renewal-tab-checkbox-selection-design.md`
- 参照実装テンプレート: `app/ui/withdrawn_tab.py`（チェックボックス選択・ラベル出力・メール送信一式）、`app/ui/member_tab.py`（共有クラス`_CheckHeader` / `_FrozenCheckDelegate`の定義元）
- このタスクはUIのみの変更（サービス層への変更なし）。既存プロジェクトの慣例に合わせ自動テストは追加せず手動確認で検証する

---

### Task 1: 列インデックスのシフトとチェックボックス選択機能一式

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Produces: `COLS`（34列、列0が空文字のチェックボックス列）、`_COL_SELECT = 0`、`BRANCH_COL_START = 20`、`_TAIL_START = 25`。`self._checked_ids: set[int]`（Task 2の`_on_label`/`_on_compose_email`が使う）、`self._records`（既存、Task 2が使う）。

- [ ] **Step 1: importとCOLS・列インデックス定数を更新する**

`app/ui/renewal_tab.py`の先頭（import〜`_TAIL_START`定義まで）を次のように置き換える：

```python
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
```

- [ ] **Step 2: `__init__`に選択状態の変数を追加する**

`__init__`メソッド：

```python
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
        self._freeze_col: int = self._get_staff_setting("renewal_freeze_col", 0)
        self._build_ui()
        self._apply_column_visibility()
        self._refresh_years()
```

を、次のように変更する：

```python
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
```

- [ ] **Step 3: `_build_ui`のテーブル構築部分を更新する（`_CheckHeader`への差し替え）**

`_build_ui`内、以下の既存コード：

```python
        self._table = QTableWidget()
        self._table.setObjectName("renewalTable")
        self._table.setStyleSheet(
            "QTableWidget#renewalTable::item:hover { background: #ffe4ec; color: #1a1a1a; }"
        )
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
        self._table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(self._show_column_menu)
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
```

を、次のように変更する：

```python
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
```

- [ ] **Step 4: 列固定オーバーレイにチェックボックスデリゲートとクリックハンドラを追加する**

`_build_ui`内、以下の既存コード：

```python
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(self._on_frozen_header_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setSelectionModel(self._table.selectionModel())
        self._frozen_view.setVisible(False)
```

を、次のように変更する：

```python
        self._frozen_view.setItemDelegateForColumn(
            _COL_SELECT, _FrozenCheckDelegate(self._checked_ids, self._frozen_view))
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(self._on_frozen_header_clicked)
        self._frozen_view.clicked.connect(self._on_frozen_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setSelectionModel(self._table.selectionModel())
        self._frozen_view.setVisible(False)
```

- [ ] **Step 5: `_fill_table`の列幅復元にチェックボックス列の固定幅を追加し、行マップを再構築する**

`_fill_table`内、以下の既存コード：

```python
        self._resizing_programmatically = True
        saved_widths = self._get_staff_setting("renewal_column_widths", {})
        for i in range(self._table.columnCount()):
            if str(i) in saved_widths:
                self._table.setColumnWidth(i, int(saved_widths[str(i)]))
            else:
                self._table.resizeColumnToContents(i)
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            if str(col) not in saved_widths:
                self._table.setColumnWidth(col, 110)
        self._resizing_programmatically = False
```

を、次のように変更する：

```python
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
```

`_fill_table`メソッド末尾、以下の既存コード：

```python
        self._update_frozen_view_geometry()

    def _on_aggregate_sort(self):
```

を、次のように変更する：

```python
        self._update_frozen_view_geometry()
        self._rebuild_member_row_map()

    def _on_aggregate_sort(self):
```

- [ ] **Step 6: `_populate_row`にチェックボックス列の描画を追加し、既存列を+1シフトする**

`_populate_row`メソッド全体を次のように置き換える：

```python
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
```

- [ ] **Step 7: `_on_sort_changed`と`_on_frozen_header_clicked`で行マップを再構築する**

`_on_sort_changed`メソッド：

```python
    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        if not self._resizing_programmatically and logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
            self._set_staff_setting("renewal_aggregate_sort_active", False)
```

を、次のように変更する：

```python
    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        self._rebuild_member_row_map()
        if not self._resizing_programmatically and logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
            self._set_staff_setting("renewal_aggregate_sort_active", False)
```

`_on_frozen_header_clicked`メソッド：

```python
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
```

を、次のように変更する：

```python
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
```

- [ ] **Step 8: `_on_cell_clicked`・`_on_row_double_clicked`が参照する列を+1する**

`_on_cell_clicked`メソッド内、以下の既存コード：

```python
        cell = self._table.item(row, col)
        id_item = self._table.item(row, 0)
```

を、次のように変更する：

```python
        cell = self._table.item(row, col)
        id_item = self._table.item(row, 1)
```

`_on_row_double_clicked`メソッド：

```python
    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 0)
```

を、次のように変更する：

```python
    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 1)
```

- [ ] **Step 9: `_exec_column_menu`でチェックボックス列を表示切替の対象外にする**

`_exec_column_menu`メソッド内、以下の既存コード：

```python
        hidden_cols = list(self._get_staff_setting("renewal_hidden_columns", []))

        outer = QVBoxLayout(dlg)
        items = list(enumerate(COLS))
        half = (len(items) + 1) // 2
```

を、次のように変更する：

```python
        hidden_cols = list(self._get_staff_setting("renewal_hidden_columns", []))

        outer = QVBoxLayout(dlg)
        items = [(i, col) for i, col in enumerate(COLS) if i != _COL_SELECT]
        half = (len(items) + 1) // 2
```

- [ ] **Step 10: 選択関連の新規メソッドを追加する**

`_show_column_menu`メソッドの後（ファイル末尾）に追記：

```python
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
```

- [ ] **Step 11: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブで以下を手動確認する。
1. 列0にチェックボックス列が表示され、既存の列（管理No.以降）が全て1つずつ後ろにずれて正しく表示される
2. ヘッダーのチェックボックスをクリックすると全選択/全解除される
3. Shiftキーを押しながら別の行をチェックすると、範囲選択される
4. 検索・フィルタ・年度切替をまたいでも選択状態が保持される
5. 「表示列選択」ダイアログにチェックボックス列自体は出てこない（非表示にできない）
6. 列ヘッダを右クリックしても「チェックボックス列まで固定」というメニューは出ない
7. 列固定を有効にした状態でチェックボックス列をクリックすると選択がトグルされる
8. 既存の枝番セルのクリックトグル・行ダブルクリックでの編集ダイアログ・ソート・集約並び替えが引き続き正しく動作する

GUIを直接操作できない場合は、実DB・実`AppConfig`・実`RenewalTab`ウィジェットを使ったスクリプトで代替検証する：`RenewalTab`を構築→`_on_check_changed(member_id, Qt.CheckState.Checked.value)`を呼ぶ→`self._checked_ids`に反映されることを確認→複数事業所の`member_id`でシフトクリック相当（Shift修飾キーはモックできないため`_last_checked_member_id`を直接設定してから範囲選択ロジックを検証）→枝番セルのクリックトグル（`_on_cell_clicked`）が列1の管理No.セルからrenewal_idを正しく取得できることを確認する。

- [ ] **Step 12: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（既存の無関係な1件の失敗を除き全件。UIファイルには自動テストがないため対象外）

- [ ] **Step 13: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add checkbox selection column with select-all and shift-click to renewal tab"
```

---

### Task 2: ラベル出力・メール送信ボタンの追加

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `self._checked_ids`・`self._records`（Task 1）、既存の`app.ui.dialogs.label_dialog.LabelDialog(engine, members: list, parent=None)`・`app.ui.dialogs.compose_email_dialog.ComposeEmailDialog(engine, config, members: list, parent=None)`（変更なし、そのまま呼び出す）

- [ ] **Step 1: ボタン行を追加する**

`_build_ui`メソッド内、以下の既存コード：

```python
        self._table.installEventFilter(self)
```

を、次のように変更する：

```python
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
```

- [ ] **Step 2: `_on_label`・`_on_compose_email`メソッドを追加する**

ファイル末尾（`_on_frozen_clicked`メソッドの後）に追記：

```python
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
```

- [ ] **Step 3: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブで以下を手動確認する。
1. 事業所を1件以上選択して「ラベル出力」を押すと、既存のラベル出力ダイアログが選択した事業所で開く
2. 事業所を1件以上選択して「メール送信」を押すと、既存のメール送信ダイアログが選択した事業所で開く
3. 未選択の状態で「ラベル出力」「メール送信」を押すと、それぞれ警告メッセージが出て何も開かない

GUIを直接操作できない場合は、実DB・実`AppConfig`・実`RenewalTab`ウィジェットを使ったスクリプトで代替検証する：チェック状態を`self._checked_ids`に設定→`_on_label`/`_on_compose_email`を呼ぶ際、ダイアログの`exec()`はモーダル実行されるため直接は呼ばず、代わりに選択→未選択の警告分岐（`members`が空の場合の`QMessageBox.warning`呼び出し）と、選択時に`members`リストが正しい`Member`オブジェクト（チェックした事業所と一致）になることを確認する。

- [ ] **Step 4: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（既存の無関係な1件の失敗を除き全件）

- [ ] **Step 5: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add label output and email send buttons to renewal tab"
```

---

## 完了後の確認事項

- 年度更新タブの一覧にチェックボックス選択列（全選択・シフトクリック範囲選択）が追加される
- 選択した事業所へラベル出力・メール送信ができる（既存ダイアログを再利用）
- サブプロジェクト①・②で実装した機能（表示/非表示・列幅・列並び替え・列固定・ソート・集約並び替え・枝番セルのクリックトグル・行ダブルクリック編集）が、列インデックスの変更後も正しく動作する
- これで年度更新タブの3段階サブプロジェクト（①列拡張②集約並び替え③チェックボックス選択）が全て完了する
