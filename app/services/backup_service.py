import sqlite3
import shutil
from pathlib import Path
from datetime import date, datetime, timedelta


class BackupService:
    _PREFIX = "rouho_backup_"
    _MARKER = "last_backup_date.txt"

    def __init__(self, db_path: str, backup_dir: str):
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir)
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def run_if_needed(self) -> bool:
        """一日の初回起動時にバックアップを実行。実行した場合 True を返す。"""
        today = date.today()
        marker = self._backup_dir / self._MARKER
        if marker.exists() and marker.read_text().strip() == today.isoformat():
            return False

        yesterday = today - timedelta(days=1)
        self._create_backup(yesterday)
        self._prune(today)
        marker.write_text(today.isoformat(), encoding="utf-8")
        return True

    def _create_backup(self, target_date: date) -> None:
        if not self._db_path.exists():
            return
        backup_path = self._backup_dir / f"{self._PREFIX}{target_date.isoformat()}.db"
        if backup_path.exists():
            return
        # sqlite3.backup でWALを含む一貫したバックアップを作成
        src = sqlite3.connect(str(self._db_path))
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _prune(self, today: date) -> None:
        """保持ポリシーに従い古いバックアップを削除。
        - 直近7日: 毎日
        - 8〜31日前: 週次（各週1件）
        - 32〜90日前: 月次（各月1件）
        - 90日超: 削除
        """
        entries = self._list_entries()
        keep = set()
        week_seen: set[int] = set()
        month_seen: set[tuple] = set()

        for d, path in entries:
            # before_restore ファイルは常に保持しない（別名なのでglobに引っかからない）
            delta = (today - d).days
            if delta < 0:
                keep.add(path)  # 未来日は保持
            elif delta <= 7:
                keep.add(path)
            elif delta <= 31:
                week_key = delta // 7
                if week_key not in week_seen:
                    week_seen.add(week_key)
                    keep.add(path)
            elif delta <= 90:
                month_key = (d.year, d.month)
                if month_key not in month_seen:
                    month_seen.add(month_key)
                    keep.add(path)

        for _, path in entries:
            if path not in keep:
                path.unlink(missing_ok=True)

    def list_backups(self) -> list[dict]:
        """バックアップ一覧を新しい順で返す。"""
        today = date.today()
        result = []
        for d, path in self._list_entries():
            delta = (today - d).days
            if delta == 0:
                age_label = "今日"
            elif delta == 1:
                age_label = "昨日"
            else:
                age_label = f"{delta}日前"
            result.append({
                "date": d,
                "age_label": age_label,
                "path": str(path),
                "size_kb": path.stat().st_size // 1024,
            })
        return result

    def restore(self, backup_path: str, engine=None) -> None:
        """バックアップから復元する。復元前に現在のDBを保存しておく。"""
        src = Path(backup_path)
        if not src.exists():
            raise FileNotFoundError(f"バックアップが見つかりません: {backup_path}")

        # 復元前スナップショットを保存
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pre_path = self._backup_dir / f"rouho_before_restore_{ts}.db"
        if self._db_path.exists():
            shutil.copy2(self._db_path, pre_path)

        # SQLAlchemy の接続を解放
        if engine is not None:
            engine.dispose()

        shutil.copy2(src, self._db_path)

    def _list_entries(self) -> list[tuple[date, Path]]:
        entries = []
        for path in self._backup_dir.glob(f"{self._PREFIX}*.db"):
            stem = path.stem[len(self._PREFIX):]
            try:
                d = date.fromisoformat(stem)
                entries.append((d, path))
            except ValueError:
                continue
        entries.sort(key=lambda x: x[0], reverse=True)
        return entries
