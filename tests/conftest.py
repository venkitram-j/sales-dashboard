from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_cache():
    """Ensure get_settings()'s lru_cache doesn't leak env vars between tests."""
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
