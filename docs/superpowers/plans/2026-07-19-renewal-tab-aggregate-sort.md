# 年度更新タブ 集約並び替えボタン 実装計画（サブプロジェクト②）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 年度更新タブの一覧に「集約並び替え」ボタンを追加し、事業所が保有する枝番の保険番号を複数キーとして一括で並び替えられるようにする。列ヘッダクリックによる単一列ソートと「集約並び替え」は、直近に行った操作が次回起動時にも復元される一貫した挙動にする。

**Architecture:** `_refresh()`の行投入以降の処理を`_fill_table(records)`に切り出し、`_refresh()`と新規`_on_aggregate_sort()`の両方から呼べるようにする。新しい永続化フラグ`renewal_aggregate_sort_active`で「集約モードか単一列ソートか」を管理し、プログラムによる`setSortIndicator`呼び出しは`_resizing_programmatically`ガードで囲むことで、ユーザー操作と区別する。

**Tech Stack:** Python 3.11+ / PyQt6（DB変更なし）

## Global Constraints

- `app/database/models.py`・`app/utils/app_config.py`への変更は行わない
- 永続化キー：`renewal_aggregate_sort_active`（bool、デフォルトfalse）を新規追加。既存の`renewal_sort_column`/`renewal_sort_order`は変更しない（集約モード中は単に参照されないだけ）
- 列ヘッダをクリックして並び替えたときは`renewal_aggregate_sort_active`をfalseにする。「集約並び替え」ボタンを押したときはtrueにする
- プログラムによる`setSortIndicator`呼び出しは`_resizing_programmatically`ガードで囲み、`_on_sort_changed`はこのガード中は永続化処理をスキップする（ただし固定ビューへのソートインジケータ同期は常に行う）
- 参照設計書: `docs/superpowers/specs/2026-07-19-renewal-tab-aggregate-sort-design.md`
- このタスクはUIのみの変更（サービス層への変更なし）。既存プロジェクトの慣例に合わせ自動テストは追加せず手動確認で検証する

---

### Task 1: `_fill_table`への切り出しと集約モード対応のソート復元

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Produces: `_aggregate_sort_key(r)`（モジュールレベル関数、`AnnualRenewal`を受け取り複数キーのタプルを返す）、`RenewalTab._fill_table(records)`（Task 2の`_on_aggregate_sort`が呼び出す）、`RenewalTab._records`（現在表示中のレコード一覧を保持する属性）

- [ ] **Step 1: `_aggregate_sort_key`関数を追加する**

`app/ui/renewal_tab.py`の`_TAIL_START = ...`定義の直後、`class RenewalTab`の直前に追記：

```python
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
```

- [ ] **Step 2: `__init__`に`self._records`を追加する**

`__init__`メソッド内、既存の`self._resizing_programmatically = False`の直後に追記：

```python
        self._records: list = []
```

- [ ] **Step 3: `_refresh`を`_fill_table`に切り出す**

`_refresh`メソッド全体を次のように置き換える：

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
            if str(i) in saved_widths:
                self._table.setColumnWidth(i, int(saved_widths[str(i)]))
            else:
                self._table.resizeColumnToContents(i)
        for i, ins_type in enumerate(INS_TYPES):
            col = BRANCH_COL_START + i
            if str(col) not in saved_widths:
                self._table.setColumnWidth(col, 110)
        self._resizing_programmatically = False

        if self._get_staff_setting("renewal_aggregate_sort_active", False):
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
```

（`setSortingEnabled(True)`を先に呼んでから`setSortIndicator`を呼ぶ既存の順序はそのまま維持する。集約モード中は`setSortIndicator`を一切呼ばない＝単一列での自動再ソートを防ぐ）

- [ ] **Step 4: `_on_sort_changed`を更新する**

`_on_sort_changed`メソッド：

```python
    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        if logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
```

を、次のように変更する：

```python
    def _on_sort_changed(self, logical_col: int, order):
        self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
        if not self._resizing_programmatically and logical_col >= 0:
            self._set_staff_setting("renewal_sort_column", logical_col)
            self._set_staff_setting("renewal_sort_order", order.value)
            self._set_staff_setting("renewal_aggregate_sort_active", False)
```

- [ ] **Step 5: インポート確認と回帰確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブが従来通り動作する（列ヘッダクリックでのソート・その永続化、表示列選択、列幅、列並び替え、列固定、枝番セルのクリックトグル）。この時点では「集約並び替え」ボタンはまだ存在しない（Task 2で追加）。既存のRenewalEditDialogを開いて保存後の一覧再表示（`_refresh`経由）も正常に動作することを確認する。

もしGUIを直接操作できない場合は、実DB・実`AppConfig`・実`RenewalTab`ウィジェットを使ったスクリプトで代替検証する：`RenewalTab`を構築→`_on_sort_changed(3, Qt.SortOrder.DescendingOrder)`を呼ぶ→`renewal_sort_column`が保存されることを確認→同じconfigから2つ目の`RenewalTab`を構築（再起動を模擬）→ソート列・順序が復元され、実際の行順に反映されることを確認する（サブプロジェクト①のTask 2検証と同じ手法）。

- [ ] **Step 6: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "refactor: extract _fill_table from _refresh, guard sort-indicator restore"
```

---

### Task 2: 「集約並び替え」ボタンの追加

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `_aggregate_sort_key`・`_fill_table`（Task 1）
- Produces: 「集約並び替え」ボタンをクリックすると枝番0→2→4→5→6の保険番号順に一覧が並び替わり、以後（列ヘッダクリックで別のソートに切り替えるまで）その状態が維持・永続化される。

- [ ] **Step 1: ボタンを追加する**

`_build_ui`内、以下の既存コード：

```python
        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.clicked.connect(self._exec_column_menu)
        top_row.addWidget(col_setting_btn)
        layout.addLayout(top_row)
```

を、次のように変更する：

```python
        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.clicked.connect(self._exec_column_menu)
        top_row.addWidget(col_setting_btn)
        agg_btn = QPushButton("集約並び替え")
        agg_btn.clicked.connect(self._on_aggregate_sort)
        top_row.addWidget(agg_btn)
        layout.addLayout(top_row)
```

- [ ] **Step 2: `_on_aggregate_sort`メソッドを追加する**

`_fill_table`メソッドの直後に追記：

```python
    def _on_aggregate_sort(self):
        self._records.sort(key=_aggregate_sort_key)
        self._set_staff_setting("renewal_aggregate_sort_active", True)
        self._fill_table(self._records)
```

- [ ] **Step 3: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブで以下を手動確認する。
1. 「集約並び替え」ボタンで、枝番0→2→4→5→6の保険番号順に一覧が並び替わる
2. 列ヘッダ（例：フリガナ）をクリックして並び替えた後に「集約並び替え」を押すと、集約順で表示され、上書きされない
3. 集約並び替え後に年度切替・検索を行っても集約順が維持される
4. 集約並び替え後にアプリを再起動しても集約順で表示される
5. 集約並び替え中に列ヘッダをクリックすると、その列でのソートに切り替わり、以後アプリを再起動してもクリックした列でソートされた状態になる（集約状態には戻らない）

GUIを直接操作できない場合は、実DB・実`AppConfig`・実`RenewalTab`ウィジェットを使ったスクリプトで代替検証する（サブプロジェクト①のTask 2/4検証と同じ手法）：複数の事業所・複数の枝番保険番号を持つテストデータを用意し、`_on_sort_changed`で列ソートを設定→`_on_aggregate_sort()`を呼ぶ→保険番号列の並び順が期待通りであることを確認→同じconfigから2つ目の`RenewalTab`を構築（再起動を模擬）→集約順が維持されていることを確認→`_on_sort_changed`を呼んで集約モードを解除→3つ目の`RenewalTab`を構築→今度は列ソート順で復元されることを確認する。

- [ ] **Step 4: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（既存の無関係な1件の失敗を除き全件。UIファイルには自動テストがないため対象外）

- [ ] **Step 5: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add aggregate sort button to renewal tab"
```

---

## 完了後の確認事項

- 年度更新タブに「集約並び替え」ボタンが追加され、枝番の保険番号順で一括並び替えできる
- 列ヘッダクリックによる単一列ソートと集約並び替えが、直近の操作を優先する形で職員別に永続化される
- チェックボックス選択列・ラベル出力・メール送信ボタンは未実装のまま（`docs/superpowers/specs/2026-07-19-renewal-tab-column-expansion-design.md`のサブプロジェクト③で対応）
