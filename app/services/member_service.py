import json
from datetime import datetime
from sqlalchemy import func
from app.database.connection import get_session
from app.database.models import (
    Member, InsuranceEntry, MemberEmailAddress, MemberChange, ChangeConfirmation, Staff,
    AnnualFeeRecord,
)
from app.utils.member_search import member_matches_keyword

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
        inactive_only: bool = False,
    ) -> list:
        with get_session(self._engine) as session:
            q = session.query(Member)
            if inactive_only:
                q = q.filter(Member.is_active == False)
            elif active_only:
                q = q.filter(Member.is_active == True)
            if ins_types:
                q = q.filter(
                    Member.insurance_entries.any(InsuranceEntry.ins_type.in_(ins_types))
                )
            if tokubetsu_only:
                q = q.filter(
                    Member.insurance_entries.any(InsuranceEntry.is_tokubetsu == True)
                )
            if ikkatsu_only:
                q = q.filter(
                    Member.insurance_entries.any(InsuranceEntry.is_ikkatsu == True)
                )
            results = q.distinct().order_by(Member.member_number).all()
            for m in results:
                _ = m.insurance_entries  # eager load
                _ = m.email_addresses
            if keyword:
                results = [m for m in results if member_matches_keyword(m, keyword)]
            session.expunge_all()
            return results

    def get(self, member_id: int):
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if m:
                _ = m.insurance_entries
                _ = m.email_addresses
            session.expunge_all()
            return m

    def create(self, data: dict, staff_name: str):
        data = dict(data)  # コピーして元データを保護
        with get_session(self._engine) as session:
            entries_data = data.pop("insurance_entries", [])
            emails_data = data.pop("email_addresses", None)
            if emails_data is None:
                legacy_email = data.get("email", "") or ""
                emails_data = ([{"address": legacy_email, "label": ""}]
                               if legacy_email else [])
            if len(emails_data) > 3:
                raise ValueError("メールアドレスは最大3件まで登録できます。")
            data["email"] = emails_data[0]["address"] if emails_data else ""
            # 事業所コードを自動採番
            max_code = session.query(func.max(Member.company_code)).scalar() or 0
            data["company_code"] = max_code + 1
            m = Member(**{k: v for k, v in data.items()})
            m.created_at = datetime.now()
            m.updated_at = datetime.now()
            session.add(m)
            session.flush()
            for e in entries_data:
                session.add(InsuranceEntry(member_id=m.id, **e))
            for i, e in enumerate(emails_data, 1):
                session.add(MemberEmailAddress(
                    member_id=m.id, address=e["address"], label=e.get("label", ""),
                    sort_order=i,
                ))
            session.flush()
            _ = m.insurance_entries
            _ = m.email_addresses
            session.expunge_all()
            return m

    def update(self, member_id: int, data: dict, reason: str, staff_name: str):
        data = dict(data)  # コピーして元データを保護
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if not m:
                raise ValueError(f"会員ID {member_id} が見つかりません。")
            # 更新前のスナップショットを取得
            snapshot = json.dumps(self.member_to_dict(m), ensure_ascii=False)

            entries_data = data.pop("insurance_entries", None)
            emails_data = data.pop("email_addresses", None)
            if emails_data is not None:
                if len(emails_data) > 3:
                    raise ValueError("メールアドレスは最大3件まで登録できます。")
                data["email"] = emails_data[0]["address"] if emails_data else ""
            for k, v in data.items():
                setattr(m, k, v)
            m.updated_at = datetime.now()

            # insurance_entries が明示的に渡された場合のみ更新（全削除→再作成）
            if entries_data is not None:
                for e in list(m.insurance_entries):
                    session.delete(e)
                session.flush()
                for e in entries_data:
                    session.add(InsuranceEntry(member_id=m.id, **e))

            if emails_data is not None:
                m.email_addresses.clear()
                session.flush()
                for i, e in enumerate(emails_data, 1):
                    m.email_addresses.append(MemberEmailAddress(
                        address=e["address"], label=e.get("label", ""),
                        sort_order=i,
                    ))

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
            session.flush()

            _ = m.insurance_entries
            _ = m.email_addresses
            session.expunge_all()
            return m

    def withdraw(self, member_id: int, withdrawn_at, reason: str, staff_name: str):
        data = {"is_active": False, "withdrawn_at": withdrawn_at, "withdraw_reason": reason}
        return self.update(member_id, data, f"脱会：{reason}", staff_name)

    def reactivate(self, member_id: int, staff_name: str):
        data = {"is_active": True, "withdrawn_at": None, "withdraw_reason": None}
        return self.update(member_id, data, "再加入", staff_name)

    def undo_withdraw(self, member_id: int, staff_name: str):
        """委託解除を取消し、名簿に戻す"""
        data = {"is_active": True, "withdrawn_at": None, "withdraw_reason": None}
        return self.update(member_id, data, "委託解除を取消", staff_name)

    def delete(self, member_id: int):
        """会員を関連データごと完全削除する"""
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if not m:
                return
            session.query(AnnualFeeRecord).filter_by(member_id=member_id).delete()
            for change in list(m.member_changes):
                session.delete(change)   # ChangeConfirmation は cascade
            for log in list(m.activity_logs):
                session.delete(log)      # ActivityConfirmation は cascade
            session.flush()
            session.delete(m)            # InsuranceEntry は cascade

    def find_by_member_number(self, member_number: str):
        with get_session(self._engine) as session:
            m = session.query(Member).filter_by(member_number=member_number).first()
            if m:
                session.expunge_all()
            return m

    def find_ins_number_conflict(
        self, branch_number: str, ins_number: str, exclude_member_id: int | None = None
    ):
        """指定の枝番号・番号の組み合わせを既に使用している会員を返す（自分自身は除外）"""
        if not ins_number:
            return None
        with get_session(self._engine) as session:
            q = (
                session.query(Member)
                .join(InsuranceEntry, InsuranceEntry.member_id == Member.id)
                .filter(
                    InsuranceEntry.branch_number == branch_number,
                    InsuranceEntry.ins_number == ins_number,
                )
            )
            if exclude_member_id is not None:
                q = q.filter(Member.id != exclude_member_id)
            m = q.first()
            if m:
                session.expunge_all()
            return m

    def get_current_snapshot(self, member_id: int) -> dict:
        """セッション内で member_to_dict を呼び DetachedInstanceError を回避する"""
        with get_session(self._engine) as session:
            m = session.get(Member, member_id)
            if not m:
                return {}
            _ = m.insurance_entries
            _ = m.email_addresses
            return self.member_to_dict(m)

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
            "company_code":      member.company_code,
            "member_number":     member.member_number,
            "is_member":         member.is_member,
            "org_name":          member.org_name,
            "org_kana":          member.org_kana,
            "dept_title":        member.dept_title,
            "rep_name":          member.rep_name,
            "rep_kana":          member.rep_kana,
            "email":             member.email,
            "email_addresses":   [
                {"address": e.address, "label": e.label or "", "sort_order": e.sort_order}
                for e in member.email_addresses
            ],
            "tel_area":          member.tel_area,
            "tel":               member.tel,
            "fax_area":          member.fax_area,
            "fax":               member.fax,
            "postal_code":       member.postal_code,
            "address":           member.address,
            "postal_code_mail":  member.postal_code_mail,
            "address_mail":      member.address_mail,
            "mail_org_name":     member.mail_org_name,
            "mail_dept_title":   member.mail_dept_title,
            "mail_person_name":  member.mail_person_name,
            "employment_ins_no": member.employment_ins_no,
            "note":              member.note,
            "registered_date":   member.registered_date.isoformat() if member.registered_date else None,
            "is_active":         member.is_active,
            "withdrawn_at":      member.withdrawn_at.isoformat() if member.withdrawn_at else None,
            "withdraw_reason":   member.withdraw_reason,
            "insurance_entries": [
                {
                    "ins_type":      e.ins_type,
                    "branch_number": e.branch_number,
                    "ins_number":    e.ins_number,
                    "is_tokubetsu":  e.is_tokubetsu,
                    "is_ikkatsu":    e.is_ikkatsu,
                }
                for e in member.insurance_entries
            ],
        }
