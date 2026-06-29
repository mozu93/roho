import sys
import os
from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app_config.json")


_APP_STYLE = """
QPushButton {
    padding: 5px 14px;
    border: 1px solid #b0b8c1;
    border-radius: 4px;
    background: #f5f7f9;
    color: #2d3748;
    min-height: 26px;
}
QPushButton:hover {
    background: #eaedf0;
    border-color: #718096;
}
QPushButton:pressed {
    background: #dde1e6;
    border-color: #4a5568;
}
QPushButton:default {
    background: #2563eb;
    color: white;
    border-color: #1d4ed8;
    font-weight: bold;
}
QPushButton:default:hover {
    background: #3b82f6;
    border-color: #2563eb;
}
QPushButton:disabled {
    color: #9ca3af;
    background: #f3f4f6;
    border-color: #e5e7eb;
}
QPushButton#sendButton {
    background: #2563eb;
    color: white;
    border-color: #1d4ed8;
    font-weight: bold;
}
QPushButton#sendButton:hover {
    background: #3b82f6;
    border-color: #2563eb;
}
QPushButton#sendButton:pressed {
    background: #1d4ed8;
}
QPushButton#sendButton:disabled {
    background: #93c5fd;
    border-color: #bfdbfe;
    color: white;
}
QListWidget, QLineEdit, QTextEdit, QComboBox {
    font-size: 11pt;
}
QTabBar::tab {
    font-size: 13pt;
}
QTableWidget {
    alternate-background-color: #f0f5fb;
    gridline-color: #d1d9e0;
}
QTableWidget::item:hover {
    background: #ffe4ec;
}
QTableWidget QHeaderView::section {
    background: #3d5a80;
    color: white;
    font-weight: bold;
    padding: 5px 6px;
    border: none;
    border-right: 1px solid #506e96;
    border-bottom: 2px solid #2c4260;
}
QTableWidget QHeaderView::section:first {
    border-left: none;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("労働保険名簿管理システム")
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(_APP_STYLE)
    code = 0
    try:
        window = MainWindow(CONFIG_PATH)
        window.show()
        code = app.exec()
    except SystemExit as e:
        code = int(str(e))
    os._exit(code)


if __name__ == "__main__":
    main()
