import hashlib
import os
import tempfile
from unittest.mock import patch, MagicMock
from app.utils.updater import check_for_update, verify_installer


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


def test_check_for_update_includes_checksum_url():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v2.0.0",
        "assets": [
            {"browser_download_url": "https://example.com/setup.exe",
             "name": "Rouho_Setup_2.0.0.exe"},
            {"browser_download_url": "https://example.com/checksums.txt",
             "name": "checksums.txt"},
        ],
        "body": "",
    }
    with patch("requests.get", return_value=mock_resp):
        result = check_for_update("owner/repo", "1.0.0")
    assert result["checksum_url"] == "https://example.com/checksums.txt"


def _make_temp_exe(content: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".exe")
    os.write(fd, content)
    os.close(fd)
    return path


def test_verify_installer_correct_hash():
    content = b"fake installer content"
    sha = hashlib.sha256(content).hexdigest()
    path = _make_temp_exe(content)
    filename = os.path.basename(path)
    checksum_text = f"{sha}  {filename}\n"
    mock_resp = MagicMock()
    mock_resp.text = checksum_text
    mock_resp.raise_for_status = lambda: None
    try:
        with patch("requests.get", return_value=mock_resp):
            assert verify_installer(path, "https://example.com/checksums.txt") is True
    finally:
        os.unlink(path)


def test_verify_installer_wrong_hash():
    content = b"fake installer content"
    path = _make_temp_exe(content)
    filename = os.path.basename(path)
    checksum_text = f"{'0' * 64}  {filename}\n"
    mock_resp = MagicMock()
    mock_resp.text = checksum_text
    mock_resp.raise_for_status = lambda: None
    try:
        with patch("requests.get", return_value=mock_resp):
            assert verify_installer(path, "https://example.com/checksums.txt") is False
    finally:
        os.unlink(path)


def test_verify_installer_no_checksum_url():
    assert verify_installer("/nonexistent/path.exe", "") is False
    assert verify_installer("/nonexistent/path.exe", None) is False
