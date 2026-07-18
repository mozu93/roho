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
