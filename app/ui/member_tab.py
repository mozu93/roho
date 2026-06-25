from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMenu,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from app.services.member_service import MemberService, INS_TYPES
from app.ui.dialogs.member_edit_dialog import MemberEditDialog
from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
from app.ui.dialogs.withdraw_dialog import WithdrawDialog
from app.ui.dialogs.import_dialog import ImportDialog

BRANCH_LABELS = {"ippan": "0", "kensetsu_koyou": "2", "ringyo": "4",
                 "kensetsu_genba": "5", "kensetsu_jimusho": "6"}
COLS = [
    "会員No.", "事業所名", "フリガナ", "所属・役職", "代表者名", "代表者フリガナ",
    "メール", "電話番号", "FAX番号", "郵便番号", "住所", "郵送先郵便番号",
    "郵送先住所", "郵送先宛名", "雇用保険事業所番号",
    "0", "2", "4", "5", "6", "特別", "一括", "最終対応日", "メモ"
]


class MemberTab(QWidget):
    def __init__(self, engine, config, config_path=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._config_path = config_path
        self._svc = MemberService(engine)
        self._members = []
        self._build_ui()
        self._apply_column_visibility()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 検索エリア
        search_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("事業所名・フリガナ・住所・電話番号で検索")
        self._keyword_edit.textChanged.connect(self._refresh)
        search_row.addWidget(self._keyword_edit)
        
        col_setting_btn = QPushButton("表示列選択")
        col_setting_btn.clicked.connect(self._on_show_column_menu_btn)
        search_row.addWidget(col_setting_btn)
        
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("枝番："))
        self._ins_checks = {}
        for ins_type in INS_TYPES:
            chk = QCheckBox(BRANCH_LABELS[ins_type])
            chk.stateChanged.connect(self._refresh)
            self._ins_checks[ins_type] = chk
            filter_row.addWidget(chk)
        filter_row.addSpacing(12)
        self._tokubetsu_chk = QCheckBox("特別加入のみ")
        self._tokubetsu_chk.stateChanged.connect(self._refresh)
        filter_row.addWidget(self._tokubetsu_chk)
        self._ikkatsu_chk = QCheckBox("一括認可のみ")
        self._ikkatsu_chk.stateChanged.connect(self._refresh)
        filter_row.addWidget(self._ikkatsu_chk)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # 一覧テーブル
        self._table = QTableWidget(0, len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(self._show_column_menu)
        self._table.itemDoubleClicked.connect(self._on_edit)
        layout.addWidget(self._table)

        # ボタン行
        btn_row = QHBoxLayout()
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self._on_add)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self._on_edit)
        withdraw_btn = QPushButton("脱会処理")
        withdraw_btn.clicked.connect(self._on_withdraw)
        history_btn = QPushButton("変更履歴")
        history_btn.clicked.connect(self._on_history)
        activity_btn = QPushButton("対応履歴")
        activity_btn.clicked.connect(self._on_activity)
        import_btn = QPushButton("Excelインポート")
        import_btn.clicked.connect(self._on_import)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        for btn in [add_btn, edit_btn, withdraw_btn, history_btn, activity_btn, import_btn, export_btn]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh(self):
        ins_types = [t for t, chk in self._ins_checks.items() if chk.isChecked()]
        members = self._svc.search(
            keyword=self._keyword_edit.text(),
            ins_types=ins_types if ins_types else None,
            tokubetsu_only=self._tokubetsu_chk.isChecked(),
            ikkatsu_only=self._ikkatsu_chk.isChecked(),
            active_only=True,
        )
        self._members = members
        self._table.setRowCount(len(members))
        for row, m in enumerate(members):
            active_types = {e.ins_type for e in m.insurance_entries}
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            has_ikkatsu = any(e.is_ikkatsu for e in m.insurance_entries)
            self._table.setItem(row, 0, QTableWidgetItem(m.member_number))
            self._table.setItem(row, 1, QTableWidgetItem(m.org_name))
            self._table.setItem(row, 2, QTableWidgetItem(m.org_kana or ""))
            self._table.setItem(row, 3, QTableWidgetItem(m.dept_title or ""))
            self._table.setItem(row, 4, QTableWidgetItem(m.rep_name or ""))
            self._table.setItem(row, 5, QTableWidgetItem(m.rep_kana or ""))
            self._table.setItem(row, 6, QTableWidgetItem(m.email or ""))
            self._table.setItem(row, 7, QTableWidgetItem(
                f"{m.tel_area or ''}-{m.tel or ''}" if m.tel else ""
            ))
            self._table.setItem(row, 8, QTableWidgetItem(
                f"{m.fax_area or ''}-{m.fax or ''}" if m.fax else ""
            ))
            self._table.setItem(row, 9, QTableWidgetItem(m.postal_code or ""))
            self._table.setItem(row, 10, QTableWidgetItem(m.address or ""))
            self._table.setItem(row, 11, QTableWidgetItem(m.postal_code_mail or ""))
            self._table.setItem(row, 12, QTableWidgetItem(m.address_mail or ""))
            self._table.setItem(row, 13, QTableWidgetItem(m.addressee_mail or ""))
            self._table.setItem(row, 14, QTableWidgetItem(m.employment_ins_no or ""))
            for col_idx, ins_type in enumerate(INS_TYPES):
                self._table.setItem(row, 15 + col_idx,
                    QTableWidgetItem("●" if ins_type in active_types else ""))
            self._table.setItem(row, 20, QTableWidgetItem("●" if has_tokubetsu else ""))
            self._table.setItem(row, 21, QTableWidgetItem("●" if has_ikkatsu else ""))
            self._table.setItem(row, 22, QTableWidgetItem(""))  # 最終対応日（Plan3で実装）
            self._table.setItem(row, 23, QTableWidgetItem(m.note or ""))

    def _selected_member(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._members):
            return None
        return self._members[row]

    def _on_add(self):
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_edit(self):
        m = self._selected_member()
        if not m:
            return
        dlg = MemberEditDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == MemberEditDialog.DialogCode.Accepted and dlg.saved:
            self._refresh()

    def _on_withdraw(self):
        m = self._selected_member()
        if not m:
            return
        dlg = WithdrawDialog(self._engine, self._config.last_staff_name, m.id, parent=self)
        if dlg.exec() == WithdrawDialog.DialogCode.Accepted and dlg.withdrawn:
            self._refresh()

    def _on_history(self):
        m = self._selected_member()
        if not m:
            return
        MemberHistoryDialog(self._engine, m.id, parent=self).exec()

    def _on_activity(self):
        m = self._selected_member()
        if not m:
            return
        from app.ui.dialogs.activity_log_dialog import ActivityLogDialog
        ActivityLogDialog(
            self._engine, m.id, self._config.last_staff_name, m.org_name, parent=self
        ).exec()
        self._refresh()  # 最終対応日更新のため

    def _on_import(self):
        dlg = ImportDialog(self._engine, self._config.last_staff_name, parent=self)
        if dlg.exec() == ImportDialog.DialogCode.Accepted:
            self._refresh()

    def _apply_column_visibility(self):
        hidden_cols = getattr(self._config, "hidden_columns", [])
        for i, col in enumerate(COLS):
            if col in hidden_cols:
                self._table.hideColumn(i)
            else:
                self._table.showColumn(i)

    def _show_column_menu(self, pos):
        global_pos = self._table.horizontalHeader().mapToGlobal(pos)
        self._exec_column_menu(global_pos)

    def _on_show_column_menu_btn(self):
        sender = self.sender()
        if sender:
            global_pos = sender.mapToGlobal(sender.rect().bottomLeft())
            self._exec_column_menu(global_pos)
        else:
            from PyQt6.QtGui import QCursor
            self._exec_column_menu(QCursor.pos())

    def _exec_column_menu(self, global_pos):
        menu = QMenu(self)
        for i, col in enumerate(COLS):
            action = QAction(col, self, checkable=True)
            action.setChecked(not self._table.isColumnHidden(i))
            # デフォルト値を使ってループのインデックスiをバインド
            action.triggered.connect(lambda checked, idx=i: self._toggle_column_visibility(idx, checked))
            menu.addAction(action)
        menu.exec(global_pos)

    def _toggle_column_visibility(self, idx, visible):
        if visible:
            self._table.showColumn(idx)
            if COLS[idx] in self._config.hidden_columns:
                self._config.hidden_columns.remove(COLS[idx])
        else:
            self._table.hideColumn(idx)
            if COLS[idx] not in self._config.hidden_columns:
                self._config.hidden_columns.append(COLS[idx])
        
        if self._config_path:
            try:
                self._config.save(self._config_path)
            except Exception as e:
                print(f"Failed to save config: {e}")

    def _on_export(self):
        from PyQt6.QtWidgets import QFileDialog
        from app.services.import_service import ExportService
        path, _ = QFileDialog.getSaveFileName(self, "Excel出力", "加入者名簿.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            ExportService(self._engine).export_excel(self._members, path)
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "完了", f"{len(self._members)}件を出力しました。")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "エラー", str(e))
