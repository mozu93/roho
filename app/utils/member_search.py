"""会員の基本情報を表記ゆれに強く検索するための共通処理。"""
import unicodedata


def normalize_search_text(value) -> str:
    """全半角・ひらがな/カタカナ・英字大小文字の差を吸収する。"""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    # NFKC後のカタカナをひらがなへ寄せ、ひらがな検索でも一致させる。
    text = "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
        for char in text
    )
    return " ".join(text.split())


def member_matches_keyword(member, keyword: str) -> bool:
    """基本情報・保険番号に、空白区切りの全検索語が含まれるか返す。"""
    terms = normalize_search_text(keyword).split()
    if not terms:
        return True

    field_names = (
        "company_code", "member_number", "org_name", "org_kana", "dept_title",
        "rep_name", "rep_kana", "email", "tel_area", "tel", "fax_area", "fax",
        "postal_code", "address", "postal_code_mail", "address_mail",
        "mail_org_name", "mail_dept_title", "mail_person_name",
        "employment_ins_no", "label_tag", "note", "registered_date",
    )
    values = [getattr(member, name, "") for name in field_names]
    for email in getattr(member, "email_addresses", ()):
        values.extend((email.address, email.label))
    for entry in getattr(member, "insurance_entries", ()):
        values.extend((entry.ins_type, entry.branch_number, entry.ins_number))

    haystack = normalize_search_text(" ".join(str(value or "") for value in values))
    return all(term in haystack for term in terms)
