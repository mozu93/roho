import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class AppConfig:
    data_dir: str = ""
    db_path: str = ""  # 後方互換性のため保持（data_dir が優先）
    last_staff_name: str = ""
    m365_tenant_id: str = ""
    m365_client_id: str = ""
    m365_test_address: str = ""
    hidden_columns: list[str] = field(default_factory=list)
    withdrawn_hidden_columns: list[str] = field(default_factory=list)
    member_column_widths: dict = field(default_factory=dict)
    staff_settings: dict = field(default_factory=dict)
    label_offsets: dict = field(default_factory=dict)
    window_geometry: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "AppConfig":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: data.get(k, v) for k, v in asdict(cls()).items()})
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()

    def save(self, path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False
