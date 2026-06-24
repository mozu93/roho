import sys
import os
from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app_config.json")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("労働保険名簿管理システム")
    try:
        window = MainWindow(CONFIG_PATH)
        window.show()
        sys.exit(app.exec())
    except SystemExit as e:
        sys.exit(int(str(e)))


if __name__ == "__main__":
    main()
