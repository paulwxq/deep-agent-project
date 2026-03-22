"""YAML 配置加载与校验模块。

从 config/agents.yaml 加载 Provider、Agent 模型和工具配置，
并校验 Provider 引用和环境变量是否就绪。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ProviderConfig:
    """模型提供商配置。"""

    type: str  # "dashscope" | "anthropic_compatible" | "openai_compatible" | "openrouter"
    api_key_env: str
    base_url: str | None = None
    base_url_env: str | None = None


@dataclass
class AgentModelConfig:
    """单个 Agent 的模型配置。"""

    provider: str
    model: str
    params: dict = field(default_factory=dict)


@dataclass
class ToolsConfig:
    """工具配置。"""

    tavily_enabled: bool = False
    tavily_api_key_env: str = "TAVILY_API_KEY"
    tavily_max_results: int = 5


@dataclass
class AppConfig:
    """应用全局配置。"""

    max_iterations: int
    log_level: str
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentModelConfig]
    tools: ToolsConfig


class ConfigError(Exception):
    """配置错误。"""


def load_config(config_path: str = "config/agents.yaml") -> AppConfig:
    """加载并校验 YAML 配置文件。

    Raises:
        ConfigError: 配置文件缺失、格式错误或引用的 Provider 未定义。
        FileNotFoundError: 配置文件不存在。
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path.resolve()}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件格式错误，期望顶层为字典: {config_path}")

    # --- global ---
    global_cfg = raw.get("global", {})
    max_iterations = global_cfg.get("max_iterations", 3)
    log_level = global_cfg.get("log_level", "DEBUG")

    # --- providers ---
    raw_providers = raw.get("providers", {})
    providers: dict[str, ProviderConfig] = {}
    for name, pcfg in raw_providers.items():
        if not isinstance(pcfg, dict) or "type" not in pcfg:
            raise ConfigError(f"Provider '{name}' 缺少 'type' 字段")
        providers[name] = ProviderConfig(
            type=pcfg["type"],
            api_key_env=pcfg.get("api_key_env", ""),
            base_url=pcfg.get("base_url"),
            base_url_env=pcfg.get("base_url_env"),
        )

    # --- agents ---
    raw_agents = raw.get("agents", {})
    agents: dict[str, AgentModelConfig] = {}
    for name, acfg in raw_agents.items():
        if not isinstance(acfg, dict):
            raise ConfigError(f"Agent '{name}' 配置格式错误")
        provider_name = acfg.get("provider", "")
        if provider_name not in providers:
            raise ConfigError(
                f"Agent '{name}' 引用的 Provider '{provider_name}' 未在 providers 中定义"
            )
        agents[name] = AgentModelConfig(
            provider=provider_name,
            model=acfg.get("model", ""),
            params=acfg.get("params", {}),
        )

    # --- tools ---
    raw_tools = raw.get("tools", {})
    tavily_cfg = raw_tools.get("tavily", {}) if isinstance(raw_tools, dict) else {}
    tools = ToolsConfig(
        tavily_enabled=tavily_cfg.get("enabled", False),
        tavily_api_key_env=tavily_cfg.get("api_key_env", "TAVILY_API_KEY"),
        tavily_max_results=tavily_cfg.get("max_results", 5),
    )

    return AppConfig(
        max_iterations=max_iterations,
        log_level=log_level,
        providers=providers,
        agents=agents,
        tools=tools,
    )


def validate_env_vars(config: AppConfig) -> list[str]:
    """检查配置中引用的环境变量是否已设置。

    Returns:
        缺失的环境变量名列表（空列表表示全部就绪）。
    """
    missing: list[str] = []

    used_providers = {a.provider for a in config.agents.values()}
    for provider_name in used_providers:
        pcfg = config.providers[provider_name]
        if pcfg.api_key_env and not os.environ.get(pcfg.api_key_env):
            missing.append(pcfg.api_key_env)
        if pcfg.base_url_env and not os.environ.get(pcfg.base_url_env):
            missing.append(pcfg.base_url_env)

    if config.tools.tavily_enabled:
        if not os.environ.get(config.tools.tavily_api_key_env):
            missing.append(config.tools.tavily_api_key_env)

    return missing
