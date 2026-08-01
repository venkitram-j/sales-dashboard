from __future__ import annotations

import pytest

import app.utils.ui as ui_module


class _RerunTriggered(Exception):
    """Stand-in for Streamlit's internal RerunException: st.rerun() never
    returns in real Streamlit, it immediately halts the script."""


class _FakeButton:
    """Records the disabled= flag it was called with and returns a
    pre-programmed click result."""

    def __init__(self, clicked: bool):
        self.clicked = clicked
        self.calls: list[dict] = []

    def __call__(self, label, disabled=False, **kwargs):
        self.calls.append({"label": label, "disabled": disabled, **kwargs})
        return self.clicked


@pytest.fixture
def fake_streamlit(monkeypatch):
    session_state: dict = {}
    monkeypatch.setattr(ui_module.st, "session_state", session_state, raising=False)

    def _rerun():
        raise _RerunTriggered

    monkeypatch.setattr(ui_module.st, "rerun", _rerun, raising=False)
    return session_state


def test_first_click_sets_busy_and_reruns_without_returning_true(fake_streamlit, monkeypatch):
    button = _FakeButton(clicked=True)
    monkeypatch.setattr(ui_module.st, "button", button, raising=False)

    with pytest.raises(_RerunTriggered):
        ui_module.blocking_button("Refresh", "busy_key")

    assert fake_streamlit["busy_key"] is True
    assert button.calls[0]["disabled"] is False  # not yet busy at render time


def test_second_run_renders_disabled_and_returns_true(fake_streamlit, monkeypatch):
    fake_streamlit["busy_key"] = True  # as left by the previous run's rerun
    button = _FakeButton(clicked=False)  # this run wasn't triggered by a click
    monkeypatch.setattr(ui_module.st, "button", button, raising=False)

    result = ui_module.blocking_button("Refresh", "busy_key")

    assert result is True
    assert button.calls[0]["disabled"] is True


def test_no_click_and_not_busy_returns_false_without_rerun(fake_streamlit, monkeypatch):
    button = _FakeButton(clicked=False)
    monkeypatch.setattr(ui_module.st, "button", button, raising=False)

    result = ui_module.blocking_button("Refresh", "busy_key")

    assert result is False
    assert "busy_key" not in fake_streamlit
    assert button.calls[0]["disabled"] is False


def test_also_disabled_combines_with_busy_flag(fake_streamlit, monkeypatch):
    button = _FakeButton(clicked=False)
    monkeypatch.setattr(ui_module.st, "button", button, raising=False)

    ui_module.blocking_button("Process Upload", "busy_key", also_disabled=True)

    assert button.calls[0]["disabled"] is True


def test_also_disabled_does_not_block_the_busy_cycle_itself(fake_streamlit, monkeypatch):
    button = _FakeButton(clicked=True)
    monkeypatch.setattr(ui_module.st, "button", button, raising=False)

    with pytest.raises(_RerunTriggered):
        ui_module.blocking_button("Process Upload", "busy_key", also_disabled=False)

    assert fake_streamlit["busy_key"] is True
