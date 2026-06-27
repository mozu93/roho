from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QApplication,
    QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QBrush


from app.services.activity_service import ActivityService

_WITHDRAWN_COLOR = QColor(220, 220, 220)  # 委託解除済み行の背景色


class ActivitySearchDialog(QDialog):
    member_selected = pyqtSignal(int)           # アクティブ会員の選択
    withdrawn_member_selected = pyqtSignal(int) # 委託解除済み会員の選択

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._svc = ActivityService(engine)
        self._results = []
        self.setWindowTitle("対応履歴検索")
        self.resize(820, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("対応内容のキーワードを入力（空欄で全件表示）")
        self._keyword_edit.returnPressed.connect(self._search)
        search_row.addWidget(self._keyword_edit)
        self._include_inactive_chk = QCheckBox("委託解除済みも含む")
        self._include_inactive_chk.stateChanged.connect(self._search)
        search_row.addWidget(self._include_inactive_chk)
        search_btn = QPushButton("検索")
        search_btn.setDefault(True)
        search_btn.clicked.connect(self._search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["状態", "事業所名", "日時", "担当者", "カテゴリ", "内容"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 80)   # 状態列は狭く
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        hint = QLabel("ダブルクリックで該当会員へ移動します。")
        hint.setStyleSheet("color:#666; font-size:9pt;")
        layout.addWidget(hint)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _search(self):
        keyword = self._keyword_edit.text().strip()
        include_inactive = self._include_inactive_chk.isChecked()
        self._results = self._svc.search_logs(keyword, include_inactive=include_inactive)
        self._table.setRowCount(len(self._results))
        for row, r in enumerate(self._results):
            cats = "・".join(r["categories"]) if r["categories"] else "なし"
            is_active = r.get("is_active", True)
            status = "" if is_active else "委託解除済"
            items = [
                QTableWidgetItem(status),
                QTableWidgetItem(r["org_name"]),
                QTableWidgetItem(r["logged_at"].strftime("%Y-%m-%d %H:%M")),
                QTableWidgetItem(r["logged_by"]),
                QTableWidgetItem(cats),
                QTableWidgetItem(r["content"]),
            ]
            for col, item in enumerate(items):
                if not is_active:
                    item.setBackground(QBrush(_WITHDRAWN_COLOR))
                self._table.setItem(row, col, item)
        self._count_label.setText(f"{len(self._results)} 件")

    def _on_double_click(self, item):
        row = item.row()
        if 0 <= row < len(self._results):
            r = self._results[row]
            if r.get("is_active", True):
                self.member_selected.emit(r["member_id"])
            else:
                self.withdrawn_member_selected.emit(r["member_id"])
            self.accept()
