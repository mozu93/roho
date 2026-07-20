import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QSplitter, QLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from app.services.member_service import MemberService

# tel_area/tel・fax_area/fax は結合表示するため別扱い
_FIELD_LABELS = [
    ("company_code",      "管理No."),
    ("member_number",     "会員No."),
    ("is_member",         "会員区分"),
    ("org_name",          "事業所名"),
    ("org_kana",          "フリガナ"),
    ("dept_title",        "所属・役職"),
    ("rep_name",          "代表者名"),
    ("rep_kana",          "代表者フリガナ"),
    ("email",             "メール"),
    ("postal_code",       "郵便番号"),
    ("address",           "住所"),
    ("postal_code_mail",  "郵送先郵便番号"),
    ("address_mail",      "郵送先住所"),
    ("mail_org_name",     "郵送先事業所名"),
    ("mail_dept_title",   "郵送先所属・役職名"),
    ("mail_person_name",  "郵送先氏名"),
    ("employment_ins_no", "雇用保険事業所番号"),
    ("note",              "メモ"),
    ("is_active",         "在籍状態"),
    ("withdrawn_at",      "委託解除日"),
    ("withdraw_reason",   "委託解除理由"),
]

_INS_TYPE_LABELS = [
    ("ippan",            "一般（0）"),
    ("kensetsu_koyou",   "建設雇用（2）"),
    ("ringyo",           "林業（4）"),
    ("kensetsu_genba",   "建設現場（5）"),
    ("kensetsu_jimusho", "建設事務所（6）"),
]

_HIGHLIGHT = QColor("#FEF3C7")


class MemberHistoryDialog(QDialog):
    def __init__(self, engine, member_id: int, parent=None):
        super().__init__(parent)
        self._svc = MemberService(engine)
        self._member_id = member_id
        self._changes = []
        m = self._svc.get(member_id)
        self.setWindowTitle(f"変更履歴: {m.org_name if m else ''}")
        self.resize(760, 580)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上部: 履歴一覧
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["変更日時", "変更者", "変更理由"])
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.currentItemChanged.connect(
            lambda cur, _: self._show_comparison(self._table.currentRow())
        )
        splitter.addWidget(self._table)

        # 下部: 対比テーブル
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(4)

        self._compare_label = QLabel("履歴を選択すると変更前後の対比を表示します")
        self._compare_label.setStyleSheet("color:#6B7280; font-size:11px;")
        bl.addWidget(self._compare_label)

        self._compare_table = QTableWidget(0, 3)
        self._compare_table.setHorizontalHeaderLabels(["項目", "変更前", "変更後"])
        self._compare_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._compare_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._compare_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._compare_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._compare_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._compare_table.setWordWrap(True)
        bl.addWidget(self._compare_table)

        splitter.addWidget(bottom)
        splitter.setSizes([160, 360])
        layout.addWidget(splitter)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn = QPushButton("閉じる")
        btn.clicked.connect(self.accept)
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _load(self):
        self._changes = self._svc.get_changes(self._member_id)
        self._table.setRowCount(0)
        for c in self._changes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(
                c.changed_at.strftime("%Y/%m/%d %H:%M")))
            self._table.setItem(row, 1, QTableWidgetItem(c.changed_by or ""))
            self._table.setItem(row, 2, QTableWidgetItem(c.change_reason or ""))

    # ── 対比表示 ──

    def _show_comparison(self, row: int):
        self._compare_table.setRowCount(0)
        if row < 0 or row >= len(self._changes):
            self._compare_label.setText("履歴を選択すると変更前後の対比を表示します")
            return

        change = self._changes[row]
        snap_before = self._parse(change.snapshot)
        ts_before = change.changed_at.strftime("%Y/%m/%d %H:%M")

        if row > 0:
            snap_after = self._parse(self._changes[row - 1].snapshot)
            ts_after = self._changes[row - 1].changed_at.strftime("%Y/%m/%d %H:%M")
        else:
            # セッション内で変換することで DetachedInstanceError を回避
            snap_after = self._svc.get_current_snapshot(self._member_id)
            ts_after = "現在"

        reason = change.change_reason or "（なし）"
        self._compare_label.setText(
            f"変更前: {ts_before}　→　変更後: {ts_after}"
            f"　　変更理由: {reason}"
            "　　※差分のある行を黄色で表示"
        )

        # 基本情報フィールド
        for key, label in _FIELD_LABELS:
            self._add_row(label,
                          self._fmt(key, snap_before.get(key)),
                          self._fmt(key, snap_after.get(key)))

        # 電話・FAX（市外局番＋番号を結合）
        self._add_row("電話番号",
                      self._fmt_tel(snap_before, "tel_area", "tel"),
                      self._fmt_tel(snap_after,  "tel_area", "tel"))
        self._add_row("FAX番号",
                      self._fmt_tel(snap_before, "fax_area", "fax"),
                      self._fmt_tel(snap_after,  "fax_area", "fax"))

        # 保険加入情報（種別ごとに 保険番号 / 特別加入 / 継続一括 の3行）
        entries_before = snap_before.get("insurance_entries", [])
        entries_after  = snap_after.get("insurance_entries",  [])
        for ins_type, type_label in _INS_TYPE_LABELS:
            eb = next((e for e in entries_before if e.get("ins_type") == ins_type), {})
            ea = next((e for e in entries_after  if e.get("ins_type") == ins_type), {})
            if not eb and not ea:
                continue
            self._add_row(
                f"{type_label}　保険番号",
                self._fmt_ins_number(eb),
                self._fmt_ins_number(ea),
            )
            self._add_row(
                f"{type_label}　特別加入",
                "あり" if eb.get("is_tokubetsu") else "なし",
                "あり" if ea.get("is_tokubetsu") else "なし",
            )
            self._add_row(
                f"{type_label}　継続一括",
                "あり" if eb.get("is_ikkatsu") else "なし",
                "あり" if ea.get("is_ikkatsu") else "なし",
            )

    def _add_row(self, label: str, s_old: str, s_new: str):
        r = self._compare_table.rowCount()
        self._compare_table.insertRow(r)
        self._compare_table.setItem(r, 0, QTableWidgetItem(label))
        self._compare_table.setItem(r, 1, QTableWidgetItem(s_old))
        self._compare_table.setItem(r, 2, QTableWidgetItem(s_new))
        if s_old != s_new:
            for c in range(3):
                self._compare_table.item(r, c).setBackground(_HIGHLIGHT)

    # ── ユーティリティ ──

    def _parse(self, snapshot_json: str) -> dict:
        try:
            return json.loads(snapshot_json) if snapshot_json else {}
        except Exception:
            return {}

    def _fmt(self, key: str, val) -> str:
        if val is None or val == "":
            return "（なし）"
        if key == "is_member":
            return "会員" if val else "非会員"
        if key == "is_active":
            return "在籍" if val else "解除"
        return str(val)

    def _fmt_tel(self, snap: dict, area_key: str, num_key: str) -> str:
        area = snap.get(area_key) or ""
        num  = snap.get(num_key)  or ""
        combined = f"{area}-{num}".strip("-") if (area or num) else ""
        return combined if combined else "（なし）"

    def _fmt_ins_number(self, entry: dict) -> str:
        if not entry:
            return "（なし）"
        parts = []
        if entry.get("branch_number"):
            parts.append(f"枝番:{entry['branch_number']}")
        if entry.get("ins_number"):
            parts.append(f"番号:{entry['ins_number']}")
        return "　".join(parts) if parts else "（未登録）"
