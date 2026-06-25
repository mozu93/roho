# app/ui/label_tab.py
import os
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QComboBox, QGroupBox, QHeaderView, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from app.services.label_service import LabelService
from app.services.member_service import MemberService, INS_TYPES
from app.services.pdf.label_pdf import LABEL_LAYOUTS, FONT_OPTIONS, DEFAULT_LAYOUT_KEY, DEFAULT_FONT_KEY

BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}


class LabelTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = LabelService(engine)
        self._member_svc = MemberService(engine)
        self._all_members = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 絞り込みエリア
        filter_group = QGroupBox("絞り込み・クイック選択")
        filter_layout = QVBoxLayout(filter_group)
        kw_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・住所で検索")
        self._keyword_edit.textChanged.connect(self._on_filter_changed)
        kw_row.addWidget(self._keyword_edit)
        filter_layout.addLayout(kw_row)

        flag_row = QHBoxLayout()
        flag_row.addWidget(QLabel("枝番："))
        self._ins_checks = {}
        for ins_type in INS_TYPES:
            chk = QCheckBox(BRANCH_LABELS[ins_type])
            chk.stateChanged.connect(self._on_filter_changed)
            self._ins_checks[ins_type] = chk
            flag_row.addWidget(chk)
        flag_row.addSpacing(12)
        self._tokubetsu_chk = QCheckBox("特別加入のみ")
        self._tokubetsu_chk.stateChanged.connect(self._on_filter_changed)
        flag_row.addWidget(self._tokubetsu_chk)
        self._withdrawn_chk = QCheckBox("脱会済みを含む")
        self._withdrawn_chk.stateChanged.connect(self._on_filter_changed)
        flag_row.addWidget(self._withdrawn_chk)
        flag_row.addStretch()
        filter_layout.addLayout(flag_row)

        quick_row = QHBoxLayout()
        all_btn = QPushButton("全アクティブ会員を選択")
        all_btn.clicked.connect(self._on_select_all_active)
        tokubetsu_btn = QPushButton("特別加入のみを選択")
        tokubetsu_btn.clicked.connect(self._on_select_tokubetsu)
        clear_btn = QPushButton("選択を解除")
        clear_btn.clicked.connect(self._on_clear_selection)
        quick_row.addWidget(all_btn)
        quick_row.addWidget(tokubetsu_btn)
        quick_row.addWidget(clear_btn)
        quick_row.addStretch()
        filter_layout.addLayout(quick_row)
        layout.addWidget(filter_group)

        # 一覧テーブル
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["選択", "会員No.", "事業所名", "住所（郵送先優先）", "特別"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 40)
        layout.addWidget(self._table)

        # ラベル設定
        settings_group = QGroupBox("ラベル設定")
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.addWidget(QLabel("用紙："))
        self._layout_combo = QComboBox()
        for key, lyt in LABEL_LAYOUTS.items():
            self._layout_combo.addItem(lyt.name, key)
        settings_layout.addWidget(self._layout_combo)
        settings_layout.addWidget(QLabel("フォント："))
        self._font_combo = QComboBox()
        for label in FONT_OPTIONS:
            self._font_combo.addItem(label)
        if DEFAULT_FONT_KEY in FONT_OPTIONS:
            self._font_combo.setCurrentText(DEFAULT_FONT_KEY)
        settings_layout.addWidget(self._font_combo)
        self._barcode_chk = QCheckBox("バーコード印字")
        settings_layout.addWidget(self._barcode_chk)
        settings_layout.addStretch()
        layout.addWidget(settings_group)

        # 出力ボタン
        btn_row = QHBoxLayout()
        self._count_label = QLabel("選択中 0件")
        btn_row.addWidget(self._count_label)
        btn_row.addStretch()
        export_btn = QPushButton("選択中をPDF出力")
        export_btn.setFixedHeight(32)
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        ins_types = [t for t, chk in self._ins_checks.items() if chk.isChecked()]
        self._all_members = self._svc.get_label_targets(
            active_only=True,
            include_withdrawn=self._withdrawn_chk.isChecked(),
            ins_types=ins_types if ins_types else None,
            tokubetsu_only=self._tokubetsu_chk.isChecked(),
        )
        kw = self._keyword_edit.text().strip().lower()
        if kw:
            self._all_members = [
                m for m in self._all_members
                if kw in (m.org_name or "").lower()
                or kw in (m.org_kana or "").lower()
                or kw in (m.address or "").lower()
                or kw in (m.address_mail or "").lower()
            ]
        self._populate_table(check_all=False)

    def _on_filter_changed(self):
        self._refresh()

    def _populate_table(self, check_all: bool = False):
        self._table.setRowCount(len(self._all_members))
        for row, m in enumerate(self._all_members):
            chk = QCheckBox()
            chk.setChecked(check_all)
            chk.stateChanged.connect(self._update_count)
            self._table.setCellWidget(row, 0, chk)
            self._table.setItem(row, 1, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_name))
            entry = self._svc.build_label_entry(m)
            addr = f"〒{entry.postal_code}　{entry.address1}" if entry.postal_code else entry.address1
            self._table.setItem(row, 3, QTableWidgetItem(addr))
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            self._table.setItem(row, 4, QTableWidgetItem("●" if has_tokubetsu else ""))
        self._update_count()

    def _update_count(self):
        count = sum(
            1 for row in range(self._table.rowCount())
            if (w := self._table.cellWidget(row, 0)) and w.isChecked()
        )
        self._count_label.setText(f"選択中 {count}件")

    def _selected_members(self) -> list:
        return [
            self._all_members[row]
            for row in range(self._table.rowCount())
            if (w := self._table.cellWidget(row, 0)) and w.isChecked()
        ]

    def _on_select_all_active(self):
        self._keyword_edit.clear()
        for chk in self._ins_checks.values():
            chk.setChecked(False)
        self._tokubetsu_chk.setChecked(False)
        self._withdrawn_chk.setChecked(False)
        self._refresh()
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(True)
        self._update_count()

    def _on_select_tokubetsu(self):
        self._tokubetsu_chk.setChecked(True)
        self._refresh()
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(True)
        self._update_count()

    def _on_clear_selection(self):
        for row in range(self._table.rowCount()):
            if w := self._table.cellWidget(row, 0):
                w.setChecked(False)
        self._update_count()

    def _on_export(self):
        members = self._selected_members()
        if not members:
            QMessageBox.warning(self, "エラー", "出力する会員を選択してください。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF保存先を選択", "宛名ラベル.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            layout_key = self._layout_combo.currentData()
            font_key = self._font_combo.currentText()
            barcode = self._barcode_chk.isChecked()
            self._svc.generate_pdf(members, path, layout_key, font_key, barcode)
            QMessageBox.information(self, "完了", f"{len(members)}件のラベルPDFを出力しました。\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
