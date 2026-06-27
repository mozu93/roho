# 労働保険事務組合 加入者名簿管理システム 設計書

**作成日：** 2026-06-24  
**ステータス：** 承認済み

---

## 1. 概要

労働保険事務組合の加入者名簿を管理するデスクトップアプリケーション。  
事業所ごとに最大5種の保険番号（枝番・番号・特別加入・継続事業一括認可フラグ）を管理し、  
対応履歴・変更履歴・脱会記録・宛名ラベルPDF出力に対応する。  
2〜3名の職員が共有フォルダ上のSQLiteデータベースを同時利用する。

---

## 2. 技術スタック

| 要素 | 採用技術 |
|---|---|
| 言語 | Python 3.11+ |
| UI | PyQt6 |
| データベース | SQLAlchemy + SQLite（WALモード） |
| PDF生成 | ReportLab（cci-billing-labelの `label_pdf.py` を流用） |
| インポート | openpyxl |
| 設定ファイル | JSON（`app_config.json`） |

---

## 3. ディレクトリ構成

```
rouho/
  main.py
  start.bat
  app_config.json              # 最終ログイン職員名などを保存
  rouho.db                     # SQLite（共有フォルダに配置）
  app/
    database/
      __init__.py
      models.py                # 全モデル定義
      connection.py            # SQLAlchemy セッション管理
    services/
      member_service.py        # 名簿CRUD・変更履歴記録
      import_service.py        # Excelインポート
      label_service.py         # ラベル出力（label_pdf.pyを利用）
      activity_service.py      # 対応履歴CRUD・既読管理
      template_service.py      # メールテンプレートCRUD
      email_service.py         # Graph API送信
      send_job_service.py      # 送信ジョブ・ログ管理
    ui/
      __init__.py
      main_window.py           # メインウィンドウ・新着バナー
      member_tab.py            # 名簿タブ
      withdrawn_tab.py         # 脱会済みタブ
      label_tab.py             # ラベル出力タブ
      email_tab.py             # メール送信タブ
      settings_tab.py          # 設定タブ
      dialogs/
        __init__.py
        member_edit_dialog.py  # 加入者編集ダイアログ
        member_history_dialog.py  # データ変更履歴ダイアログ
        activity_log_dialog.py # 対応履歴ダイアログ
        withdraw_dialog.py     # 脱会処理ダイアログ
        import_dialog.py       # Excelインポート列マッピングダイアログ
        template_edit_dialog.py  # テンプレート編集ダイアログ
        merge_preview_dialog.py  # 差し込みプレビューダイアログ
    utils/
      app_config.py            # app_config.json 読み書き
    services/
      pdf/
        label_pdf.py           # cci-billing-labelから流用
  app/
    version.py               # バージョン番号の単一管理源（例：__version__ = "1.0.0"）
    utils/
      updater.py             # GitHub APIチェック・ダウンロード・インストーラー起動
  assets/
    icons/
      rouho.ico              # アプリアイコン
  installer/
    setup.iss                # Inno Setup インストーラー定義
  rouho.spec                 # PyInstaller ビルド定義
  .github/
    workflows/
      release.yml            # タグpushで自動ビルド＆リリース
  docs/
    superpowers/
      specs/
        2026-06-24-rouho-design.md
  tests/
  requirements.txt
```

---

## 4. データモデル

### `members`（加入者名簿）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| member_number | TEXT | UNIQUE, NOT NULL | 会員No. |
| org_name | TEXT | NOT NULL | 事業所名 |
| org_kana | TEXT | | 事業所フリガナ |
| dept_title | TEXT | | 所属・役職 |
| rep_name | TEXT | | 代表者名 |
| rep_kana | TEXT | | 代表者フリガナ |
| email | TEXT | | メールアドレス |
| tel_area | TEXT | | 市外局番（電話） |
| tel | TEXT | | 電話番号 |
| fax_area | TEXT | | 市外局番（FAX） |
| fax | TEXT | | FAX番号 |
| postal_code | TEXT | | 郵便番号（事業所） |
| address | TEXT | | 住所（事業所） |
| postal_code_mail | TEXT | | 郵送先郵便番号 |
| address_mail | TEXT | | 郵送先住所 |
| addressee_mail | TEXT | | 郵送先宛名 |
| label_tag | TEXT | | ラベル（Excelの AB列） |
| employment_ins_no | TEXT | | 雇用保険事業所番号 |
| note | TEXT | | メモ（Excelの AD列） |
| is_active | BOOLEAN | DEFAULT TRUE | 有効フラグ |
| withdrawn_at | DATE | | 脱会日 |
| withdraw_reason | TEXT | | 脱会理由 |
| created_at | DATETIME | NOT NULL | |
| updated_at | DATETIME | NOT NULL | |

---

### `insurance_entries`（保険番号）

1事業所につき最大5レコード（保険種別ごと）。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| member_id | INTEGER | FK → members | |
| ins_type | TEXT | NOT NULL | `ippan`（一般・労＆雇）/ `kensetsu_koyou`（建設業・他雇用）/ `ringyo`（林業・労災）/ `kensetsu_genba`（建設業・現場）/ `kensetsu_jimusho`（建設業・事務所） |
| branch_number | TEXT | | 枝番（0/2/4/5/6） |
| ins_number | TEXT | | 番号 |
| is_tokubetsu | BOOLEAN | DEFAULT FALSE | 特別加入フラグ |
| is_ikkatsu | BOOLEAN | DEFAULT FALSE | 継続事業一括認可フラグ |

**枝番と保険種別の対応：**

| ins_type | 枝番 | Excelの列 | 説明 |
|---|---|---|---|
| ippan | 0 | R+S | 一般・労働保険＆雇用保険 |
| kensetsu_koyou | 2 | T+U | 建設業・その他雇用保険 |
| ringyo | 4 | V+W | 林業・労災 |
| kensetsu_genba | 5 | X+Y | 建設業・現場 |
| kensetsu_jimusho | 6 | Z+AA | 建設業・事務所 |

---

### `member_changes`（データ変更履歴）

住所・保険番号など正式データ変更のスナップショット記録。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| member_id | INTEGER | FK → members | |
| changed_at | DATETIME | NOT NULL | 変更日時 |
| changed_by | TEXT | NOT NULL | 職員名 |
| change_reason | TEXT | NOT NULL | 変更理由 |
| snapshot | TEXT | NOT NULL | 変更前データ全体（JSON）。members全フィールド＋insurance_entries配列を含む |

---

### `activity_logs`（対応履歴）

電話対応・相談など日常業務の時系列ログ。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| member_id | INTEGER | FK → members | |
| logged_at | DATETIME | NOT NULL | 記録日時 |
| logged_by | TEXT | NOT NULL | 職員名 |
| content | TEXT | NOT NULL | 内容 |

---

### `activity_categories`（対応カテゴリマスタ）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| name | TEXT | NOT NULL | カテゴリ名（例：新規加入、労災申請） |
| sort_order | INTEGER | NOT NULL | 表示順 |

---

### `activity_log_categories`（対応履歴↔カテゴリ 中間テーブル）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| activity_log_id | INTEGER | FK → activity_logs | |
| category_id | INTEGER | FK → activity_categories | |

---

### `activity_confirmations`（対応履歴の既読管理）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| activity_log_id | INTEGER | FK → activity_logs | |
| staff_id | INTEGER | FK → staff | |
| confirmed_at | DATETIME | NOT NULL | 既読日時 |

---

### `change_confirmations`（データ変更履歴の既読管理）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| member_change_id | INTEGER | FK → member_changes | |
| staff_id | INTEGER | FK → staff | |
| confirmed_at | DATETIME | NOT NULL | 既読日時 |

---

### `email_templates`（メールテンプレート）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| name | TEXT | NOT NULL | テンプレート名 |
| subject | TEXT | NOT NULL | 件名（差し込み記法対応） |
| body | TEXT | NOT NULL | 本文（差し込み記法対応） |
| created_at | DATETIME | NOT NULL | |
| updated_at | DATETIME | NOT NULL | |

---

### `send_jobs`（送信ジョブ）

1回の一斉配信単位。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| name | TEXT | NOT NULL | ジョブ名（例：2026年7月 特別加入者へのご案内） |
| template_id | INTEGER | FK → email_templates | |
| staff_id | INTEGER | FK → staff | 操作者 |
| status | TEXT | NOT NULL | draft / sending / done / error |
| total_count | INTEGER | | 送信対象件数 |
| success_count | INTEGER | | 成功件数 |
| error_count | INTEGER | | エラー件数 |
| created_at | DATETIME | NOT NULL | |
| sent_at | DATETIME | | 送信完了日時 |

---

### `send_logs`（送信ログ）

会員ごとの送信結果。

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| job_id | INTEGER | FK → send_jobs | |
| member_id | INTEGER | FK → members | |
| to_address | TEXT | NOT NULL | 実際の送信先アドレス |
| subject | TEXT | NOT NULL | 実際に送信した件名 |
| status | TEXT | NOT NULL | success / error / skip |
| error_message | TEXT | | エラー内容 |
| sent_at | DATETIME | | |

---

### `staff`（職員マスタ）

| カラム | 型 | 制約 | 説明 |
|---|---|---|---|
| id | INTEGER | PK | |
| name | TEXT | NOT NULL | 職員名 |
| is_active | BOOLEAN | DEFAULT TRUE | 有効フラグ |

---

## 5. 職員ログイン仕様

- 初回起動時：職員選択ダイアログを表示（ドロップダウン、パスワードなし）
- 2回目以降：`app_config.json` に保存した最終選択職員を自動適用
- メインウィンドウ右上に「ログイン中：山田さん　[ログアウト]」を常時表示
- ログアウトボタン押下で職員選択ダイアログを再表示

---

## 6. 各タブの機能仕様

### 6.1 名簿タブ

**一覧テーブル（表示列）**  
会員No. / 事業所名 / フリガナ / 電話 / 保険種別（5種のどれが有効かを●で表示） / 特別加入 / 最終対応日

**検索・絞り込み（上部）**
- キーワード検索：事業所名・フリガナ・住所・電話番号（部分一致）
- 枝番フィルタ：0 / 2 / 4 / 5 / 6（複数選択可）
- 特別加入のみ表示チェックボックス
- 継続事業一括認可のみ表示チェックボックス

**操作ボタン**  
追加 / 編集 / 脱会処理 / 変更履歴 / 対応履歴 / Excel出力

**Excel出力（`member_service.py`）**
- 名簿タブの現在の検索・絞り込み結果をそのまま `.xlsx` で出力
- 出力列：会員No. / 事業所名 / フリガナ / 代表者名 / メール / 電話 / FAX / 郵便番号 / 住所 / 郵送先郵便番号 / 郵送先住所 / 郵送先宛名 / 雇用保険事業所番号 / 保険番号5種（枝番・番号・特別加入・一括）/ メモ
- ファイル保存ダイアログで保存先を指定
- openpyxl で生成

**編集ダイアログ（`member_edit_dialog.py`）**
- 基本情報全フィールド入力
- 保険番号5種（枝番・番号・特別加入・一括フラグ）
- 変更理由入力欄（保存時必須）
- 保存時に変更前スナップショットを `member_changes` に自動記録
- 保存時に他職員の `change_confirmations` に未読レコードを自動作成

**対応履歴ダイアログ（`activity_log_dialog.py`）**
- 時系列ログ表示（新しい順）
- カテゴリ（複数選択可）+ 内容テキスト + 保存ボタン
- 職員名は自動付与（ログイン中職員）
- 保存後、他職員の `activity_confirmations` に未読レコードを自動作成

**脱会処理ダイアログ（`withdraw_dialog.py`）**
- 脱会日・脱会理由を入力
- 確認後 `is_active=False`・`withdrawn_at`・`withdraw_reason` を更新

---

### 6.2 脱会済みタブ

- 脱会済み会員一覧（脱会日・事業所名・脱会理由）
- ダブルクリックで詳細参照（読み取り専用）
- 再加入ボタン（確認ダイアログ付き、`is_active=True` に戻す）

---

### 6.3 ラベル出力タブ

**絞り込みエリア（上部）**
- キーワード検索：事業所名・フリガナ・住所（部分一致）
- 枝番フィルタ：0 / 2 / 4 / 5 / 6（複数選択可）
- 特別加入のみ表示チェックボックス
- 脱会済みを含める（チェックボックス）
- クイック選択ボタン：[全アクティブ会員] [特別加入のみ] → クリックで一致する会員を自動チェック

**会員一覧テーブル（チェックボックス付き）**
- 表示列：チェックボックス / 会員No. / 事業所名 / 住所（郵送先優先）/ 枝番 / 特別加入
- 絞り込み結果をリアルタイム表示
- 列ヘッダーのチェックボックスで表示中の全件を一括選択／解除
- 個別チェックボックスで任意の会員を選択

**ラベル設定**
- 用紙種別：A-ONE 28185（3列×6行）/ 28187（2列×6行）/ 51002（2列×5行）
- フォント選択
- バーコード印字オン/オフ

**宛名ルール**  
`postal_code_mail` / `address_mail` / `addressee_mail` が入力されていれば優先。  
空の場合は `postal_code` / `address` / `org_name` にフォールバック。

**出力ボタン：「選択中 N件をPDF出力」→ PDF保存ダイアログ**

---

### 6.4 メール送信タブ

送信フローをステップ形式で展開する（temp_mailと同方式）。

**Step 1：宛先選択**
- キーワード・枝番・特別加入フラグで絞り込み
- チェックボックス付き一覧で個別選択
- クイック選択：[全アクティブ会員] [特別加入のみ] [枝番指定]
- メールアドレス未登録の会員はグレー表示・スキップ扱い

**Step 2：テンプレート選択**
- ドロップダウンでテンプレート選択
- 件名・本文プレビュー（その場で一時編集可）
- プレースホルダー：`{事業所名}` `{代表者名}` `{会員No.}` `{所属・役職}`

**Step 3：添付ファイル（任意）**
- 全社共通ファイル：複数ファイル選択可
- 会社別ファイル：フォルダ＋ファイル名ルール（例：`{会員No.}.pdf`）でマッチング確認

**Step 4：最終確認・送信**
- 送信対象一覧（事業所名・送信先アドレス・添付）
- ジョブ名入力欄
- テスト送信ボタン（自分のアドレスへ1通）
- 「送信実行」→ プログレスバーで進捗表示
- 完了後サマリー（成功N件・エラーN件・スキップN件）

**送信履歴（タブ下部またはサブパネル）**
- ジョブ一覧（送信日・操作者・ジョブ名・成功/エラー件数）
- ジョブ選択で明細表示（事業所名・送信先・ステータス・エラー内容）

---

### 6.5 設定タブ

- **職員管理**：追加・有効/無効切り替え
- **対応カテゴリ管理**：追加・編集・削除・表示順並び替え
- **メールテンプレート管理**：追加・編集・削除
- **Microsoft 365設定**：テナントID・クライアントID・テスト送信先（接続テスト＆サインインボタン付き）

---

### 6.5 新着フィード（全タブ共通・ウィンドウ上部バナー）

```
[新着 3件] ▼
・2026-06-24 13:02  ㈱サンプル商事  対応メモ（山田）  [✓]
・2026-06-24 11:45  △△建設㈱       住所変更（鈴木）  [✓]
                                        [すべて既読にする]
```

- ログイン中職員の未読 `activity_logs`（`activity_confirmations` 未登録）および `member_changes`（`change_confirmations` 未登録）のみ表示
- ダブルクリックで該当事業所の対応履歴または変更履歴ダイアログへ遷移
- [✓] ボタンで個別既読 → `activity_confirmations` にレコード追加
- [すべて既読にする] で一括既読処理
- 既読後はバナーの件数バッジが更新

---

## 7. Excelインポート仕様

### 事前準備（ユーザー側作業）

インポート前にExcelを加工し、各保険番号ペアの右に2列（特別加入フラグ・一括フラグ）を追加する。セルの色を見て、該当する場合は `1` を入力する。

| 元の列 | 意味 | 追加列① | 追加列② |
|---|---|---|---|
| R+S | 一般・労＆雇 | 特別加入（1=ON） | 一括（1=ON） |
| T+U | 建設業・他雇用 | 特別加入 | 一括 |
| V+W | 林業・労災 | 特別加入 | 一括 |
| X+Y | 建設業・現場 | 特別加入 | 一括 |
| Z+AA | 建設業・事務所 | 特別加入 | 一括 |

### インポートダイアログ（`import_dialog.py`）

- Excelファイル選択
- 列マッピング確認画面（ヘッダー行から自動推定、手動修正可）
- 既存会員No.と重複した場合は「上書き」または「スキップ」を選択
- インポート結果サマリー（追加N件・更新N件・スキップN件）

---

## 8. 共有フォルダ運用

- `rouho.db` と `app_config.json` をNAS上の共有フォルダに配置
- SQLite WALモード（Write-Ahead Logging）を有効化して同時書き込み競合を最小化
- NASはSMBv2以上を推奨。SMBv1環境ではファイルロックが正常に機能しない場合がある
- 同一事業所を2人が同時に編集・保存した場合のみ競合の可能性あり。その際は「書き込みエラーが発生しました。再度お試しください」メッセージを表示して再読み込みを促す
- 同時送信・一斉操作などは想定しない

---

## 9. 外部ライブラリ

```
PyQt6
SQLAlchemy
openpyxl
reportlab
requests    # Graph API HTTP通信
msal        # Microsoft Authentication Library（トークン取得）
packaging   # semver バージョン比較（自動アップデート用）
```

---

## 10. ビルド・配布・自動アップデート仕様

cci-billing-labelの同機能と同方式（参照実装）。

### バージョン管理

`app/version.py` に `__version__ = "1.0.0"` のみを持つ。PyInstaller spec・Inno Setup・GitHub Actions の全員がここから取得する。

### 自動アップデートチェック

- 起動時にバックグラウンドスレッド（`QThread`）で GitHub API を非同期チェック（タイムアウト8秒）
- エンドポイント: `https://api.github.com/repos/{owner}/rouho/releases/latest`
- `packaging.version.Version` で semver 比較
- チェック失敗（ネット不通等）はサイレント失敗（バナー非表示のまま）

### アップデートバナー UI（`app/ui/update_banner.py`）

新バージョン検出時にメインウィンドウ上部（新着バナーの下）に黄色バナーを表示。

```
状態遷移：非表示 → バナー表示＋ダウンロードボタン → プログレスバー → 今すぐ更新ボタン
```

### PyInstaller ビルド（`rouho.spec`）

- `one-dir` 形式（`COLLECT`）、`console=False`
- `assets/` フォルダを同梱
- 出力 exe 名: `Rouho`

### Inno Setup（`installer/setup.iss`）

- インストール先: `{localappdata}\Rouho`（管理者権限不要）
- スタートメニュー・デスクトップショートカット作成
- アンインストーラー付き

### GitHub Actions（`.github/workflows/release.yml`）

トリガー: `v*.*.*` タグの push

1. Python 3.11 セットアップ・依存インストール
2. `app/version.py` からバージョン取得
3. PyInstaller でビルド
4. Inno Setup でインストーラー作成
5. GitHub Release に自動公開

### リリース手順（開発者）

```bash
# app/version.py の __version__ を更新してコミット
git tag v1.0.1
git push origin v1.0.1
# → GitHub Actions が自動でビルド・リリース
```

---

## 11. Microsoft Graph API 認証仕様

委任アクセス許可（Delegated）を使用する。職員が自分のMicrosoft 365アカウントでサインインし、そのアカウントとして送信する。クライアントシークレット不要。

**設定項目（app_config.json に保存）：**
- テナントID（tenant_id）
- クライアントID（client_id）
- テスト送信先アドレス（test_address）

**認証フロー：**
1. 初回送信時（またはトークン期限切れ時）にMSALのデバイスコードフローでブラウザ認証
2. 取得したトークンをMSALのトークンキャッシュに保存（以降は自動更新）
3. `https://graph.microsoft.com/v1.0/me/sendMail` にPOSTしてメール送信

**必要なAzure ADアプリ権限：** `Mail.Send`（委任アクセス許可）

**セキュリティ：**
- ログに認証情報・トークンを出力しない
