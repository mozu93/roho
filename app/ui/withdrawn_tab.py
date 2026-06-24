from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class WithdrawnTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).addWidget(QLabel("脱会済みタブ（実装予定）"))
