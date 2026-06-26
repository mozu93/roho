from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from app.services.activity_service import ActivityService


class ActivitySearchDialog(QDialog):
    member_selected = pyqtSignal(int)  # 会員IDを通知

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._svc = ActivityService(engine)
        self._results = []
        self.setWindowTitle("対応履歴検索")
        self.resize(780, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("対応内容のキーワードを入力（空欄で全件表示）")
        self._keyword_edit.returnPressed.connect(self._search)
        search_row.addWidget(self._keyword_edit)
        search_btn = QPushButton("検索")
        search_btn.setDefault(True)
        search_btn.clicked.connect(self._search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["事業所名", "日時", "担当者", "カテゴリ", "内容"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tbl_font = QFont(QApplication.instance().font())
        tbl_font.setPointSize(tbl_font.pointSize() + 2)
        self._table.setFont(tbl_font)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        hint = QLabel("ダブルクリックで名簿タブの該当会員へ移動します。")
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
        self._results = self._svc.search_logs(keyword)
        self._table.setRowCount(len(self._results))
        for row, r in enumerate(self._results):
            cats = "・".join(r["categories"]) if r["categories"] else "なし"
            self._table.setItem(row, 0, QTableWidgetItem(r["org_name"]))
            self._table.setItem(row, 1, QTableWidgetItem(
                r["logged_at"].strftime("%Y-%m-%d %H:%M")
            ))
            self._table.setItem(row, 2, QTableWidgetItem(r["logged_by"]))
            self._table.setItem(row, 3, QTableWidgetItem(cats))
            self._table.setItem(row, 4, QTableWidgetItem(r["content"]))
        self._count_label.setText(f"{len(self._results)} 件")

    def _on_double_click(self, item):
        row = item.row()
        if 0 <= row < len(self._results):
            self.member_selected.emit(self._results[row]["member_id"])
            self.accept()
