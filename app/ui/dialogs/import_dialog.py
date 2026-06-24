# app/ui/dialogs/import_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QFileDialog, QMessageBox,
)
from app.services.import_service import ImportService


class ImportDialog(QDialog):
    def __init__(self, engine, staff_name: str, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._staff_name = staff_name
        self.setWindowTitle("Excelインポート")
        self.setFixedSize(500, 180)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        file_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Excelファイルを選択してください")
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(self._path_edit)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)
        self._overwrite_chk = QCheckBox("既存の会員番号を上書きする")
        layout.addWidget(self._overwrite_chk)
        btn_row = QHBoxLayout()
        import_btn = QPushButton("インポート実行")
        import_btn.setDefault(True)
        import_btn.clicked.connect(self._on_import)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Excelファイルを選択", "", "Excel (*.xlsx *.xls)")
        if path:
            self._path_edit.setText(path)

    def _on_import(self):
        path = self._path_edit.text()
        if not path:
            QMessageBox.warning(self, "エラー", "ファイルを選択してください。")
            return
        try:
            svc = ImportService(self._engine)
            result = svc.import_excel(path, overwrite=self._overwrite_chk.isChecked(),
                                      staff_name=self._staff_name)
            QMessageBox.information(
                self, "インポート完了",
                f"追加：{result['added']}件\n更新：{result['updated']}件\nスキップ：{result['skipped']}件"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "インポートエラー", str(e))
