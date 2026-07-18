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
