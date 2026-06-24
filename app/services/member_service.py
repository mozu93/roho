import json
from datetime import datetime
from app.database.connection import get_session
from app.database.models import (
    Member, InsuranceEntry, MemberChange, ChangeConfirmation, Staff,
)

INS_TYPES = ["ippan", "kensetsu_koyou", "ringyo", "kensetsu_genba", "kensetsu_jimusho"]


class MemberService:
    def __init__(self, engine):
        self._engine = engine

    def search(
        self,
        keyword: str = "",
        ins_types: list = None,
        tokubetsu_only: bool = False,
        ikkatsu_only: bool = False,
        active_only: bool = True,
    ) -> list:
        with get_session(self._engine) as session:
            q = session.query(Member)
            if active_only:
                q = q.filter(Member.is_active == True)
            if keyword:
                kw = f"%{keyword}%"
                q = q.filter(
                    Member.org_name.like(kw)
                    | Member.org_kana.like(kw)
                    | Member.address.like(kw)
                    | Member.tel.like(kw)
                )
            if ins_types:
                q = q.join(Member.insurance_entries).filter(
                    InsuranceEntry.ins_type.in_(ins_types)
                )
            if tokubetsu_only:
                q = q.join(Member.insurance_entries, isouter=True).filter(
                    InsuranceEntry.is_tokubetsu == True
                )
            if ikkatsu_only:
                q = q.join(Member.insurance_entries, isouter=True).filter(
                    InsuranceEntry.is_ikkatsu == True
                )
            results = q.distinct().order_by(Member.member_number).all()
            for m in results:
                _ = m.insurance_entries  # eager load
            session.expunge_all()
            return results

    def get(self, member_id: int):
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if m:
                _ = m.insurance_entries
            session.expunge_all()
            return m

    def create(self, data: dict, staff_name: str):
        data = dict(data)  # コピーして元データを保護
        with get_session(self._engine) as session:
            entries_data = data.pop("insurance_entries", [])
            m = Member(**{k: v for k, v in data.items()})
            m.created_at = datetime.now()
            m.updated_at = datetime.now()
            session.add(m)
            session.flush()
            for e in entries_data:
                session.add(InsuranceEntry(member_id=m.id, **e))
            session.flush()
            _ = m.insurance_entries
            session.expunge_all()
            return m

    def update(self, member_id: int, data: dict, reason: str, staff_name: str):
        data = dict(data)  # コピーして元データを保護
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            # 更新前のスナップショットを取得
            snapshot = json.dumps(self.member_to_dict(m), ensure_ascii=False)

            entries_data = data.pop("insurance_entries", [])
            for k, v in data.items():
                setattr(m, k, v)
            m.updated_at = datetime.now()

            # 保険番号を更新（全削除→再作成）
            for e in list(m.insurance_entries):
                session.delete(e)
            session.flush()
            for e in entries_data:
                session.add(InsuranceEntry(member_id=m.id, **e))

            # 変更履歴を記録
            change = MemberChange(
                member_id=m.id,
                changed_at=datetime.now(),
                changed_by=staff_name,
                change_reason=reason,
                snapshot=snapshot,
            )
            session.add(change)
            session.flush()

            # 他職員に未読通知を作成（変更者以外のアクティブな職員）
            other_staff = (
                session.query(Staff)
                .filter(Staff.is_active == True, Staff.name != staff_name)
                .all()
            )
            for s in other_staff:
                session.add(ChangeConfirmation(
                    member_change_id=change.id,
                    staff_id=s.id,
                    confirmed_at=None,  # None=未読
                ))

            _ = m.insurance_entries
            session.expunge_all()
            return m

    def withdraw(self, member_id: int, withdrawn_at, reason: str, staff_name: str):
        data = {"is_active": False, "withdrawn_at": withdrawn_at, "withdraw_reason": reason}
        return self.update(member_id, data, f"脱会：{reason}", staff_name)

    def reactivate(self, member_id: int, staff_name: str):
        data = {"is_active": True, "withdrawn_at": None, "withdraw_reason": None}
        return self.update(member_id, data, "再加入", staff_name)

    def get_changes(self, member_id: int) -> list:
        with get_session(self._engine) as session:
            changes = (
                session.query(MemberChange)
                .filter_by(member_id=member_id)
                .order_by(MemberChange.changed_at.desc())
                .all()
            )
            session.expunge_all()
            return changes

    def member_to_dict(self, member: Member) -> dict:
        return {
            "id": member.id,
            "member_number": member.member_number,
            "org_name": member.org_name,
            "org_kana": member.org_kana,
            "rep_name": member.rep_name,
            "tel": member.tel,
            "address": member.address,
            "is_active": member.is_active,
            "insurance_entries": [
                {
                    "ins_type": e.ins_type,
                    "branch_number": e.branch_number,
                    "ins_number": e.ins_number,
                    "is_tokubetsu": e.is_tokubetsu,
                    "is_ikkatsu": e.is_ikkatsu,
                }
                for e in member.insurance_entries
            ],
        }
