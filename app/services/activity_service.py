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
            _ = log.categories
            session.expunge_all()
            return log

    def get_unread(self, staff_name: str) -> list[dict]:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name, is_active=True).first()
            if not staff:
                return []

            # 未読の activity_logs
            unread_logs = (
                session.query(ActivityConfirmation)
                .filter_by(staff_id=staff.id, confirmed_at=None)
                .all()
            )
            results = []
            for conf in unread_logs:
                log = session.get(ActivityLog, conf.activity_log_id)
                if not log:
                    continue
                member = session.get(Member, log.member_id)
                results.append({
                    "type": "activity",
                    "id": conf.id,
                    "event_id": log.id,
                    "member_id": log.member_id,
                    "org_name": member.org_name if member else "",
                    "logged_at": log.logged_at,
                    "logged_by": log.logged_by,
                    "content": log.content[:40],
                })

            # 未読の member_changes
            unread_changes = (
                session.query(ChangeConfirmation)
                .filter_by(staff_id=staff.id, confirmed_at=None)
                .all()
            )
            for conf in unread_changes:
                change = session.get(MemberChange, conf.member_change_id)
                if not change:
                    continue
                member = session.get(Member, change.member_id)
                results.append({
                    "type": "change",
                    "id": conf.id,
                    "event_id": change.id,
                    "member_id": change.member_id,
                    "org_name": member.org_name if member else "",
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
