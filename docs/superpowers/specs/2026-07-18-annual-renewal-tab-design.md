# 年度更新タブ 設計書

**作成日：** 2026-07-18
**ステータス：** 承認済み
**関連ドキュメント：** `年度更新・手数料計算機能_仕様書たたき台.html`（業務仕様たたき台、4章・10.1/10.2節）、`docs/superpowers/specs/2026-07-18-fee-calculation-tab-design.md`（手数料計算タブ設計書。本機能は同じ層構造・実装パターンを踏襲する）

---

## 1. 概要

労働保険名簿管理システムに「年度更新タブ」を新設する。委託事業所ごとに、年度更新関連書類の提出状況を枝番別に管理し、全体状況を自動集計する。手数料計算タブと同じく名簿（`members`）を参照するのみで、事業所の基本情報を複製しない。

業務仕様たたき台の実装ステップでは第3段階（提出状況管理・対応履歴連携）に位置づけられる機能。Excel出力・前年比較・Excel取込は対象外（将来段階）。

---

## 2. 既存アプリとの整合

既存パターン（`models.py` → `services/` → `ui/` → `ui/dialogs/` → `main_window.py`）をそのまま踏襲する。手数料計算タブ（`fee_service.py` / `fee_tab.py` / `fee_edit_dialog.py`）と同型の構成とする。

既存DBとの対応（手数料計算タブ設計書と同じ）：

| 仕様書の用語 | 既存DB |
|---|---|
| 事業所 | `members` テーブル（`member_id` で参照） |
| 管理No. | `members.company_code` |
| 会員No. | `members.member_number` |
| 委託中 | `members.is_active = True`（対象生成の抽出条件） |
| 枝番 | `insurance_entries.branch_number`／`ins_type`（`ippan`/`kensetsu_koyou`/`ringyo`/`kensetsu_genba`/`kensetsu_jimusho`） |

手数料計算タブと異なり、年度ごとの料率のような「年度別ルール」を持たないため、`AnnualFeeRule`に相当するテーブルは作らない。新規テーブルのみ追加するため手動マイグレーションSQLは不要（`Base.metadata.create_all()`が自動作成）。

---

## 3. データモデル（`app/database/models.py` に追記）

```python
class AnnualRenewal(Base):
    __tablename__ = "annual_renewals"
    __table_args__ = (UniqueConstraint("fiscal_year", "member_id"),)

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)

    overall_status = Column(String, nullable=False, default="未提出")
    overall_status_manual = Column(Boolean, nullable=False, default=False)  # 手動指定フラグ
    last_contacted_at = Column(Date)
    note = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member")
    items = relationship("AnnualRenewalItem", back_populates="renewal", cascade="all, delete-orphan")


class AnnualRenewalItem(Base):
    __tablename__ = "annual_renewal_items"
    __table_args__ = (UniqueConstraint("annual_renewal_id", "branch_type"),)

    id = Column(Integer, primary_key=True)
    annual_renewal_id = Column(Integer, ForeignKey("annual_renewals.id"), nullable=False)
    branch_type = Column(String, nullable=False)  # ippan/kensetsu_koyou/ringyo/kensetsu_genba/kensetsu_jimusho
    submission_status = Column(String, nullable=False, default="未提出")  # 未提出/提出済/不備あり/対象外
    confirmed_at = Column(Date)

    renewal = relationship("AnnualRenewal", back_populates="items")
```

---

## 4. ロジック（`app/services/renewal_service.py`）

### 4.1 全体状況の自動判定（純粋関数）

```python
def compute_overall_status(item_statuses: list[str]) -> str:
    """対象外を除く枝番別提出状況から全体状況を自動判定する。"""
    relevant = [s for s in item_statuses if s != "対象外"]
    if not relevant:
        return "未提出"
    if any(s == "不備あり" for s in relevant):
        return "不備あり"
    if all(s == "提出済" for s in relevant):
        return "提出済"
    if all(s == "未提出" for s in relevant):
        return "未提出"
    return "一部提出"
```

判定優先順位：①いずれかが「不備あり」→不備あり　②全て提出済→提出済　③全て未提出→未提出　④それ以外（混在）→一部提出。

「完了」は自動判定では出力されない値。`AnnualRenewal.overall_status_manual == True` のときのみ、担当者が最終確認として明示的に選択できる（手数料タブの支払時期上書きと異なり、**上書き理由の入力は必須にしない**）。

### 4.2 対象生成（`generate_records(fiscal_year: int) -> int`）

委託中事業所（`is_active=True`）のうち、指定年度に`AnnualRenewal`が未作成のものだけ新規作成する。既存レコードはスキップし上書きしない（`fee_service.generate_records`と同じ方針）。各事業所が保有する枝番（`insurance_entries`の`ins_type`の集合）ごとに、状況「未提出」の`AnnualRenewalItem`を作成する。`overall_status`は生成時点で全枝番が「未提出」のため`compute_overall_status`により「未提出」となる。

手数料計算タブと異なり年度別ルールテーブルを持たないため、「新年度追加」→「対象生成」の2段階UIは取らず、**「対象生成」ボタン1つ**で年度を入力させて生成する。

### 4.3 枝番の後発差分への対応（`get(renewal_id)`）

編集ダイアログ表示時、対象事業所が現在保有する枝番のうち`AnnualRenewalItem`が存在しないものがあれば、状況「未提出」で自動追加する（遅延生成）。保有しなくなった枝番のitemは削除せず残す（データを消さない方針）。

### 4.4 更新（`update(renewal_id, items_data, renewal_data) -> AnnualRenewal`）

- 各`AnnualRenewalItem`の`submission_status`／`confirmed_at`を更新する。
- `submission_status`が「提出済」に変更され、かつ`confirmed_at`が未入力の場合、サーバ側で今日の日付を自動セットする（手動上書き可）。
- `overall_status_manual`がFalseの場合、更新後の全item状況から`compute_overall_status`で`overall_status`を再計算して保存する。Trueの場合は`renewal_data`で渡された値をそのまま保存する。

---

## 5. UI

### 5.1 `app/ui/renewal_tab.py`（一覧タブ）

- 年度ドロップダウン（既存`annual_renewals`にある年度を列挙）
- 「対象生成」ボタン：西暦年をダイアログ入力し、その年度で`generate_records`を実行
- 検索欄（事業所名・管理No.・会員No.）
- フィルタ：すべて／未提出／一部提出／提出済／不備あり／完了
- 一覧テーブル（管理No.・会員No.・事業所名・全体状況・最終対応日・備考）。ダブルクリックで編集ダイアログを開く

画面サイズは対象環境（1366×768、ウィンドウ幅1280px以内）に収める。

### 5.2 `app/ui/dialogs/renewal_edit_dialog.py`（編集ダイアログ）

`fee_edit_dialog.py`と同じ QScrollArea + QFormLayout 構成。幅780px以下・高さ600px以下。

- **枝番別提出状況グループ**：事業所が保有する枝番ごとに「状況コンボ（未提出/提出済/不備あり/対象外）＋確認日（QDateEdit、任意）」。状況変更時に確認日を自動セットするロジックは4.4節参照。
- **全体状況グループ**：自動判定結果を常時表示するラベル（`compute_overall_status`をライブ計算）＋「手動指定」チェック＋コンボ（5値：未提出/一部提出/提出済/不備あり/完了）。チェックOFF時はコンボを無効化し自動判定値を表示する。
- **最終対応日**：任意入力（チェック＋QDateEdit、手数料タブの入金日と同じUIパターン）
- **備考**：自由入力（QTextEdit）
- **「対応履歴」ボタン**：`ActivityLogDialog(engine, member_id, staff_name, org_name, parent=self)`を開く。ダイアログのコンストラクタに`staff_name`（呼び出し元の`config.last_staff_name`）を渡す。

保存時：サーバ側（`renewal_service.py`）で全体状況を再計算して保存する（画面入力値をそのまま信用しない、手数料計算タブと同じ方針）。

### 5.3 `main_window.py`

タブ順を仕様書3章の想定通りにする：「名簿 → 委託解除済 → **年度更新** → 手数料計算 → 設定」。`_renewal_tab`を`_fee_tab`の前に挿入する。

---

## 6. 今回除外する範囲

Excel出力、前年比較・会員区分差異チェック、Excel取込（業務仕様たたき台の第4段階、および手数料計算タブと同様に将来対応）。

---

## 7. テスト計画

`tests/test_renewal_service.py` を新規作成し、pytest（`:memory:` SQLite fixtureパターン、既存`tests/test_fee_service.py`と同型）で以下を検証する。

- `compute_overall_status`：不備あり優先、全提出済、全未提出、混在（一部提出）、対象外を除外して判定、空リスト（未提出扱い）
- 対象生成：委託中事業所のみ対象、既存レコードのスキップ（UNIQUE制約）、非委託事業所の除外、保有枝番ごとのitem生成
- 枝番の後発差分：`get()`呼び出し時に新規枝番のitemが自動追加されること、既存itemは維持されること
- 更新：item状況変更後の全体状況自動再計算、`overall_status_manual=True`時は自動再計算されないこと、「提出済」変更時の確認日自動セット

---

## 8. 未確定事項（本段階の実装には影響しない）

業務仕様たたき台13章の未決事項のうち、Excel取込の対象形式・前年比較の詳細は本段階では対象外。年度途中の委託解除事業所の扱いは、手数料計算タブと同様「レコードを残し削除しない」方針を踏襲する。
