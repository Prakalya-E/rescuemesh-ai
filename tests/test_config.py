import os
from pathlib import Path
import pytest
from backend.app import config


def test_relative_sqlite_url_is_anchored_to_project_root():
    url = config.absolutize_sqlite("sqlite:///./rescuemesh.db")
    assert url.endswith("/rescuemesh.db") and config.ROOT.as_posix() in url


def test_absolute_memory_and_other_databases_are_unchanged():
    for u in ("sqlite:///:memory:", "postgresql+psycopg://u:p@h/db"):
        assert config.absolutize_sqlite(u) == u


def test_settings_do_not_depend_on_launch_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = config.Settings(DATABASE_URL="sqlite:///./x.db")
    assert config.ROOT.as_posix() in s.DATABASE_URL


def test_loaded_settings_point_at_one_absolute_database():
    url = config.settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        pytest.skip("not using SQLite")
    assert Path(url[len("sqlite:///"):]).is_absolute()
