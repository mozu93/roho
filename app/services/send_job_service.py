from datetime import datetime
from app.database.connection import get_session
from app.database.models import SendJob, SendLog, Staff, EmailTemplate


class SendJobService:
    def __init__(self, engine):
        self._engine = engine

    def create_job(self, name: str, template_id: int, staff_name: str) -> SendJob:
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=staff_name).first()
            job = SendJob(
                name=name,
                template_id=template_id,
                staff_id=staff.id if staff else None,
                status="draft",
                created_at=datetime.now(),
            )
            session.add(job)
            session.flush()
            session.expunge_all()
            return job

    def execute_job(
        self,
        job_id: int,
        targets: list,  # list of Member
        email_svc,
        template_svc,
        attachments: list[dict] | None = None,
        progress_callback=None,
    ) -> dict:
        """
        targets: メールアドレスがある Member のリスト
        attachments: [{"path": str, "name": str}] の共通添付ファイルリスト
        progress_callback: fn(current, total) → UIのプログレスバー更新用
        """
        with get_session(self._engine) as session:
            job = session.get(SendJob, job_id)
            job.status = "sending"
            job.total_count = len(targets)
            job.success_count = 0
            job.error_count = 0

        results = {"success": 0, "error": 0, "skip": 0}

        # トークンを一度だけ取得
        from app.services.email_service import DeviceCodeRequired
        app_obj = email_svc._get_app()
        accounts = app_obj.get_accounts()
        if not accounts:
            raise RuntimeError("未認証です。先にサインインしてください。")
        token_result = app_obj.acquire_token_silent(
            ["Mail.Send"], account=accounts[0]
        )
        if not token_result or "access_token" not in token_result:
            raise RuntimeError("トークン取得失敗。再サインインしてください。")
        token = token_result["access_token"]

        with get_session(self._engine) as session:
            job = session.get(SendJob, job_id)
            template = session.get(EmailTemplate, job.template_id)
            session.expunge_all()

        for idx, member in enumerate(targets):
            if progress_callback:
                progress_callback(idx + 1, len(targets))

            if not member.email:
                results["skip"] += 1
                self._log(job_id, member.id, "", "", "skip", "メールアドレスなし")
                continue

            try:
                subject, body = template_svc.render(template, member)
                email_svc.send(
                    to_address=member.email,
                    subject=subject,
                    body=body,
                    attachments=attachments,
                    token=token,
                )
                results["success"] += 1
                self._log(job_id, member.id, member.email, subject, "success", None)
            except Exception as e:
                results["error"] += 1
                self._log(job_id, member.id, member.email, "", "error", str(e)[:500])

        with get_session(self._engine) as session:
            job = session.get(SendJob, job_id)
            job.status = "done" if results["error"] == 0 else "error"
            job.success_count = results["success"]
            job.error_count = results["error"]
            job.sent_at = datetime.now()

        return results

    def _log(self, job_id, member_id, to_address, subject, status, error_msg):
        with get_session(self._engine) as session:
            session.add(SendLog(
                job_id=job_id,
                member_id=member_id,
                to_address=to_address,
                subject=subject,
                status=status,
                error_message=error_msg,
                sent_at=datetime.now() if status == "success" else None,
            ))

    def get_jobs(self) -> list[SendJob]:
        with get_session(self._engine) as session:
            jobs = (
                session.query(SendJob)
                .order_by(SendJob.created_at.desc())
                .all()
            )
            session.expunge_all()
            return jobs

    def get_logs(self, job_id: int) -> list[SendLog]:
        with get_session(self._engine) as session:
            logs = (
                session.query(SendLog)
                .filter_by(job_id=job_id)
                .all()
            )
            session.expunge_all()
            return logs
