from datetime import date, datetime
from app.database.connection import get_session
from app.database.models import AnnualRenewal, AnnualRenewalItem, Member

SUBMISSION_STATUSES = ["未提出", "提出済", "不備あり", "対象外"]
OVERALL_STATUSES = ["未提出", "一部提出", "提出済", "不備あり", "完了"]


def compute_overall_status(item_statuses: list) -> str:
    """対象外を除く枝番別提出状況から全体状況を自動判定する（DBアクセスなしの純粋関数）。
    優先順位: いずれかが不備あり > 全て提出済 > 全て未提出 > それ以外(一部提出)。"""
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
