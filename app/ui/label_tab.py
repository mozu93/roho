from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel


class LabelTab(QWidget):
    def __init__(self, engine, config, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).addWidget(QLabel("ラベル出力タブ（実装予定）"))
