# 手数料計算タブ（第1段階）設計書

**作成日：** 2026-07-18
**ステータス：** 承認済み
**関連ドキュメント：** `年度更新・手数料計算機能_仕様書たたき台.html`（業務仕様たたき台）

---

## 1. 概要

労働保険名簿管理システムに「手数料計算タブ」を新設する。委託事業所ごとに年度別の枝番別概算保険料を入力し、会員／非会員の計算ルールに基づいて事務手数料を自動計算する。あわせて支払方法・支払時期・入金・督促状況を管理する。

本設計書は、業務仕様たたき台（HTML）で定義された全体像のうち、**第1段階**（手数料計算タブのコア機能。Excel出力・年度更新タブ・Excel取込・対応履歴連携・前年比較機能は含まない）の実装範囲を対象とする。

---

## 2. 既存アプリとの整合

既存アプリは PyQt6 + SQLAlchemy + SQLite（WAL）構成で、`models.py`（全モデル）→ `services/`（CRUD・業務ロジック）→ `ui/`（タブ）→ `ui/dialogs/`（編集ダイアログ）→ `main_window.py`（タブ登録）という一貫した層構造を持つ。本機能もこのパターンをそのまま踏襲する。

既存DBとの対応（レビュー時に確認済み）：

| 仕様書の用語 | 既存DB |
|---|---|
| 事業所 | `members` テーブル（`member_id` で参照） |
| 管理No. | `members.company_code` |
| 会員No. | `members.member_number` |
| 会員区分 | `members.is_member` |
| 登録日 | `members.registered_date`（新規委託年月の初期値候補） |
| 委託中 | `members.is_active = True`（対象生成の抽出条件） |
| 枝番 | `insurance_entries.branch_number` |

新規テーブルのみを追加するため、`connection.py` への手動マイグレーションSQLは不要（`Base.metadata.create_all()` が自動作成する）。

**用語注意：** 既存の `insurance_entries.is_ikkatsu`（継続事業一括認可フラグ）と、本機能の「保険料一括払い」（支払時期1期判定用）は別概念。新カラム名は `is_lump_sum_payment` とし、混同を避ける。

---

## 3. データモデル（`app/database/models.py` に追記）

```python
class AnnualFeeRule(Base):
    __tablename__ = "annual_fee_rules"
    fiscal_year = Column(Integer, primary_key=True)   # 西暦（例: 2026）
    fee_rate = Column(Float, nullable=False, default=0.05)
    member_min_fee = Column(Integer, nullable=False, default=5000)
    non_member_addition = Column(Integer, nullable=False, default=14000)
    tax_rate = Column(Float, nullable=False, default=0.10)


class AnnualFeeRecord(Base):
    __tablename__ = "annual_fee_records"
    __table_args__ = (UniqueConstraint("fiscal_year", "member_id"),)

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)

    is_member_for_fee = Column(Boolean, nullable=False)   # 生成時に members.is_member をコピー
    member_override_reason = Column(Text)                 # 名簿と異なる値に上書きした場合のみ必須

    premium_branch_0 = Column(Integer, nullable=False, default=0)
    premium_branch_2 = Column(Integer, nullable=False, default=0)
    premium_branch_4 = Column(Integer, nullable=False, default=0)
    premium_branch_5 = Column(Integer, nullable=False, default=0)
    premium_branch_6 = Column(Integer, nullable=False, default=0)

    # 計算結果（保存値が正。再計算ボタン実行時のみ更新する）
    premium_total = Column(Integer, nullable=False, default=0)
    five_percent_amount = Column(Integer, nullable=False, default=0)
    base_fee_amount = Column(Integer, nullable=False, default=0)
    non_member_addition_amount = Column(Integer, nullable=False, default=0)
    fee_without_tax = Column(Integer, nullable=False, default=0)
    tax_amount = Column(Integer, nullable=False, default=0)
    total_amount = Column(Integer, nullable=False, default=0)

    is_lump_sum_payment = Column(Boolean, nullable=False, default=False)
    entrust_start_month = Column(Date)      # 新規委託年月。生成時に members.registered_date を初期値
    auto_payment_period = Column(String)     # "1期"/"2期"/"3期"/"請求なし"
    final_payment_period = Column(String)
    payment_period_override_reason = Column(Text)
    payment_method = Column(String)          # "口座振替"/"振込"/"持参"

    paid_amount = Column(Integer)
    paid_at = Column(Date)
    reminder_status = Column(String, nullable=False, default="未督促")
    note = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member")
```

---

## 4. 計算ロジック（`app/services/fee_service.py`）

### 4.1 手数料計算

```
premium_total = 枝番0 + 枝番2 + 枝番4 + 枝番5 + 枝番6（空欄は0円）
five_percent_amount = floor(premium_total * fee_rate)

if premium_total == 0:
    fee_without_tax = member_min_fee（会員 5,000円） / non_member_addition（非会員 14,000円、下限適用なし）
else:
    base_fee_amount = max(five_percent_amount, member_min_fee)
    fee_without_tax = base_fee_amount（会員） / base_fee_amount + non_member_addition（非会員）

tax_amount = floor(fee_without_tax * tax_rate)
total_amount = fee_without_tax + tax_amount
```

`fee_rate` / `member_min_fee` / `non_member_addition` / `tax_rate` は `AnnualFeeRule`（年度別）から取得する。既存レコードの計算結果は保存値を正とし、料率変更後は「再計算」ボタン実行時のみ反映する。

### 4.2 支払時期の自動判定

優先順位（レビュー時に確定済み）：

```
1. is_lump_sum_payment == True                        → 1期
2. entrust_start_month が当該年度内（4月～翌3月）の新規委託  → 月から判定
     4月～8月  → 2期
     9月～12月 → 3期
     1月～3月  → 請求なし
3. それ以外（既存事業所）                                → 2期
```

「新規委託かつ一括払い」の組み合わせは実務上発生しない前提とするが、両方に該当するデータが入力された場合は①（一括払い）が優先される。

---

## 5. UI

### 5.1 `app/ui/fee_tab.py`（一覧タブ）

- 年度ドロップダウン（既存データのある年度を列挙）＋「新年度追加」ボタン（西暦年を入力し、`AnnualFeeRule` を前年度からコピーして作成）
- 検索欄（事業所名・管理No.・会員No.）
- フィルタ：未入力／未入金／入金済／1期／2期／3期／請求なし／非会員／督促中
- 一覧テーブル（ダブルクリックで編集ダイアログを開く）
- 操作ボタン：「対象生成」（名簿の委託中事業所 `is_active=True` から未作成分のみレコードを追加。既存レコードはスキップし上書きしない）、「再計算」（選択年度の全件を現在の `AnnualFeeRule` で再計算）

画面サイズは対象環境（1366×768、ウィンドウ幅1280px以内）に収める。列数が多いため横スクロール前提とし、事業所名など先頭列の固定表示は既存 `member_tab.py` の凍結列実装を参考に検討する（必須ではない）。

### 5.2 `app/ui/dialogs/fee_edit_dialog.py`（編集ダイアログ）

`member_edit_dialog.py` と同じ QScrollArea + QFormLayout 構成。幅780px以下・高さ600px以下に収める。

入力項目：会員区分（初期値は名簿参照、チェックで上書き可・上書き時は理由必須）、枝番別概算保険料（事業所が保有しない枝番は入力不可）、計算結果（自動計算・読み取り専用表示）、一括払い区分、委託開始年月、支払時期（自動判定値を表示、手動変更時は理由必須）、支払方法、入金額、入金日、督促状況、備考。

保存時：
- サーバ側（`fee_service.py`）で計算結果を再計算して保存する（画面入力値をそのまま信用しない）
- 入金日が入力された場合、督促状況を自動的に「完了」へ更新する（手動上書き可）

---

## 6. 今回除外する範囲（第1段階外）

Excel出力、年度更新タブ（提出状況管理）、Excel取込、対応履歴への連携記録、前年比較・会員区分差異チェックは含めない。

---

## 7. テスト計画

`tests/test_fee_service.py` を新規作成し、pytest（既存 `tests/test_member_service.py` と同じ `:memory:` SQLite fixtureパターン）で以下を検証する。

- 手数料計算：会員／非会員の通常計算、概算保険料合計0円の例外、端数切り捨て
- 支払時期自動判定：1期（一括払い）／2期（既存事業所）／3期・請求なし（新規委託の月判定）／優先順位（一括払い＋新規委託の同時該当）
- 対象生成：委託中事業所のみ対象、既存レコードのスキップ（UNIQUE制約）、非委託事業所の除外
- 会員区分上書き：上書き時の理由必須チェック
- 入金日入力時の督促状況自動更新

---

## 8. 未確定事項（第1段階の実装には影響しない）

以下は業務仕様たたき台の未決事項として残っているが、第1段階の実装には影響しないため実装しながら決定する：Excel取込の対象形式、一括払い区分の将来的な保持場所（名簿側への移設要否）、入金状態の詳細化（一部入金・過入金）、年度途中の委託解除事業所の扱い。
