# 手数料計算タブ（第1段階）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 労働保険名簿管理システムに「手数料計算タブ」を追加し、年度別に事業所ごとの概算保険料から事務手数料を自動計算、支払方法・支払時期・入金・督促状況を管理できるようにする。

**Architecture:** 既存の `models.py` → `services/` → `ui/` → `ui/dialogs/` → `main_window.py` という層構造をそのまま踏襲する。新規テーブル `annual_fee_rules` / `annual_fee_records` を追加し、`fee_service.py` に計算ロジックとCRUDを実装、`fee_tab.py`（一覧）と `fee_edit_dialog.py`（編集）でUIを構築する。

**Tech Stack:** Python 3.11+ / PyQt6 / SQLAlchemy + SQLite（WAL） / pytest（サービス層のTDD）

## Global Constraints

- 対象環境: 画面解像度1366×768、ウィンドウ幅1280px以内、ダイアログ幅780px以下・高さ600px以下（プロジェクトのCLAUDE.mdより）
- 新規テーブルのみ追加のため `app/database/connection.py` への手動マイグレーションは不要（`Base.metadata.create_all()` が自動作成）
- 既存の `insurance_entries.is_ikkatsu`（継続事業一括認可）と本機能の `is_lump_sum_payment`（保険料一括払い）は別概念。混同しないこと
- 会員区分の名簿上書き・支払時期の自動判定と異なる値への変更は、いずれも理由の入力を必須とする
- 概算保険料合計が0円の場合、会員は5,000円（通常式で自然に成立）、非会員は14,000円（下限5,000円は適用せず加算分のみ）
- 参照設計書: `docs/superpowers/specs/2026-07-18-fee-calculation-tab-design.md`

---

### Task 1: データモデル追加（AnnualFeeRule / AnnualFeeRecord）

**Files:**
- Modify: `app/database/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `AnnualFeeRule`（主キー `fiscal_year`）、`AnnualFeeRecord`（`UniqueConstraint("fiscal_year", "member_id")`）。後続タスクはこれらのカラム名をそのまま使う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_models.py` の末尾に追記：

```python
def test_annual_fee_rule_create(db):
    from app.database.models import AnnualFeeRule
    rule = AnnualFeeRule(fiscal_year=2026, fee_rate=0.05, member_min_fee=5000,
                          non_member_addition=14000, tax_rate=0.10)
    db.add(rule)
    db.commit()
    assert db.get(AnnualFeeRule, 2026).member_min_fee == 5000

def test_annual_fee_record_unique_constraint(db):
    from app.database.models import AnnualFeeRecord
    from sqlalchemy.exc import IntegrityError
    m = Member(member_number="9001", org_name="㈱テスト商事")
    db.add(m)
    db.flush()
    db.add(AnnualFeeRecord(
        fiscal_year=2026, member_id=m.id, is_member_for_fee=True,
        auto_payment_period="2期", final_payment_period="2期",
    ))
    db.commit()
    db.add(AnnualFeeRecord(
        fiscal_year=2026, member_id=m.id, is_member_for_fee=True,
        auto_payment_period="2期", final_payment_period="2期",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_models.py -v -k annual_fee`
Expected: FAIL（`ImportError: cannot import name 'AnnualFeeRule'`）

- [ ] **Step 3: models.py にモデルを追加する**

`app/database/models.py` 冒頭のimportを変更：

```python
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Float,
    Text, ForeignKey, Table, UniqueConstraint,
)
```

ファイル末尾（`SendLog` クラスの後）に追記：

```python
class AnnualFeeRule(Base):
    __tablename__ = "annual_fee_rules"
    fiscal_year = Column(Integer, primary_key=True)
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

    is_member_for_fee = Column(Boolean, nullable=False)
    member_override_reason = Column(Text)

    premium_branch_0 = Column(Integer, nullable=False, default=0)
    premium_branch_2 = Column(Integer, nullable=False, default=0)
    premium_branch_4 = Column(Integer, nullable=False, default=0)
    premium_branch_5 = Column(Integer, nullable=False, default=0)
    premium_branch_6 = Column(Integer, nullable=False, default=0)

    premium_total = Column(Integer, nullable=False, default=0)
    five_percent_amount = Column(Integer, nullable=False, default=0)
    base_fee_amount = Column(Integer, nullable=False, default=0)
    non_member_addition_amount = Column(Integer, nullable=False, default=0)
    fee_without_tax = Column(Integer, nullable=False, default=0)
    tax_amount = Column(Integer, nullable=False, default=0)
    total_amount = Column(Integer, nullable=False, default=0)

    is_lump_sum_payment = Column(Boolean, nullable=False, default=False)
    entrust_start_month = Column(Date)
    auto_payment_period = Column(String)
    final_payment_period = Column(String)
    payment_period_override_reason = Column(Text)
    payment_method = Column(String)

    paid_amount = Column(Integer)
    paid_at = Column(Date)
    reminder_status = Column(String, nullable=False, default="未督促")
    note = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member")
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_models.py -v -k annual_fee`
Expected: PASS（2件）

- [ ] **Step 5: 全体のテストも壊れていないことを確認**

Run: `python -m pytest tests/test_models.py tests/test_connection.py -v`
Expected: PASS（全件）

- [ ] **Step 6: コミット**

```bash
git add app/database/models.py tests/test_models.py
git commit -m "feat: add AnnualFeeRule and AnnualFeeRecord models"
```

---

### Task 2: 手数料計算ロジック（純粋関数 calculate_fee）

**Files:**
- Create: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Consumes: `AnnualFeeRule`（Task 1）
- Produces: `calculate_fee(premiums: dict, is_member: bool, rule: AnnualFeeRule) -> dict`
  戻り値キー: `premium_total, five_percent_amount, base_fee_amount, non_member_addition_amount, fee_without_tax, tax_amount, total_amount`（すべて `int`）。
  `premiums` は `{"branch_0": int, "branch_2": int, "branch_4": int, "branch_5": int, "branch_6": int}`（キー欠損は0円扱い）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` を新規作成：

```python
import pytest
from app.database.models import AnnualFeeRule
from app.services.fee_service import calculate_fee


def _rule(fiscal_year=2026):
    return AnnualFeeRule(
        fiscal_year=fiscal_year, fee_rate=0.05, member_min_fee=5000,
        non_member_addition=14000, tax_rate=0.10,
    )


def test_calculate_fee_member_below_minimum():
    result = calculate_fee({"branch_0": 80000}, True, _rule())
    assert result["premium_total"] == 80000
    assert result["five_percent_amount"] == 4000
    assert result["fee_without_tax"] == 5000
    assert result["tax_amount"] == 500
    assert result["total_amount"] == 5500


def test_calculate_fee_member_above_minimum():
    result = calculate_fee({"branch_0": 200000}, True, _rule())
    assert result["five_percent_amount"] == 10000
    assert result["fee_without_tax"] == 10000
    assert result["total_amount"] == 11000


def test_calculate_fee_non_member_below_minimum():
    result = calculate_fee({"branch_0": 80000}, False, _rule())
    assert result["fee_without_tax"] == 19000
    assert result["tax_amount"] == 1900
    assert result["total_amount"] == 20900


def test_calculate_fee_non_member_above_minimum():
    result = calculate_fee({"branch_0": 200000}, False, _rule())
    assert result["fee_without_tax"] == 24000
    assert result["total_amount"] == 26400


def test_calculate_fee_zero_premium_member():
    result = calculate_fee({}, True, _rule())
    assert result["premium_total"] == 0
    assert result["fee_without_tax"] == 5000
    assert result["total_amount"] == 5500


def test_calculate_fee_zero_premium_non_member():
    result = calculate_fee({}, False, _rule())
    assert result["fee_without_tax"] == 14000
    assert result["tax_amount"] == 1400
    assert result["total_amount"] == 15400


def test_calculate_fee_sums_all_branches():
    premiums = {"branch_0": 10000, "branch_2": 20000, "branch_4": 30000,
                "branch_5": 40000, "branch_6": 100000}
    result = calculate_fee(premiums, True, _rule())
    assert result["premium_total"] == 200000


def test_calculate_fee_rounding_floor():
    # 概算保険料合計 199,999円 → 5%計算額は floor(9999.95) = 9999円
    result = calculate_fee({"branch_0": 199999}, True, _rule())
    assert result["five_percent_amount"] == 9999
    assert result["fee_without_tax"] == 9999
    # 消費税 floor(9999 * 0.10) = 999円
    assert result["tax_amount"] == 999
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.fee_service'`）

- [ ] **Step 3: 最小実装を書く**

`app/services/fee_service.py` を新規作成：

```python
import math
from datetime import date, datetime
from app.database.models import AnnualFeeRule

BRANCH_KEYS = ("branch_0", "branch_2", "branch_4", "branch_5", "branch_6")
PAYMENT_METHODS = ["口座振替", "振込", "持参"]
PAYMENT_PERIODS = ["1期", "2期", "3期", "請求なし"]
REMINDER_STATUSES = ["未督促", "督促済", "再督促予定", "完了"]


def calculate_fee(premiums: dict, is_member: bool, rule: AnnualFeeRule) -> dict:
    """概算保険料から事務手数料を計算する（DBアクセスなしの純粋関数）。"""
    premium_total = sum(premiums.get(k, 0) or 0 for k in BRANCH_KEYS)
    five_percent_amount = math.floor(premium_total * rule.fee_rate)

    if premium_total == 0 and not is_member:
        # 例外ルール: 非会員は下限5,000円を適用せず、加算分14,000円のみ請求する
        base_fee_amount = 0
        non_member_addition_amount = rule.non_member_addition
        fee_without_tax = rule.non_member_addition
    else:
        base_fee_amount = max(five_percent_amount, rule.member_min_fee)
        if is_member:
            non_member_addition_amount = 0
            fee_without_tax = base_fee_amount
        else:
            non_member_addition_amount = rule.non_member_addition
            fee_without_tax = base_fee_amount + rule.non_member_addition

    tax_amount = math.floor(fee_without_tax * rule.tax_rate)
    total_amount = fee_without_tax + tax_amount

    return {
        "premium_total": premium_total,
        "five_percent_amount": five_percent_amount,
        "base_fee_amount": base_fee_amount,
        "non_member_addition_amount": non_member_addition_amount,
        "fee_without_tax": fee_without_tax,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
    }
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（8件）

- [ ] **Step 5: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add calculate_fee pure function for fee calculation"
```

---

### Task 3: 支払時期自動判定ロジック（純粋関数 determine_payment_period）

**Files:**
- Modify: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Produces: `determine_payment_period(fiscal_year: int, is_lump_sum_payment: bool, entrust_start_month: date | None) -> str`
  戻り値は `"1期" | "2期" | "3期" | "請求なし"` のいずれか。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` に追記：

```python
from datetime import date
from app.services.fee_service import determine_payment_period


def test_determine_payment_period_lump_sum_priority():
    # 一括払い かつ 新規委託月（本来3期相当）でも 1期が優先される
    result = determine_payment_period(2026, True, date(2026, 10, 1))
    assert result == "1期"


def test_determine_payment_period_existing_member_default():
    result = determine_payment_period(2026, False, None)
    assert result == "2期"


def test_determine_payment_period_new_entrust_summer():
    result = determine_payment_period(2026, False, date(2026, 6, 1))
    assert result == "2期"


def test_determine_payment_period_new_entrust_autumn():
    result = determine_payment_period(2026, False, date(2026, 10, 1))
    assert result == "3期"


def test_determine_payment_period_new_entrust_winter_no_billing():
    result = determine_payment_period(2026, False, date(2027, 2, 1))
    assert result == "請求なし"


def test_determine_payment_period_old_entrust_defaults_to_2ki():
    # 委託開始が年度範囲(2026-04-01〜2027-03-31)より前 → 既存事業所扱いで2期
    result = determine_payment_period(2026, False, date(2020, 6, 1))
    assert result == "2期"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v -k determine_payment_period`
Expected: FAIL（`ImportError: cannot import name 'determine_payment_period'`）

- [ ] **Step 3: 実装を追加する**

`app/services/fee_service.py` の `calculate_fee` 関数の後に追記：

```python
def determine_payment_period(fiscal_year: int, is_lump_sum_payment: bool,
                              entrust_start_month) -> str:
    """支払時期を自動判定する。優先順位: 一括払い > 新規委託の月判定 > 既存事業所(2期)。"""
    if is_lump_sum_payment:
        return "1期"
    if entrust_start_month is not None:
        fy_start = date(fiscal_year, 4, 1)
        fy_end = date(fiscal_year + 1, 3, 31)
        if fy_start <= entrust_start_month <= fy_end:
            month = entrust_start_month.month
            if 4 <= month <= 8:
                return "2期"
            if 9 <= month <= 12:
                return "3期"
            return "請求なし"
    return "2期"
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（14件）

- [ ] **Step 5: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add determine_payment_period pure function"
```

---

### Task 4: FeeService（年度ルール管理）

**Files:**
- Modify: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Consumes: `AnnualFeeRule`（Task 1）、`get_session`（`app.database.connection`）
- Produces: `FeeService(engine)`、`FeeService.list_years() -> list[int]`（降順）、`FeeService.get_or_create_rule(fiscal_year: int) -> AnnualFeeRule`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` の先頭（既存の `import pytest` の下）に fixture を追加する：

```python
from sqlalchemy import create_engine
from app.database.models import Base, Member
from app.database.connection import get_session
from app.services.fee_service import FeeService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def svc(engine):
    return FeeService(engine)
```

ファイル末尾にテストを追記：

```python
def test_get_or_create_rule_creates_default(svc):
    rule = svc.get_or_create_rule(2026)
    assert rule.fiscal_year == 2026
    assert rule.fee_rate == 0.05
    assert rule.member_min_fee == 5000


def test_get_or_create_rule_returns_existing(svc):
    first = svc.get_or_create_rule(2026)
    with get_session(svc._engine) as session:
        r = session.get(AnnualFeeRule, 2026)
        r.member_min_fee = 6000
    second = svc.get_or_create_rule(2026)
    assert second.member_min_fee == 6000


def test_get_or_create_rule_copies_previous_year(svc):
    with get_session(svc._engine) as session:
        session.add(AnnualFeeRule(fiscal_year=2025, fee_rate=0.05,
                                   member_min_fee=4500, non_member_addition=13000,
                                   tax_rate=0.10))
    rule = svc.get_or_create_rule(2026)
    assert rule.member_min_fee == 4500
    assert rule.non_member_addition == 13000


def test_list_years_descending(svc):
    svc.get_or_create_rule(2025)
    svc.get_or_create_rule(2026)
    svc.get_or_create_rule(2024)
    assert svc.list_years() == [2026, 2025, 2024]
```

`AnnualFeeRule` を使うため、ファイル冒頭のimportに追記：

```python
from app.database.models import Base, Member, AnnualFeeRule
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v -k "get_or_create_rule or list_years"`
Expected: FAIL（`AttributeError: 'FeeService' object has no attribute...` または `NameError: name 'FeeService' is not defined`）

- [ ] **Step 3: 実装を追加する**

`app/services/fee_service.py` の冒頭の import 群を以下のように変更する（`from app.database.connection import get_session` を追加）：

```python
import math
from datetime import date, datetime
from app.database.connection import get_session
from app.database.models import AnnualFeeRule
```

ファイル末尾に追記：

```python
class FeeService:
    def __init__(self, engine):
        self._engine = engine

    def list_years(self) -> list:
        with get_session(self._engine) as session:
            rows = (
                session.query(AnnualFeeRule.fiscal_year)
                .order_by(AnnualFeeRule.fiscal_year.desc())
                .all()
            )
            return [r[0] for r in rows]

    def get_or_create_rule(self, fiscal_year: int) -> AnnualFeeRule:
        with get_session(self._engine) as session:
            rule = session.get(AnnualFeeRule, fiscal_year)
            if rule:
                session.expunge(rule)
                return rule
            prev = (
                session.query(AnnualFeeRule)
                .filter(AnnualFeeRule.fiscal_year < fiscal_year)
                .order_by(AnnualFeeRule.fiscal_year.desc())
                .first()
            )
            if prev:
                rule = AnnualFeeRule(
                    fiscal_year=fiscal_year, fee_rate=prev.fee_rate,
                    member_min_fee=prev.member_min_fee,
                    non_member_addition=prev.non_member_addition,
                    tax_rate=prev.tax_rate,
                )
            else:
                rule = AnnualFeeRule(fiscal_year=fiscal_year)
            session.add(rule)
            session.flush()
            session.expunge(rule)
            return rule
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（18件）

- [ ] **Step 5: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add FeeService rule management (list_years, get_or_create_rule)"
```

---

### Task 5: FeeService.generate_records（対象生成）

**Files:**
- Modify: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Consumes: `Member`（`is_active`, `is_member`, `registered_date`）、`calculate_fee`、`determine_payment_period`、`get_or_create_rule`
- Produces: `FeeService.generate_records(fiscal_year: int) -> int`（追加件数を返す）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` に追記：

```python
from app.database.models import AnnualFeeRecord


def test_generate_records_creates_for_active_members(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=False))
        session.add(Member(member_number="9003", org_name="C社", is_active=False, is_member=True))
    added = svc.generate_records(2026)
    assert added == 2  # 委託中の2件のみ
    with get_session(svc._engine) as session:
        records = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).all()
        assert len(records) == 2


def test_generate_records_skips_existing(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    added_second = svc.generate_records(2026)
    assert added_second == 0


def test_generate_records_copies_is_member_and_computes_zero_fee(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=False))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first()
        assert record.is_member_for_fee is False
        assert record.premium_total == 0
        assert record.fee_without_tax == 14000  # 非会員・0円例外ルール
        assert record.auto_payment_period == "2期"  # 委託開始月未設定は既存扱い
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v -k generate_records`
Expected: FAIL（`AttributeError: 'FeeService' object has no attribute 'generate_records'`）

- [ ] **Step 3: 実装を追加する**

`app/services/fee_service.py` の `FeeService` クラス内、`get_or_create_rule` メソッドの後に追記：

```python
    def generate_records(self, fiscal_year: int) -> int:
        """名簿の委託中事業所から、当該年度にまだレコードがない分だけ追加する。"""
        rule = self.get_or_create_rule(fiscal_year)
        zero_premiums = {k: 0 for k in BRANCH_KEYS}
        with get_session(self._engine) as session:
            existing_ids = {
                r[0] for r in session.query(AnnualFeeRecord.member_id)
                .filter(AnnualFeeRecord.fiscal_year == fiscal_year).all()
            }
            members = session.query(Member).filter(Member.is_active == True).all()
            added = 0
            for m in members:
                if m.id in existing_ids:
                    continue
                calc = calculate_fee(zero_premiums, m.is_member, rule)
                period = determine_payment_period(fiscal_year, False, m.registered_date)
                session.add(AnnualFeeRecord(
                    fiscal_year=fiscal_year,
                    member_id=m.id,
                    is_member_for_fee=m.is_member,
                    entrust_start_month=m.registered_date,
                    is_lump_sum_payment=False,
                    auto_payment_period=period,
                    final_payment_period=period,
                    reminder_status="未督促",
                    **calc,
                ))
                added += 1
            return added
```

`Member` を使うため、ファイル冒頭のimportに追記：

```python
from app.database.models import AnnualFeeRule, AnnualFeeRecord, Member
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（21件）

- [ ] **Step 5: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add FeeService.generate_records for target generation"
```

---

### Task 6: FeeService.get / update / recalculate_all

**Files:**
- Modify: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Produces:
  - `FeeService.get(record_id: int) -> AnnualFeeRecord | None`
  - `FeeService.update(record_id: int, data: dict) -> AnnualFeeRecord`（`ValueError` を理由未入力時に送出）
  - `FeeService.recalculate_all(fiscal_year: int) -> int`（再計算件数を返す）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` に追記：

```python
def test_update_recalculates_fee(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    updated = svc.update(record_id, {
        "premium_branch_0": 200000,
        "is_member_for_fee": True,
        "is_lump_sum_payment": False,
        "entrust_start_month": None,
        "payment_method": "振込",
    })
    assert updated.premium_total == 200000
    assert updated.fee_without_tax == 10000
    assert updated.total_amount == 11000


def test_update_requires_reason_for_member_override(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    with pytest.raises(ValueError):
        svc.update(record_id, {"is_member_for_fee": False})  # 理由なし → エラー

    updated = svc.update(record_id, {
        "is_member_for_fee": False, "member_override_reason": "特例対応のため",
    })
    assert updated.is_member_for_fee is False


def test_update_requires_reason_for_payment_period_override(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    with pytest.raises(ValueError):
        svc.update(record_id, {"final_payment_period": "1期"})  # 自動判定(2期)と異なるが理由なし

    updated = svc.update(record_id, {
        "final_payment_period": "1期", "payment_period_override_reason": "事業所希望のため",
    })
    assert updated.final_payment_period == "1期"


def test_update_sets_reminder_completed_when_paid(svc):
    from datetime import date
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id

    updated = svc.update(record_id, {"paid_amount": 5500, "paid_at": date(2026, 8, 1)})
    assert updated.reminder_status == "完了"


def test_recalculate_all_applies_new_rule(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id
    svc.update(record_id, {"premium_branch_0": 80000})

    with get_session(svc._engine) as session:
        rule = session.get(AnnualFeeRule, 2026)
        rule.member_min_fee = 6000

    count = svc.recalculate_all(2026)
    assert count == 1
    with get_session(svc._engine) as session:
        record = session.get(AnnualFeeRecord, record_id)
        assert record.fee_without_tax == 6000
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v -k "update or recalculate"`
Expected: FAIL（`AttributeError: 'FeeService' object has no attribute 'update'`）

- [ ] **Step 3: 実装を追加する**

`app/services/fee_service.py` の `generate_records` メソッドの後に追記：

```python
    _UPDATABLE_FIELDS = (
        "is_member_for_fee", "member_override_reason",
        "premium_branch_0", "premium_branch_2", "premium_branch_4",
        "premium_branch_5", "premium_branch_6",
        "is_lump_sum_payment", "entrust_start_month",
        "final_payment_period", "payment_period_override_reason",
        "payment_method", "paid_amount", "paid_at",
        "reminder_status", "note",
    )

    def get(self, record_id: int):
        with get_session(self._engine) as session:
            record = session.get(AnnualFeeRecord, record_id)
            if record:
                _ = record.member
                session.expunge_all()
            return record

    def update(self, record_id: int, data: dict) -> AnnualFeeRecord:
        with get_session(self._engine) as session:
            record = session.get(AnnualFeeRecord, record_id)
            if not record:
                raise ValueError(f"手数料レコードID {record_id} が見つかりません。")
            member = session.get(Member, record.member_id)

            new_is_member = data.get("is_member_for_fee", record.is_member_for_fee)
            new_reason = data.get("member_override_reason", record.member_override_reason)
            if new_is_member != member.is_member and not new_reason:
                raise ValueError("会員区分を名簿と異なる値へ変更する場合は理由の入力が必須です。")

            for field in self._UPDATABLE_FIELDS:
                if field in data:
                    setattr(record, field, data[field])

            rule = session.get(AnnualFeeRule, record.fiscal_year)
            premiums = {
                "branch_0": record.premium_branch_0, "branch_2": record.premium_branch_2,
                "branch_4": record.premium_branch_4, "branch_5": record.premium_branch_5,
                "branch_6": record.premium_branch_6,
            }
            calc = calculate_fee(premiums, record.is_member_for_fee, rule)
            for k, v in calc.items():
                setattr(record, k, v)

            record.auto_payment_period = determine_payment_period(
                record.fiscal_year, record.is_lump_sum_payment, record.entrust_start_month)
            if "final_payment_period" not in data:
                record.final_payment_period = record.auto_payment_period
            elif record.final_payment_period != record.auto_payment_period \
                    and not record.payment_period_override_reason:
                raise ValueError("支払時期を自動判定と異なる値へ変更する場合は理由の入力が必須です。")

            if "paid_at" in data and data["paid_at"] and "reminder_status" not in data:
                record.reminder_status = "完了"

            record.updated_at = datetime.now()
            session.flush()
            _ = record.member
            session.expunge_all()
            return record

    def recalculate_all(self, fiscal_year: int) -> int:
        rule = self.get_or_create_rule(fiscal_year)
        with get_session(self._engine) as session:
            records = session.query(AnnualFeeRecord).filter(
                AnnualFeeRecord.fiscal_year == fiscal_year).all()
            for record in records:
                premiums = {
                    "branch_0": record.premium_branch_0, "branch_2": record.premium_branch_2,
                    "branch_4": record.premium_branch_4, "branch_5": record.premium_branch_5,
                    "branch_6": record.premium_branch_6,
                }
                calc = calculate_fee(premiums, record.is_member_for_fee, rule)
                for k, v in calc.items():
                    setattr(record, k, v)
                record.auto_payment_period = determine_payment_period(
                    fiscal_year, record.is_lump_sum_payment, record.entrust_start_month)
                if not record.payment_period_override_reason:
                    record.final_payment_period = record.auto_payment_period
                record.updated_at = datetime.now()
            return len(records)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（26件）

- [ ] **Step 5: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add FeeService.get/update/recalculate_all with validation rules"
```

---

### Task 7: FeeService.search（一覧検索・フィルタ）

**Files:**
- Modify: `app/services/fee_service.py`
- Test: `tests/test_fee_service.py`

**Interfaces:**
- Produces: `FeeService.search(fiscal_year: int, keyword: str = "", status_filter: str | None = None) -> list[AnnualFeeRecord]`
  `status_filter` は `None | "未入力" | "未入金" | "入金済" | "1期" | "2期" | "3期" | "請求なし" | "非会員" | "督促中"`。各レコードの `.member` はロード済み。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_fee_service.py` に追記：

```python
def test_search_by_keyword(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="㈱テスト商事", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="△△建設", is_active=True, is_member=True))
    svc.generate_records(2026)
    results = svc.search(2026, keyword="テスト")
    assert len(results) == 1
    assert results[0].member.org_name == "㈱テスト商事"


def test_search_filter_non_member(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=False))
    svc.generate_records(2026)
    results = svc.search(2026, status_filter="非会員")
    assert len(results) == 1
    assert results[0].member.org_name == "B社"


def test_search_filter_unpaid_excludes_no_billing(svc):
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
        session.add(Member(member_number="9002", org_name="B社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        records = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).all()
        records[0].final_payment_period = "請求なし"
        records[1].final_payment_period = "2期"
    results = svc.search(2026, status_filter="未入金")
    assert len(results) == 1
    assert results[0].final_payment_period == "2期"


def test_search_filter_paid(svc):
    from datetime import date
    with get_session(svc._engine) as session:
        session.add(Member(member_number="9001", org_name="A社", is_active=True, is_member=True))
    svc.generate_records(2026)
    with get_session(svc._engine) as session:
        record_id = session.query(AnnualFeeRecord).filter_by(fiscal_year=2026).first().id
    svc.update(record_id, {"paid_amount": 5500, "paid_at": date(2026, 8, 1)})
    results = svc.search(2026, status_filter="入金済")
    assert len(results) == 1
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `python -m pytest tests/test_fee_service.py -v -k search`
Expected: FAIL（`AttributeError: 'FeeService' object has no attribute 'search'`）

- [ ] **Step 3: 実装を追加する**

`app/services/fee_service.py` の `recalculate_all` メソッドの後に追記：

```python
    def search(self, fiscal_year: int, keyword: str = "", status_filter: str = None) -> list:
        with get_session(self._engine) as session:
            q = (
                session.query(AnnualFeeRecord)
                .join(Member, AnnualFeeRecord.member_id == Member.id)
                .filter(AnnualFeeRecord.fiscal_year == fiscal_year)
            )
            if keyword:
                kw = f"%{keyword}%"
                cond = Member.org_name.like(kw) | Member.member_number.like(kw)
                if keyword.isdigit():
                    cond = cond | (Member.company_code == int(keyword))
                q = q.filter(cond)

            if status_filter == "未入力":
                q = q.filter(AnnualFeeRecord.premium_total == 0)
            elif status_filter == "未入金":
                q = q.filter(
                    AnnualFeeRecord.paid_at.is_(None),
                    AnnualFeeRecord.final_payment_period != "請求なし",
                )
            elif status_filter == "入金済":
                q = q.filter(AnnualFeeRecord.paid_at.isnot(None))
            elif status_filter in ("1期", "2期", "3期", "請求なし"):
                q = q.filter(AnnualFeeRecord.final_payment_period == status_filter)
            elif status_filter == "非会員":
                q = q.filter(AnnualFeeRecord.is_member_for_fee == False)
            elif status_filter == "督促中":
                q = q.filter(AnnualFeeRecord.reminder_status.in_(["督促済", "再督促予定"]))

            records = q.order_by(Member.member_number).all()
            for r in records:
                _ = r.member
            session.expunge_all()
            return records
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `python -m pytest tests/test_fee_service.py -v`
Expected: PASS（30件）

- [ ] **Step 5: 全サービステストを通しで実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（既存分含めすべて）

- [ ] **Step 6: コミット**

```bash
git add app/services/fee_service.py tests/test_fee_service.py
git commit -m "feat: add FeeService.search with keyword and status filters"
```

---

### Task 8: 編集ダイアログ（fee_edit_dialog.py）

**Files:**
- Create: `app/ui/dialogs/fee_edit_dialog.py`

**Interfaces:**
- Consumes: `FeeService`（Task 4-7）, `MemberService`, `INS_TYPES`（`app.services.member_service`）, `calculate_fee`, `determine_payment_period`
- Produces: `FeeEditDialog(engine, record_id: int, parent=None)`。`dlg.saved: bool` を公開し、`dlg.exec()` で開く（`QDialog.exec()` の戻り値が真の場合に呼び出し側が一覧を再読込する）。

このタスクはUIのため既存プロジェクトの慣例（`member_edit_dialog.py` 等)に合わせ、自動テストではなく手動確認で検証する（プロジェクトに `pytest-qt` は依存として存在するが、既存UIコードにも自動テストは書かれていない）。

- [ ] **Step 1: ダイアログを実装する**

`app/ui/dialogs/fee_edit_dialog.py` を新規作成：

```python
# app/ui/dialogs/fee_edit_dialog.py
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QWidget,
    QLabel, QComboBox, QCheckBox, QLineEdit, QDateEdit, QTextEdit,
    QPushButton, QGroupBox, QMessageBox,
)
from PyQt6.QtCore import QDate
from app.services.fee_service import (
    FeeService, calculate_fee, determine_payment_period,
    PAYMENT_METHODS, PAYMENT_PERIODS, REMINDER_STATUSES,
)
from app.services.member_service import MemberService, INS_TYPES

BRANCH_FIELD = {
    "ippan": "premium_branch_0", "kensetsu_koyou": "premium_branch_2",
    "ringyo": "premium_branch_4", "kensetsu_genba": "premium_branch_5",
    "kensetsu_jimusho": "premium_branch_6",
}
BRANCH_LABEL = {
    "ippan": "枝番0（一般・労災＆雇用）", "kensetsu_koyou": "枝番2（建設業・他雇用）",
    "ringyo": "枝番4（林業・労災）", "kensetsu_genba": "枝番5（建設業・現場）",
    "kensetsu_jimusho": "枝番6（建設業・事務所）",
}


def _make_digit_handler(field):
    def _handler(text):
        converted = "".join(c for c in text if c.isdigit())
        if converted != text:
            field.blockSignals(True)
            field.setText(converted)
            field.setCursorPosition(len(converted))
            field.blockSignals(False)
    return _handler


class FeeEditDialog(QDialog):
    def __init__(self, engine, record_id: int, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._record_id = record_id
        self._svc = FeeService(engine)
        self._member_svc = MemberService(engine)
        self.saved = False

        self._record = self._svc.get(record_id)
        if self._record is None:
            raise ValueError(f"手数料レコードID {record_id} が見つかりません。")
        self._member = self._member_svc.get(self._record.member_id)
        self.setWindowTitle(f"手数料計算 — {self._member.org_name}")
        self.setMinimumWidth(700)
        self.resize(700, 580)
        self._build_ui()
        self._load()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)

        member_group = QGroupBox("会員区分")
        mfl = QFormLayout(member_group)
        mfl.addRow(QLabel(f"名簿の会員区分：{'会員' if self._member.is_member else '非会員'}"))
        self._f_override = QCheckBox("名簿と異なる区分に上書きする")
        self._f_is_member = QComboBox()
        self._f_is_member.addItem("会員", True)
        self._f_is_member.addItem("非会員", False)
        self._f_is_member.setEnabled(False)
        self._f_override_reason = QLineEdit()
        self._f_override_reason.setEnabled(False)
        self._f_override.toggled.connect(self._f_is_member.setEnabled)
        self._f_override.toggled.connect(self._f_override_reason.setEnabled)
        self._f_override.toggled.connect(self._recalculate)
        self._f_is_member.currentIndexChanged.connect(self._recalculate)
        mfl.addRow(self._f_override)
        mfl.addRow("上書き区分", self._f_is_member)
        mfl.addRow("上書き理由", self._f_override_reason)
        form_layout.addWidget(member_group)

        premium_group = QGroupBox("枝番別概算保険料（空欄は0円）")
        pfl = QFormLayout(premium_group)
        self._premium_fields = {}
        member_ins_types = {e.ins_type for e in self._member.insurance_entries}
        for ins_type in INS_TYPES:
            edit = QLineEdit()
            edit.setEnabled(ins_type in member_ins_types)
            edit.textChanged.connect(_make_digit_handler(edit))
            edit.textChanged.connect(self._recalculate)
            pfl.addRow(BRANCH_LABEL[ins_type], edit)
            self._premium_fields[ins_type] = edit
        form_layout.addWidget(premium_group)

        result_group = QGroupBox("計算結果（自動計算・編集不可）")
        rfl = QFormLayout(result_group)
        self._r_premium_total = QLabel("0円")
        self._r_five_percent = QLabel("0円")
        self._r_fee_without_tax = QLabel("0円")
        self._r_tax = QLabel("0円")
        self._r_total = QLabel("0円")
        rfl.addRow("概算保険料合計", self._r_premium_total)
        rfl.addRow("5%計算額", self._r_five_percent)
        rfl.addRow("税抜手数料", self._r_fee_without_tax)
        rfl.addRow("消費税", self._r_tax)
        rfl.addRow("請求合計", self._r_total)
        form_layout.addWidget(result_group)

        payment_group = QGroupBox("支払時期・支払方法")
        pyfl = QFormLayout(payment_group)
        self._f_lump_sum = QCheckBox("保険料を一括で支払う事業所")
        self._f_lump_sum.toggled.connect(self._recalculate)
        self._f_entrust_month = QDateEdit()
        self._f_entrust_month.setCalendarPopup(True)
        self._f_entrust_month.setDisplayFormat("yyyy-MM-dd")
        self._f_entrust_month.dateChanged.connect(self._recalculate)
        self._r_auto_period = QLabel("-")
        self._f_final_period = QComboBox()
        self._f_final_period.addItems(PAYMENT_PERIODS)
        self._f_period_reason = QLineEdit()
        self._f_period_reason.setPlaceholderText("自動判定と異なる場合は必須")
        self._f_payment_method = QComboBox()
        self._f_payment_method.addItems(PAYMENT_METHODS)
        pyfl.addRow(self._f_lump_sum)
        pyfl.addRow("委託開始年月", self._f_entrust_month)
        pyfl.addRow("自動判定支払時期", self._r_auto_period)
        pyfl.addRow("確定支払時期", self._f_final_period)
        pyfl.addRow("変更理由", self._f_period_reason)
        pyfl.addRow("支払方法", self._f_payment_method)
        form_layout.addWidget(payment_group)

        pay_group = QGroupBox("入金・督促")
        payfl = QFormLayout(pay_group)
        self._f_paid_amount = QLineEdit()
        self._f_paid_amount.textChanged.connect(_make_digit_handler(self._f_paid_amount))
        self._f_has_paid = QCheckBox("入金あり")
        self._f_paid_at = QDateEdit(QDate.currentDate())
        self._f_paid_at.setCalendarPopup(True)
        self._f_paid_at.setEnabled(False)
        self._f_has_paid.toggled.connect(self._f_paid_at.setEnabled)
        self._f_reminder_status = QComboBox()
        self._f_reminder_status.addItems(REMINDER_STATUSES)
        self._f_note = QTextEdit()
        self._f_note.setFixedHeight(60)
        payfl.addRow("入金額", self._f_paid_amount)
        payfl.addRow(self._f_has_paid)
        payfl.addRow("入金日", self._f_paid_at)
        payfl.addRow("督促状況", self._f_reminder_status)
        payfl.addRow("備考", self._f_note)
        form_layout.addWidget(pay_group)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        main_layout.addLayout(btn_row)

    def _load(self):
        r = self._record
        if r.is_member_for_fee != self._member.is_member:
            self._f_override.setChecked(True)
        idx = self._f_is_member.findData(r.is_member_for_fee)
        self._f_is_member.setCurrentIndex(idx if idx >= 0 else 0)
        self._f_override_reason.setText(r.member_override_reason or "")

        for ins_type, field in self._premium_fields.items():
            value = getattr(r, BRANCH_FIELD[ins_type])
            field.setText(str(value) if value else "")

        self._f_lump_sum.setChecked(r.is_lump_sum_payment)
        if r.entrust_start_month:
            self._f_entrust_month.setDate(QDate(
                r.entrust_start_month.year, r.entrust_start_month.month,
                r.entrust_start_month.day))
        idx = self._f_final_period.findText(r.final_payment_period or "2期")
        self._f_final_period.setCurrentIndex(idx if idx >= 0 else 1)
        self._f_period_reason.setText(r.payment_period_override_reason or "")
        idx = self._f_payment_method.findText(r.payment_method or "")
        if idx >= 0:
            self._f_payment_method.setCurrentIndex(idx)

        self._f_paid_amount.setText(str(r.paid_amount) if r.paid_amount else "")
        if r.paid_at:
            self._f_has_paid.setChecked(True)
            self._f_paid_at.setDate(QDate(r.paid_at.year, r.paid_at.month, r.paid_at.day))
        idx = self._f_reminder_status.findText(r.reminder_status or "未督促")
        self._f_reminder_status.setCurrentIndex(idx if idx >= 0 else 0)
        self._f_note.setPlainText(r.note or "")

        self._recalculate()

    def _current_premiums(self) -> dict:
        result = {}
        for ins_type, field in self._premium_fields.items():
            text = field.text().strip()
            key = BRANCH_FIELD[ins_type].replace("premium_", "")
            result[key] = int(text) if text else 0
        return result

    def _recalculate(self):
        rule = self._svc.get_or_create_rule(self._record.fiscal_year)
        is_member = self._f_is_member.currentData() if self._f_override.isChecked() \
            else self._member.is_member
        calc = calculate_fee(self._current_premiums(), is_member, rule)
        self._r_premium_total.setText(f"{calc['premium_total']:,}円")
        self._r_five_percent.setText(f"{calc['five_percent_amount']:,}円")
        self._r_fee_without_tax.setText(f"{calc['fee_without_tax']:,}円")
        self._r_tax.setText(f"{calc['tax_amount']:,}円")
        self._r_total.setText(f"{calc['total_amount']:,}円")

        qd = self._f_entrust_month.date()
        entrust = date(qd.year(), qd.month(), qd.day())
        auto_period = determine_payment_period(
            self._record.fiscal_year, self._f_lump_sum.isChecked(), entrust)
        self._r_auto_period.setText(auto_period)

    def _on_save(self):
        is_member = self._f_is_member.currentData() if self._f_override.isChecked() \
            else self._member.is_member
        override_reason = self._f_override_reason.text().strip()
        if self._f_override.isChecked() and not override_reason:
            QMessageBox.warning(self, "入力エラー", "会員区分の上書き理由を入力してください。")
            return

        qd = self._f_entrust_month.date()
        entrust = date(qd.year(), qd.month(), qd.day())

        paid_amount_text = self._f_paid_amount.text().strip()
        paid_amount = int(paid_amount_text) if paid_amount_text else None
        paid_at = None
        if self._f_has_paid.isChecked():
            qd2 = self._f_paid_at.date()
            paid_at = date(qd2.year(), qd2.month(), qd2.day())

        premiums = self._current_premiums()
        data = {
            "is_member_for_fee": is_member,
            "member_override_reason": override_reason if self._f_override.isChecked() else None,
            "premium_branch_0": premiums["branch_0"],
            "premium_branch_2": premiums["branch_2"],
            "premium_branch_4": premiums["branch_4"],
            "premium_branch_5": premiums["branch_5"],
            "premium_branch_6": premiums["branch_6"],
            "is_lump_sum_payment": self._f_lump_sum.isChecked(),
            "entrust_start_month": entrust,
            "final_payment_period": self._f_final_period.currentText(),
            "payment_period_override_reason": self._f_period_reason.text().strip(),
            "payment_method": self._f_payment_method.currentText(),
            "paid_amount": paid_amount,
            "paid_at": paid_at,
            "reminder_status": self._f_reminder_status.currentText(),
            "note": self._f_note.toPlainText(),
        }
        try:
            self._svc.update(self._record_id, data)
            self.saved = True
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", str(e))
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
```

`fee_service.py` から `PAYMENT_METHODS` / `PAYMENT_PERIODS` / `REMINDER_STATUSES` をインポートしているため、Task 2 で定義済みのモジュール定数がそのまま使える（Task 2 の Step 3 で追加済み）。

- [ ] **Step 2: 手動確認**

以下のコマンドでアプリを起動し、動作を確認する（実行前提として Task 9・10 でタブに組み込まれている必要があるため、このステップは Task 10 完了後にまとめて実施してもよい）。

```bash
python main.py
```

確認項目：
1. 手数料計算タブから対象事業所をダブルクリックしてダイアログが開く
2. 概算保険料を入力すると計算結果がリアルタイムに更新される
3. 事業所が保有しない枝番の入力欄が無効化されている
4. 会員区分を上書きすると理由未入力で保存エラーになる
5. 保存後、一覧に反映される

- [ ] **Step 3: コミット**

```bash
git add app/ui/dialogs/fee_edit_dialog.py
git commit -m "feat: add FeeEditDialog for editing fee records"
```

---

### Task 9: 一覧タブ（fee_tab.py）

**Files:**
- Create: `app/ui/fee_tab.py`

**Interfaces:**
- Consumes: `FeeService`（Task 4-7）、`FeeEditDialog`（Task 8）
- Produces: `FeeTab(engine, config, config_path, parent=None)`。`main_window.py` から `QTabWidget.addTab()` で追加する。`FeeTab._refresh()` を公開（タブ切替時のリフレッシュ用）。

- [ ] **Step 1: タブを実装する**

`app/ui/fee_tab.py` を新規作成：

```python
# app/ui/fee_tab.py
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QLabel, QMessageBox, QInputDialog,
)
from PyQt6.QtCore import Qt
from app.services.fee_service import FeeService
from app.ui.dialogs.fee_edit_dialog import FeeEditDialog

FILTERS = ["すべて", "未入力", "未入金", "入金済", "1期", "2期", "3期", "請求なし", "非会員", "督促中"]
COLS = ["管理No.", "会員No.", "事業所名", "会員区分", "概算保険料合計", "請求合計",
        "支払時期", "支払方法", "入金額", "入金日", "督促状況"]


class FeeTab(QWidget):
    def __init__(self, engine, config, config_path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = FeeService(engine)
        self._build_ui()
        self._refresh_years()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("年度："))
        self._year_combo = QComboBox()
        self._year_combo.currentIndexChanged.connect(self._refresh)
        top_row.addWidget(self._year_combo)
        add_year_btn = QPushButton("新年度追加")
        add_year_btn.clicked.connect(self._on_add_year)
        top_row.addWidget(add_year_btn)
        gen_btn = QPushButton("対象生成")
        gen_btn.clicked.connect(self._on_generate)
        top_row.addWidget(gen_btn)
        recalc_btn = QPushButton("再計算")
        recalc_btn.clicked.connect(self._on_recalculate)
        top_row.addWidget(recalc_btn)
        top_row.addStretch()
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
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)

    def _current_fiscal_year(self):
        data = self._year_combo.currentData()
        return int(data) if data is not None else None

    def _refresh_years(self):
        years = self._svc.list_years()
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        for y in years:
            self._year_combo.addItem(f"{y}年度", y)
        self._year_combo.blockSignals(False)
        self._refresh()

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
                "会員" if r.is_member_for_fee else "非会員",
                f"{r.premium_total:,}",
                f"{r.total_amount:,}",
                r.final_payment_period or "",
                r.payment_method or "",
                f"{r.paid_amount:,}" if r.paid_amount else "",
                r.paid_at.strftime("%Y-%m-%d") if r.paid_at else "",
                r.reminder_status or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, r.id)
                self._table.setItem(row, col, item)

    def _on_row_double_clicked(self, index):
        item = self._table.item(index.row(), 0)
        if not item:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        dlg = FeeEditDialog(self._engine, record_id, parent=self)
        if dlg.exec():
            self._refresh()

    def _on_add_year(self):
        year, ok = QInputDialog.getInt(
            self, "新年度追加", "西暦年度を入力してください（例：2026）",
            datetime.now().year, 2000, 2100)
        if not ok:
            return
        self._svc.get_or_create_rule(year)
        self._refresh_years()
        idx = self._year_combo.findData(year)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)

    def _on_generate(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            QMessageBox.warning(self, "確認", "先に年度を選択または追加してください。")
            return
        added = self._svc.generate_records(fiscal_year)
        QMessageBox.information(self, "対象生成", f"{added}件のレコードを追加しました。")
        self._refresh()

    def _on_recalculate(self):
        fiscal_year = self._current_fiscal_year()
        if fiscal_year is None:
            return
        count = self._svc.recalculate_all(fiscal_year)
        QMessageBox.information(self, "再計算", f"{count}件を再計算しました。")
        self._refresh()
```

- [ ] **Step 2: 手動確認**

Task 10 完了後、`python main.py` でアプリを起動し以下を確認する：
1. タブに「手数料計算」が表示される
2. 年度が1件も無い状態で「新年度追加」→ 西暦年を入力 → プルダウンに追加される
3. 「対象生成」で委託中事業所の件数分レコードが追加される（2回目実行時は0件）
4. 検索・フィルタが一覧に反映される
5. 「再計算」でメッセージが表示され、一覧が更新される

- [ ] **Step 3: コミット**

```bash
git add app/ui/fee_tab.py
git commit -m "feat: add FeeTab list view with search, filter, and generate/recalculate actions"
```

---

### Task 10: main_window.py への統合

**Files:**
- Modify: `app/ui/main_window.py`

**Interfaces:**
- Consumes: `FeeTab`（Task 9）

- [ ] **Step 1: タブを追加する**

`app/ui/main_window.py` の import 群に追記（`from app.ui.withdrawn_tab import WithdrawnTab` の直後）：

```python
from app.ui.fee_tab import FeeTab
```

`_build_ui` メソッド内、`self._tabs.addTab(self._withdrawn_tab, "委託解除済")` の直後に追記：

```python
        self._fee_tab = FeeTab(self._engine, self._config, self._config_path)
        self._tabs.addTab(self._fee_tab, "手数料計算")
```

`_on_tab_changed` メソッドを以下のように変更（`elif widget is self._member_tab:` の後に分岐を追加）：

```python
    def _on_tab_changed(self, index: int):
        widget = self._tabs.widget(index)
        if widget is self._withdrawn_tab:
            self._withdrawn_tab._refresh()
        elif widget is self._member_tab:
            self._member_tab._refresh()
            self._member_tab.refresh_categories()
        elif widget is self._fee_tab:
            self._fee_tab._refresh()
```

- [ ] **Step 2: 起動確認**

Run: `python main.py`
Expected: エラーなく起動し、タブバーに「名簿」「委託解除済」「手数料計算」「設定」が順に表示される。「手数料計算」タブをクリックし、Task 8・9 の手動確認項目（ダイアログの開閉、対象生成、検索・フィルタ、再計算）を通しで実施する。

- [ ] **Step 3: 全自動テストを実行**

Run: `python -m pytest tests/ -v`
Expected: PASS（全件。UIファイルには自動テストがないため対象外）

- [ ] **Step 4: コミット**

```bash
git add app/ui/main_window.py
git commit -m "feat: register FeeTab in main window"
```

---

## 完了後の確認事項

- 第1段階の範囲（手数料計算タブのコア機能）が完成し、Excel出力・年度更新タブ・Excel取込・対応履歴連携は未実装のまま
- `docs/superpowers/specs/2026-07-18-fee-calculation-tab-design.md` の8章「未確定事項」は第1段階の実装には影響しないため、そのまま残す
