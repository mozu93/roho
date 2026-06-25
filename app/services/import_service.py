# app/services/import_service.py
import openpyxl
from app.database.connection import get_session
from app.database.models import Member, InsuranceEntry
from app.services.member_service import MemberService

# Excel列インデックス（0始まり）→フィールドマッピング
# A(0)=事業所コード（自動採番のためインポート時は無視）
DEFAULT_COL_MAP = {
    "member_number":  1,   # B
    "is_member":      2,   # C  1or"会員"=会員、0or"非会員"=非会員
    "org_name":       3,   # D
    "org_kana":       4,   # E
    "dept_title":     5,   # F
    "rep_name":       6,   # G
    "rep_kana":       7,   # H
    "email":          8,   # I
    "tel_area":       9,   # J
    "tel":           10,   # K
    "fax_area":      11,   # L
    "fax":           12,   # M
    "postal_code":   13,   # N
    "address":       14,   # O
    "postal_code_mail": 15,  # P
    "address_mail":  16,   # Q
    "addressee_mail": 17,  # R
    "employment_ins_no": 18,  # S
    # 保険番号（T=19始まり、各2列＋フラグ2列）
    "ins_ippan_branch":           19,
    "ins_ippan_number":           20,
    "ins_ippan_tokubetsu":        21,
    "ins_ippan_ikkatsu":          22,
    "ins_kensetsu_koyou_branch":  23,
    "ins_kensetsu_koyou_number":  24,
    "ins_kensetsu_koyou_tokubetsu": 25,
    "ins_kensetsu_koyou_ikkatsu": 26,
    "ins_ringyo_branch":          27,
    "ins_ringyo_number":          28,
    "ins_ringyo_tokubetsu":       29,
    "ins_ringyo_ikkatsu":         30,
    "ins_kensetsu_genba_branch":  31,
    "ins_kensetsu_genba_number":  32,
    "ins_kensetsu_genba_tokubetsu": 33,
    "ins_kensetsu_genba_ikkatsu": 34,
    "ins_kensetsu_jimusho_branch": 35,
    "ins_kensetsu_jimusho_number": 36,
    "ins_kensetsu_jimusho_tokubetsu": 37,
    "ins_kensetsu_jimusho_ikkatsu": 38,
    "note":              39,
}

INS_TYPE_KEYS = [
    ("ippan",            "ins_ippan"),
    ("kensetsu_koyou",   "ins_kensetsu_koyou"),
    ("ringyo",           "ins_ringyo"),
    ("kensetsu_genba",   "ins_kensetsu_genba"),
    ("kensetsu_jimusho", "ins_kensetsu_jimusho"),
]
BRANCH_NUMBERS = {
    "ippan": "0", "kensetsu_koyou": "2",
    "ringyo": "4", "kensetsu_genba": "5", "kensetsu_jimusho": "6",
}


class ImportService:
    def __init__(self, engine):
        self._engine = engine
        self._svc = MemberService(engine)

    def import_excel(
        self,
        path: str,
        col_map: dict | None = None,
        overwrite: bool = False,
        staff_name: str = "インポート",
    ) -> dict:
        col_map = col_map or DEFAULT_COL_MAP
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        result = {"added": 0, "updated": 0, "skipped": 0}

        for row in ws.iter_rows(min_row=2, values_only=True):
            member_number = str(row[col_map["member_number"]] or "").strip() or None
            org_name = str(row[col_map["org_name"]] or "").strip()
            if not org_name:
                result["skipped"] += 1
                continue

            def _get(key):
                idx = col_map.get(key)
                if idx is None or idx >= len(row):
                    return None
                return row[idx]

            ins_entries = []
            for ins_type, prefix in INS_TYPE_KEYS:
                branch = str(_get(f"{prefix}_branch") or "").strip()
                number = str(_get(f"{prefix}_number") or "").strip()
                if branch or number:
                    ins_entries.append({
                        "ins_type": ins_type,
                        "branch_number": branch or BRANCH_NUMBERS[ins_type],
                        "ins_number": number,
                        "is_tokubetsu": bool(_get(f"{prefix}_tokubetsu")),
                        "is_ikkatsu": bool(_get(f"{prefix}_ikkatsu")),
                    })

            raw_is_member = _get("is_member")
            if isinstance(raw_is_member, str):
                is_member = raw_is_member.strip() not in ("0", "非会員", "false", "False")
            else:
                is_member = bool(raw_is_member) if raw_is_member is not None else True

            data = {
                "member_number": member_number,
                "is_member": is_member,
                "org_name": org_name,
                "org_kana": str(_get("org_kana") or ""),
                "dept_title": str(_get("dept_title") or ""),
                "rep_name": str(_get("rep_name") or ""),
                "rep_kana": str(_get("rep_kana") or ""),
                "email": str(_get("email") or ""),
                "tel_area": str(_get("tel_area") or ""),
                "tel": str(_get("tel") or ""),
                "fax_area": str(_get("fax_area") or ""),
                "fax": str(_get("fax") or ""),
                "postal_code": str(_get("postal_code") or ""),
                "address": str(_get("address") or ""),
                "postal_code_mail": str(_get("postal_code_mail") or ""),
                "address_mail": str(_get("address_mail") or ""),
                "addressee_mail": str(_get("addressee_mail") or ""),
                "employment_ins_no": str(_get("employment_ins_no") or ""),
                "note": str(_get("note") or ""),
                "insurance_entries": ins_entries,
            }

            # 既存チェック（会員Noがあればそれで、なければ事業所名で照合）
            with get_session(self._engine) as session:
                if member_number:
                    existing = session.query(Member).filter_by(
                        member_number=member_number
                    ).first()
                else:
                    existing = session.query(Member).filter_by(
                        org_name=org_name
                    ).first()
                exists = existing is not None
                if exists:
                    member_id = existing.id

            if exists and not overwrite:
                result["skipped"] += 1
                continue

            if exists:
                self._svc.update(member_id, data, "Excelインポートによる更新", staff_name)
                result["updated"] += 1
            else:
                self._svc.create(data, staff_name)
                result["added"] += 1

        return result


class ExportService:
    def __init__(self, engine):
        self._engine = engine

    def export_excel(self, members: list, output_path: str) -> None:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "加入者名簿"
        headers = [
            "事業所コード", "会員No.", "会員/非会員", "事業所名", "フリガナ", "所属・役職",
            "代表者名", "代表者フリガナ", "メール", "市外局番", "電話番号", "FAX市外局番", "FAX",
            "郵便番号", "住所", "郵送先郵便番号", "郵送先住所", "郵送先宛名",
            "雇用保険事業所番号",
            "一般枝番", "一般番号", "一般特別加入", "一般一括",
            "建設他雇枝番", "建設他雇番号", "建設他雇特別", "建設他雇一括",
            "林業枝番", "林業番号", "林業特別", "林業一括",
            "建設現場枝番", "建設現場番号", "建設現場特別", "建設現場一括",
            "建設事務所枝番", "建設事務所番号", "建設事務所特別", "建設事務所一括",
            "メモ",
        ]
        ws.append(headers)
        ins_order = ["ippan", "kensetsu_koyou", "ringyo", "kensetsu_genba", "kensetsu_jimusho"]
        for m in members:
            ins_map = {e.ins_type: e for e in m.insurance_entries}
            ins_cols = []
            for ins_type in ins_order:
                e = ins_map.get(ins_type)
                ins_cols += [
                    e.branch_number if e else "",
                    e.ins_number if e else "",
                    1 if (e and e.is_tokubetsu) else "",
                    1 if (e and e.is_ikkatsu) else "",
                ]
            ws.append([
                m.company_code or "", m.member_number or "",
                "会員" if getattr(m, "is_member", True) else "非会員",
                m.org_name, m.org_kana or "", m.dept_title or "",
                m.rep_name or "", m.rep_kana or "", m.email or "",
                m.tel_area or "", m.tel or "", m.fax_area or "", m.fax or "",
                m.postal_code or "", m.address or "",
                m.postal_code_mail or "", m.address_mail or "", m.addressee_mail or "",
                m.employment_ins_no or "",
            ] + ins_cols + [m.note or ""])
        wb.save(output_path)
