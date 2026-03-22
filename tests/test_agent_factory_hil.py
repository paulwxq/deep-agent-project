"""HIL 工具注入与 checkpointer 条件挂载测试。

验证 create_orchestrator_agent() 根据 hil_clarify / hil_confirm 标志，
独立注入 ask_user / confirm_continue 工具，并按需挂载 checkpointer。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config_loader import AgentModelConfig, AppConfig, ProviderConfig, ToolsConfig


def _make_config(hil_clarify: bool, hil_confirm: bool) -> AppConfig:
    provider = ProviderConfig(type="dashscope", api_key_env="DASHSCOPE_API_KEY")
    agent_cfg = AgentModelConfig(provider="dashscope", model="qwen3-max")
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        file_log_level="DEBUG",
        hil_clarify=hil_clarify,
        hil_confirm=hil_confirm,
        providers={"dashscope": provider},
        agents={
            "orchestrator": agent_cfg,
            "writer": agent_cfg,
            "reviewer": agent_cfg,
        },
        tools=ToolsConfig(),
    )


@pytest.fixture()
def mock_create_deep_agent():
    """Patch create_deep_agent and all model/middleware dependencies."""
    with (
        patch("src.agent_factory.create_deep_agent") as mock_cda,
        patch("src.agent_factory.create_model") as mock_model,
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
    ):
        mock_model.return_value = MagicMock()
        mock_cda.return_value = MagicMock()
        yield mock_cda


class TestHilToolInjection:
    def test_only_ask_user_injected_when_clarify_only(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert any(t.name == "ask_user" for t in tools)
        assert not any(t.name == "confirm_continue" for t in tools)

    def test_only_confirm_continue_injected_when_confirm_only(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=True)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert any(t.name == "confirm_continue" for t in tools)
        assert not any(t.name == "ask_user" for t in tools)

    def test_both_tools_injected_when_both_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=True)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        tool_names = {t.name for t in tools}
        assert "ask_user" in tool_names
        assert "confirm_continue" in tool_names

    def test_no_hil_tools_when_both_disabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert tools == []


class TestCheckpointerCondition:
    def test_checkpointer_present_when_any_hil_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        for clarify, confirm in [(True, False), (False, True), (True, True)]:
            mock_create_deep_agent.reset_mock()
            cfg = _make_config(hil_clarify=clarify, hil_confirm=confirm)
            create_orchestrator_agent(cfg)
            call_kwargs = mock_create_deep_agent.call_args.kwargs
            assert "checkpointer" in call_kwargs, (
                f"checkpointer missing for hil_clarify={clarify}, hil_confirm={confirm}"
            )

    def test_no_checkpointer_when_both_disabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        assert "checkpointer" not in call_kwargs
