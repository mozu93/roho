import math
from datetime import date, datetime
from app.database.connection import get_session
from app.database.models import AnnualFeeRule, AnnualFeeRecord, Member

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
