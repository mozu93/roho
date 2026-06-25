# app/services/label_service.py
from dataclasses import dataclass
from app.database.connection import get_session
from app.database.models import Member, InsuranceEntry


@dataclass
class LabelEntry:
    """label_pdf.py の generate_label_pdf が期待するエントリ形式"""
    company_name: str = ""
    postal_code: str = ""
    address1: str = ""
    address2: str = ""
    title: str = ""
    person_name: str = ""
    barcode_address: str = ""
    entry_mode: str = "inherit"


class LabelService:
    def __init__(self, engine):
        self._engine = engine

    def get_label_targets(
        self,
        active_only: bool = True,
        include_withdrawn: bool = False,
        ins_types: list[str] | None = None,
        tokubetsu_only: bool = False,
    ) -> list[Member]:
        with get_session(self._engine) as session:
            q = session.query(Member)
            if active_only and not include_withdrawn:
                q = q.filter(Member.is_active == True)
            elif include_withdrawn and not active_only:
                pass  # 全件
            # active_only=True, include_withdrawn=True → active のみ（デフォルト）
            if ins_types:
                q = q.filter(
                    Member.insurance_entries.any(InsuranceEntry.ins_type.in_(ins_types))
                )
            if tokubetsu_only:
                q = q.filter(
                    Member.insurance_entries.any(InsuranceEntry.is_tokubetsu == True)
                )
            members = q.distinct().order_by(Member.member_number).all()
            for m in members:
                _ = m.insurance_entries
            session.expunge_all()
            return members

    def build_label_entry(self, member: Member) -> LabelEntry:
        # 郵送先住所優先フォールバック
        if member.postal_code_mail:
            postal = member.postal_code_mail
            addr1 = member.address_mail or ""
            company = member.addressee_mail or member.org_name or ""
        else:
            postal = member.postal_code or ""
            addr1 = member.address or ""
            company = member.org_name or ""
        return LabelEntry(
            company_name=company,
            postal_code=postal,
            address1=addr1,
            address2="",
            title="",
            person_name="",
            barcode_address=addr1,
            entry_mode="inherit",
        )

    def generate_pdf(
        self,
        members: list[Member],
        output_path: str,
        layout_key: str = "a_one_28185",
        font_key: str = "MSPゴシック",
        barcode_enabled: bool = False,
        batch_mode: str = "no_person",
    ) -> str:
        from app.services.pdf.label_pdf import generate_label_pdf
        entries = [self.build_label_entry(m) for m in members]
        return generate_label_pdf(
            entries=entries,
            output_path=output_path,
            batch_mode=batch_mode,
            layout_key=layout_key,
            font_key=font_key,
            barcode_enabled=barcode_enabled,
        )
