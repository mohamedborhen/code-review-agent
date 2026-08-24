"""Tests for the subagent builder factory."""

import pytest

from infrastructure.agents_runtime.subagents.factory import (
    SUBAGENT_CONFIGS,
    build_subagent_spec,
)


def test_all_five_subagents_configured():
    expected = {"compliance", "security", "performance", "regression", "fix_suggestion"}
    assert set(SUBAGENT_CONFIGS.keys()) == expected


@pytest.mark.parametrize("name", list(SUBAGENT_CONFIGS.keys()))
def test_factory_returns_spec_dict(name):
    import asyncio
    from unittest.mock import AsyncMock, patch

    with patch("infrastructure.agents_runtime.subagents.factory.scope_agent_tools", new_callable=AsyncMock, return_value=[]):
        spec = asyncio.run(
            build_subagent_spec(name, mcp_client=None, store=None)
        )
        assert isinstance(spec, dict)
        assert spec["name"] == name
        assert "description" in spec
        assert "system_prompt" in spec
        assert isinstance(spec["tools"], list)


@pytest.mark.parametrize("name", list(SUBAGENT_CONFIGS.keys()))
def test_factory_adds_capture_middleware(name):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from infrastructure.agents_runtime.capture import CaptureStore

    store = CaptureStore()
    with patch("infrastructure.agents_runtime.subagents.factory.scope_agent_tools", new_callable=AsyncMock, return_value=[]):
        spec = asyncio.run(
            build_subagent_spec(name, mcp_client=None, store=store)
        )
        assert "middleware" in spec
        assert len(spec["middleware"]) == 1
