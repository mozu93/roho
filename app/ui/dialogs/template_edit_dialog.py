# app/ui/dialogs/template_edit_dialog.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QTextEdit, QPushButton, QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt, QEvent
from app.services.template_service import TemplateService

_PLACEHOLDERS = [
    ("{事業所名}", "事業所名"),
    ("{代表者名}", "代表者名"),
    ("{会員No.}", "会員No."),
    ("{所属・役職}", "所属・役職"),
]


class TemplateEditDialog(QDialog):
    def __init__(self, engine, template_id: int | None = None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._template_id = template_id
        self._svc = TemplateService(engine)
        self.saved = False
        self._last_focused = None
        self.setWindowTitle("テンプレート編集" if template_id else "テンプレート追加")
        self.resize(600, 520)
        self._build_ui()
        if template_id:
            self._load(template_id)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("テンプレート")
        fl = QFormLayout(grp)
        self._name_edit = QLineEdit()
        self._subject_edit = QLineEdit()
        self._body_edit = QTextEdit()
        fl.addRow("テンプレート名：", self._name_edit)
        fl.addRow("件名：", self._subject_edit)
        fl.addRow("本文：", self._body_edit)
        layout.addWidget(grp)

        # 件名・本文のフォーカスを追跡してプレースホルダー挿入先を決定
        self._subject_edit.installEventFilter(self)
        self._body_edit.installEventFilter(self)

        # プレースホルダーボタン行
        ph_row = QHBoxLayout()
        ph_lbl = QLabel("挿入：")
        ph_lbl.setStyleSheet("color:#666; font-size:9pt;")
        ph_row.addWidget(ph_lbl)
        for token, label in _PLACEHOLDERS:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet("font-size:9pt; padding:0 8px;")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda checked, t=token: self._insert_placeholder(t))
            ph_row.addWidget(btn)
        ph_row.addStretch()
        layout.addLayout(ph_row)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn and obj in (self._subject_edit, self._body_edit):
            self._last_focused = obj
        return super().eventFilter(obj, event)

    def _insert_placeholder(self, token: str):
        target = self._last_focused or self._body_edit
        if isinstance(target, QLineEdit):
            pos = target.cursorPosition()
            text = target.text()
            target.setText(text[:pos] + token + text[pos:])
            target.setCursorPosition(pos + len(token))
        else:
            target.insertPlainText(token)

    def _load(self, template_id: int):
        t = self._svc.get(template_id)
        if t:
            self._name_edit.setText(t.name)
            self._subject_edit.setText(t.subject)
            self._body_edit.setPlainText(t.body)

    def _on_save(self):
        name = self._name_edit.text().strip()
        subject = self._subject_edit.text().strip()
        body = self._body_edit.toPlainText().strip()
        if not name or not subject or not body:
            QMessageBox.warning(self, "入力エラー", "テンプレート名・件名・本文は必須です。")
            return
        try:
            if self._template_id:
                self._svc.update(self._template_id, name, subject, body)
            else:
                self._svc.create(name, subject, body)
            self.saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
