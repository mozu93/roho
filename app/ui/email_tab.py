from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class EmailTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).addWidget(QLabel("メール送信タブ（実装予定）"))
