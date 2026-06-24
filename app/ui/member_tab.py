from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class MemberTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).addWidget(QLabel("名簿タブ（実装予定）"))
