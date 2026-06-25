import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class AppConfig:
    db_path: str = ""
    last_staff_name: str = ""
    m365_tenant_id: str = ""
    m365_client_id: str = ""
    m365_test_address: str = ""
    hidden_columns: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "AppConfig":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: data.get(k, v) for k, v in asdict(cls()).items()})
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
