"""Agent 工厂的 provider 装配测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from src.config_loader import AgentModelConfig, AppConfig, ProviderConfig, ToolsConfig


def _make_config() -> AppConfig:
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        file_log_level="DEBUG",
        hil_clarify=False,
        providers={
            "deepseek": ProviderConfig(type="deepseek", api_key_env="DEEPSEEK_API_KEY"),
            "moonshot": ProviderConfig(
                type="openai_compatible",
                api_key_env="MOONSHOT_API_KEY",
                base_url="https://api.moonshot.cn/v1",
            ),
            "minimax": ProviderConfig(
                type="anthropic_compatible",
                api_key_env="MINIMAX_API_KEY",
                base_url="https://api.minimaxi.com/anthropic",
            ),
        },
        agents={
            "orchestrator": AgentModelConfig(
                provider="deepseek",
                model="deepseek-chat",
                params={"temperature": 0.3, "timeout": 30},
            ),
            "writer": AgentModelConfig(
                provider="moonshot",
                model="kimi-k2.5",
                params={"thinking": {"type": "disabled"}, "timeout": 30},
            ),
            "reviewer1": AgentModelConfig(
                provider="moonshot",
                model="kimi-k2.5",
                params={"thinking": {"type": "disabled"}, "timeout": 30},
            ),
            "reviewer2": AgentModelConfig(
                enabled=True,
                provider="minimax",
                model="minimax-2.5",
                params={"thinking": {"type": "disabled"}, "timeout": 30},
            ),
        },
        tools=ToolsConfig(),
    )


def test_create_orchestrator_agent_accepts_multi_provider_models(
    monkeypatch: pytest.MonkeyPatch,
):
    for key in ["ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-moonshot")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax")

    with (
        patch("src.agent_factory.create_deep_agent") as mock_create_deep_agent,
        patch("src.agent_factory._ensure_review_state"),
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
    ):
        mock_create_deep_agent.return_value = MagicMock()

        from src.agent_factory import create_orchestrator_agent

        create_orchestrator_agent(_make_config())

    call_kwargs = mock_create_deep_agent.call_args.kwargs
    assert isinstance(call_kwargs["model"], ChatDeepSeek)
    assert isinstance(call_kwargs["subagents"][0]["model"], ChatOpenAI)
    assert isinstance(call_kwargs["subagents"][1]["model"], ChatOpenAI)
