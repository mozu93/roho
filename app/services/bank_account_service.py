import re
import unicodedata
from datetime import datetime

from app.database.connection import get_session
from app.database.models import BankAccount, Member
from app.utils.kana import to_halfwidth_kana


ACCOUNT_TYPE_NAMES = {"1": "普通", "2": "当座", "4": "貯蓄"}
_ZENGIN_ALLOWED = re.compile(r"^[0-9A-Z ｦ-ﾟ()\-./]+$")


def normalize_recipient_name(value: str) -> str:
    """受取人名を全銀データで扱える半角表記に正規化する。"""
    value = unicodedata.normalize("NFKC", value or "")
    value = to_halfwidth_kana(value).upper()
    return " ".join(value.split())


def validate_bank_account(data: dict) -> dict:
    """正規化済みコピーを返す。不正時は項目別メッセージをまとめて通知する。"""
    normalized = dict(data)
    for key in ("bank_code", "bank_name", "branch_code", "branch_name",
                "account_type", "account_number"):
        normalized[key] = str(normalized.get(key, "")).strip()
    normalized["recipient_name_kana"] = normalize_recipient_name(
        normalized.get("recipient_name_kana", "")
    )
    normalized["is_enabled"] = bool(normalized.get("is_enabled", True))

    errors = []
    checks = (
        (re.fullmatch(r"[0-9]{4}", normalized["bank_code"]),
         "金融機関コードは4桁の数字で入力してください。"),
        (0 < len(normalized["bank_name"]) <= 100, "金融機関名を入力してください。"),
        (re.fullmatch(r"[0-9]{3}", normalized["branch_code"]),
         "支店コードは3桁の数字で入力してください。"),
        (0 < len(normalized["branch_name"]) <= 100, "支店名を入力してください。"),
        (normalized["account_type"] in ACCOUNT_TYPE_NAMES, "預金種目を選択してください。"),
        (re.fullmatch(r"[0-9]{7}", normalized["account_number"]),
         "口座番号は7桁の数字で入力してください。"),
    )
    errors.extend(message for valid, message in checks if not valid)
    recipient = normalized["recipient_name_kana"]
    if not recipient:
        errors.append("受取人名カナを入力してください。")
    elif len(recipient) > 48:
        errors.append("受取人名カナは半角48文字以内で入力してください。")
    elif not _ZENGIN_ALLOWED.fullmatch(recipient):
        errors.append("受取人名カナに全銀で使用できない文字が含まれています。")
    if errors:
        raise ValueError("\n".join(errors))
    return normalized


class BankAccountService:
    def __init__(self, engine):
        self._engine = engine

    def list_for_member(self, member_id: int, include_disabled: bool = True) -> list:
        with get_session(self._engine) as session:
            q = session.query(BankAccount).filter_by(member_id=member_id)
            if not include_disabled:
                q = q.filter(BankAccount.is_enabled == True)
            rows = q.order_by(
                BankAccount.is_enabled.desc(), BankAccount.bank_code,
                BankAccount.branch_code, BankAccount.id,
            ).all()
            session.expunge_all()
            return rows

    def get(self, account_id: int):
        with get_session(self._engine) as session:
            row = session.get(BankAccount, account_id)
            if row:
                session.expunge(row)
            return row

    def create(self, member_id: int, data: dict):
        values = validate_bank_account(data)
        with get_session(self._engine) as session:
            if not session.get(Member, member_id):
                raise ValueError("対象の顧客が見つかりません。")
            self._ensure_not_duplicate(session, member_id, values)
            row = BankAccount(member_id=member_id, **values)
            session.add(row)
            session.flush()
            session.expunge(row)
            return row

    def update(self, account_id: int, data: dict):
        values = validate_bank_account(data)
        with get_session(self._engine) as session:
            row = session.get(BankAccount, account_id)
            if not row:
                raise ValueError("対象の口座は既に削除されています。")
            self._ensure_not_duplicate(session, row.member_id, values, account_id)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.flush()
            session.expunge(row)
            return row

    def delete(self, account_id: int) -> bool:
        with get_session(self._engine) as session:
            row = session.get(BankAccount, account_id)
            if not row:
                return False
            session.delete(row)
            return True

    @staticmethod
    def _ensure_not_duplicate(session, member_id: int, values: dict,
                              exclude_id: int | None = None):
        q = session.query(BankAccount).filter_by(
            member_id=member_id,
            bank_code=values["bank_code"],
            branch_code=values["branch_code"],
            account_type=values["account_type"],
            account_number=values["account_number"],
        )
        if exclude_id is not None:
            q = q.filter(BankAccount.id != exclude_id)
        if q.first():
            raise ValueError("同じ振込先口座が既に登録されています。")
