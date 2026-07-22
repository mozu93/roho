import json
from unittest.mock import patch

import pytest

from app.services.bank_master_service import BankMasterService


class _Response:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self._value, ensure_ascii=False).encode("utf-8")


def test_search_banks_uses_name_query():
    service = BankMasterService()
    with patch("urllib.request.urlopen", return_value=_Response([
        {"code": "0155", "name": "百五銀行"}
    ])) as urlopen:
        result = service.search_banks("百五")
    assert result[0]["code"] == "0155"
    assert "name=%E7%99%BE%E4%BA%94" in urlopen.call_args.args[0].full_url


def test_search_branches_requires_selected_bank():
    with pytest.raises(ValueError, match="先に金融機関"):
        BankMasterService().search_branches("", "旭")


def test_search_branches_uses_bank_code():
    service = BankMasterService()
    with patch("urllib.request.urlopen", return_value=_Response([
        {"code": "307", "name": "旭が丘支店"}
    ])) as urlopen:
        result = service.search_branches("0155", "旭")
    assert result[0]["code"] == "307"
    assert "/banks/0155/branches/search.json" in urlopen.call_args.args[0].full_url
