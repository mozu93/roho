import os
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.utils.updater import UpdateChecker, download_installer, launch_installer, verify_installer


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
        self._action_btn.setMinimumWidth(180)
        self._action_btn.clicked.connect(self._on_action)
        layout.addWidget(self._action_btn)

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
            self._progress_bar.hide()
            checksum_url = self._update_info.get("checksum_url", "")
            if checksum_url:
                if not verify_installer(dest, checksum_url):
                    QMessageBox.critical(
                        self, "セキュリティエラー",
                        "ダウンロードファイルのチェックサムが一致しません。\nインストールを中止しました。",
                    )
                    self._action_btn.setEnabled(True)
                    return
            else:
                ret = QMessageBox.warning(
                    self, "チェックサム未確認",
                    "このリリースにはチェックサムファイルがありません。\n"
                    "信頼できるソースからダウンロードされた場合のみ続行してください。\n\n続行しますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ret != QMessageBox.StandardButton.Yes:
                    self._action_btn.setEnabled(True)
                    return
            self._installer_path = dest
            self._action_btn.setText("今すぐ更新して再起動")
            self._action_btn.setEnabled(True)
        except Exception:
            self._progress_bar.hide()
            self._action_btn.setEnabled(True)
            self._message_label.setText("ダウンロードに失敗しました。後で再試行してください。")

    def _do_install(self):
        import sys
        import os
        reply = QMessageBox.question(
            self, "更新確認",
            "インストーラーを起動してアプリを終了します。よいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if getattr(sys, "frozen", False):
            launch_installer(self._installer_path)
            # os._exit でクリーンアップをスキップし即座にプロセスを終了
            # （sys.exit だと Qt/Python の後処理中に DLL ロックが残る）
            os._exit(0)
        else:
            QMessageBox.information(
                self, "開発環境",
                f"インストーラーのパス:\n{self._installer_path}"
            )
