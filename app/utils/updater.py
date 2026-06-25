import os
import subprocess
import tempfile
import requests
from packaging.version import Version
from PyQt6.QtCore import QThread, pyqtSignal

GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"


def check_for_update(repo: str, current_version: str, timeout: int = 8) -> dict | None:
    try:
        resp = requests.get(GITHUB_API.format(repo=repo), timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        latest_tag = data.get("tag_name", "").lstrip("v")
        if not latest_tag:
            return None
        if Version(latest_tag) <= Version(current_version):
            return None
        # インストーラーのダウンロードURL（.exe ファイル）
        download_url = ""
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".exe"):
                download_url = asset["browser_download_url"]
                break
        return {
            "version": latest_tag,
            "download_url": download_url,
            "body": data.get("body", ""),
        }
    except Exception:
        return None


def download_installer(url: str, dest_path: str, progress_cb=None) -> str:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    progress_cb(downloaded, total)
    return dest_path


def launch_installer(path: str) -> None:
    bat = os.path.join(tempfile.gettempdir(), "rouho_update.bat")
    with open(bat, "w") as f:
        f.write(f'@echo off\nping 127.0.0.1 -n 3 >nul\n"{path}" /SILENT\n')
    subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW)


class UpdateChecker(QThread):
    update_available = pyqtSignal(dict)
    check_done = pyqtSignal()

    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._current_version = current_version

    def run(self):
        result = check_for_update(self._repo, self._current_version)
        if result:
            self.update_available.emit(result)
        self.check_done.emit()
