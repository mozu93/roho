# 年度更新タブ 一覧画面 枝番別クイック提出済切替 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 年度更新タブの一覧画面に枝番別の状況列（固定5列）を追加し、セルをクリックするだけで「未提出」⇔「提出済」を切り替え、確認日（提出日）を自動セット／クリアできるようにする。

**Architecture:** サービス層に`RenewalService.toggle_item(renewal_id, branch_type)`を追加し、`search()`はitemsも事前ロードするよう修正する。UI層（`RenewalTab`）は一覧テーブルの列構成を拡張し、`cellClicked`シグナルで枝番セルのクリックを検知して`toggle_item`を呼び、対象行のみ再描画する。

**Tech Stack:** Python 3.11+ / PyQt6 / SQLAlchemy + SQLite（WAL） / pytest（サービス層のTDD）

## Global Constraints

- 対象環境: 画面解像度1366×768、ウィンドウ幅1280px以内（プロジェクトのCLAUDE.mdより）
- 「提出済」への切替時、確認日が未入力なら本日日付を自動セットする（既存`update()`と同じ方針）
- 「不備あり」「対象外」のセルはクリックしても変化しない（誤操作防止）
- 参照設計書: `docs/superpowers/specs/2026-07-19-renewal-tab-branch-quick-toggle-design.md`

---

### Task 1: RenewalService.search() でitemsも事前ロードする

**Files:**
- Modify: `app/services/renewal_service.py:142-146`
- Test: `tests/test_renewal_service.py`

**Interfaces:**
- Consumes: 既存の`RenewalService.search(fiscal_year, keyword="", status_filter=None) -> list[AnnualRenewal]`
- Produces: `search()`が返す各`AnnualRenewal`の`.items`にセッション終了後もアクセスできる（`DetachedInstanceError`が発生しない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_renewal_service.py`の末尾に追記：

```python
def test_search_results_have_items_loaded(svc):
    with get_session(svc._engine) as session:
        m = Member(member_number="9001", org_name="A社", is_active=True, is_member=True)
        session.add(m)
        session.flush()
        session.add(InsuranceEntry(member_id=m.id, ins_type="ippan", branch_number="0"))
    svc.generate_records(2026)
    results = svc.search(2026)
    assert len(results) == 1
    assert len(results[0].items) == 1
    assert results[0].items[0].branch_type == "ippan"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_renewal_service.py -v -k test_search_results_have_items_loaded`
Expected: FAIL（`sqlalchemy.orm.exc.DetachedInstanceError`）

- [ ] **Step 3: search()を修正する**

`app/services/renewal_service.py`の`search()`メソッド内、以下の箇所：

```python
            records = q.order_by(Member.member_number).all()
            for r in records:
                _ = r.member
            session.expunge_all()
            return records
```

を、次のように変更する：

```python
            records = q.order_by(Member.member_number).all()
            for r in records:
                _ = r.member
                _ = r.items
            session.expunge_all()
            return records
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_renewal_service.py -v -k test_search_results_have_items_loaded`
Expected: PASS

- [ ] **Step 5: 全サービステストを通しで実行**

Run: `python -m pytest tests/test_renewal_service.py -v`
Expected: PASS（既存20件＋新規1件の全21件）

- [ ] **Step 6: コミット**

```bash
git add app/services/renewal_service.py tests/test_renewal_service.py
git commit -m "fix: eager-load items in RenewalService.search results"
```

---

### Task 2: RenewalService.toggle_item（枝番のワンクリック提出済切替）

**Files:**
- Modify: `app/services/renewal_service.py`（末尾、`search()`の後に追記）
- Test: `tests/test_renewal_service.py`

**Interfaces:**
- Consumes: `AnnualRenewal`, `AnnualRenewalItem`, `compute_overall_status`（Task 2既存関数）、`get_session`
- Produces: `RenewalService.toggle_item(renewal_id: int, branch_type: str) -> AnnualRenewal`。戻り値の`.member`と`.items`はロード済み。存在しないrenewal_idには`ValueError`を送出する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_renewal_service.py`の末尾に追記：

```python
def test_toggle_item_marks_submitted_with_today(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    updated = svc.toggle_item(renewal_id, "ippan")
    item = next(i for i in updated.items if i.branch_type == "ippan")
    assert item.submission_status == "提出済"
    assert item.confirmed_at == date.today()


def test_toggle_item_reverts_and_clears_confirmed_at(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    svc.toggle_item(renewal_id, "ippan")
    updated = svc.toggle_item(renewal_id, "ippan")
    item = next(i for i in updated.items if i.branch_type == "ippan")
    assert item.submission_status == "未提出"
    assert item.confirmed_at is None


def test_toggle_item_noop_when_deficient(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    svc.update(renewal_id, {"ippan": {"submission_status": "不備あり", "confirmed_at": None}},
               {"overall_status_manual": False, "overall_status": None,
                "last_contacted_at": None, "note": ""})
    updated = svc.toggle_item(renewal_id, "ippan")
    item = next(i for i in updated.items if i.branch_type == "ippan")
    assert item.submission_status == "不備あり"
    assert item.confirmed_at is None


def test_toggle_item_noop_when_not_applicable(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    svc.update(renewal_id, {"ippan": {"submission_status": "対象外", "confirmed_at": None}},
               {"overall_status_manual": False, "overall_status": None,
                "last_contacted_at": None, "note": ""})
    updated = svc.toggle_item(renewal_id, "ippan")
    item = next(i for i in updated.items if i.branch_type == "ippan")
    assert item.submission_status == "対象外"


def test_toggle_item_respects_manual_overall_status(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan",))
    svc.update(renewal_id, {"ippan": {"submission_status": "未提出", "confirmed_at": None}},
               {"overall_status_manual": True, "overall_status": "完了",
                "last_contacted_at": None, "note": ""})
    updated = svc.toggle_item(renewal_id, "ippan")
    assert updated.overall_status == "完了"


def test_toggle_item_recomputes_overall_status(svc):
    renewal_id = _setup_renewal(svc, ins_types=("ippan", "kensetsu_koyou"))
    svc.toggle_item(renewal_id, "ippan")
    updated = svc.toggle_item(renewal_id, "kensetsu_koyou")
    assert updated.overall_status == "提出済"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_renewal_service.py -v -k test_toggle_item`
Expected: FAIL（`AttributeError: 'RenewalService' object has no attribute 'toggle_item'`）

- [ ] **Step 3: 実装を追加する**

`app/services/renewal_service.py`の`search()`メソッドの後（クラス末尾）に追記：

```python
    def toggle_item(self, renewal_id: int, branch_type: str) -> AnnualRenewal:
        with get_session(self._engine) as session:
            renewal = session.get(AnnualRenewal, renewal_id)
            if not renewal:
                raise ValueError(f"年度更新レコードID {renewal_id} が見つかりません。")
            item = next((i for i in renewal.items if i.branch_type == branch_type), None)
            if item is not None and item.submission_status in ("未提出", "提出済"):
                if item.submission_status == "未提出":
                    item.submission_status = "提出済"
                    item.confirmed_at = date.today()
                else:
                    item.submission_status = "未提出"
                    item.confirmed_at = None

                if not renewal.overall_status_manual:
                    renewal.overall_status = compute_overall_status(
                        [i.submission_status for i in renewal.items])
                renewal.updated_at = datetime.now()
                session.flush()

            _ = renewal.member
            _ = renewal.items
            session.expunge_all()
            return renewal
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_renewal_service.py -v -k test_toggle_item`
Expected: PASS（6件）

- [ ] **Step 5: 全サービステストを通しで実行**

Run: `python -m pytest tests/test_renewal_service.py -v`
Expected: PASS（全27件）

- [ ] **Step 6: コミット**

```bash
git add app/services/renewal_service.py tests/test_renewal_service.py
git commit -m "feat: add RenewalService.toggle_item for one-click submit toggle"
```

---

### Task 3: RenewalTab 一覧に枝番別状況列を追加する

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `RenewalService.search()`（Task 1でitems事前ロード済み）、`INS_TYPES`（`app.services.member_service`）、`BRANCH_LABEL`（`app.ui.dialogs.renewal_edit_dialog`）
- Produces: `RenewalTab`の一覧テーブルが枝番別列（固定5列、保有しない枝番は「－」）を表示する。列インデックス定数`BRANCH_COL_START = 3`を後続タスク（Task 4）が使用する。

このタスクはUIのため既存プロジェクトの慣例（`renewal_edit_dialog.py`等）に合わせ、自動テストではなく手動確認で検証する。

- [ ] **Step 1: importとCOLS構成を変更する**

`app/ui/renewal_tab.py`の先頭import群：

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
```

- [ ] **Step 2: `_build_ui`にヘッダーツールチップと列幅を追加する**

`_build_ui`メソッド内、以下の既存コード：

```python
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)
```

を、次のように変更する：

```python
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
```

- [ ] **Step 3: `_refresh`を行ごとの描画処理（`_populate_row`）に分割する**

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
        self._table.setRowCount(len(records))
        for row, r in enumerate(records):
            m = r.member
            values = [
                str(m.company_code or ""),
                m.member_number or "",
                m.org_name,
                r.overall_status or "",
                r.last_contacted_at.strftime("%Y-%m-%d") if r.last_contacted_at else "",
                (r.note or "")[:30],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, r.id)
                self._table.setItem(row, col, item)
```

を、次のように変更する：

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
```

- [ ] **Step 4: インポート確認と起動確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること（エラーなくインポートできること）

Run: `python main.py`
Expected: エラーなく起動し、「年度更新」タブの一覧に「管理No.・会員No.・事業所名・枝番0・枝番2・枝番4・枝番5・枝番6・全体状況・最終対応日・備考」の順で列が表示される。対象生成済みのレコードがあれば、保有しない枝番は「－」、保有する枝番は状況名（「提出済」の場合は日付付き）が表示される。枝番列ヘッダーにマウスオーバーするとフルラベルのツールチップが出る。

- [ ] **Step 5: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: display per-branch submission status columns in renewal list"
```

---

### Task 4: 枝番セルのワンクリック提出済切替を実装する

**Files:**
- Modify: `app/ui/renewal_tab.py`

**Interfaces:**
- Consumes: `RenewalService.toggle_item(renewal_id, branch_type) -> AnnualRenewal`（Task 2）、`BRANCH_COL_START`・`_populate_row`（Task 3）
- Produces: 一覧の枝番セルをクリックすると即座に「未提出」⇔「提出済」が切り替わる（該当行のみ再描画）。「不備あり」「対象外」セルはクリックしても変化しない。

このタスクもUIのため手動確認で検証する。

- [ ] **Step 1: `cellClicked`シグナルの接続とハンドラを追加する**

`_build_ui`メソッド内、`self._table.doubleClicked.connect(self._on_row_double_clicked)`の直後に追記：

```python
        self._table.cellClicked.connect(self._on_cell_clicked)
```

`_on_row_double_clicked`メソッドの直前に、新規メソッドを追加：

```python
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
```

- [ ] **Step 2: インポート確認と動作確認**

Run: `python -c "from app.ui.renewal_tab import RenewalTab; print(1)"`
Expected: `1`が出力されること

Run: `python main.py`
Expected: 「年度更新」タブで以下を手動確認する。
1. 「未提出」の枝番セルをクリックすると即座に「提出済 (本日のMM-DD)」に変わり、全体状況列も連動して再計算される（`一部提出`→`提出済`など）
2. 「提出済」のセルを再クリックすると「未提出」に戻り、日付表示も消える
3. 「不備あり」「対象外」のセルをクリックしても表示が変化しない
4. 「－」（保有しない枝番）のセルをクリックしても何も起きない
5. 行のダブルクリックでは従来通り編集ダイアログが開く
6. ウィンドウ幅1280px以内に一覧テーブルが収まっている

- [ ] **Step 3: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（全件。UIファイルには自動テストがないため対象外）

- [ ] **Step 4: コミット**

```bash
git add app/ui/renewal_tab.py
git commit -m "feat: add one-click submit toggle for branch cells in renewal list"
```

---

## 完了後の確認事項

- 年度更新タブの一覧画面で、枝番ごとの提出状況・提出日が可視化される
- 枝番セルのワンクリックで「未提出」⇔「提出済」を切り替えられ、提出日が自動セット／クリアされる
- 「不備あり」「対象外」への変更は引き続き編集ダイアログで行う（設計書6章の除外範囲どおり）
