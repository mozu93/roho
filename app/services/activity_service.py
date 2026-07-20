# app/services/activity_service.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.connection import get_session
from app.database.models import (
    ActivityLog, ActivityCategory, ActivityConfirmation,
    MemberChange, ChangeConfirmation, Staff, Member,
)


class ActivityService:
    def __init__(self, engine):
        self._engine = engine

    def get_logs(self, member_id: int) -> list[ActivityLog]:
        with get_session(self._engine) as session:
            logs = (
                session.query(ActivityLog)
                .filter_by(member_id=member_id)
                .order_by(ActivityLog.logged_at.desc())
                .all()
            )
            for log in logs:
                _ = log.categories
            session.expunge_all()
            return logs

    def add_log(
        self,
        member_id: int,
        content: str,
        category_ids: list[int],
        staff_name: str,
    ) -> ActivityLog:
        with get_session(self._engine) as session:
            log = ActivityLog(
                member_id=member_id,
                logged_at=datetime.now(),
                logged_by=staff_name,
                content=content,
            )
            if category_ids:
                cats = session.query(ActivityCategory).filter(
                    ActivityCategory.id.in_(category_ids)
                ).all()
                log.categories = cats
            session.add(log)
            session.flush()

            # 他職員への未読通知
            other_staff = (
                session.query(Staff)
                .filter(Staff.is_active == True, Staff.name != staff_name)
                .all()
            )
            for s in other_staff:
                session.add(ActivityConfirmation(
                    activity_log_id=log.id,
                    staff_id=s.id,
                    confirmed_at=None,
                ))
            session.flush()
            _ = log.categories
            session.expunge_all()
            return log

    def delete_log(self, log_id: int) -> None:
        with get_session(self._engine) as session:
            log = session.get(ActivityLog, log_id)
            if log:
                session.delete(log)

    def get_unread(self, staff_name: str) -> list[dict]:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name, is_active=True).first()
            if not staff:
                return []

            # 未読の activity_logs を JOIN で一括取得（N+1 回避）
            act_rows = (
                session.query(ActivityConfirmation, ActivityLog, Member)
                .join(ActivityLog, ActivityConfirmation.activity_log_id == ActivityLog.id)
                .join(Member, ActivityLog.member_id == Member.id)
                .filter(
                    ActivityConfirmation.staff_id == staff.id,
                    ActivityConfirmation.confirmed_at.is_(None),
                )
                .all()
            )
            results = []
            for conf, log, member in act_rows:
                results.append({
                    "type": "activity",
                    "id": conf.id,
                    "event_id": log.id,
                    "member_id": log.member_id,
                    "org_name": member.org_name,
                    "logged_at": log.logged_at,
                    "logged_by": log.logged_by,
                    "content": log.content[:40],
                })

            # 未読の member_changes を JOIN で一括取得（N+1 回避）
            chg_rows = (
                session.query(ChangeConfirmation, MemberChange, Member)
                .join(MemberChange, ChangeConfirmation.member_change_id == MemberChange.id)
                .join(Member, MemberChange.member_id == Member.id)
                .filter(
                    ChangeConfirmation.staff_id == staff.id,
                    ChangeConfirmation.confirmed_at.is_(None),
                )
                .all()
            )
            for conf, change, member in chg_rows:
                results.append({
                    "type": "change",
                    "id": conf.id,
                    "event_id": change.id,
                    "member_id": change.member_id,
                    "org_name": member.org_name,
                    "logged_at": change.changed_at,
                    "logged_by": change.changed_by,
                    "content": change.change_reason[:40],
                })

            results.sort(key=lambda x: x["logged_at"], reverse=True)
            return results

    def confirm_activity(self, log_id: int, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            conf = (
                session.query(ActivityConfirmation)
                .filter_by(activity_log_id=log_id, staff_id=staff.id)
                .first()
            )
            if conf:
                conf.confirmed_at = datetime.now()

    def confirm_change(self, change_id: int, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            conf = (
                session.query(ChangeConfirmation)
                .filter_by(member_change_id=change_id, staff_id=staff.id)
                .first()
            )
            if conf:
                conf.confirmed_at = datetime.now()

    def confirm_all(self, staff_name: str) -> None:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            if not staff:
                return
            now = datetime.now()
            for conf in session.query(ActivityConfirmation).filter_by(
                staff_id=staff.id, confirmed_at=None
            ).all():
                conf.confirmed_at = now
            for conf in session.query(ChangeConfirmation).filter_by(
                staff_id=staff.id, confirmed_at=None
            ).all():
                conf.confirmed_at = now

    def search_logs(self, keyword: str, member_id: int = None,
                    include_inactive: bool = False) -> list[dict]:
        with get_session(self._engine) as session:
            q = (
                session.query(ActivityLog, Member)
                .join(Member, ActivityLog.member_id == Member.id)
            )
            if not include_inactive:
                q = q.filter(Member.is_active == True)
            if member_id is not None:
                q = q.filter(ActivityLog.member_id == member_id)
            if keyword:
                q = q.filter(ActivityLog.content.like(f"%{keyword}%"))
            q = q.order_by(ActivityLog.logged_at.desc())
            results = []
            for log, member in q.all():
                _ = log.categories
                results.append({
                    "log_id": log.id,
                    "member_id": member.id,
                    "org_name": member.org_name,
                    "is_active": member.is_active,
                    "logged_at": log.logged_at,
                    "logged_by": log.logged_by,
                    "categories": [c.name for c in log.categories],
                    "content": log.content,
                })
            return results

    def get_last_changed_at_map(self, member_ids: list[int]) -> dict:
        """各メンバーの最終変更日時を {member_id: datetime} で返す（変更履歴ベース）"""
        if not member_ids:
            return {}
        from sqlalchemy import func
        with get_session(self._engine) as session:
            rows = (
                session.query(MemberChange.member_id, func.max(MemberChange.changed_at))
                .filter(MemberChange.member_id.in_(member_ids))
                .group_by(MemberChange.member_id)
                .all()
            )
            return {mid: dt for mid, dt in rows}

    def get_last_logged_at_map(self, member_ids: list[int]) -> dict:
        """各メンバーの最終対応日時を {member_id: datetime} で返す（一括取得）"""
        if not member_ids:
            return {}
        from sqlalchemy import func
        with get_session(self._engine) as session:
            rows = (
                session.query(ActivityLog.member_id, func.max(ActivityLog.logged_at))
                .filter(ActivityLog.member_id.in_(member_ids))
                .group_by(ActivityLog.member_id)
                .all()
            )
            return {mid: dt for mid, dt in rows}

    def get_categories(self) -> list[ActivityCategory]:
        with get_session(self._engine) as session:
            cats = session.query(ActivityCategory).order_by(
                ActivityCategory.sort_order, ActivityCategory.id
            ).all()
            session.expunge_all()
            return cats

    def add_category(self, name: str) -> ActivityCategory:
        with get_session(self._engine) as session:
            max_order = session.query(ActivityCategory).count()
            cat = ActivityCategory(name=name, sort_order=max_order)
            session.add(cat)
            session.flush()
            session.expunge_all()
            return cat

    def get_or_create_category(self, name: str) -> ActivityCategory:
        """名前に対応するカテゴリを返し、未登録なら追加する。"""
        with get_session(self._engine) as session:
            cat = session.query(ActivityCategory).filter_by(name=name).first()
            if cat is None:
                cat = ActivityCategory(
                    name=name,
                    sort_order=session.query(ActivityCategory).count(),
                )
                session.add(cat)
                session.flush()
            session.expunge_all()
            return cat

    def delete_category(self, category_id: int) -> None:
        with get_session(self._engine) as session:
            cat = session.get(ActivityCategory, category_id)
            if cat:
                session.delete(cat)

    def reorder_categories(self, ids: list[int]) -> None:
        with get_session(self._engine) as session:
            for order, cat_id in enumerate(ids):
                cat = session.get(ActivityCategory, cat_id)
                if cat:
                    cat.sort_order = order
