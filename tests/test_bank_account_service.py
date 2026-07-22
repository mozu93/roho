import pytest
from sqlalchemy import create_engine

from app.database.connection import get_session
from app.database.models import Base, Member
from app.services.bank_account_service import (
    BankAccountService, normalize_recipient_name, validate_bank_account,
)


@pytest.fixture
def engine():
    value = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(value)
    return value


@pytest.fixture
def member_id(engine):
    with get_session(engine) as session:
        member = Member(company_code=1001, org_name="テスト商事")
        session.add(member)
        session.flush()
        return member.id


@pytest.fixture
def service(engine):
    return BankAccountService(engine)


def valid_data(**overrides):
    data = {
        "bank_code": "0001",
        "bank_name": "みずほ銀行",
        "branch_code": "001",
        "branch_name": "東京営業部",
        "account_type": "1",
        "account_number": "0123456",
        "recipient_name_kana": "かぶしきがいしゃ　サンプル",
        "is_enabled": True,
    }
    data.update(overrides)
    return data


def test_normalize_recipient_name():
    assert normalize_recipient_name("やまだ　ＴＡＲＯＵ") == "ﾔﾏﾀﾞ TAROU"
    assert normalize_recipient_name("ガッコウ") == "ｶﾞｯｺｳ"


def test_create_preserves_leading_zero_and_normalizes_kana(service, member_id):
    account = service.create(member_id, valid_data())
    assert account.bank_code == "0001"
    assert account.branch_code == "001"
    assert account.account_number == "0123456"
    assert account.recipient_name_kana == "ｶﾌﾞｼｷｶﾞｲｼｬ ｻﾝﾌﾟﾙ"


@pytest.mark.parametrize("field,value,message", [
    ("bank_code", "123", "金融機関コード"),
    ("bank_code", "12A4", "金融機関コード"),
    ("branch_code", "12", "支店コード"),
    ("account_type", "3", "預金種目"),
    ("account_number", "123456", "口座番号"),
    ("recipient_name_kana", "山田", "全銀で使用できない"),
])
def test_validation_rejects_invalid_values(field, value, message):
    with pytest.raises(ValueError, match=message):
        validate_bank_account(valid_data(**{field: value}))


def test_validation_reports_all_missing_required_fields():
    with pytest.raises(ValueError) as exc_info:
        validate_bank_account({})
    message = str(exc_info.value)
    assert "金融機関コード" in message
    assert "支店コード" in message
    assert "口座番号" in message
    assert "受取人名カナ" in message


def test_duplicate_is_rejected_for_same_member(service, member_id):
    service.create(member_id, valid_data())
    with pytest.raises(ValueError, match="既に登録"):
        service.create(member_id, valid_data(bank_name="別表記"))


def test_list_update_filter_and_delete(service, member_id):
    active = service.create(member_id, valid_data())
    service.create(member_id, valid_data(
        bank_code="0005", account_number="7654321", is_enabled=False
    ))
    assert len(service.list_for_member(member_id)) == 2
    assert [row.id for row in service.list_for_member(member_id, include_disabled=False)] == [
        active.id
    ]

    updated = service.update(active.id, valid_data(branch_name="本店", is_enabled=False))
    assert updated.branch_name == "本店"
    assert not updated.is_enabled
    assert service.list_for_member(member_id, include_disabled=False) == []
    assert service.delete(active.id)
    assert service.get(active.id) is None


def test_member_relationship(engine, service, member_id):
    service.create(member_id, valid_data())
    with get_session(engine) as session:
        member = session.get(Member, member_id)
        assert len(member.bank_accounts) == 1
