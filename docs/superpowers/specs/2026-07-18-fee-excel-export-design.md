# 手数料計算タブ Excel出力（第2段階・全件一覧のみ）設計書

**作成日：** 2026-07-18
**ステータス：** 承認済み
**関連ドキュメント：**
- `年度更新・手数料計算機能_仕様書たたき台.html`（業務仕様たたき台、9章「Excel出力仕様」）
- `docs/superpowers/specs/2026-07-18-fee-calculation-tab-design.md`（第1段階設計書）

---

## 1. 概要

第1段階で実装した手数料計算タブに、年度別の計算結果をExcelへ出力する機能を追加する。業務仕様たたき台9章では6種類の出力シート（全件一覧・未入金一覧・入金済一覧・期別集計・支払方法別集計・非会員一覧）を想定しているが、本段階では利用頻度の最も高い「全件一覧」シートのみを対象とする。他のシート（集計系・フィルタ系）は今後の段階で追加する。

---

## 2. 既存パターンとの整合

既存アプリには `app/services/import_service.py` の `ExportService.export_excel(members, output_path)` という名簿Excel出力の前例があり、`app/ui/member_tab.py:1214` の `_on_export()` から `QFileDialog.getSaveFileName` → サービス呼び出し → `QMessageBox.information` という一貫したパターンで呼び出されている。本機能もこのパターンをそのまま踏襲する。

既存 `export_excel` は openpyxl の `Workbook()` を作成し、`ws.append(headers)` の後に `ws.append([...])` で行を追加する素朴な実装（フォント装飾やセル書式指定なし）であり、本機能もこの簡素なスタイルに合わせる。日付は `strftime("%Y-%m-%d")` の文字列として出力する（既存の `registered_date` 出力と同じ扱い）。

---

## 3. 出力仕様

### 3.1 呼び出しフロー

1. 手数料計算タブの一覧画面に「Excel出力」ボタンを追加する（`app/ui/fee_tab.py` の操作ボタン行、「再計算」ボタンの後ろ）。
2. クリック時、`QFileDialog.getSaveFileName` で保存先を選択させる。初期ファイル名は `手数料計算_{選択中の年度}年度.xlsx`（例：`手数料計算_2026年度.xlsx`）。
3. `FeeExportService(engine).export_excel(fiscal_year, path)` を呼び出す。
4. 成功時は `QMessageBox.information` で件数を表示。失敗時は既存パターンと同様に `QMessageBox.critical` で例外内容を表示。
5. 年度が未選択（対象年度がない）場合はボタン押下時に警告を出し、出力しない（既存の「対象生成」「再計算」ボタンと同じガード方針）。

### 3.2 シート構成

シート名：`全件一覧`。1シートのみ。

### 3.3 出力列（仕様書9.2節、全26列）

年度、管理No.、会員No.、事業所名、会員区分、枝番0概算、枝番2概算、枝番4概算、枝番5概算、枝番6概算、概算保険料合計、5%計算額、下限適用後手数料、非会員加算、税抜手数料、消費税、請求合計、自動判定支払時期、確定支払時期、変更理由、支払方法、入金額、入金日、差額、督促状況、備考

列と `AnnualFeeRecord` / `Member` の対応：

| 出力列 | データソース |
|---|---|
| 年度 | `record.fiscal_year` |
| 管理No. | `member.company_code` |
| 会員No. | `member.member_number` |
| 事業所名 | `member.org_name` |
| 会員区分 | `"会員"` / `"非会員"`（`record.is_member_for_fee`） |
| 枝番0〜6概算 | `record.premium_branch_0/2/4/5/6` |
| 概算保険料合計 | `record.premium_total` |
| 5%計算額 | `record.five_percent_amount` |
| 下限適用後手数料 | `record.base_fee_amount` |
| 非会員加算 | `record.non_member_addition_amount` |
| 税抜手数料 | `record.fee_without_tax` |
| 消費税 | `record.tax_amount` |
| 請求合計 | `record.total_amount` |
| 自動判定支払時期 | `record.auto_payment_period` |
| 確定支払時期 | `record.final_payment_period` |
| 変更理由 | `record.payment_period_override_reason` |
| 支払方法 | `record.payment_method` |
| 入金額 | `record.paid_amount` |
| 入金日 | `record.paid_at`（文字列変換） |
| 差額 | `record.paid_amount - record.total_amount`（`paid_amount` が `None` の場合は空欄。8.1節の方針を踏襲） |
| 督促状況 | `record.reminder_status` |
| 備考 | `record.note` |

数値列は生の `int`／`None`（空欄）をそのままセルへ書き込む。文字列列は `None` の場合は空文字列にフォールバックする（既存 `export_excel` と同じ `or ""` の慣習）。

### 3.4 対象データの取得・並び順

`FeeService.search(fiscal_year)`（フィルタなし、全件）を呼び出す。この際 `.member` は事前ロード済みなのでセッションクローズ後も安全に参照できる（第1段階で確認済み）。並び順は `search()` が返す順（会員No.昇順）をそのまま使う。

---

## 4. 実装

### 4.1 新規ファイル

`app/services/fee_export_service.py`：

```python
class FeeExportService:
    def __init__(self, engine):
        self._engine = engine

    def export_excel(self, fiscal_year: int, output_path: str) -> int:
        """指定年度の全件一覧をExcel出力する。出力件数を返す。"""
```

内部で `FeeService(self._engine).search(fiscal_year)` を呼び、openpyxlで1シートを構築して保存する。

### 4.2 既存ファイルの変更

`app/ui/fee_tab.py`：
- 操作ボタン行に「Excel出力」ボタンを追加（`_on_export` ハンドラを新設）
- `_on_export` は年度未選択時に警告、選択済みなら `QFileDialog.getSaveFileName` → `FeeExportService.export_excel` 呼び出し → 完了/エラーメッセージ

---

## 5. テスト計画

`tests/test_fee_export_service.py` を新規作成し、pytest（`tests/test_fee_service.py` と同じ `:memory:` SQLiteパターン）で以下を検証する。

- 出力ファイルが実際に作成され、openpyxlで読み戻すとヘッダー行が26列の期待値と一致する
- 会員・非会員それぞれのレコードが正しい値で1行ずつ出力される
- `paid_amount` が `None` のレコードは「差額」列が空欄になる
- `note` などの `None` 値を持つ文字列列が空文字列で出力される（クラッシュしない）

---

## 6. 今回除外する範囲

未入金一覧、入金済一覧、期別集計、支払方法別集計、非会員一覧の各シートは対象外（今後の段階で追加）。
