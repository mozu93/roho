from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QFileDialog, QMessageBox, QDoubleSpinBox,
    QSpinBox,
)
from app.services.label_service import LabelService
from app.services.pdf.label_pdf import LABEL_LAYOUTS, FONT_OPTIONS, DEFAULT_FONT_KEY

_LAYOUTS = {
    "a_one_28185": LABEL_LAYOUTS["a_one_28185"],  # 3列×6行
    "a_one_28187": LABEL_LAYOUTS["a_one_28187"],  # 2列×6行
}


class LabelDialog(QDialog):
    def __init__(self, engine, members: list, config=None, config_path=None, parent=None):
        super().__init__(parent)
        self._svc = LabelService(engine)
        self._members = members
        self._config = config
        self._config_path = config_path
        self._offsets = dict(getattr(config, "label_offsets", {}) or {})
        self.setWindowTitle(f"ラベル出力  ({len(members)}件)")
        self.setMinimumWidth(360)
        self.resize(430, 270)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("用紙："))
        self._layout_combo = QComboBox()
        for key, lyt in _LAYOUTS.items():
            self._layout_combo.addItem(lyt.name, key)
        self._layout_combo.currentIndexChanged.connect(self._load_offset_fields)
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

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("印刷位置補正：横"))
        self._offset_h = self._make_offset_spin()
        offset_row.addWidget(self._offset_h)
        offset_row.addWidget(QLabel("縦"))
        self._offset_v = self._make_offset_spin()
        offset_row.addWidget(self._offset_v)
        offset_row.addStretch()
        layout.addLayout(offset_row)
        note = QLabel("印刷位置がずれる場合のみ調整してください（右・上へ動かす場合は正の値）。")
        note.setStyleSheet("color: #555; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._load_offset_fields()
        self._offset_h.valueChanged.connect(self._remember_offset)
        self._offset_v.valueChanged.connect(self._remember_offset)

        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("印刷開始位置："))
        self._start_slot = QSpinBox()
        self._start_slot.setMinimum(1)
        self._start_slot.setFixedWidth(70)
        self._start_slot.setToolTip(
            "ラベル用紙の何面目から印刷するかを指定します。使用済みの面を避ける場合に使います。")
        start_row.addWidget(self._start_slot)
        self._start_slot_suffix = QLabel()
        start_row.addWidget(self._start_slot_suffix)
        start_row.addStretch()
        layout.addLayout(start_row)
        self._layout_combo.currentIndexChanged.connect(self._update_start_slot)
        self._update_start_slot()

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

    @staticmethod
    def _make_offset_spin():
        spin = QDoubleSpinBox()
        spin.setRange(-15.0, 15.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" mm")
        spin.setFixedWidth(90)
        return spin

    def _load_offset_fields(self):
        key = self._layout_combo.currentData()
        values = self._offsets.get(key, {})
        self._offset_h.setValue(float(values.get("h_mm", 0.0)))
        self._offset_v.setValue(float(values.get("v_mm", 0.0)))

    def _remember_offset(self):
        """用紙を切り替えても、入力中の補正値を保持する。"""
        key = self._layout_combo.currentData()
        self._offsets[key] = {
            "h_mm": self._offset_h.value(),
            "v_mm": self._offset_v.value(),
        }

    def _update_start_slot(self):
        """用紙ごとの面数に合わせて印刷開始位置の範囲を更新する。"""
        layout = _LAYOUTS[self._layout_combo.currentData()]
        per_page = layout.cols * layout.rows
        self._start_slot.setMaximum(per_page)
        self._start_slot_suffix.setText(f"面目から（全{per_page}面）")

    def _save_current_offset(self):
        key = self._layout_combo.currentData()
        self._offsets[key] = {
            "h_mm": self._offset_h.value(),
            "v_mm": self._offset_v.value(),
        }
        if self._config is not None:
            self._config.label_offsets = self._offsets
            if self._config_path:
                self._config.save(self._config_path)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF保存先を選択", "宛名ラベル.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            layout_key = self._layout_combo.currentData()
            font_key = self._font_combo.currentText()
            self._save_current_offset()
            offset = self._offsets[layout_key]
            self._svc.generate_pdf(
                self._members, path, layout_key, font_key, False,
                offset_h_mm=offset["h_mm"], offset_v_mm=offset["v_mm"],
                start_slot=self._start_slot.value() - 1,
            )
            QMessageBox.information(self, "完了", f"{len(self._members)}件のラベルPDFを出力しました。\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
