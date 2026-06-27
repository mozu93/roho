from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QFileDialog, QMessageBox,
)
from app.services.label_service import LabelService
from app.services.pdf.label_pdf import LABEL_LAYOUTS, FONT_OPTIONS, DEFAULT_FONT_KEY

_LAYOUTS = {
    "a_one_28185": LABEL_LAYOUTS["a_one_28185"],  # 3列×6行
    "a_one_28187": LABEL_LAYOUTS["a_one_28187"],  # 2列×6行
}


class LabelDialog(QDialog):
    def __init__(self, engine, members: list, parent=None):
        super().__init__(parent)
        self._svc = LabelService(engine)
        self._members = members
        self.setWindowTitle(f"ラベル出力  ({len(members)}件)")
        self.setMinimumWidth(360)
        self.resize(400, 160)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("用紙："))
        self._layout_combo = QComboBox()
        for key, lyt in _LAYOUTS.items():
            self._layout_combo.addItem(lyt.name, key)
        row1.addWidget(self._layout_combo)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("フォント："))
        self._font_combo = QComboBox()
        for label in FONT_OPTIONS:
            self._font_combo.addItem(label)
        if DEFAULT_FONT_KEY in FONT_OPTIONS:
            self._font_combo.setCurrentText(DEFAULT_FONT_KEY)
        row2.addWidget(self._font_combo)
        row2.addStretch()
        layout.addLayout(row2)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.reject)
        export_btn = QPushButton("PDF出力")
        export_btn.setDefault(True)
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF保存先を選択", "宛名ラベル.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            layout_key = self._layout_combo.currentData()
            font_key = self._font_combo.currentText()
            self._svc.generate_pdf(self._members, path, layout_key, font_key, False)
            QMessageBox.information(self, "完了", f"{len(self._members)}件のラベルPDFを出力しました。\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
