"""What every test gets: no test reaches a real provider with the person's real key, and none writes into the real cache."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_token_harbor(monkeypatch, tmp_path):
    """Token Harbor's key lives in the person's .env, and `load_env_file` copies it into the environment of any test that builds a gateway: without
    this, a test that lists the picker's models would ask the real catalogue (the network, the real key) and find models the test does not expect.
    A test that wants Token Harbor sets its own key and hands the catalogue a mock transport."""
    from dxf_autoparam.ai import tokenharbor

    monkeypatch.setenv("TOKENHARBOR_API_KEY", "")  # `load_env_file` only fills what is missing: an empty key stays empty
    monkeypatch.delenv("TOKENHARBOR_MODELS", raising=False)
    monkeypatch.delenv("TOKENHARBOR_BASE_URL", raising=False)
    monkeypatch.setattr(tokenharbor, "FILE", tmp_path / "tokenharbor_models.json")
    tokenharbor.forget()
    yield
    tokenharbor.forget()
