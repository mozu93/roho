# app/ui/notification_banner.py
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from app.services.activity_service import ActivityService


class NotificationBanner(QWidget):
    navigate_to_member = pyqtSignal(int, str, int)  # member_id, event_type, event_id

    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._config = config
        self._svc = ActivityService(engine)
        self._items = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.setStyleSheet(
            "NotificationBanner { background:#FEF9C3; border-bottom:2px solid #FDE047; }"
        )
        main = QVBoxLayout(self)
        main.setContentsMargins(6, 4, 6, 4)

        header_row = QHBoxLayout()
        self._title_label = QLabel("新着 0件")
        self._title_label.setStyleSheet("font-weight:bold;")
        header_row.addWidget(self._title_label)
        header_row.addStretch()
        confirm_all_btn = QPushButton("すべて既読にする")
        confirm_all_btn.setFixedHeight(24)
        confirm_all_btn.clicked.connect(self._on_confirm_all)
        header_row.addWidget(confirm_all_btn)
        main.addLayout(header_row)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        main.addWidget(self._list_widget)

    def refresh(self):
        staff_name = self._config.last_staff_name
        if not staff_name:
            self.hide()
            return

        self._items = self._svc.get_unread(staff_name)
        # リストをクリア
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._items:
            self.hide()
            return

        self.show()
        self._title_label.setText(f"新着 {len(self._items)}件")

        for item in self._items[:10]:  # 最大10件表示
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            dt_str = item["logged_at"].strftime("%m-%d %H:%M")
            event_icon = "📝" if item["type"] == "activity" else "✏️"
            text = (
                f"{dt_str}　{item['org_name']}　"
                f"{event_icon}{item['content']}（{item['logged_by']}）"
            )
            lbl = QLabel(text)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            member_id = item["member_id"]
            event_type = item["type"]
            event_id = item["event_id"]
            lbl.mouseDoubleClickEvent = lambda e, mid=member_id, et=event_type, eid=event_id: \
                self.navigate_to_member.emit(mid, et, eid)
            row_layout.addWidget(lbl)
            row_layout.addStretch()

            # 個別既読ボタン
            conf_btn = QPushButton("✓")
            conf_btn.setFixedSize(24, 20)
            conf_id = item["id"]
            conf_type = item["type"]
            conf_event_id = item["event_id"]
            conf_btn.clicked.connect(
                lambda _, t=conf_type, eid=conf_event_id: self._on_confirm_one(t, eid)
            )
            row_layout.addWidget(conf_btn)
            self._list_layout.addWidget(row)

    def _on_confirm_one(self, event_type: str, event_id: int):
        staff_name = self._config.last_staff_name
        if event_type == "activity":
            self._svc.confirm_activity(event_id, staff_name)
        else:
            self._svc.confirm_change(event_id, staff_name)
        self.refresh()

    def _on_confirm_all(self):
        self._svc.confirm_all(self._config.last_staff_name)
        self.refresh()
