from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PyQt6.QtCore import Qt
from app.version import __version__


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("バージョン情報")
        self.setFixedSize(340, 200)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 20, 24, 16)

        title = QLabel("労働保険名簿管理システム")
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        ver = QLabel(f"バージョン　{__version__}")
        ver.setStyleSheet("font-size:11px; color:#555;")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ver)

        layout.addStretch()

        copy_lbl = QLabel("© 2026　労働保険事務組合")
        copy_lbl.setStyleSheet("color:#888; font-size:9pt;")
        copy_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copy_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.setDefault(True)
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
