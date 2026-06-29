import hashlib
import os
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
        download_url = ""
        checksum_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".exe"):
                download_url = asset["browser_download_url"]
            elif name == "checksums.txt":
                checksum_url = asset["browser_download_url"]
        return {
            "version": latest_tag,
            "download_url": download_url,
            "checksum_url": checksum_url,
            "body": data.get("body", ""),
        }
    except Exception:
        return None


def verify_installer(path: str, checksum_url: str, timeout: int = 30) -> bool:
    """ダウンロード済みインストーラーの SHA-256 をリリースの checksums.txt と照合する。"""
    if not checksum_url:
        return False
    try:
        resp = requests.get(checksum_url, timeout=timeout)
        resp.raise_for_status()
        installer_name = os.path.basename(path).lower()
        expected_hash = ""
        for line in resp.text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lower() == installer_name:
                expected_hash = parts[0].lower()
                break
        if not expected_hash:
            return False
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest() == expected_hash
    except Exception:
        return False



def launch_installer(path: str) -> None:
    """ShellExecuteW で PowerShell ヘルパーを起動し、本プロセス終了後にインストーラーを実行する。
    /CLOSEAPPLICATIONS をインストーラー側で使うと TerminateProcess との競合が発生し
    「アプリを自動終了できない」エラーになるため、本プロセスの PID が完全に消えてから
    インストーラーを起動する方式に変更。
    PowerShell は ShellExecuteW 経由で起動するため PyInstaller の Job Object 外となり、
    TerminateProcess で道連れにならない。
    """
    import base64
    import ctypes
    import os

    my_pid = os.getpid()
    escaped_path = path.replace("'", "''")
    ps_lines = [
        f"$p = {my_pid}",
        "while (Get-Process -Id $p -ErrorAction SilentlyContinue) {",
        "    Start-Sleep -Milliseconds 300",
        "}",
        f"Start-Process -FilePath '{escaped_path}' -ArgumentList '/SILENT', '/NOCLOSEAPPLICATIONS'",
    ]
    encoded = base64.b64encode(
        "\r\n".join(ps_lines).encode("utf-16-le")
    ).decode("ascii")
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "open", "powershell.exe",
        f"-WindowStyle Hidden -NonInteractive -EncodedCommand {encoded}",
        None, 0,  # SW_HIDE
    )
    if ret <= 32:
        raise OSError(f"アップデートヘルパーの起動に失敗しました (ShellExecute code={ret})")


class DownloadThread(QThread):
    progress = pyqtSignal(int, int)  # downloaded, total
    finished = pyqtSignal(str)       # dest_path
    failed = pyqtSignal(str)         # error message

    def __init__(self, url: str, dest_path: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._dest_path = dest_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        try:
            resp = requests.get(self._url, stream=True, timeout=120)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(self._dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if self._cancelled:
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self.progress.emit(downloaded, total)
            if not self._cancelled:
                self.finished.emit(self._dest_path)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(str(e))


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
