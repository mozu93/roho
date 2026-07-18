from datetime import date, datetime
from app.database.connection import get_session
from app.database.models import AnnualRenewal, AnnualRenewalItem, Member, InsuranceEntry

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


class RenewalService:
    def __init__(self, engine):
        self._engine = engine

    def list_years(self) -> list:
        with get_session(self._engine) as session:
            rows = (
                session.query(AnnualRenewal.fiscal_year)
                .distinct()
                .order_by(AnnualRenewal.fiscal_year.desc())
                .all()
            )
            return [r[0] for r in rows]

    def generate_records(self, fiscal_year: int) -> int:
        """名簿の委託中事業所から、当該年度にまだレコードがない分だけ追加する。
        保有する枝番ごとに未提出のitemを作成する。"""
        with get_session(self._engine) as session:
            existing_ids = {
                r[0] for r in session.query(AnnualRenewal.member_id)
                .filter(AnnualRenewal.fiscal_year == fiscal_year).all()
            }
            members = session.query(Member).filter(Member.is_active == True).all()
            added = 0
            for m in members:
                if m.id in existing_ids:
                    continue
                renewal = AnnualRenewal(
                    fiscal_year=fiscal_year,
                    member_id=m.id,
                    overall_status="未提出",
                    overall_status_manual=False,
                )
                session.add(renewal)
                session.flush()
                branch_types = {e.ins_type for e in m.insurance_entries}
                for branch_type in branch_types:
                    session.add(AnnualRenewalItem(
                        annual_renewal_id=renewal.id,
                        branch_type=branch_type,
                        submission_status="未提出",
                    ))
                added += 1
            return added

    def get(self, renewal_id: int):
        with get_session(self._engine) as session:
            renewal = session.get(AnnualRenewal, renewal_id)
            if not renewal:
                return None
            member = session.get(Member, renewal.member_id)
            existing_types = {i.branch_type for i in renewal.items}
            member_types = {e.ins_type for e in member.insurance_entries}
            missing = member_types - existing_types
            if missing:
                for branch_type in missing:
                    session.add(AnnualRenewalItem(
                        annual_renewal_id=renewal.id,
                        branch_type=branch_type,
                        submission_status="未提出",
                    ))
                session.flush()
                session.refresh(renewal, attribute_names=["items"])
            _ = renewal.member
            _ = renewal.items
            session.expunge_all()
            return renewal

    def update(self, renewal_id: int, items_data: dict, renewal_data: dict) -> AnnualRenewal:
        with get_session(self._engine) as session:
            renewal = session.get(AnnualRenewal, renewal_id)
            if not renewal:
                raise ValueError(f"年度更新レコードID {renewal_id} が見つかりません。")

            for item in renewal.items:
                data = items_data.get(item.branch_type)
                if not data:
                    continue
                new_status = data["submission_status"]
                confirmed_at = data.get("confirmed_at")
                if confirmed_at is None and new_status == "提出済":
                    confirmed_at = date.today()
                item.submission_status = new_status
                item.confirmed_at = confirmed_at

            manual = renewal_data.get("overall_status_manual", False)
            renewal.overall_status_manual = manual
            if manual:
                renewal.overall_status = renewal_data["overall_status"]
            else:
                renewal.overall_status = compute_overall_status(
                    [i.submission_status for i in renewal.items])

            renewal.last_contacted_at = renewal_data.get("last_contacted_at")
            renewal.note = renewal_data.get("note", "")
            renewal.updated_at = datetime.now()
            session.flush()
            _ = renewal.member
            _ = renewal.items
            session.expunge_all()
            return renewal

    def search(self, fiscal_year: int, keyword: str = "", status_filter: str = None) -> list:
        with get_session(self._engine) as session:
            q = (
                session.query(AnnualRenewal)
                .join(Member, AnnualRenewal.member_id == Member.id)
                .filter(AnnualRenewal.fiscal_year == fiscal_year)
            )
            if keyword:
                kw = f"%{keyword}%"
                cond = Member.org_name.like(kw) | Member.member_number.like(kw)
                if keyword.isdigit():
                    cond = cond | (Member.company_code == int(keyword))
                q = q.filter(cond)
            if status_filter:
                q = q.filter(AnnualRenewal.overall_status == status_filter)

            records = q.order_by(Member.member_number).all()
            for r in records:
                _ = r.member
            session.expunge_all()
            return records
