from __future__ import annotations

import sys

import app.config.settings as settings_module


def test_base_dir_is_project_root_when_not_frozen():
    assert getattr(sys, "frozen", False) is False
    resolved = settings_module._base_dir()
    # project root contains main.py
    assert (resolved / "main.py").exists()


def test_base_dir_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "inventory_app.exe"
    fake_exe.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    resolved = settings_module._base_dir()

    assert resolved == tmp_path
