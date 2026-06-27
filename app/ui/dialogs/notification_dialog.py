from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from app.services.activity_service import ActivityService


class NotificationDialog(QDialog):
    navigate_to_member = pyqtSignal(int, str, int)

    def __init__(self, items: list, engine, config, parent=None):
        super().__init__(parent)
        self._items = items
        self._engine = engine
        self._config = config
        self._svc = ActivityService(engine)
        self.setWindowTitle(f"未読通知 {len(items)}件")
        self.setMinimumWidth(520)
        self.setMaximumHeight(560)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-size:13px; padding:4px 0;")
        layout.addWidget(self._title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._build_list()

        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        confirm_all_btn = QPushButton("すべて既読にする")
        confirm_all_btn.clicked.connect(self._confirm_all)
        btn_row.addWidget(confirm_all_btn)
        close_btn = QPushButton("閉じる")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_list(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._title_label.setText(f"未読通知が <b>{len(self._items)}</b> 件あります")
        self.setWindowTitle(f"未読通知 {len(self._items)}件")

        for i, item in enumerate(self._items):
            row = QWidget()
            row_h = QHBoxLayout(row)
            row_h.setContentsMargins(4, 10, 4, 10)
            row_h.setSpacing(8)

            dt_str = item["logged_at"].strftime("%m/%d %H:%M")
            icon = "📝" if item["type"] == "activity" else "✏️"
            lbl = QLabel(
                f"<b>{dt_str}</b>　{item['org_name']}　"
                f"{icon} {item['content']}　"
                f"<span style='color:#888;'>（{item['logged_by']}）</span>"
            )
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.setToolTip("ダブルクリックで対象会員へジャンプ")

            mid = item["member_id"]
            et = item["type"]
            eid = item["event_id"]
            lbl.mouseDoubleClickEvent = lambda _e, m=mid, t=et, e=eid: self._jump(m, t, e)

            chk = QCheckBox()
            chk.setToolTip("チェックで既読にする")
            chk.toggled.connect(
                lambda checked, t=item["type"], e=item["event_id"]:
                    self._confirm_one(t, e) if checked else None
            )

            row_h.addWidget(lbl, 1)
            row_h.addWidget(chk)
            self._list_layout.addWidget(row)

            # 区切り線（最後の行以外）
            if i < len(self._items) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                self._list_layout.addWidget(line)

        self._list_layout.addStretch()

    def _reload(self):
        self._items = self._svc.get_unread(self._config.last_staff_name)
        if not self._items:
            self.accept()
            return
        self._build_list()

    def _jump(self, member_id: int, event_type: str, event_id: int):
        self.navigate_to_member.emit(member_id, event_type, event_id)

    def _confirm_one(self, event_type: str, event_id: int):
        staff_name = self._config.last_staff_name
        if event_type == "activity":
            self._svc.confirm_activity(event_id, staff_name)
        else:
            self._svc.confirm_change(event_id, staff_name)
        self._reload()

    def _confirm_all(self):
        self._svc.confirm_all(self._config.last_staff_name)
        self.accept()
