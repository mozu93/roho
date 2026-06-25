from datetime import datetime
from app.database.connection import get_session
from app.database.models import EmailTemplate, Member


class TemplateService:
    def __init__(self, engine):
        self._engine = engine

    def get_all(self) -> list[EmailTemplate]:
        with get_session(self._engine) as session:
            templates = session.query(EmailTemplate).order_by(EmailTemplate.name).all()
            session.expunge_all()
            return templates

    def get(self, template_id: int) -> EmailTemplate | None:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            if t:
                session.expunge_all()
            return t

    def create(self, name: str, subject: str, body: str) -> EmailTemplate:
        with get_session(self._engine) as session:
            now = datetime.now()
            t = EmailTemplate(name=name, subject=subject, body=body,
                              created_at=now, updated_at=now)
            session.add(t)
            session.flush()
            session.expunge_all()
            return t

    def update(self, template_id: int, name: str, subject: str, body: str) -> EmailTemplate:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            t.name = name
            t.subject = subject
            t.body = body
            t.updated_at = datetime.now()
            session.flush()
            session.expunge_all()
            return t

    def delete(self, template_id: int) -> None:
        with get_session(self._engine) as session:
            t = session.get(EmailTemplate, template_id)
            if t:
                session.delete(t)

    def render(self, template: EmailTemplate, member: Member) -> tuple[str, str]:
        # Ensure member attributes are loaded by merging into a session if detached
        with get_session(self._engine) as session:
            member = session.merge(member)
            replacements = {
                "{事業所名}": member.org_name or "",
                "{代表者名}": member.rep_name or "",
                "{会員No.}": member.member_number or "",
                "{所属・役職}": member.dept_title or "",
            }

        subject = template.subject
        body = template.body
        for placeholder, value in replacements.items():
            subject = subject.replace(placeholder, value)
            body = body.replace(placeholder, value)
        return subject, body
