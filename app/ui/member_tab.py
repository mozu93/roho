import html
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMenu,
    QGroupBox, QScrollArea, QTextEdit, QMessageBox,
    QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QBrush, QFont
from PyQt6.QtWidgets import QApplication
from app.services.member_service import MemberService, INS_TYPES
from app.services.activity_service import ActivityService
from app.ui.dialogs.member_edit_dialog import MemberEditDialog
from app.ui.dialogs.member_history_dialog import MemberHistoryDialog
from app.ui.dialogs.withdraw_dialog import WithdrawDialog
from app.ui.dialogs.import_dialog import ImportDialog


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)

        self_text = self.text()
        other_text = other.text()

        if not self_text and not other_text:
            return False

        table = self.tableWidget()
        is_ascending = True
        if table:
            header = table.horizontalHeader()
            is_ascending = (header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder)

        if not self_text:
            return not is_ascending
        if not other_text:
            return is_ascending

        try:
            return float(self_text) < float(other_text)
        except ValueError:
            pass

        return self_text < other_text


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
        self._activity_svc = ActivityService(engine)
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

        # 中央の分割エリア（テーブルと対応履歴パネル）
        content_layout = QHBoxLayout()

        # 一覧テーブル
        self._table = QTableWidget(0, len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.horizontalHeader().customContextMenuRequested.connect(self._show_column_menu)
        self._table.itemDoubleClicked.connect(self._on_edit)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        content_layout.addWidget(self._table, stretch=2)

        # 対応履歴パネル
        self._activity_panel = QGroupBox("対応履歴")
        self._activity_panel.setFixedWidth(380)
        panel_layout = QVBoxLayout(self._activity_panel)

        # プレースホルダー（未選択時）
        self._placeholder_label = QLabel("名簿から会員を選択してください。")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._placeholder_label)

        # 対応履歴のコンテンツ（選択時に表示）
        self._activity_content = QWidget()
        content_vbox = QVBoxLayout(self._activity_content)
        content_vbox.setContentsMargins(0, 0, 0, 0)

        # 新規メモ入力エリア
        input_group = QGroupBox("新規対応メモを追加")
        input_layout = QVBoxLayout(input_group)

        # カテゴリ選択
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("カテゴリ："))
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("カテゴリなし", None)
        for cat in self._activity_svc.get_categories():
            self._cat_combo.addItem(cat.name, cat.id)
        cat_row.addWidget(self._cat_combo)
        cat_row.addStretch()
        input_layout.addLayout(cat_row)

        # テキスト入力
        self._content_edit = QTextEdit()
        self._content_edit.setFixedHeight(160)
        self._content_edit.setPlaceholderText("対応内容を入力してください")
        input_layout.addWidget(self._content_edit)

        # 保存ボタン
        save_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save_activity)
        save_row.addStretch()
        save_row.addWidget(save_btn)
        input_layout.addLayout(save_row)

        content_vbox.addWidget(input_group, stretch=1)

        # 履歴表示エリア
        log_scroll = QScrollArea()
        log_scroll.setWidgetResizable(True)
        self._log_container = QWidget()
        self._log_vbox = QVBoxLayout(self._log_container)
        self._log_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        log_scroll.setWidget(self._log_container)
        content_vbox.addWidget(log_scroll, stretch=2)
        panel_layout.addWidget(self._activity_content)

        # 初期状態は非表示
        self._activity_content.setVisible(False)

        content_layout.addWidget(self._activity_panel)
        layout.addLayout(content_layout)

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
        import_btn = QPushButton("Excelインポート")
        import_btn.clicked.connect(self._on_import)
        export_btn = QPushButton("Excel出力")
        export_btn.clicked.connect(self._on_export)
        for btn in [add_btn, edit_btn, withdraw_btn, history_btn, import_btn, export_btn]:
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh(self):
        self._table.setSortingEnabled(False)
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
            has_tokubetsu = any(e.is_tokubetsu for e in m.insurance_entries)
            has_ikkatsu = any(e.is_ikkatsu for e in m.insurance_entries)
            
            no_item = SortableTableWidgetItem(m.member_number)
            no_item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._table.setItem(row, 0, no_item)
            
            self._table.setItem(row, 1, SortableTableWidgetItem(m.org_name))
            self._table.setItem(row, 2, SortableTableWidgetItem(m.org_kana or ""))
            self._table.setItem(row, 3, SortableTableWidgetItem(m.dept_title or ""))
            self._table.setItem(row, 4, SortableTableWidgetItem(m.rep_name or ""))
            self._table.setItem(row, 5, SortableTableWidgetItem(m.rep_kana or ""))
            self._table.setItem(row, 6, SortableTableWidgetItem(m.email or ""))
            self._table.setItem(row, 7, SortableTableWidgetItem(
                f"{m.tel_area or ''}-{m.tel or ''}" if m.tel else ""
            ))
            self._table.setItem(row, 8, SortableTableWidgetItem(
                f"{m.fax_area or ''}-{m.fax or ''}" if m.fax else ""
            ))
            self._table.setItem(row, 9, SortableTableWidgetItem(m.postal_code or ""))
            self._table.setItem(row, 10, SortableTableWidgetItem(m.address or ""))
            self._table.setItem(row, 11, SortableTableWidgetItem(m.postal_code_mail or ""))
            self._table.setItem(row, 12, SortableTableWidgetItem(m.address_mail or ""))
            self._table.setItem(row, 13, SortableTableWidgetItem(m.addressee_mail or ""))
            self._table.setItem(row, 14, SortableTableWidgetItem(m.employment_ins_no or ""))
            ins_map = {e.ins_type: e for e in m.insurance_entries}
            for col_idx, ins_type in enumerate(INS_TYPES):
                entry = ins_map.get(ins_type)
                val = entry.ins_number if entry else ""
                item = SortableTableWidgetItem(val)
                if entry:
                    if entry.is_tokubetsu and entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(216, 180, 254)))  # 薄い紫
                    elif entry.is_tokubetsu:
                        item.setBackground(QBrush(QColor(226, 240, 217)))  # 薄い緑
                    elif entry.is_ikkatsu:
                        item.setBackground(QBrush(QColor(255, 224, 178)))  # 薄いオレンジ
                self._table.setItem(row, 15 + col_idx, item)
            self._table.setItem(row, 20, SortableTableWidgetItem("●" if has_tokubetsu else ""))
            self._table.setItem(row, 21, SortableTableWidgetItem("●" if has_ikkatsu else ""))
            self._table.setItem(row, 22, SortableTableWidgetItem(""))  # 最終対応日（Plan3で実装）
            self._table.setItem(row, 23, SortableTableWidgetItem(m.note or ""))
        self._table.setSortingEnabled(True)

    def _selected_member(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if not item:
            return None
        member_id = item.data(Qt.ItemDataRole.UserRole)
        for m in self._members:
            if m.id == member_id:
                return m
        return None

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

    def _on_selection_changed(self):
        m = self._selected_member()
        if not m:
            self._placeholder_label.setVisible(True)
            self._activity_content.setVisible(False)
            self._activity_panel.setTitle("対応履歴")
            return
        
        self._placeholder_label.setVisible(False)
        self._activity_content.setVisible(True)
        self._activity_panel.setTitle(f"対応履歴 - {m.org_name}")
        self._load_activity_logs(m.id)

    def _load_activity_logs(self, member_id):
        # 既存ウィジェットを削除
        while self._log_vbox.count():
            item = self._log_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        logs = self._activity_svc.get_logs(member_id)
        for log in logs:
            cat_names = "・".join(c.name for c in log.categories) if log.categories else "カテゴリなし"
            entry = QWidget()
            entry.setStyleSheet("border:1px solid #ddd; border-radius:4px; padding:4px; margin:2px;")
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(6, 4, 6, 4)
            header = QLabel(
                f"<b>{log.logged_at.strftime('%Y-%m-%d %H:%M')}</b>　{html.escape(log.logged_by)}　"
                f"<span style='color:#666'>[{html.escape(cat_names)}]</span>"
            )
            content = QLabel(log.content)
            content.setTextFormat(Qt.TextFormat.PlainText)
            content.setWordWrap(True)
            entry_layout.addWidget(header)
            entry_layout.addWidget(content)
            self._log_vbox.addWidget(entry)

        if not logs:
            self._log_vbox.addWidget(QLabel("対応履歴はありません。"))

    def _on_save_activity(self):
        m = self._selected_member()
        if not m:
            return
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "入力エラー", "内容を入力してください。")
            return
        cat_id = self._cat_combo.currentData()
        cat_ids = [cat_id] if cat_id is not None else []
        try:
            self._activity_svc.add_log(m.id, content, cat_ids, self._config.last_staff_name)
            self._content_edit.clear()
            self._cat_combo.setCurrentIndex(0)
            self._load_activity_logs(m.id)
            self._refresh()  # 最終対応日更新のため
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))

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
