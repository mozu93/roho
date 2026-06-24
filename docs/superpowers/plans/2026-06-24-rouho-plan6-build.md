# 労働保険名簿管理システム Plan 6: ビルド・配布・自動アップデート

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PyInstaller + Inno Setup で exe ビルド、GitHub Actions で自動リリース、アプリ内自動アップデートバナーを実装する。

**Architecture:** cci-billing-label の同実装と同方式。`app/utils/updater.py` が起動時にバックグラウンドでGitHub APIをポーリング。新バージョン検出時に `UpdateBanner` を表示。Inno Setup でインストーラーを生成し、GitHub Release に添付。

**Tech Stack:** Python 3.11+, PyQt6, PyInstaller, Inno Setup, GitHub Actions, packaging

## Global Constraints

- Plan 1〜5 完了が前提
- `app/version.py` がバージョン番号の唯一の管理源
- インストール先: `{localappdata}\Rouho`（管理者権限不要）
- GitHub リポジトリ名は実装時に確定する（以下 `{OWNER}/{REPO}` と表記）
- タグ形式: `v{VERSION}`（例: `v1.0.0`）

---

### Task 1: アップデートチェッカー

**Files:**
- Create: `app/utils/updater.py`
- Create: `tests/test_updater.py`

**Interfaces:**
- Produces:
  - `check_for_update(repo: str, current_version: str, timeout: int = 8) -> dict | None`
    → 新バージョンがあれば `{"version": str, "download_url": str, "body": str}` を返す
    → なければ `None`
  - `UpdateChecker(repo, current_version, parent=None)` (QThread)
    → シグナル `update_available(dict)`, `check_done()`
  - `download_installer(url, dest_path, progress_cb=None) -> str`
  - `launch_installer(path: str) -> None`

- [ ] **Step 1: テストを書く**

```python
# tests/test_updater.py
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
```

- [ ] **Step 2: テスト実行（失敗を確認）**

```
pytest tests/test_updater.py -v
```
Expected: ImportError

- [ ] **Step 3: app/utils/updater.py を実装**

```python
# app/utils/updater.py
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
```

- [ ] **Step 4: テスト実行（全パスを確認）**

```
pytest tests/test_updater.py -v
```
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add app/utils/updater.py tests/test_updater.py
git commit -m "feat: add update checker"
```

---

### Task 2: アップデートバナー UI

**Files:**
- Create: `app/ui/update_banner.py`
- Modify: `app/ui/main_window.py`

**Interfaces:**
- Consumes: `UpdateChecker`, `download_installer`, `launch_installer`
- Produces: `UpdateBanner(repo, current_version, parent=None)`

- [ ] **Step 1: app/ui/update_banner.py を実装**

```python
# app/ui/update_banner.py
import os
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.utils.updater import UpdateChecker, download_installer, launch_installer


class UpdateBanner(QWidget):
    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._current_version = current_version
        self._update_info = None
        self._installer_path = None
        self.setStyleSheet(
            "UpdateBanner { background:#FEF9C3; border-bottom:2px solid #FDE047; }"
        )
        self.setFixedHeight(40)
        self._build_ui()
        self.hide()
        self._start_check()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        self._message_label = QLabel("")
        layout.addWidget(self._message_label)
        layout.addStretch()
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(160)
        self._progress_bar.hide()
        layout.addWidget(self._progress_bar)
        self._action_btn = QPushButton("ダウンロード")
        self._action_btn.setFixedWidth(130)
        self._action_btn.clicked.connect(self._on_action)
        layout.addWidget(self._action_btn)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

    def _start_check(self):
        self._checker = UpdateChecker(self._repo, self._current_version, parent=self)
        self._checker.update_available.connect(self._on_update_found)
        self._checker.start()

    def _on_update_found(self, info: dict):
        self._update_info = info
        self._message_label.setText(
            f"新しいバージョン v{info['version']} が利用可能です"
        )
        self._action_btn.setText("ダウンロード")
        self.show()

    def _on_action(self):
        if self._installer_path and os.path.exists(self._installer_path):
            self._do_install()
        else:
            self._do_download()

    def _do_download(self):
        if not self._update_info or not self._update_info.get("download_url"):
            QMessageBox.warning(self, "エラー", "ダウンロードURLが見つかりません。")
            return
        self._action_btn.setEnabled(False)
        self._progress_bar.show()
        self._progress_bar.setRange(0, 100)

        dest = os.path.join(
            tempfile.gettempdir(),
            f"Rouho_Setup_{self._update_info['version']}.exe"
        )
        try:
            download_installer(
                self._update_info["download_url"],
                dest,
                progress_cb=lambda c, t: self._progress_bar.setValue(int(c / t * 100)),
            )
            self._installer_path = dest
            self._progress_bar.hide()
            self._action_btn.setText("今すぐ更新して再起動")
            self._action_btn.setEnabled(True)
        except Exception as e:
            self._progress_bar.hide()
            self._action_btn.setEnabled(True)
            self._message_label.setText("ダウンロードに失敗しました。後で再試行してください。")

    def _do_install(self):
        import sys
        reply = QMessageBox.question(
            self, "更新確認",
            "インストーラーを起動してアプリを終了します。よいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if getattr(sys, "frozen", False):
            launch_installer(self._installer_path)
            sys.exit(0)
        else:
            QMessageBox.information(
                self, "開発環境",
                f"インストーラーのパス:\n{self._installer_path}"
            )
```

- [ ] **Step 2: main_window.py にアップデートバナーを追加**

`app/ui/main_window.py` の `_build_ui` 内で、通知バナーの下にアップデートバナーを追加する。

インポートに追加：
```python
from app.ui.update_banner import UpdateBanner
```

`_build_ui` のタブウィジェット追加直前に：
```python
GITHUB_REPO = "your-org/rouho"  # リリース時に実際のリポジトリ名に変更
from app.version import __version__
self._update_banner = UpdateBanner(GITHUB_REPO, __version__)
root.addWidget(self._update_banner)
```

- [ ] **Step 3: コミット**

```bash
git add app/ui/update_banner.py app/ui/main_window.py
git commit -m "feat: add auto-update banner"
```

---

### Task 3: PyInstaller スペックファイル

**Files:**
- Create: `rouho.spec`
- Create: `assets/icons/rouho.ico`（Pythonスクリプトで生成）
- Create: `generate_icon.py`

- [ ] **Step 1: アイコン生成スクリプトを作成**

```python
# generate_icon.py
from PIL import Image, ImageDraw, ImageFont
import struct, zlib, io

def create_icon():
    """シンプルな青い四角アイコンを生成する"""
    sizes = [16, 32, 48, 256]
    images = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (37, 99, 235, 255))  # blue-600
        draw = ImageDraw.Draw(img)
        # "R" の文字
        font_size = max(8, size // 2)
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "R", font=font)
        x = (size - (bbox[2] - bbox[0])) // 2
        y = (size - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), "R", fill="white", font=font)
        images.append(img)

    import os
    os.makedirs("assets/icons", exist_ok=True)
    images[0].save(
        "assets/icons/rouho.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print("アイコン生成完了: assets/icons/rouho.ico")

if __name__ == "__main__":
    create_icon()
```

実行：
```
pip install pillow
python generate_icon.py
```

- [ ] **Step 2: rouho.spec を作成**

```python
# rouho.spec
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# バージョン取得
with open("app/version.py") as f:
    exec(f.read())
VERSION = __version__

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("app_config.json", "."),
    ],
    hiddenimports=[
        "sqlalchemy.dialects.sqlite",
        "msal",
        "reportlab",
        "openpyxl",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Rouho",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/icons/rouho.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Rouho",
)
```

- [ ] **Step 3: ビルドテスト（ローカル）**

```
pip install pyinstaller
pyinstaller rouho.spec --clean
```
確認：`dist/Rouho/Rouho.exe` が生成されること。起動して動作確認。

- [ ] **Step 4: コミット**

```bash
git add rouho.spec generate_icon.py assets/
git commit -m "chore: add PyInstaller spec and app icon"
```

---

### Task 4: Inno Setup インストーラー定義

**Files:**
- Create: `installer/setup.iss`

- [ ] **Step 1: installer/setup.iss を作成**

```iss
; installer/setup.iss
#define MyAppName "労働保険名簿管理システム"
#define MyAppExeName "Rouho.exe"
#define MyAppVersion GetFileVersion("..\dist\Rouho\Rouho.exe")
#define MyOutputBase "Rouho_Setup"

[Setup]
AppId={{F3A2B1C4-8D5E-4F6A-9B3C-2E7D1F0A8C5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=労働保険事務組合
DefaultDirName={localappdata}\Rouho
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename={#MyOutputBase}_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; GroupDescription: "追加タスク:"

[Files]
Source: "..\dist\Rouho\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "アプリを起動する"; Flags: nowait postinstall skipifsilent
```

- [ ] **Step 2: ローカルでインストーラー生成テスト**

Inno Setup をインストール後：
```
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```
確認：`installer_output/Rouho_Setup_1.0.0.exe` が生成されること。

- [ ] **Step 3: コミット**

```bash
git add installer/setup.iss
git commit -m "chore: add Inno Setup installer definition"
```

---

### Task 5: GitHub Actions 自動リリース

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: .github/workflows/release.yml を作成**

```yaml
# .github/workflows/release.yml
name: Build and Release

on:
  push:
    tags:
      - "v*.*.*"

jobs:
  build:
    runs-on: windows-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt pyinstaller pillow

      - name: Get version from tag
        id: get_version
        run: |
          $version = "${{ github.ref_name }}".TrimStart("v")
          echo "VERSION=$version" >> $env:GITHUB_OUTPUT

      - name: Generate icon
        run: python generate_icon.py

      - name: Build with PyInstaller
        run: pyinstaller rouho.spec --clean

      - name: Install Inno Setup
        run: choco install innosetup --no-progress -y

      - name: Build installer
        run: |
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: installer_output/Rouho_Setup_${{ steps.get_version.outputs.VERSION }}.exe
          generate_release_notes: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: リリース手順ドキュメント確認**

```
# app/version.py の __version__ を "1.0.1" に更新してコミット
# git tag v1.0.1
# git push origin v1.0.1
# → GitHub Actions が自動でビルド・リリース
```

- [ ] **Step 3: コミット**

```bash
git add .github/
git commit -m "chore: add GitHub Actions release workflow"
```

---

### Task 6: .gitignore・最終整備

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: .gitignore を作成**

```gitignore
# Python
__pycache__/
*.py[cod]
*.pyo
.pytest_cache/
*.egg-info/

# PyInstaller
dist/
build/
*.spec.bak

# Inno Setup output
installer_output/

# Database & config (本番ファイルはコミットしない)
rouho.db
app_config.json

# MSAL token cache
~/.rouho_token_cache.bin
*.bin

# OS
.DS_Store
Thumbs.db
desktop.ini
```

- [ ] **Step 2: 全テスト実行**

```
pytest -v
```
Expected: 全 passed

- [ ] **Step 3: 最終コミット**

```bash
git add .gitignore
git commit -m "chore: add gitignore and finalize project"
```

- [ ] **Step 4: GitHub にプッシュしてv1.0.0タグを作成**

```bash
git remote add origin https://github.com/{OWNER}/rouho.git
git push -u origin main
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions でビルドが走り、Releases にインストーラーが公開されることを確認する。
