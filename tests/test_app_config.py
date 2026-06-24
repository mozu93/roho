import json
import os
import tempfile
from app.utils.app_config import AppConfig


def test_load_defaults():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({}, f)
        path = f.name
    try:
        cfg = AppConfig.load(path)
        assert cfg.db_path == ""
        assert cfg.last_staff_name == ""
    finally:
        os.unlink(path)


def test_save_and_reload():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({}, f)
        path = f.name
    try:
        cfg = AppConfig.load(path)
        cfg.last_staff_name = "山田"
        cfg.db_path = r"\\nas\share\rouho.db"
        cfg.save(path)
        cfg2 = AppConfig.load(path)
        assert cfg2.last_staff_name == "山田"
        assert cfg2.db_path == r"\\nas\share\rouho.db"
    finally:
        os.unlink(path)


def test_load_missing_file_returns_defaults():
    cfg = AppConfig.load("/nonexistent/path.json")
    assert cfg.db_path == ""
