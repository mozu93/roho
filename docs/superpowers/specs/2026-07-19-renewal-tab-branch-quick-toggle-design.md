# 年度更新タブ 一覧画面 枝番別クイック提出済切替 設計書

**作成日：** 2026-07-19
**ステータス：** 承認済み
**関連ドキュメント：** `docs/superpowers/specs/2026-07-18-annual-renewal-tab-design.md`（年度更新タブ 設計書、本機能はその追加拡張）

---

## 1. 背景・課題

年度更新タブの一覧画面（`app/ui/renewal_tab.py`）は現在、事業所ごとの「全体状況」（枝番横断の集計値）のみを表示しており、枝番別の提出状況・提出日は表示されない。枝番を「提出済」にするには、毎回一覧から編集ダイアログ（`RenewalEditDialog`）を開き、枝番ごとのプルダウンを手動で変更する必要があり、「一覧画面で簡単に提出済にする」という運用ニーズを満たしていない。

なお、確認日（提出日）を「提出済」変更時に未入力なら本日日付を自動セットするロジック自体は`RenewalService.update()`に既に実装済み（`app/services/renewal_service.py:104-107`）。今回の課題は一覧画面のUI・操作導線の不足であり、日付自動セットのロジックは新設する`toggle_item`にも踏襲する。

---

## 2. 概要

一覧テーブルに枝番別の状況列（固定5列）を追加し、セルをクリックするだけで「未提出」⇔「提出済」を切り替えられるようにする。「提出済」への切替時は確認日（提出日）を自動的に本日日付にセットし、一覧上に表示する。

---

## 3. サービス層（`app/services/renewal_service.py`）

### 3.1 新規メソッド：`toggle_item(renewal_id: int, branch_type: str) -> AnnualRenewal`

```python
def toggle_item(self, renewal_id: int, branch_type: str) -> AnnualRenewal:
    with get_session(self._engine) as session:
        renewal = session.get(AnnualRenewal, renewal_id)
        if not renewal:
            raise ValueError(f"年度更新レコードID {renewal_id} が見つかりません。")
        item = next((i for i in renewal.items if i.branch_type == branch_type), None)
        if item is None or item.submission_status not in ("未提出", "提出済"):
            _ = renewal.member
            _ = renewal.items
            session.expunge_all()
            return renewal  # 対象なし／不備あり・対象外は無変更

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

挙動：
- 「未提出」→「提出済」：`confirmed_at`を本日日付にセット
- 「提出済」→「未提出」：`confirmed_at`を`None`にクリア（誤クリック取り消しを想定した仕様）
- 「不備あり」「対象外」：無変更（UI側でもクリック無効化するが、サービス層でも防御する）
- `overall_status_manual == True`の場合、`overall_status`は変更しない（`update()`と同じ方針）
- `overall_status_manual == False`の場合、`compute_overall_status`で再計算する

### 3.2 `search()`の修正

`renewal.items`を事前ロードしていないため、一覧描画時に枝番情報へアクセスできない。`search()`内で`_ = r.member`と同様に`_ = r.items`を追加し、`session.expunge_all()`前にロードする。

---

## 4. UI層（`app/ui/renewal_tab.py`）

### 4.1 列構成の変更

```
管理No. / 会員No. / 事業所名 / 枝番0 / 枝番2 / 枝番4 / 枝番5 / 枝番6 / 全体状況 / 最終対応日 / 備考
```

- 枝番列は`BRANCH_LABEL`（`renewal_edit_dialog.py`で定義済み）の並び順に固定5列。列ヘッダーは短縮表示（例：「枝番0」）、フルラベル（例：「枝番0（一般・労災＆雇用）」）はツールチップで表示。
- 事業所がその枝番を保有しない場合、セルは「－」表示・クリック無効。
- 枝番セルの表示文言：
  - 「提出済」→ `提出済 07/19`（`confirmed_at`を`MM-DD`形式で1行表示）
  - それ以外（未提出／不備あり／対象外）→ 状況名のみ
- 列幅：対象環境（ウィンドウ幅1280px以内）に収めるため、枝番列は各70px程度に狭め、既存の備考列幅を縮小して調整する。

### 4.2 クリック操作

- `QTableWidget.cellClicked`シグナルをハンドラに接続し、クリックされた列が枝番列かどうかを判定する。
- 枝番列かつセルが「－」（対象外の保有なし）でない場合のみ、そのセルの現在の状況を見て：
  - 「未提出」または「提出済」→ `RenewalService.toggle_item(renewal_id, branch_type)`を呼び出す
  - 「不備あり」「対象外」→ 何もしない（誤操作防止。変更したい場合はダブルクリックで編集ダイアログを開く）
- 呼び出し後、該当行のみ再描画する（全件再検索はしない）。
- 既存のダブルクリック（行全体で編集ダイアログを開く）動作は変更しない。枝番セルをダブルクリックした場合、シングルクリック分のトグルが先に発火し、続けて編集ダイアログが開く（Qtの標準的なクリック→ダブルクリックのイベント発火順序であり、意図した副作用として許容する）。

---

## 5. テスト計画

`tests/test_renewal_service.py`に`toggle_item`のテストを追加：

- 未提出→提出済で`confirmed_at`が本日日付になること
- 提出済→未提出で`confirmed_at`が`None`にクリアされること
- 「不備あり」「対象外」の場合は状況・確認日とも変化しないこと
- `overall_status_manual=True`のときは`toggle_item`後も`overall_status`が上書きされないこと
- 全item提出済になった場合に`overall_status`が自動的に「提出済」に再計算されること
- `search()`で返されるレコードの`.items`にアクセスできること（`DetachedInstanceError`が発生しないこと）

UI（`renewal_tab.py`）は既存の年度更新タブと同じ方針を踏襲し、自動テスト対象外とする。`python main.py`を起動し、以下を手動確認する：
1. 一覧に枝番別列が表示され、保有しない枝番は「－」表示
2. 未提出セルをクリックすると「提出済 (本日日付)」に変わり、全体状況が連動して再計算される
3. 提出済セルを再クリックすると「未提出」に戻り、確認日表示も消える
4. 「不備あり」「対象外」セルはクリックしても変化しない
5. ウィンドウ幅1280px以内に一覧テーブルが収まる

---

## 6. 今回除外する範囲

- 枝番セルからの「不備あり」「対象外」への直接切替（引き続き編集ダイアログで対応）
- 一覧上での複数行一括切替（1件ずつのクリック操作のみ）
