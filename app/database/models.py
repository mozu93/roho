from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Float,
    Text, ForeignKey, Table, UniqueConstraint, CheckConstraint, Index,
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
    mail_org_name = Column(String)
    mail_dept_title = Column(String)
    mail_person_name = Column(String)
    label_tag = Column(String)
    employment_ins_no = Column(String)
    note = Column(Text)
    registered_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    withdrawn_at = Column(Date)
    withdraw_reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    insurance_entries = relationship(
        "InsuranceEntry", back_populates="member", cascade="all, delete-orphan"
    )
    email_addresses = relationship(
        "MemberEmailAddress", back_populates="member",
        order_by="MemberEmailAddress.sort_order", cascade="all, delete-orphan"
    )
    bank_accounts = relationship(
        "BankAccount", back_populates="member", cascade="all, delete-orphan"
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


class MemberEmailAddress(Base):
    __tablename__ = "member_email_addresses"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    address = Column(String, nullable=False)
    label = Column(String, default="")
    sort_order = Column(Integer, nullable=False, default=1)

    member = relationship("Member", back_populates="email_addresses")


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        CheckConstraint(
            "length(bank_code) = 4 AND bank_code NOT GLOB '*[^0-9]*'",
            name="ck_bank_accounts_bank_code",
        ),
        CheckConstraint(
            "length(branch_code) = 3 AND branch_code NOT GLOB '*[^0-9]*'",
            name="ck_bank_accounts_branch_code",
        ),
        CheckConstraint("account_type IN ('1', '2', '4')", name="ck_bank_accounts_type"),
        CheckConstraint(
            "length(account_number) = 7 AND account_number NOT GLOB '*[^0-9]*'",
            name="ck_bank_accounts_number",
        ),
        CheckConstraint("length(trim(bank_name)) > 0", name="ck_bank_accounts_bank_name"),
        CheckConstraint("length(trim(branch_name)) > 0", name="ck_bank_accounts_branch_name"),
        CheckConstraint(
            "length(recipient_name_kana) BETWEEN 1 AND 48",
            name="ck_bank_accounts_recipient",
        ),
        Index("ix_bank_accounts_member_enabled", "member_id", "is_enabled"),
    )

    id = Column(Integer, primary_key=True)
    member_id = Column(
        Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_code = Column(String(4), nullable=False)
    bank_name = Column(String(100), nullable=False)
    branch_code = Column(String(3), nullable=False)
    branch_name = Column(String(100), nullable=False)
    account_type = Column(String(1), nullable=False)
    account_number = Column(String(7), nullable=False)
    recipient_name_kana = Column(String(48), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member", back_populates="bank_accounts")


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
    signature = Column(Text, nullable=True)


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


class AnnualFeeRule(Base):
    __tablename__ = "annual_fee_rules"
    fiscal_year = Column(Integer, primary_key=True)
    fee_rate = Column(Float, nullable=False, default=0.05)
    member_min_fee = Column(Integer, nullable=False, default=5000)
    non_member_addition = Column(Integer, nullable=False, default=14000)
    tax_rate = Column(Float, nullable=False, default=0.10)


class AnnualFeeRecord(Base):
    __tablename__ = "annual_fee_records"
    __table_args__ = (UniqueConstraint("fiscal_year", "member_id"),)

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)

    is_member_for_fee = Column(Boolean, nullable=False)
    member_override_reason = Column(Text)

    premium_branch_0 = Column(Integer, nullable=False, default=0)
    premium_branch_2 = Column(Integer, nullable=False, default=0)
    premium_branch_4 = Column(Integer, nullable=False, default=0)
    premium_branch_5 = Column(Integer, nullable=False, default=0)
    premium_branch_6 = Column(Integer, nullable=False, default=0)

    premium_total = Column(Integer, nullable=False, default=0)
    five_percent_amount = Column(Integer, nullable=False, default=0)
    base_fee_amount = Column(Integer, nullable=False, default=0)
    non_member_addition_amount = Column(Integer, nullable=False, default=0)
    fee_without_tax = Column(Integer, nullable=False, default=0)
    tax_amount = Column(Integer, nullable=False, default=0)
    total_amount = Column(Integer, nullable=False, default=0)

    is_lump_sum_payment = Column(Boolean, nullable=False, default=False)
    entrust_start_month = Column(Date)
    auto_payment_period = Column(String)
    final_payment_period = Column(String)
    payment_period_override_reason = Column(Text)
    payment_method = Column(String)

    paid_amount = Column(Integer)
    paid_at = Column(Date)
    reminder_status = Column(String, nullable=False, default="未督促")
    note = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member")


class AnnualRenewal(Base):
    __tablename__ = "annual_renewals"
    __table_args__ = (UniqueConstraint("fiscal_year", "member_id"),)

    id = Column(Integer, primary_key=True)
    fiscal_year = Column(Integer, nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)

    overall_status = Column(String, nullable=False, default="未提出")
    overall_status_manual = Column(Boolean, nullable=False, default=False)
    last_contacted_at = Column(Date)
    note = Column(Text)

    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    member = relationship("Member")
    items = relationship(
        "AnnualRenewalItem", back_populates="renewal", cascade="all, delete-orphan"
    )


class AnnualRenewalItem(Base):
    __tablename__ = "annual_renewal_items"
    __table_args__ = (UniqueConstraint("annual_renewal_id", "branch_type"),)

    id = Column(Integer, primary_key=True)
    annual_renewal_id = Column(Integer, ForeignKey("annual_renewals.id"), nullable=False)
    branch_type = Column(String, nullable=False)
    submission_status = Column(String, nullable=False, default="未提出")
    confirmed_at = Column(Date)

    renewal = relationship("AnnualRenewal", back_populates="items")
