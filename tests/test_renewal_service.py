import pytest
from app.services.renewal_service import compute_overall_status


def test_compute_overall_status_all_submitted():
    assert compute_overall_status(["提出済", "提出済"]) == "提出済"


def test_compute_overall_status_all_not_submitted():
    assert compute_overall_status(["未提出", "未提出"]) == "未提出"


def test_compute_overall_status_mixed_is_partial():
    assert compute_overall_status(["提出済", "未提出"]) == "一部提出"


def test_compute_overall_status_deficiency_takes_priority():
    assert compute_overall_status(["提出済", "不備あり"]) == "不備あり"


def test_compute_overall_status_excludes_not_applicable():
    assert compute_overall_status(["提出済", "対象外"]) == "提出済"


def test_compute_overall_status_empty_list_is_not_submitted():
    assert compute_overall_status([]) == "未提出"


def test_compute_overall_status_all_not_applicable_is_not_submitted():
    assert compute_overall_status(["対象外", "対象外"]) == "未提出"
