"""模型工厂模块。

根据 Provider 类型和 Agent 配置创建 LangChain 模型实例，
对上层调用者屏蔽原生集成 vs API 兼容模式的差异。
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

from src.config_loader import AgentModelConfig, ProviderConfig
from src.reasoning_compat import (
    ReasoningCompatibleChatDeepSeek,
    ReasoningCompatibleChatOpenAI,
)


def create_model(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
) -> BaseChatModel:
    """根据 Provider type 路由到不同的模型创建策略。

    Raises:
        ValueError: 不支持的 Provider 类型。
        KeyError: 所需环境变量未设置。
    """
    api_key = os.environ.get(provider_config.api_key_env, "")
    if not api_key:
        raise KeyError(
            f"环境变量 '{provider_config.api_key_env}' 未设置，"
            f"请在 .env 文件中配置"
        )

    params = agent_config.params

    match provider_config.type:
        case "dashscope":
            return _create_dashscope(provider_config, agent_config, api_key, params)
        case "anthropic_compatible":
            return _create_anthropic_compatible(provider_config, agent_config, api_key, params)
        case "openai_compatible":
            return _create_openai_compatible(provider_config, agent_config, api_key, params)
        case "deepseek":
            return _create_deepseek(provider_config, agent_config, api_key, params)
        case "openrouter":
            return _create_openrouter(agent_config, api_key, params)
        case _:
            raise ValueError(f"不支持的 Provider 类型: {provider_config.type}")


def _create_dashscope(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    from langchain_qwq import ChatQwen

    base_url = None
    if provider_config.base_url_env:
        base_url = os.environ.get(provider_config.base_url_env)

    kwargs: dict = {
        "model": agent_config.model,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "max_retries" in params:
        kwargs["max_retries"] = params["max_retries"]
    if "timeout" in params:
        kwargs["request_timeout"] = params["timeout"]
    if "enable_thinking" in params:
        kwargs["enable_thinking"] = params["enable_thinking"]
    if "thinking_budget" in params:
        kwargs["thinking_budget"] = params["thinking_budget"]
    thinking = params.get("thinking")
    if isinstance(thinking, dict):
        thinking_type = thinking.get("type")
        if thinking_type in {"enabled", "disabled"}:
            kwargs["enable_thinking"] = thinking_type == "enabled"
        if "budget_tokens" in thinking:
            kwargs["thinking_budget"] = thinking["budget_tokens"]

    return ChatQwen(**kwargs)


def _create_anthropic_compatible(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    base_url = provider_config.base_url
    if provider_config.base_url_env:
        base_url = os.environ.get(provider_config.base_url_env, base_url)

    kwargs: dict = {
        "model_name": agent_config.model,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "max_retries" in params:
        kwargs["max_retries"] = params["max_retries"]
    if "timeout" in params:
        kwargs["timeout"] = params["timeout"]
    if "thinking" in params:
        kwargs["thinking"] = params["thinking"]
    if "betas" in params:
        kwargs["betas"] = params["betas"]

    return ChatAnthropic(**kwargs)


def _create_openai_compatible(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    base_url = provider_config.base_url
    if provider_config.base_url_env:
        base_url = os.environ.get(provider_config.base_url_env, base_url)

    kwargs: dict = {
        "model": agent_config.model,
        "api_key": api_key,
        "provider_name": agent_config.provider,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "max_retries" in params:
        kwargs["max_retries"] = params["max_retries"]
    if "timeout" in params:
        kwargs["timeout"] = params["timeout"]
    extra_body = dict(params.get("extra_body", {}))
    if "thinking" in params:
        extra_body["thinking"] = params["thinking"]
    if extra_body:
        kwargs["extra_body"] = extra_body
    if "reasoning" in params:
        kwargs["reasoning"] = params["reasoning"]
    kwargs["preserve_reasoning"] = params.get(
        "preserve_reasoning",
        isinstance(params.get("thinking"), dict)
        and params["thinking"].get("type") == "enabled",
    )

    return ReasoningCompatibleChatOpenAI(**kwargs)


def _create_deepseek(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    base_url = provider_config.base_url
    if provider_config.base_url_env:
        base_url = os.environ.get(provider_config.base_url_env, base_url)

    kwargs: dict = {
        "model": agent_config.model,
        "api_key": api_key,
        "provider_name": "deepseek",
    }
    if base_url:
        kwargs["base_url"] = base_url
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "max_retries" in params:
        kwargs["max_retries"] = params["max_retries"]
    if "timeout" in params:
        kwargs["timeout"] = params["timeout"]
    extra_body = dict(params.get("extra_body", {}))
    if "thinking" in params:
        extra_body["thinking"] = params["thinking"]
    if extra_body:
        kwargs["extra_body"] = extra_body
    kwargs["preserve_reasoning"] = params.get(
        "preserve_reasoning",
        agent_config.model == "deepseek-reasoner"
        or (
            isinstance(params.get("thinking"), dict)
            and params["thinking"].get("type") == "enabled"
        ),
    )

    return ReasoningCompatibleChatDeepSeek(**kwargs)


def _create_openrouter(
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    model_name = f"openrouter:{agent_config.model}"
    kwargs: dict = {}
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]

    os.environ["OPENROUTER_API_KEY"] = api_key

    return init_chat_model(model_name, **kwargs)
