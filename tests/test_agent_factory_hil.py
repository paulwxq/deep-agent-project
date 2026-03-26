"""HIL 工具注入与 checkpointer 条件挂载测试。

验证 create_orchestrator_agent() 根据 hil_clarify / hil_confirm 标志：
- ask_user 注入到 Writer 子代理（不在 Orchestrator tools 中）
- confirm_continue 注入到 Orchestrator tools
- checkpointer 按需挂载
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


def _writer_tools(mock_create_deep_agent) -> list:
    """从 create_deep_agent 的 subagents 参数中提取 Writer 的 tools 列表。"""
    subagents = mock_create_deep_agent.call_args.kwargs["subagents"]
    writer = next(s for s in subagents if s["name"] == "writer")
    return writer["tools"]


class TestHilToolInjection:
    def test_ask_user_in_writer_when_clarify_only(self, mock_create_deep_agent):
        """hil_clarify=True → ask_user 注入到 Writer，Orchestrator tools 为空。"""
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=False)
        create_orchestrator_agent(cfg)
        orch_tools = mock_create_deep_agent.call_args.kwargs["tools"]
        writer_tool_names = {t.name for t in _writer_tools(mock_create_deep_agent)}
        assert "ask_user" in writer_tool_names
        assert not any(t.name == "ask_user" for t in orch_tools)
        assert not any(t.name == "confirm_continue" for t in orch_tools)

    def test_only_confirm_continue_in_orchestrator_when_confirm_only(self, mock_create_deep_agent):
        """hil_confirm=True → confirm_continue 在 Orchestrator，ask_user 不在 Writer。"""
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=True)
        create_orchestrator_agent(cfg)
        orch_tools = mock_create_deep_agent.call_args.kwargs["tools"]
        writer_tool_names = {t.name for t in _writer_tools(mock_create_deep_agent)}
        assert any(t.name == "confirm_continue" for t in orch_tools)
        assert "ask_user" not in writer_tool_names

    def test_both_enabled(self, mock_create_deep_agent):
        """hil_clarify=True + hil_confirm=True → ask_user 在 Writer，confirm_continue 在 Orchestrator。"""
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=True)
        create_orchestrator_agent(cfg)
        orch_tool_names = {t.name for t in mock_create_deep_agent.call_args.kwargs["tools"]}
        writer_tool_names = {t.name for t in _writer_tools(mock_create_deep_agent)}
        assert "ask_user" in writer_tool_names
        assert "confirm_continue" in orch_tool_names
        assert "ask_user" not in orch_tool_names

    def test_no_hil_tools_when_both_disabled(self, mock_create_deep_agent):
        """hil_clarify=False + hil_confirm=False → Orchestrator 和 Writer 均无 HIL 工具。"""
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=False)
        create_orchestrator_agent(cfg)
        orch_tools = mock_create_deep_agent.call_args.kwargs["tools"]
        writer_tool_names = {t.name for t in _writer_tools(mock_create_deep_agent)}
        assert orch_tools == []
        assert "ask_user" not in writer_tool_names


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


def test_create_orchestrator_agent_logs_llm_config(caplog):
    from src.agent_factory import create_orchestrator_agent

    cfg = _make_config(hil_clarify=False, hil_confirm=False)

    with (
        patch("src.agent_factory.create_deep_agent") as mock_cda,
        patch("src.agent_factory.create_model") as mock_model,
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
        caplog.at_level("DEBUG", logger="deep_agent_project"),
    ):
        mock_model.return_value = MagicMock()
        mock_cda.return_value = MagicMock()
        create_orchestrator_agent(cfg)

    assert 'LLM 配置 [orchestrator]: provider=dashscope, type=dashscope, model=qwen3-max, params={}' in caplog.text
    assert 'LLM 配置 [writer]: provider=dashscope, type=dashscope, model=qwen3-max, params={}' in caplog.text
    assert 'LLM 配置 [reviewer]: provider=dashscope, type=dashscope, model=qwen3-max, params={}' in caplog.text
