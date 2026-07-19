# 年度更新タブ 集約並び替えボタン 設計書（サブプロジェクト②）

**作成日：** 2026-07-19
**ステータス：** 承認済み
**関連ドキュメント：** `docs/superpowers/specs/2026-07-19-renewal-tab-column-expansion-design.md`（サブプロジェクト①、列拡張・表示切替・列固定。本機能はその追加拡張）

---

## 1. 背景

年度更新タブの一覧に、名簿タブ（`member_tab.py`）・委託解除済タブ（`withdrawn_tab.py`）にある「集約並び替え」ボタンを追加する。事業所が保有する枝番（保険番号）を優先順位付きの複数キーとして一括で並び替える機能。

設計検討の過程で、名簿タブの`_on_aggregate_sort`をそのまま踏襲すると、直前に列ヘッダをクリックして単一列ソートが有効になっていた場合、集約並び替えの結果が`_fill_table`末尾のソート復元処理によって即座に上書きされ、ボタンが実質機能しないという名簿タブ自体に存在する不具合を引き継いでしまうことが判明した。年度更新タブではこれを修正し、「直近に行った並び替え操作（列クリックか集約並び替えか）が次回起動時にも復元される」という一貫した挙動にする。

---

## 2. 挙動

- **列ヘッダをクリックして並び替えたとき**：`renewal_aggregate_sort_active`をfalseにし、従来通りその列・順序を`renewal_sort_column`/`renewal_sort_order`に保存する（集約並び替え状態は解除される）
- **「集約並び替え」ボタンを押したとき**：`renewal_aggregate_sort_active`をtrueにし、集約並び替えの結果を表示する（`renewal_sort_column`/`renewal_sort_order`自体は上書きしない。フラグがtrueの間は単に使われないだけ）
- **次回タブを開いたとき（`_refresh()`実行時）**：`renewal_aggregate_sort_active`がtrueなら、DBから取得した最新の`records`に対して集約並び替えを再適用し、単一列ソートインジケータは表示しない。falseなら従来通り`renewal_sort_column`/`renewal_sort_order`を復元する

---

## 3. 並び替えキー

`member_tab.py`/`withdrawn_tab.py`の`_on_aggregate_sort`と同じロジック：`INS_TYPES`の順（ippan→kensetsu_koyou→ringyo→kensetsu_genba→kensetsu_jimusho）で、各枝番の`ins_number`を複数キーとして並び替える。数値文字列として解釈できる場合は数値として、できない場合は文字列として比較する（`int(val)`が成功すれば`(0, int(val))`、失敗すれば`(1, val or "")`というタプルキー、保有しない枝番は空文字列扱い）。

```python
def _aggregate_sort_key(r):
    def _ins_key(ins_type):
        entry = next((e for e in r.member.insurance_entries if e.ins_type == ins_type), None)
        val = entry.ins_number if entry else ""
        try:
            return (0, int(val))
        except (ValueError, TypeError):
            return (1, val or "")
    return tuple(_ins_key(t) for t in INS_TYPES)
```

---

## 4. 実装方針

### 4.1 `_records`の保持とリファクタリング

`RenewalTab`に`self._records: list = []`を追加する。現在`_refresh()`に一体化している「DB取得後の行投入〜列幅復元〜ソート復元〜列固定更新」の処理を、`_fill_table(records)`という新メソッドに切り出す（`member_tab.py`/`withdrawn_tab.py`と同じ命名・構造）。`_refresh()`は「年度・検索条件からDB取得 → `self._records`に保存 → 集約モードなら並び替え適用 → `_fill_table(self._records)`呼び出し」という薄い処理になる。

### 4.2 プログラム的な`setSortIndicator`呼び出しのガード

`_fill_table`末尾の単一列ソート復元（`setSortIndicator(saved_col, saved_ord)`）は、Qtの`sortIndicatorChanged`シグナルを発火させる。これは`_on_sort_changed`（列ヘッダクリック時のハンドラ）にも届いてしまうため、既存の`_resizing_programmatically`ガード（サブプロジェクト①で確立したパターン）でこの呼び出しを囲み、`_on_sort_changed`側もこのガードを見て早期リターンするようにする。これにより：
- プログラムによる復元が「ユーザーが列をクリックした」と誤認され、集約並び替えフラグが意図せずfalseに戻ってしまう不具合を防ぐ
- 副次効果として、既存の「`_refresh()`のたびに同じ値を無駄にディスクへ再書き込みする」という軽微な非効率（サブプロジェクト①の最終レビューでMinor指摘済み）も解消される

### 4.3 `_fill_table`の末尾処理

```python
aggregate_active = self._get_staff_setting("renewal_aggregate_sort_active", False)
self._table.setSortingEnabled(True)
if not aggregate_active:
    saved_col = self._get_staff_setting("renewal_sort_column", -1)
    saved_ord = Qt.SortOrder(self._get_staff_setting(
        "renewal_sort_order", Qt.SortOrder.AscendingOrder.value))
    if saved_col >= 0:
        self._resizing_programmatically = True
        self._table.horizontalHeader().setSortIndicator(saved_col, saved_ord)
        self._resizing_programmatically = False
self._update_frozen_view_geometry()
```

集約モードがtrueのときは単一列インジケータを一切設定しない（設定すると即座にその列で再ソートされ、集約順が崩れるため）。

### 4.4 `_on_sort_changed`の更新

`self._frozen_view`側インジケータの同期は、プログラムによる復元時にも見た目の一貫性のため常に行う（早期returnで丸ごとスキップしない）。永続化処理のみをガードで囲む：

```python
def _on_sort_changed(self, logical_col: int, order):
    self._frozen_view.horizontalHeader().setSortIndicator(logical_col, order)
    if not self._resizing_programmatically and logical_col >= 0:
        self._set_staff_setting("renewal_sort_column", logical_col)
        self._set_staff_setting("renewal_sort_order", order.value)
        self._set_staff_setting("renewal_aggregate_sort_active", False)
```

### 4.5 `_on_aggregate_sort`（新規）

```python
def _on_aggregate_sort(self):
    self._records.sort(key=_aggregate_sort_key)
    self._set_staff_setting("renewal_aggregate_sort_active", True)
    self._fill_table(self._records)
```

### 4.6 `_refresh`（更新後）

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
```

### 4.7 UI

「集約並び替え」ボタンを一覧上部（「表示列選択」ボタンの近く）に追加する。

---

## 5. 永続化キー

新規追加：`renewal_aggregate_sort_active`（bool、デフォルトfalse）。既存の`renewal_sort_column`/`renewal_sort_order`は変更せず、単に集約モード中は参照されないだけとする（列クリックで集約モードを抜けたときに、直前の列ソート設定へ自然に戻れるようにするため）。

---

## 6. テスト計画

UIのみの変更（サービス層への変更なし）のため、既存プロジェクトの慣例に合わせ自動テストは追加せず手動確認する：

1. 「集約並び替え」ボタンで、枝番0→2→4→5→6の保険番号順に一覧が並び替わる
2. 列ヘッダ（例：フリガナ）をクリックして並び替えた後に「集約並び替え」を押すと、集約順で表示され、上書きされない
3. 集約並び替え後にタブを離れて戻る（年度切替・検索）と、集約順が維持される
4. 集約並び替え後にアプリを再起動しても、集約順で表示される
5. 集約並び替え中に列ヘッダをクリックすると、その列でのソートに切り替わり、以後は通常の単一列ソートとして永続化される（再度アプリを再起動してもクリックした列でソートされた状態になる）

---

## 7. 今回除外する範囲

- チェックボックス選択列・ラベル出力・メール送信ボタン（サブプロジェクト③）
