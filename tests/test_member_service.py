import pytest
from sqlalchemy import create_engine
from app.database.models import Base, Staff, AnnualFeeRecord
from app.database.connection import get_session
from app.services.member_service import MemberService


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with get_session(eng) as s:
        s.add(Staff(name="山田"))
        s.add(Staff(name="鈴木"))
    return eng


@pytest.fixture
def svc(engine):
    return MemberService(engine)


def test_create_member(svc):
    data = {
        "member_number": "9001",
        "org_name": "㈱テスト商事",
        "insurance_entries": [
            {"ins_type": "ippan", "branch_number": "0", "ins_number": "101",
             "is_tokubetsu": False, "is_ikkatsu": False}
        ]
    }
    m = svc.create(data, "山田")
    assert m.member_number == "9001"
    assert len(m.insurance_entries) == 1


def test_create_and_update_three_labeled_email_addresses(svc):
    m = svc.create({
        "member_number": "9010", "org_name": "メールテスト社",
        "insurance_entries": [],
        "email_addresses": [
            {"address": "main@example.jp", "label": "代表"},
            {"address": "soumu@example.jp", "label": "総務"},
            {"address": "staff@example.jp", "label": "担当者"},
        ],
    }, "山田")
    assert [(e.address, e.label) for e in m.email_addresses] == [
        ("main@example.jp", "代表"),
        ("soumu@example.jp", "総務"),
        ("staff@example.jp", "担当者"),
    ]
    assert m.email == "main@example.jp"
    assert len(svc.search(keyword="総務")) == 1

    updated = svc.update(m.id, {
        "email_addresses": [{"address": "new@example.jp", "label": "新担当"}],
    }, "メール変更", "山田")
    assert [(e.address, e.label) for e in updated.email_addresses] == [
        ("new@example.jp", "新担当")
    ]
    assert updated.email == "new@example.jp"


def test_email_addresses_are_limited_to_three(svc):
    with pytest.raises(ValueError, match="最大3件"):
        svc.create({
            "member_number": "9011", "org_name": "上限テスト社",
            "insurance_entries": [],
            "email_addresses": [
                {"address": f"mail{i}@example.jp", "label": ""} for i in range(4)
            ],
        }, "山田")


def test_search_by_keyword(svc):
    svc.create({"member_number": "9001", "org_name": "㈱テスト商事", "insurance_entries": []}, "山田")
    svc.create({"member_number": "9002", "org_name": "△△建設", "insurance_entries": []}, "山田")
    results = svc.search(keyword="テスト")
    assert len(results) == 1
    assert results[0].org_name == "㈱テスト商事"


def test_search_by_rep_name_and_kana(svc):
    svc.create({
        "member_number": "9001", "org_name": "㈱テスト商事",
        "rep_name": "山田太郎", "rep_kana": "ヤマダタロウ",
        "insurance_entries": [],
    }, "山田")
    svc.create({
        "member_number": "9002", "org_name": "△△建設",
        "rep_name": "鈴木一郎", "rep_kana": "スズキイチロウ",
        "insurance_entries": [],
    }, "山田")
    by_name = svc.search(keyword="山田太郎")
    assert len(by_name) == 1
    assert by_name[0].org_name == "㈱テスト商事"
    by_kana = svc.search(keyword="スズキ")
    assert len(by_kana) == 1
    assert by_kana[0].org_name == "△△建設"


def test_search_normalizes_kana_and_covers_all_basic_fields(svc):
    svc.create({
        "member_number": "9001", "org_name": "テスト商事", "org_kana": "ﾃｽﾄｼｮｳｼﾞ",
        "dept_title": "営業部", "rep_name": "山田太郎", "email": "info@example.jp",
        "fax": "059-123-4567", "postal_code_mail": "514-0001",
        "address_mail": "津市丸之内1-2", "mail_org_name": "郵送先株式会社",
        "mail_dept_title": "総務課", "mail_person_name": "鈴木花子",
        "employment_ins_no": "1234-567890-1", "note": "要確認", "insurance_entries": [],
    }, "山田")

    # 全角/半角、ひらがな/カタカナを区別せず、基本情報の各項目を検索できる。
    for keyword in ("テストショウジ", "てすと", "営業部", "info@example.jp", "丸之内",
                    "郵送先", "総務課", "鈴木", "1234-567890-1", "要確認"):
        assert len(svc.search(keyword=keyword)) == 1


def test_search_by_ins_type(svc):
    svc.create({"member_number": "9001", "org_name": "A社", "insurance_entries": [
        {"ins_type": "ippan", "branch_number": "0", "ins_number": "101",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")
    svc.create({"member_number": "9002", "org_name": "B社", "insurance_entries": [
        {"ins_type": "kensetsu_koyou", "branch_number": "2", "ins_number": "202",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")
    results = svc.search(ins_types=["ippan"])
    assert len(results) == 1


def test_find_ins_number_conflict(svc):
    a = svc.create({"member_number": "9001", "org_name": "A社", "insurance_entries": [
        {"ins_type": "ippan", "branch_number": "0", "ins_number": "101",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")
    svc.create({"member_number": "9002", "org_name": "B社", "insurance_entries": [
        {"ins_type": "kensetsu_koyou", "branch_number": "2", "ins_number": "101",
         "is_tokubetsu": False, "is_ikkatsu": False}
    ]}, "山田")

    # 同じ枝番かつ同じ番号 → 重複
    dup = svc.find_ins_number_conflict("0", "101")
    assert dup is not None
    assert dup.org_name == "A社"

    # 枝番が異なれば同じ番号でも重複としない
    assert svc.find_ins_number_conflict("2", "999") is None

    # 自分自身は除外される
    assert svc.find_ins_number_conflict("0", "101", exclude_member_id=a.id) is None


def test_update_creates_change_record(svc):
    m = svc.create({"member_number": "9001", "org_name": "旧社名", "insurance_entries": []}, "山田")
    svc.update(m.id, {"org_name": "新社名", "insurance_entries": []}, "住所変更のため", "山田")
    changes = svc.get_changes(m.id)
    assert len(changes) == 1
    assert changes[0].change_reason == "住所変更のため"


def test_withdraw_and_reactivate(svc):
    from datetime import date
    m = svc.create({"member_number": "9001", "org_name": "㈱テスト", "insurance_entries": []}, "山田")
    svc.withdraw(m.id, date(2026, 6, 1), "自己都合", "山田")
    results = svc.search(active_only=True)
    assert len(results) == 0
    svc.reactivate(m.id, "山田")
    results = svc.search(active_only=True)
    assert len(results) == 1


def test_search_inactive_only(svc):
    from datetime import date
    m = svc.create({"member_number": "9001", "org_name": "㈱テスト商事", "insurance_entries": []}, "山田")
    svc.withdraw(m.id, date.today(), "廃業のため", "山田")
    svc.create({"member_number": "9002", "org_name": "△△建設", "insurance_entries": []}, "山田")
    results = svc.search(inactive_only=True)
    assert len(results) == 1
    assert results[0].member_number == "9001"


def test_delete_removes_annual_fee_records(svc, engine):
    m = svc.create({"member_number": "9001", "org_name": "㈱テスト商事", "insurance_entries": []}, "山田")
    with get_session(engine) as s:
        s.add(AnnualFeeRecord(
            fiscal_year=2026,
            member_id=m.id,
            is_member_for_fee=True,
            auto_payment_period="2期",
            final_payment_period="2期",
        ))

    svc.delete(m.id)

    with get_session(engine) as s:
        assert s.query(AnnualFeeRecord).filter_by(member_id=m.id).count() == 0
