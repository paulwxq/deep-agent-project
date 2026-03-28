"""AgentFactory 中 HIL / reviewer 装配测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config_loader import AgentModelConfig, AppConfig, ProviderConfig, ToolsConfig


def _make_config(hil_clarify: bool, reviewer2_enabled: bool) -> AppConfig:
    providers = {
        "dashscope": ProviderConfig(type="dashscope", api_key_env="DASHSCOPE_API_KEY"),
        "minimax": ProviderConfig(type="anthropic_compatible", api_key_env="MINIMAX_API_KEY"),
    }
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        file_log_level="DEBUG",
        hil_clarify=hil_clarify,
        providers=providers,
        agents={
            "orchestrator": AgentModelConfig(provider="dashscope", model="qwen3-max"),
            "writer": AgentModelConfig(provider="dashscope", model="qwen3-max"),
            "reviewer1": AgentModelConfig(provider="dashscope", model="qwen3-max"),
            "reviewer2": AgentModelConfig(
                enabled=reviewer2_enabled,
                provider="minimax",
                model="minimax-2.5",
                max_reviewer_iterations=2,
            ),
        },
        tools=ToolsConfig(),
    )


@pytest.fixture()
def mock_create_deep_agent():
    with (
        patch("src.agent_factory.create_deep_agent") as mock_cda,
        patch("src.agent_factory.create_model") as mock_model,
        patch("src.agent_factory._ensure_review_state"),
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
    ):
        mock_model.return_value = MagicMock()
        mock_cda.return_value = MagicMock()
        yield mock_cda


def _writer_tools(mock_create_deep_agent) -> list:
    subagents = mock_create_deep_agent.call_args.kwargs["subagents"]
    writer = next(s for s in subagents if s["name"] == "writer")
    return writer["tools"]


class TestHilAndReviewerInjection:
    def test_confirm_continue_always_in_orchestrator(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent

        cfg = _make_config(hil_clarify=False, reviewer2_enabled=False)
        create_orchestrator_agent(cfg)
        orch_tool_names = {t.name for t in mock_create_deep_agent.call_args.kwargs["tools"]}
        assert "confirm_continue" in orch_tool_names

    def test_ask_user_only_in_writer_when_clarify_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent

        cfg = _make_config(hil_clarify=True, reviewer2_enabled=False)
        create_orchestrator_agent(cfg)
        writer_tool_names = {t.name for t in _writer_tools(mock_create_deep_agent)}
        assert "ask_user" in writer_tool_names

    def test_reviewer2_subagent_only_when_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent

        cfg = _make_config(hil_clarify=False, reviewer2_enabled=True)
        create_orchestrator_agent(cfg)
        subagent_names = [s["name"] for s in mock_create_deep_agent.call_args.kwargs["subagents"]]
        assert subagent_names == ["writer", "reviewer1", "reviewer2"]

    def test_checkpointer_always_present(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent

        cfg = _make_config(hil_clarify=False, reviewer2_enabled=False)
        create_orchestrator_agent(cfg)
        assert "checkpointer" in mock_create_deep_agent.call_args.kwargs


def test_create_orchestrator_agent_logs_llm_config(caplog):
    from src.agent_factory import create_orchestrator_agent

    cfg = _make_config(hil_clarify=False, reviewer2_enabled=True)

    with (
        patch("src.agent_factory.create_deep_agent") as mock_cda,
        patch("src.agent_factory.create_model") as mock_model,
        patch("src.agent_factory._ensure_review_state"),
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
        caplog.at_level("DEBUG", logger="deep_agent_project"),
    ):
        mock_model.return_value = MagicMock()
        mock_cda.return_value = MagicMock()
        create_orchestrator_agent(cfg)

    assert "LLM 配置 [reviewer1]" in caplog.text
    assert "LLM 配置 [reviewer2]" in caplog.text
