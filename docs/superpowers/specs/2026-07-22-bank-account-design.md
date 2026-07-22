# 振込先口座管理機能 設計書

**作成日：** 2026-07-22  
**対象：** 労働保険事務組合 加入者名簿管理システム  
**ステータス：** 設計案

---

## 1. 概要

顧客（既存システムでは `members` の事業所）ごとに複数の振込先口座を登録し、顧客詳細から追加・編集・削除できるようにする。保存時に全銀向けの桁数・文字種を保証し、将来の総合振込データ生成では再変換せず口座情報を利用できる状態にする。

### 既存項目との対応

| 要件上の名称 | 既存システム | 備考 |
|---|---|---|
| 顧客マスタ | `members` | 新規顧客テーブルは作成しない |
| 顧客コード | `members.company_code` | 画面・外部仕様で使用する一意な業務コード |
| 顧客名 | `members.org_name` | 事業所名 |
| 顧客マスタの主キー | `members.id` | 振込先口座の実FKに使用する |

`company_code` は業務上の顧客コードとして表示・検索に使う。一方、変更され得る業務コードをFKにせず、不変の `members.id` を参照する。APIでは顧客コードを受け、サービス層で `members.id` に解決する。

---

## 2. テーブル設計

### 2.1 `bank_accounts`（振込先口座マスタ）

| 論理名 | カラム名 | SQLite / SQLAlchemy型 | NULL | 制約・初期値 | 説明 |
|---|---|---|---|---|---|
| 口座ID | `id` | INTEGER | 不可 | PK, AUTOINCREMENT | 内部識別子 |
| 顧客ID | `member_id` | INTEGER | 不可 | FK → `members.id` | 顧客コードから解決した内部FK |
| 金融機関コード | `bank_code` | VARCHAR(4) | 不可 | CHECK: 4桁数字 | 先頭ゼロを保持するため文字列 |
| 金融機関名 | `bank_name` | VARCHAR(100) | 不可 | TRIM後1文字以上 | 表示・照合用 |
| 支店コード | `branch_code` | VARCHAR(3) | 不可 | CHECK: 3桁数字 | 先頭ゼロを保持するため文字列 |
| 支店名 | `branch_name` | VARCHAR(100) | 不可 | TRIM後1文字以上 | 表示・照合用 |
| 預金種目コード | `account_type` | VARCHAR(1) | 不可 | CHECK IN (`1`,`2`,`4`) | 1:普通、2:当座、4:貯蓄 |
| 口座番号 | `account_number` | VARCHAR(7) | 不可 | CHECK: 7桁数字 | 先頭ゼロを保持するため文字列 |
| 受取人名カナ | `recipient_name_kana` | VARCHAR(48) | 不可 | 正規化後1～48文字 | 半角カナ等の全銀許容文字で保存 |
| 使用可否フラグ | `is_enabled` | BOOLEAN | 不可 | DEFAULT TRUE | TRUEのみ振込出力候補 |
| 登録日 | `created_at` | DATETIME | 不可 | DEFAULT 現在日時 | 作成日時 |
| 更新日 | `updated_at` | DATETIME | 不可 | DEFAULT 現在日時、更新時変更 | 最終更新日時 |

金融機関名・支店名も画面要件上の必須項目とする。全銀出力に直接必要な5項目に加え、コードの入力誤りを画面で確認可能にするためである。

### 2.2 DDL案（SQLite）

```sql
CREATE TABLE bank_accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id           INTEGER NOT NULL,
    bank_code           VARCHAR(4) NOT NULL,
    bank_name           VARCHAR(100) NOT NULL,
    branch_code         VARCHAR(3) NOT NULL,
    branch_name         VARCHAR(100) NOT NULL,
    account_type        VARCHAR(1) NOT NULL,
    account_number      VARCHAR(7) NOT NULL,
    recipient_name_kana VARCHAR(48) NOT NULL,
    is_enabled          BOOLEAN NOT NULL DEFAULT 1,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bank_accounts_member
        FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE,
    CONSTRAINT ck_bank_code
        CHECK (length(bank_code) = 4 AND bank_code NOT GLOB '*[^0-9]*'),
    CONSTRAINT ck_branch_code
        CHECK (length(branch_code) = 3 AND branch_code NOT GLOB '*[^0-9]*'),
    CONSTRAINT ck_account_type CHECK (account_type IN ('1', '2', '4')),
    CONSTRAINT ck_account_number
        CHECK (length(account_number) = 7 AND account_number NOT GLOB '*[^0-9]*'),
    CONSTRAINT ck_bank_name CHECK (length(trim(bank_name)) > 0),
    CONSTRAINT ck_branch_name CHECK (length(trim(branch_name)) > 0),
    CONSTRAINT ck_recipient_name CHECK (
        length(recipient_name_kana) BETWEEN 1 AND 48
    )
);

CREATE INDEX ix_bank_accounts_member_id
    ON bank_accounts(member_id);

CREATE INDEX ix_bank_accounts_enabled
    ON bank_accounts(member_id, is_enabled);
```

同一顧客への同一口座の重複は通常入力ミスと考え、サービス層で `member_id + bank_code + branch_code + account_type + account_number` の重複を拒否する。既存重複データの取込みなど将来要件を妨げないよう、DBのUNIQUE制約にはしない。

### 2.3 マイグレーション・DB設定

- SQLAlchemyモデル `BankAccount` を追加し、`Member.bank_accounts` に `cascade="all, delete-orphan"` を設定する。
- 接続ごとに `PRAGMA foreign_keys=ON` を実行し、SQLiteでもFKと `ON DELETE CASCADE` を有効化する。
- `Base.metadata.create_all()` により新規DBへ作成し、既存DBには `CREATE TABLE IF NOT EXISTS` 相当で追加する。既存顧客データの変換は不要。
- 日時は既存実装に合わせてローカル日時で保存する。将来サーバー化する場合はUTCへ統一する。

---

## 3. リレーション設計

```text
members（顧客） 1 ───── 0..N bank_accounts（振込先口座）
  PK id                       PK id
  UQ company_code            FK member_id → members.id
```

- 1顧客は0件以上の振込先口座を持つ。
- 1口座は必ず1顧客に属する。
- 顧客削除時は口座も削除する。ただし通常運用の「脱会」は `members.is_active=False` であり、口座情報は保持する。
- 顧客コード変更時も `member_id` は変わらないため、口座との関連を維持できる。
- 口座単体の顧客付替えは許可しない。必要な場合は削除後、正しい顧客へ再登録する。

---

## 4. 画面設計

### 4.1 配置

既存の顧客編集／詳細ダイアログに「振込先口座」セクションまたはタブを追加する。新規顧客は顧客本体を保存して `members.id` が発行された後に口座を追加可能とする。

```text
┌ 振込先口座 ─────────────────────────────────────────┐
│ [追加] [編集] [削除]                                  │
│ 有効│金融機関(コード)│支店(コード)│種目│口座番号│受取人名カナ │
│  ✓ │○○銀行(0001)  │本店(001)  │普通│1234567│ｶ)ｻﾝﾌﾟﾙ    │
│    │△△銀行(0002)  │中央(105)  │当座│7654321│ﾔﾏﾀﾞ ﾀﾛｳ  │
└────────────────────────────────────────────────────┘
```

一覧は有効口座を先、次に `bank_code`, `branch_code`, `id` の順で表示する。無効口座は文字色をグレーにする。ダブルクリックは編集と同じ動作とする。

### 4.2 追加・編集ダイアログ

| 入力欄 | UI | 必須 | 補足 |
|---|---|---|---|
| 金融機関コード | 4文字テキスト | 必須 | 数字のみ。入力完了時に検証 |
| 金融機関名 | テキスト | 必須 | 前後空白除去 |
| 支店コード | 3文字テキスト | 必須 | 数字のみ |
| 支店名 | テキスト | 必須 | 前後空白除去 |
| 預金種目 | コンボボックス | 必須 | 普通(1)／当座(2)／貯蓄(4) |
| 口座番号 | 7文字テキスト | 必須 | 数字のみ、マスク表示しない |
| 受取人名カナ | テキスト | 必須 | 入力中は全角可、保存時正規化後の値を併記 |
| 使用可否 | チェックボックス | 必須 | 初期値ON |

- 保存押下時、すべてのエラーを各欄の直下とダイアログ上部に表示する。
- 検証成功時のみ保存し、一覧を再読込する。
- 削除時は「金融機関名・支店名・口座番号末尾4桁」を示す確認ダイアログを表示する。
- 削除は物理削除とする。振込履歴機能追加後は履歴参照を保つため論理削除へ再検討する。
- 無効化は削除せず履歴的に口座を残したい場合に利用する。

### 4.3 権限・競合・エラー

- 現行システムには操作権限区分がないため、全ログイン職員が追加・編集・削除可能とする。
- SQLiteロック時は「口座情報を保存できませんでした。再度お試しください。」と表示し、入力値を保持する。
- 編集対象が他端末で削除済みなら「対象の口座は既に削除されています。」と表示して一覧を更新する。

---

## 5. API設計

現行はPyQt6デスクトップアプリでHTTPサーバーを持たないため、`bank_account_service.py` のサービスAPIを正式な境界とする。将来Web化する場合のHTTP対応も併記する。

### 5.1 ローカルサービスAPI

| 操作 | シグネチャ | 結果 |
|---|---|---|
| 一覧 | `list_bank_accounts(session, company_code, include_disabled=True)` | `list[BankAccountDTO]` |
| 取得 | `get_bank_account(session, account_id)` | `BankAccountDTO`、不存在はNotFound |
| 追加 | `create_bank_account(session, company_code, data)` | 作成済みDTO |
| 編集 | `update_bank_account(session, account_id, data)` | 更新済みDTO |
| 削除 | `delete_bank_account(session, account_id)` | 戻り値なし |

`data` の共通形式：

```json
{
  "bank_code": "0001",
  "bank_name": "みずほ銀行",
  "branch_code": "001",
  "branch_name": "東京営業部",
  "account_type": "1",
  "account_number": "0123456",
  "recipient_name_kana": "株式会社サンプル",
  "is_enabled": true
}
```

サービス層は顧客存在確認、正規化、入力検証、重複確認を1トランザクション内で行う。UIからSQLAlchemyモデルを直接更新しない。

### 5.2 将来のHTTP API対応

| Method | Path | 内容 | 成功 |
|---|---|---|---|
| GET | `/api/customers/{companyCode}/bank-accounts?includeDisabled=true` | 一覧 | 200 |
| POST | `/api/customers/{companyCode}/bank-accounts` | 追加 | 201 |
| GET | `/api/bank-accounts/{accountId}` | 1件取得 | 200 |
| PUT | `/api/bank-accounts/{accountId}` | 全項目編集 | 200 |
| DELETE | `/api/bank-accounts/{accountId}` | 削除 | 204 |

エラー形式：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "入力内容を確認してください。",
  "errors": {
    "bank_code": ["金融機関コードは4桁の数字で入力してください。"]
  }
}
```

| 状態 | HTTP | コード |
|---|---:|---|
| 入力不正 | 400 | `VALIDATION_ERROR` |
| 顧客・口座なし | 404 | `CUSTOMER_NOT_FOUND` / `BANK_ACCOUNT_NOT_FOUND` |
| 同一口座重複 | 409 | `DUPLICATE_BANK_ACCOUNT` |
| DB競合 | 409 | `WRITE_CONFLICT` |
| 予期しないエラー | 500 | `INTERNAL_ERROR` |

レスポンスの口座番号は現行の社内デスクトップ運用では全桁を返す。外部公開APIにする際は既定で末尾4桁のみとし、全桁取得に追加権限を要求する。

---

## 6. 入力チェック仕様

### 6.1 項目別チェック

| 項目 | 正規化 | 検証 | エラーメッセージ |
|---|---|---|---|
| 金融機関コード | 前後空白除去 | `^[0-9]{4}$` | 金融機関コードは4桁の数字で入力してください。 |
| 金融機関名 | 前後空白除去 | 1～100文字 | 金融機関名を入力してください。 |
| 支店コード | 前後空白除去 | `^[0-9]{3}$` | 支店コードは3桁の数字で入力してください。 |
| 支店名 | 前後空白除去 | 1～100文字 | 支店名を入力してください。 |
| 預金種目コード | 文字列化 | `1`, `2`, `4` のいずれか | 預金種目を選択してください。 |
| 口座番号 | 前後空白除去 | `^[0-9]{7}$` | 口座番号は7桁の数字で入力してください。 |
| 受取人名カナ | 下記手順で正規化 | 正規化後1～48文字、許容文字のみ | 受取人名カナに全銀で使用できない文字が含まれています。 |
| 使用可否 | なし | Boolean | 使用可否を指定してください。 |

桁不足をゼロ埋めして補正すると誤口座につながるため、コードと口座番号の自動ゼロ埋めはしない。

### 6.2 受取人名カナの正規化

保存前に以下の順で処理し、処理後の文字列をDBに保存する。

1. Unicode NFKC正規化を行う。
2. ひらがなを対応するカタカナへ変換する。
3. 全角カタカナを半角カタカナへ変換する（濁点・半濁点を含む）。
4. 英字は半角大文字、数字は半角へ変換する。
5. 全角・連続空白を半角空白1文字へ変換し、前後空白を除去する。
6. 全銀で一般的に使用する `0-9 A-Z ｱ-ﾝ ﾞ ﾟ`、半角空白、および許容記号 `()-. /` のみに限定する。
7. 法人格は入力された読みを保持する。略語（例：`ｶ)`）への自動変換は行わない。
8. 48文字以内であることを確認する。超過時に切り捨てずエラーとする。

例：`株式会社　サンプル` → `ｶﾌﾞｼｷｶﾞｲｼｬ ｻﾝﾌﾟﾙ`、`やまだ 太郎` → `ﾔﾏﾀﾞ ﾀﾛｳ`。漢字は読みを確定できないため自動変換できず、許容文字エラーとして利用者にカナ入力を促す。

> 注：受取人名の実際の最大桁数・許容記号・法人略語は、採用する銀行の全銀協規定／接続仕様を実装時に確認する。本設計の48文字は一般的な総合振込レコードの受取人名欄を前提とする。

### 6.3 複合チェック

- 指定 `company_code` の顧客が存在しない場合は保存しない。
- 同一顧客で金融機関コード、支店コード、預金種目、口座番号がすべて一致する口座は、使用可否に関係なく重複エラーとする。編集時は自身を除外する。
- 金融機関コードと金融機関名、支店コードと支店名の正当性は、現時点では外部マスタがないため形式のみ検証する。将来、金融機関マスタ導入時に存在・組合せを検証する。
- UIとサービス層の両方で検証し、DB CHECK制約を最終防御とする。

---

## 7. サンプルデータ

顧客コード `1001` が `members.id = 10` に対応している例：

```sql
INSERT INTO bank_accounts (
    member_id, bank_code, bank_name, branch_code, branch_name,
    account_type, account_number, recipient_name_kana, is_enabled,
    created_at, updated_at
) VALUES
    (10, '0001', 'みずほ銀行', '001', '東京営業部',
     '1', '0123456', 'ｶ)ｻﾝﾌﾟﾙ', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    (10, '0005', '三菱ＵＦＪ銀行', '001', '本店',
     '2', '7654321', 'ｶ)ｻﾝﾌﾟﾙ', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
```

API返却例：

```json
[
  {
    "id": 1,
    "company_code": 1001,
    "bank_code": "0001",
    "bank_name": "みずほ銀行",
    "branch_code": "001",
    "branch_name": "東京営業部",
    "account_type": "1",
    "account_type_name": "普通",
    "account_number": "0123456",
    "recipient_name_kana": "ｶ)ｻﾝﾌﾟﾙ",
    "is_enabled": true,
    "created_at": "2026-07-22T10:00:00+09:00",
    "updated_at": "2026-07-22T10:00:00+09:00"
  }
]
```

---

## 8. 全銀フォーマット出力時の利用方法

### 8.1 抽出

出力対象顧客と振込金額を確定後、次の条件で口座を取得する。

```sql
SELECT
    m.company_code,
    b.bank_code,
    b.branch_code,
    b.account_type,
    b.account_number,
    b.recipient_name_kana
FROM members AS m
JOIN bank_accounts AS b ON b.member_id = m.id
WHERE m.id IN (:target_member_ids)
  AND m.is_active = 1
  AND b.is_enabled = 1;
```

1顧客に有効口座が複数ある場合、現要件には優先口座の指定がないため自動選択しない。出力画面で振込先を1件選ばせる。将来、`is_default` または `priority` を追加すれば既定口座を自動選択できる。

### 8.2 データレコードへのマッピング

| 全銀データレコード項目 | 取得元 | 編集方法 |
|---|---|---|
| 被仕向金融機関番号 | `bank_code` | 4桁をそのまま使用 |
| 被仕向支店番号 | `branch_code` | 3桁をそのまま使用 |
| 預金種目 | `account_type` | 1桁をそのまま使用 |
| 口座番号 | `account_number` | 7桁をそのまま使用 |
| 受取人名 | `recipient_name_kana` | 採用仕様の固定長まで半角空白で右詰め補完 |

口座情報は文字列として扱い、数値変換による先頭ゼロ欠落を防ぐ。固定長化・文字コード変換はDB保存時ではなくファイル生成時に行う。

### 8.3 出力処理フロー

1. 出力対象、振込金額、各顧客の有効な振込先口座を選択する。
2. 口座の必須5項目と桁数を出力直前にも再検証する。
3. 依頼人情報からヘッダーレコードを作成する。
4. 選択口座と金額からデータレコードを作成する。
5. 件数・合計金額を集計してトレーラーレコードを作成する。
6. エンドレコードを付与する。
7. 採用銀行の仕様に従い、固定長、改行、文字コード（例：Shift_JIS）でファイル化する。
8. 出力日時、操作者、対象口座ID、金額、ファイル識別子を将来の振込出力履歴へ保存する。

### 8.4 出力前エラー

- 有効口座0件：`顧客コード1001には使用可能な振込先口座がありません。`
- 有効口座複数かつ未選択：`顧客コード1001の振込先口座を選択してください。`
- 保存済みデータが現行仕様に不適合：対象顧客と項目を一覧表示し、1件でもあればファイルを生成しない。
- 文字コード変換不能：置換文字を出力せず、該当する受取人名をエラーにする。

---

## 9. テスト観点・受入条件

- 1顧客へ2件以上の口座を登録し、一覧表示・個別編集・個別削除できる。
- 顧客Aの画面に顧客Bの口座が表示・更新されない。
- 先頭ゼロを含む各コード・口座番号が欠落せず保存、再表示される。
- `123`、`12A4` など不正な金融機関コードを拒否する。
- 預金種目 `3` をUI、サービス、DBの各層で拒否する。
- 全角カナ、ひらがな、全角英数字を規定の半角カナ・半角大文字へ変換して保存する。
- 漢字や未許可記号、48文字超過は切り捨てず拒否する。
- 必須項目を複数空にした場合、該当する全項目のエラーを同時表示する。
- 同一顧客の同一口座を拒否し、異なる顧客への同一口座登録は許可する。
- 無効口座は一覧に残るが、全銀出力候補に含まれない。
- 顧客コード変更後も口座の関連が維持される。
- 顧客の物理削除時は関連口座が残存しない。

