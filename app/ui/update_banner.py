import os
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QProgressBar, QMessageBox,
)
from app.utils.updater import UpdateChecker, DownloadThread, launch_installer, verify_installer


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
            if self._installer_path:
                self._installer_path = None
                self._action_btn.setText("ダウンロード")
                QMessageBox.warning(
                    self, "ファイルが見つかりません",
                    "インストーラーが見つかりません。\n"
                    "Windows セキュリティによって検疫された可能性があります。\n\n"
                    "Windowsセキュリティ → 保護の履歴 から許可するか、\n"
                    "再度ダウンロードしてください。",
                )
                return
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
        self._download_thread = DownloadThread(
            self._update_info["download_url"], dest, parent=self
        )
        self._download_thread.progress.connect(
            lambda c, t: self._progress_bar.setValue(int(c / t * 100))
        )
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.failed.connect(self._on_download_failed)
        self._download_thread.start()

    def _on_download_finished(self, dest: str):
        self._progress_bar.hide()
        # Zone.Identifier ADS を削除して Defender の検疫を防ぐ（チェックサム検証済みのため安全）
        try:
            import ctypes
            ctypes.windll.kernel32.DeleteFileW(dest + ":Zone.Identifier")
        except Exception:
            pass
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

    def _on_download_failed(self, _error: str):
        self._progress_bar.hide()
        self._action_btn.setEnabled(True)
        self._message_label.setText("ダウンロードに失敗しました。後で再試行してください。")

    def stop_threads(self):
        """アプリ終了時にバックグラウンドスレッドを安全に停止する。"""
        dl = getattr(self, "_download_thread", None)
        if dl is not None and dl.isRunning():
            dl.cancel()
            dl.quit()
            if not dl.wait(3000):
                dl.terminate()
                dl.wait(1000)

        checker = getattr(self, "_checker", None)
        if checker is not None and checker.isRunning():
            checker.quit()
            if not checker.wait(3000):
                checker.terminate()
                checker.wait(1000)

    def _do_install(self):
        reply = QMessageBox.question(
            self, "更新確認",
            "インストーラーを起動してアプリを終了します。よいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            launch_installer(self._installer_path)
        except Exception as e:
            QMessageBox.critical(
                self, "インストーラー起動エラー",
                "インストーラーを自動起動できませんでした。\n"
                "手動でインストーラーを実行してください:\n\n"
                f"{self._installer_path}\n\nエラー: {e}",
            )
            return
        # closeEvent 経由で終了する（closeEvent 内の TerminateProcess + os._exit が確実）
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self.window().close)
