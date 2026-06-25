from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date,
    Text, ForeignKey, Table,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# 中間テーブル（activity_log ↔ category）
ActivityLogCategory = Table(
    "activity_log_categories",
    Base.metadata,
    Column("activity_log_id", Integer, ForeignKey("activity_logs.id"), primary_key=True),
    Column("category_id", Integer, ForeignKey("activity_categories.id"), primary_key=True),
)

# 後方互換エイリアス（activity_log_categories という名前でも参照できるようにする）
activity_log_categories = ActivityLogCategory


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    company_code = Column(Integer, unique=True, nullable=True)  # 事業所コード（自動採番）
    member_number = Column(String, unique=True, nullable=True)   # 会員のみ必須
    is_member = Column(Boolean, nullable=False, default=True)    # 会員/非会員
    org_name = Column(String, nullable=False)
    org_kana = Column(String)
    dept_title = Column(String)
    rep_name = Column(String)
    rep_kana = Column(String)
    email = Column(String)
    tel_area = Column(String)
    tel = Column(String)
    fax_area = Column(String)
    fax = Column(String)
    postal_code = Column(String)
    address = Column(String)
    postal_code_mail = Column(String)
    address_mail = Column(String)
    addressee_mail = Column(String)
    label_tag = Column(String)
    employment_ins_no = Column(String)
    note = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    withdrawn_at = Column(Date)
    withdraw_reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    insurance_entries = relationship(
        "InsuranceEntry", back_populates="member", cascade="all, delete-orphan"
    )
    member_changes = relationship("MemberChange", back_populates="member")
    activity_logs = relationship("ActivityLog", back_populates="member")


class InsuranceEntry(Base):
    __tablename__ = "insurance_entries"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    ins_type = Column(String, nullable=False)
    branch_number = Column(String)
    ins_number = Column(String)
    is_tokubetsu = Column(Boolean, nullable=False, default=False)
    is_ikkatsu = Column(Boolean, nullable=False, default=False)

    member = relationship("Member", back_populates="insurance_entries")


class MemberChange(Base):
    __tablename__ = "member_changes"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    changed_at = Column(DateTime, nullable=False, default=datetime.now)
    changed_by = Column(String, nullable=False)
    change_reason = Column(Text, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON文字列

    member = relationship("Member", back_populates="member_changes")
    confirmations = relationship(
        "ChangeConfirmation", back_populates="member_change", cascade="all, delete-orphan"
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    logged_at = Column(DateTime, nullable=False, default=datetime.now)
    logged_by = Column(String, nullable=False)
    content = Column(Text, nullable=False)

    member = relationship("Member", back_populates="activity_logs")
    categories = relationship(
        "ActivityCategory", secondary=activity_log_categories, back_populates="activity_logs"
    )
    confirmations = relationship(
        "ActivityConfirmation", back_populates="activity_log", cascade="all, delete-orphan"
    )


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    activity_logs = relationship(
        "ActivityLog", secondary=activity_log_categories, back_populates="categories"
    )


class ActivityConfirmation(Base):
    __tablename__ = "activity_confirmations"
    id = Column(Integer, primary_key=True)
    activity_log_id = Column(Integer, ForeignKey("activity_logs.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=True, default=None)  # None=未読

    activity_log = relationship("ActivityLog", back_populates="confirmations")


class ChangeConfirmation(Base):
    __tablename__ = "change_confirmations"
    id = Column(Integer, primary_key=True)
    member_change_id = Column(Integer, ForeignKey("member_changes.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=True, default=None)  # None=未読

    member_change = relationship("MemberChange", back_populates="confirmations")


class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class SendJob(Base):
    __tablename__ = "send_jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    template_id = Column(Integer, ForeignKey("email_templates.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    status = Column(String, nullable=False, default="draft")
    total_count = Column(Integer)
    success_count = Column(Integer)
    error_count = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    sent_at = Column(DateTime)

    logs = relationship("SendLog", back_populates="job", cascade="all, delete-orphan")


class SendLog(Base):
    __tablename__ = "send_logs"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("send_jobs.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"))
    to_address = Column(String, nullable=False)
    subject = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    error_message = Column(Text)
    sent_at = Column(DateTime)

    job = relationship("SendJob", back_populates="logs")
