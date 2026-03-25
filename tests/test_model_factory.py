"""model_factory 单元测试。

覆盖范围：
  - DeepSeek provider 路由到项目自定义兼容封装
  - Moonshot 继续复用 openai_compatible 路由
  - DashScope / Anthropic compatible 的 thinking 参数透传
  - 缺少 API Key / 未知 provider 的错误路径
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config_loader import AgentModelConfig, ProviderConfig
from src.model_factory import create_model


def _make_agent(provider: str, model: str, **params) -> AgentModelConfig:
    return AgentModelConfig(provider=provider, model=model, params=params)


class TestCreateModel:
    def test_deepseek_provider_uses_chatdeepseek(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")

        provider = ProviderConfig(type="deepseek", api_key_env="DEEPSEEK_API_KEY")
        agent = _make_agent(
            "deepseek",
            "deepseek-chat",
            temperature=0.3,
            max_tokens=8192,
            max_retries=6,
            timeout=120,
        )

        with patch("src.model_factory.ReasoningCompatibleChatDeepSeek") as mock_chat_deepseek:
            model = create_model(provider, agent)

        assert model is mock_chat_deepseek.return_value
        mock_chat_deepseek.assert_called_once_with(
            model="deepseek-chat",
            api_key="sk-deepseek",
            provider_name="deepseek",
            temperature=0.3,
            max_tokens=8192,
            max_retries=6,
            timeout=120,
            preserve_reasoning=False,
        )

    def test_deepseek_base_url_env_overrides_static_base_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
        monkeypatch.setenv("DEEPSEEK_API_BASE", "https://deepseek-proxy.example/v1")

        provider = ProviderConfig(
            type="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            base_url_env="DEEPSEEK_API_BASE",
        )
        agent = _make_agent("deepseek", "deepseek-chat")

        with patch("src.model_factory.ReasoningCompatibleChatDeepSeek") as mock_chat_deepseek:
            create_model(provider, agent)

        mock_chat_deepseek.assert_called_once_with(
            model="deepseek-chat",
            api_key="sk-deepseek",
            base_url="https://deepseek-proxy.example/v1",
            provider_name="deepseek",
            preserve_reasoning=False,
        )

    def test_moonshot_openai_compatible_uses_reasoning_chatopenai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-moonshot")

        provider = ProviderConfig(
            type="openai_compatible",
            api_key_env="MOONSHOT_API_KEY",
            base_url="https://api.moonshot.cn/v1",
        )
        agent = _make_agent(
            "moonshot",
            "kimi-k2.5",
            max_tokens=16384,
            max_retries=6,
            timeout=180,
            thinking={"type": "disabled"},
        )

        with patch("src.model_factory.ReasoningCompatibleChatOpenAI") as mock_chat_openai:
            model = create_model(provider, agent)

        assert model is mock_chat_openai.return_value
        mock_chat_openai.assert_called_once_with(
            model="kimi-k2.5",
            api_key="sk-moonshot",
            base_url="https://api.moonshot.cn/v1",
            provider_name="moonshot",
            max_tokens=16384,
            max_retries=6,
            timeout=180,
            extra_body={"thinking": {"type": "disabled"}},
            preserve_reasoning=False,
        )

    def test_dashscope_maps_standard_thinking_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")

        provider = ProviderConfig(type="dashscope", api_key_env="DASHSCOPE_API_KEY")
        agent = _make_agent(
            "dashscope",
            "qwen3-plus",
            thinking={"type": "enabled", "budget_tokens": 2048},
            timeout=30,
        )

        with patch("langchain_qwq.ChatQwen") as mock_chat_qwen:
            create_model(provider, agent)

        mock_chat_qwen.assert_called_once_with(
            model="qwen3-plus",
            api_key="sk-dashscope",
            request_timeout=30,
            enable_thinking=True,
            thinking_budget=2048,
        )

    def test_anthropic_compatible_passes_thinking_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-minimax")

        provider = ProviderConfig(
            type="anthropic_compatible",
            api_key_env="MINIMAX_API_KEY",
            base_url="https://api.minimaxi.com/anthropic",
        )
        agent = _make_agent(
            "minimax",
            "MiniMax-M2.7",
            thinking={"type": "enabled", "budget_tokens": 2048},
            timeout=60,
        )

        with patch("langchain_anthropic.ChatAnthropic") as mock_chat_anthropic:
            create_model(provider, agent)

        mock_chat_anthropic.assert_called_once_with(
            model_name="MiniMax-M2.7",
            api_key="sk-minimax",
            base_url="https://api.minimaxi.com/anthropic",
            timeout=60,
            thinking={"type": "enabled", "budget_tokens": 2048},
        )

    def test_missing_api_key_raises_keyerror(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        provider = ProviderConfig(type="deepseek", api_key_env="DEEPSEEK_API_KEY")
        agent = _make_agent("deepseek", "deepseek-chat")

        with pytest.raises(KeyError, match="DEEPSEEK_API_KEY"):
            create_model(provider, agent)

    def test_unknown_provider_type_raises_valueerror(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("UNKNOWN_API_KEY", "sk-test")

        provider = ProviderConfig(type="unknown", api_key_env="UNKNOWN_API_KEY")
        agent = _make_agent("unknown", "some-model")

        with pytest.raises(ValueError, match="不支持的 Provider 类型"):
            create_model(provider, agent)
