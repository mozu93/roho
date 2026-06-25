from unittest.mock import patch, MagicMock
from app.utils.updater import check_for_update


def test_no_update_when_same_version():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v1.0.0",
        "assets": [{"browser_download_url": "https://example.com/setup.exe",
                    "name": "Rouho_Setup_1.0.0.exe"}],
        "body": "",
    }
    with patch("requests.get", return_value=mock_resp):
        result = check_for_update("owner/repo", "1.0.0")
    assert result is None


def test_update_available_when_newer():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v1.1.0",
        "assets": [{"browser_download_url": "https://example.com/setup.exe",
                    "name": "Rouho_Setup_1.1.0.exe"}],
        "body": "バグ修正",
    }
    with patch("requests.get", return_value=mock_resp):
        result = check_for_update("owner/repo", "1.0.0")
    assert result is not None
    assert result["version"] == "1.1.0"


def test_returns_none_on_network_error():
    with patch("requests.get", side_effect=Exception("network error")):
        result = check_for_update("owner/repo", "1.0.0")
    assert result is None
