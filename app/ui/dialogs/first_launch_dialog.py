import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QRadioButton, QButtonGroup, QWidget,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class FirstLaunchDialog(QDialog):
    """初回起動時にデータの保存場所を選択させるダイアログ。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_dir = ""  # 空文字 = ローカル（設定ファイルと同フォルダ）
        self.setWindowTitle("初回セットアップ - データ保存場所の選択")
        self.setMinimumWidth(500)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("データの保存場所を選んでください")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        desc = QLabel(
            "このPCだけで使う場合は「ローカル」を、\n"
            "複数のPCで同じデータを共有する場合は「共有フォルダ」を選んでください。\n"
            "（この設定は後から「設定」タブで変更できます）"
        )
        desc.setStyleSheet("color:#4B5563; line-height:1.5;")
        layout.addWidget(desc)

        # ── ローカル選択肢 ──
        self._local_radio = QRadioButton(
            "このPCだけで使う（ローカル保存）"
        )
        self._local_radio.setChecked(True)
        layout.addWidget(self._local_radio)

        local_hint = QLabel("　　データはアプリと同じフォルダに保存されます。")
        local_hint.setStyleSheet("color:#6B7280; font-size:9pt;")
        layout.addWidget(local_hint)

        # ── 共有フォルダ選択肢 ──
        self._shared_radio = QRadioButton(
            "共有フォルダを使う（複数PCで共有）"
        )
        layout.addWidget(self._shared_radio)

        shared_hint = QLabel(
            "　　ネットワーク上の共有フォルダを指定すると、\n"
            "　　複数のPCから同じデータにアクセスできます。"
        )
        shared_hint.setStyleSheet("color:#6B7280; font-size:9pt;")
        layout.addWidget(shared_hint)

        # フォルダ入力欄（共有選択時のみ表示）
        self._folder_area = QWidget()
        fa = QHBoxLayout(self._folder_area)
        fa.setContentsMargins(20, 4, 0, 4)
        fa.setSpacing(6)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText(
            "共有フォルダのパスを入力、または「参照」で選択..."
        )
        browse_btn = QPushButton("参照...")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._on_browse)
        fa.addWidget(self._folder_edit)
        fa.addWidget(browse_btn)
        self._folder_area.setEnabled(False)
        self._folder_area.setVisible(False)
        layout.addWidget(self._folder_area)

        group = QButtonGroup(self)
        group.addButton(self._local_radio)
        group.addButton(self._shared_radio)
        self._local_radio.toggled.connect(self._on_radio_changed)
        self._shared_radio.toggled.connect(self._on_radio_changed)

        layout.addSpacing(8)

        # ── ボタン行 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("この設定で開始する")
        ok_btn.setDefault(True)
        ok_btn.setFixedWidth(160)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_radio_changed(self):
        is_shared = self._shared_radio.isChecked()
        self._folder_area.setEnabled(is_shared)
        self._folder_area.setVisible(is_shared)
        self.adjustSize()

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "共有フォルダを選択", self._folder_edit.text() or ""
        )
        if folder:
            self._folder_edit.setText(folder)

    def _on_ok(self):
        if self._shared_radio.isChecked():
            path = self._folder_edit.text().strip()
            if not path:
                QMessageBox.warning(
                    self, "エラー", "共有フォルダのパスを入力してください。"
                )
                return
            if not os.path.isdir(path):
                QMessageBox.warning(
                    self, "エラー",
                    f"指定したフォルダが存在しません：\n{path}"
                    "\n\n先にフォルダを作成してから再度選択してください。",
                )
                return
            self.selected_dir = path
        else:
            self.selected_dir = ""
        self.accept()
