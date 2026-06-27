from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QMessageBox,
)
from app.database.connection import get_session
from app.database.models import Staff


class StaffLoginDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self.selected_name: str | None = None
        self.setWindowTitle("担当者を選択してください")
        self.setFixedSize(320, 140)
        self._build_ui()
        self._load_staff()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("担当者："))
        self._combo = QComboBox()
        self._combo.setEditable(True)
        layout.addWidget(self._combo)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _load_staff(self):
        with get_session(self._engine) as session:
            staff_list = (
                session.query(Staff)
                .filter_by(is_active=True)
                .order_by(Staff.id)
                .all()
            )
            for s in staff_list:
                self._combo.addItem(s.name)

    def _on_ok(self):
        name = self._combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "エラー", "担当者名を入力または選択してください。")
            return
            
        with get_session(self._engine) as session:
            staff = session.query(Staff).filter_by(name=name).first()
            if not staff:
                staff = Staff(name=name, is_active=True)
                session.add(staff)
                # Session is automatically committed by get_session

        self.selected_name = name
        self.accept()
