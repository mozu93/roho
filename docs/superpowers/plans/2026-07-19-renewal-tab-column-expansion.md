# 年度更新タブ 列拡張・表示切替・列固定 実装計画（サブプロジェクト①）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 年度更新タブの一覧に、名簿タブ（`member_tab.py`）・委託解除済タブ（`withdrawn_tab.py`）と同等の列拡張・列表示/非表示・列並び替え・列固定機能を追加する。

**Architecture:** `withdrawn_tab.py`を実装テンプレートとして踏襲する。`member_tab.py`が公開する共有クラス（`SortableTableWidgetItem`, `_SelectionDelegate`）をインポートして再利用し、列カスタマイズ（表示/非表示・幅・並び順・固定）の永続化は`app_config.py`のスキーマ変更なしに、既存の`staff_settings`辞書へ`renewal_`プレフィックス付きキーで保存する（`member_tab.py` / `withdrawn_tab.py`と同じ`_get_staff_setting`/`_set_staff_setting`パターン）。チェックボックス選択列・ラベル出力・メール送信・集約並び替えボタンは対象外（別サブプロジェクト）。

**Tech Stack:** Python 3.11+ / PyQt6 / SQLAlchemy（DB変更なし）

## Global Constraints

- 対象環境: 画面解像度1366×768、ウィンドウ幅1280px以内（プロジェクトのCLAUDE.mdより）。列数が大幅に増えるため水平スクロールは前提（名簿タブ・委託解除済タブと同じ）
- `app/database/models.py`・`app/utils/app_config.py`への変更は行わない（新規テーブル・新規設定フィールド不要。永続化は既存`staff_settings`辞書のキー追加のみ）
- 列ラベルの重複を避けるため、`Member`単位の情報は「最終対応日（全体）」「メモ（全体）」、`AnnualRenewal`単位の情報は「最終対応日（年度更新）」「備考（年度更新）」と区別する
- 列固定・表示/非表示・列幅・列並び替え・ソート順の永続化キー名: `renewal_freeze_col` / `renewal_hidden_columns` / `renewal_column_widths` / `renewal_column_order` / `renewal_sort_column` / `renewal_sort_order`（名簿タブ・委託解除済タブの同名キーと衝突しないよう`renewal_`プレフィックスを付ける）
- 参照設計書: `docs/superpowers/specs/2026-07-19-renewal-tab-column-expansion-design.md`
- 参照実装テンプレート: `app/ui/withdrawn_tab.py`（列カスタマイズ機能一式）、`app/ui/member_tab.py`（共有クラス`SortableTableWidgetItem` / `_SelectionDelegate`の定義元）
- このタスクはUIのみの変更（サービス層への変更なし）。既存プロジェクトの慣例（`member_tab.py` / `withdrawn_tab.py` / `renewal_tab.py`いずれも自動テストなし）に合わせ、自動テストは追加せず手動確認で検証する

---

### Task 1: 列拡張とデータ表示（表示列は全て常時表示、固定・並び替えなし）

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `ActivityService.get_last_logged_at_map(member_ids) -> dict` / `get_last_changed_at_map(member_ids) -> dict`（`app/services/activity_service.py`、既存）、`RenewalService.search()`（既にmember全スカラー列と`member.insurance_entries`を事前ロード済み）
- Produces: `COLS`（33列）、`BRANCH_COL_START = 19`、`_TAIL_START = 24`（`BRANCH_COL_START + len(INS_TYPES)`）。後続タスクはこの列インデックス構成をそのまま使う。

- [ ] **Step 1: importとCOLS・列インデックス定数を書き換える**

`app/ui/renewal_tab.py`の先頭（import〜COLS定義まで）を次のように置き換える：

```python
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
```

`SortableTableWidgetItem`は`app.ui.member_tab`で定義済みの、数値文字列を数値として比較する`QTableWidgetItem`サブクラス（Task 2でソートを有効化する際に必要。Task 1時点ではソートは無効のままだが、後続タスクで置き換えずに済むよう先にこのクラスで統一する）。

- [ ] **Step 2: `RenewalTab.__init__`に`ActivityService`と対応履歴マップを追加する**

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
        self._build_ui()
        self._refresh_years()
```

- [ ] **Step 3: `_build_ui`の列幅設定部分を新しい列インデックスに合わせて修正する**

`_build_ui`内、以下の既存コード：

```python
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            self._table.setColumnWidth(col, 110)
            self._table.horizontalHeaderItem(col).setToolTip(BRANCH_LABEL[ins_type])
```

はそのままで変更不要（`BRANCH_COL_START`が新しい値になるだけで、ロジックは同じ）。他の`_build_ui`内容も変更不要。

- [ ] **Step 4: `_refresh`で対応履歴マップを取得する**

`_refresh`メソッド：

```python
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
```

- [ ] **Step 5: `_populate_row`を全列分に拡張する**

`_populate_row`メソッド全体を次のように置き換える：

```python
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
```

（`_TAIL_START + 0`〜`+8`: 特別／継続一括／登録日／最終更新日／最終対応日（全体）／メモ（全体）／全体状況／最終対応日（年度更新）／備考（年度更新）の9列）

- [ ] **Step 6: `_on_cell_clicked`の範囲判定を新しい`BRANCH_COL_START`に合わせる**

`_on_cell_clicked`メソッドは変更不要（`BRANCH_COL_START`と`len(INS_TYPES)`を参照する既存ロジックのまま、定数の値が変わるだけで正しく動作する）。

- [ ] **Step 7: インポート確認と起動確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: エラーなく起動し、「年度更新」タブの一覧に33列（管理No.〜備考（年度更新））が表示される。名簿タブの該当会員と同じ値（フリガナ・代表者名・住所・電話番号・特別・継続一括・登録日など）が表示されることを確認する。既存の枝番セルのクリックトグル（未提出⇔提出済）が引き続き動作することを確認する。列固定・表示/非表示・並び替えはまだ未実装のため対象外。

- [ ] **Step 8: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: expand renewal tab list columns to match member list"
```

---

### Task 2: ソート可能化とソート順の永続化

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: Task 1の`COLS`（列数33）
- Produces: `_get_staff_setting(key, default) -> Any`、`_set_staff_setting(key, value) -> None`（後続タスクも使う）。列ヘッダクリックでソートでき、ソート列・順序が職員別に保存・復元される。

- [ ] **Step 1: `_get_staff_setting`/`_set_staff_setting`ヘルパーを追加する**

`__init__`メソッドの直後に追記：

```python
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
```

- [ ] **Step 2: `_build_ui`でソートを有効化し、ヘッダのソート変更シグナルを接続する**

`_build_ui`内の以下の既存コード：

```python
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
```

を、次のように変更する：

```python
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
```

- [ ] **Step 3: ソート変更ハンドラと復元処理を追加する**

`_on_cell_clicked`メソッドの直前に新規メソッドを追加：

```python
    def _on_sort_changed(self, logical_col: int, order):
        if logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
```

`_refresh`メソッド内、`self._table.setRowCount(0)`の直後（fiscal_year Noneチェックより後、`records = ...`より前）に処理は不要。代わりに`_refresh`メソッド末尾（`for row, r in enumerate(records): self._populate_row(row, r)`の直後）に追記：

```python
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
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            self._populate_row(row, r)
        saved_col = self._get_staff_setting("renewal_sort_column", -1)
        saved_ord = Qt.SortOrder(self._get_staff_setting(
            "renewal_sort_order", Qt.SortOrder.AscendingOrder.value))
        self._table.setSortingEnabled(True)
        if saved_col >= 0:
            self._table.horizontalHeader().setSortIndicator(saved_col, saved_ord)
```

（`setSortingEnabled(False)`→行投入→`setSortingEnabled(True)`は、投入中に毎行ソートが走るのを防ぐための既存パターン。`member_tab.py`/`withdrawn_tab.py`と同じ）

- [ ] **Step 4: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「事業所名」列ヘッダをクリックすると五十音順にソートされる。別の列（例：登録日）でソートし直し、一度アプリを再起動しても同じ列・同じ順序でソートされた状態で表示される。

- [ ] **Step 5: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: enable sortable columns with persisted sort order in renewal tab"
```

---

### Task 3: 列の表示/非表示（表示列選択ダイアログ）＋列幅の永続化

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: Task 2の`_get_staff_setting`/`_set_staff_setting`
- Produces: 「表示列選択」ボタンで開くダイアログから各列の表示/非表示を切り替えられ、職員別に保存・復元される。列幅変更も職員別に保存・復元される。

- [ ] **Step 1: importを追加する**

`app/ui/renewal_tab.py`の先頭import群：

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QMenu, QDialog, QGridLayout, QCheckBox,
)
```

- [ ] **Step 2: `_resizing_programmatically`フラグを`__init__`に追加する**

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
        self._build_ui()
        self._apply_column_visibility()
        self._refresh_years()
```

- [ ] **Step 3: 「表示列選択」ボタンを追加し、幅変更シグナルを接続する**

`_build_ui`内、`top_row`のブロック：

```python
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
```

を、次のように変更する：

```python
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
        layout.addLayout(top_row)
```

`_build_ui`内、ヘッダ関連の既存コード：

```python
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
```

を、次のように変更する：

```python
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
```

- [ ] **Step 4: 列幅の適用処理を`_refresh`に追加する**

`_refresh`メソッド内、`self._table.setRowCount(len(records))`の直後（`for row, r in enumerate(records):`より前）に追記：

```python
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            self._populate_row(row, r)

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

        saved_col = self._get_staff_setting("renewal_sort_column", -1)
```

（枝番列は保存済み幅がなければ既存の110px初期値を維持する。他列は保存済み幅があればそれを、なければ内容に合わせて自動調整する）

- [ ] **Step 5: 列表示/非表示のメソッド一式を追加する**

`_on_generate`メソッドの後（ファイル末尾）に追記：

```python
    # ── 列表示・幅 ──

    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting("renewal_hidden_columns", [])
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)

    def _exec_column_menu(self, *_):
        dlg = QDialog(self)
        dlg.setWindowTitle("表示列選択")
        dlg.setMinimumWidth(320)

        hidden_cols = list(self._get_staff_setting("renewal_hidden_columns", []))

        outer = QVBoxLayout(dlg)
        items = list(enumerate(COLS))
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
        self._set_staff_setting("renewal_hidden_columns", hidden)

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        if self._resizing_programmatically:
            return
        widths = dict(self._get_staff_setting("renewal_column_widths", {}))
        if new_size == 0:
            widths.pop(str(logical_index), None)
        else:
            widths[str(logical_index)] = new_size
        self._set_staff_setting("renewal_column_widths", widths)
```

- [ ] **Step 6: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「表示列選択」ボタンでダイアログが開き、任意の列のチェックを外すと一覧から即座に消える。列幅をドラッグで変更する。アプリを再起動しても、非表示にした列は非表示のまま、変更した列幅もそのまま復元される。

- [ ] **Step 7: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add column visibility toggle and persisted column widths to renewal tab"
```

---

### Task 4: 列の並び替え（ドラッグ）の永続化

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: Task 3の`_apply_column_visibility`
- Produces: 列ヘッダをドラッグで並び替えでき、職員別に保存・復元される。

- [ ] **Step 1: `_build_ui`でセクション移動を許可し、シグナルを接続する**

`_build_ui`内の以下の既存コード：

```python
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
```

を、次のように変更する：

```python
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
        self._table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
```

- [ ] **Step 2: `_apply_column_visibility`で保存済みの列順を復元する**

`_apply_column_visibility`メソッド：

```python
    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting("renewal_hidden_columns", [])
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)
```

を、次のように変更する：

```python
    def _apply_column_visibility(self):
        hidden_cols = self._get_staff_setting("renewal_hidden_columns", [])
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)
        order = self._get_staff_setting("renewal_column_order")
        if order and len(order) == len(COLS):
            header = self._table.horizontalHeader()
            self._resizing_programmatically = True
            for visual, logical in enumerate(order):
                current = header.visualIndex(logical)
                if current != visual:
                    header.moveSection(current, visual)
            self._resizing_programmatically = False
```

- [ ] **Step 3: 並び替えハンドラを追加する**

`_on_column_resized`メソッドの後に追記：

```python
    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        if self._resizing_programmatically:
            return
        header = self._table.horizontalHeader()
        order = [header.logicalIndex(v) for v in range(self._table.columnCount())]
        self._set_staff_setting("renewal_column_order", order)
```

- [ ] **Step 4: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 列ヘッダをドラッグして順番を入れ替えられる。アプリを再起動しても入れ替えた順番のまま表示される。

- [ ] **Step 5: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add draggable column reordering with persistence to renewal tab"
```

---

### Task 5: 列固定（フリーズ）

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `_SelectionDelegate`（`app.ui.member_tab`）、Task 1〜4の列構成・永続化ヘルパー一式
- Produces: 列ヘッダを右クリック→「〇〇列まで固定」で、その列までが左側に固定されたまま水平スクロールできる。「列固定を解除」で解除できる。固定状態は職員別に保存・復元される。

- [ ] **Step 1: importを追加する**

`app/ui/renewal_tab.py`の先頭import群：

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog, QMenu, QDialog, QGridLayout, QCheckBox,
    QApplication, QTableView, QFrame,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QEvent
from app.ui.member_tab import SortableTableWidgetItem, _SelectionDelegate
```

- [ ] **Step 2: `__init__`に`_freeze_col`を追加する**

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
        self._freeze_col: int = self._get_staff_setting("renewal_freeze_col", 0)
        self._build_ui()
        self._apply_column_visibility()
        self._refresh_years()
```

- [ ] **Step 3: `_build_ui`にフォント拡大・選択デリゲート・固定ビューオーバーレイを追加する**

`_build_ui`メソッド全体を次のように置き換える：

```python
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
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self._table.horizontalHeader().sectionResized.connect(self._on_column_resized)
        self._table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(self._show_column_menu)
        self._table.setItemDelegate(_SelectionDelegate(self._table))
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            self._table.setColumnWidth(col, 110)
            self._table.horizontalHeaderItem(col).setToolTip(BRANCH_LABEL[ins_type])
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
        self._frozen_view.horizontalHeader().setSortIndicatorShown(True)
        self._frozen_view.horizontalHeader().sectionClicked.connect(self._on_frozen_header_clicked)
        self._frozen_view.doubleClicked.connect(self._on_frozen_double_clicked)
        self._frozen_view.setSelectionModel(self._table.selectionModel())
        self._frozen_view.setVisible(False)

        self._table.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue)
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self._table.verticalScrollBar().setValue)

        self._table.installEventFilter(self)
```

（既存の`_table`構築内容はそのまま維持しつつ、フォント拡大は名簿タブ固有の装飾のため今回は追加しない。固定ビューは委託解除済タブと同様、選択モデルを本体テーブルと共有することでチェックボックス列なしでも行選択が同期する）

- [ ] **Step 4: 固定ビューのジオメトリ同期・イベントフィルタ・右クリックメニューを追加する**

`_on_section_moved`メソッドの後（ファイル末尾）に追記：

```python
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

    def _on_frozen_double_clicked(self, index):
        self._table.selectRow(index.row())
        self._on_row_double_clicked(self._table.model().index(index.row(), 0))

    def _show_column_menu(self, pos):
        header = self._table.horizontalHeader()
        logical = header.logicalIndexAt(pos)
        menu = QMenu(self)
        if 0 <= logical < len(COLS):
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
```

- [ ] **Step 5: `_on_sort_changed`で固定ビューのソート表示も同期する**

`_on_sort_changed`メソッド：

```python
    def _on_sort_changed(self, logical_col: int, order):
        if logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
```

を、次のように変更する：

```python
    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        if logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
```

- [ ] **Step 6: `_refresh`と`_toggle_column_visibility`・`_on_column_resized`で固定ビューの再描画をトリガーする**

`_refresh`メソッド末尾（`if saved_col >= 0: self._table.horizontalHeader().setSortIndicator(saved_col, saved_ord)`の後）に追記：

```python
        self._update_frozen_view_geometry()
```

`_toggle_column_visibility`メソッド末尾（`self._set_staff_setting("renewal_hidden_columns", hidden)`の後）に追記：

```python
        if self._freeze_col > 0:
            self._update_frozen_view_geometry()
```

`_on_column_resized`メソッド末尾（`self._set_staff_setting("renewal_column_widths", widths)`の後）に追記：

```python
        if self._freeze_col > 0 and logical_index <= self._freeze_col:
            self._update_frozen_view_geometry()
```

- [ ] **Step 7: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブで以下を手動確認する。
1. 列ヘッダを右クリック→「事業所名」列まで固定を選択すると、管理No.〜事業所名列が左側に固定される
2. その状態で一覧を右へ横スクロールしても、固定した列は常に表示され続ける
3. 「列固定を解除」で解除できる
4. 固定した状態でアプリを再起動しても固定が維持される
5. 固定列をダブルクリックすると編集ダイアログが開く（既存の行ダブルクリック動作と同じ）
6. 列の表示/非表示・幅変更・並び替えを行った後も、固定列の表示が正しく追従する
7. ウィンドウ幅1280px以内でクラッシュ・レイアウト崩れがないこと

- [ ] **Step 8: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（全件。UIファイルには自動テストがないため対象外）

- [ ] **Step 9: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add column freeze (pin) support to renewal tab"
```

---

## 完了後の確認事項

- 年度更新タブの一覧が名簿タブと同等の列（枝番単体列を除く）を表示する
- 列の表示/非表示・幅・並び順・ソート順・列固定が職員別に保存・復元される
- 既存の枝番セルのワンクリック提出済切替・ダブルクリック編集ダイアログが引き続き正しく動作する
- チェックボックス選択列・ラベル出力・メール送信・集約並び替えボタンは未実装のまま（`docs/superpowers/specs/2026-07-19-renewal-tab-column-expansion-design.md`のサブプロジェクト②③で対応）
