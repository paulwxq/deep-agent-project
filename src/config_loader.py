"""YAML 配置加载与校验模块。

从 config/agents.yaml 加载 Provider、Agent 模型和工具配置，
并校验双阶段 reviewer 配置与环境变量是否就绪。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ProviderConfig:
    """模型提供商配置。"""

    type: str
    api_key_env: str
    base_url: str | None = None
    base_url_env: str | None = None


@dataclass
class AgentModelConfig:
    """单个 Agent 的模型配置。"""

    enabled: bool = True
    provider: str = ""
    model: str = ""
    max_reviewer_iterations: int = 3
    params: dict = field(default_factory=dict)


@dataclass
class Context7Config:
    """Context7 MCP 工具配置。"""

    enabled: bool = False
    api_key_env: str = "CONTEXT7_API_KEY"
    url: str = "https://mcp.context7.com/mcp"


@dataclass
class ToolsConfig:
    """工具配置。"""

    tavily_enabled: bool = False
    tavily_api_key_env: str = "TAVILY_API_KEY"
    tavily_max_results: int = 5
    context7: Context7Config = field(default_factory=Context7Config)


@dataclass
class AppConfig:
    """应用全局配置。"""

    max_iterations: int
    log_level: str
    file_log_level: str
    hil_clarify: bool
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentModelConfig]
    tools: ToolsConfig


class ConfigError(Exception):
    """配置错误。"""


def _require_bool(value: object, field_name: str) -> bool:
    """确保 YAML 字段是原生布尔值。"""
    if not isinstance(value, bool):
        raise ConfigError(
            f"配置字段 '{field_name}' 必须为布尔值（YAML 原生 true/false），"
            f"不支持字符串或数字类型（当前值: {value!r}）"
        )
    return value


def _validate_enabled_agent(
    agent_name: str,
    agent_cfg: AgentModelConfig,
    providers: dict[str, ProviderConfig],
) -> None:
    """校验启用中的 agent 配置。"""
    if not agent_cfg.provider:
        raise ConfigError(f"Agent '{agent_name}' 缺少 provider 配置")
    if not agent_cfg.model:
        raise ConfigError(f"Agent '{agent_name}' 缺少 model 配置")
    if agent_cfg.provider not in providers:
        raise ConfigError(
            f"Agent '{agent_name}' 引用的 Provider '{agent_cfg.provider}' 未在 providers 中定义"
        )


def _validate_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"配置字段 '{field_name}' 必须为正整数（当前值: {value!r}）")
    return value


def load_config(config_path: str = "config/agents.yaml") -> AppConfig:
    """加载并校验 YAML 配置文件。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path.resolve()}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件格式错误，期望顶层为字典: {config_path}")

    global_cfg = raw.get("global", {})
    max_iterations = global_cfg.get("max_iterations", 3)
    log_level = global_cfg.get("log_level", "INFO")
    file_log_level = global_cfg.get("file_log_level", "DEBUG")
    hil_clarify = _require_bool(global_cfg.get("hil_clarify", False), "hil_clarify")

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

    raw_agents = raw.get("agents", {})
    if "reviewer" in raw_agents and "reviewer1" not in raw_agents:
        raise ConfigError(
            "检测到旧配置键 'agents.reviewer'。请手动重命名为 'agents.reviewer1'，"
            "并按需新增可选的 'agents.reviewer2'。"
        )

    agents: dict[str, AgentModelConfig] = {}
    for name, acfg in raw_agents.items():
        if not isinstance(acfg, dict):
            raise ConfigError(f"Agent '{name}' 配置格式错误")
        agents[name] = AgentModelConfig(
            enabled=_require_bool(acfg.get("enabled", True), f"agents.{name}.enabled"),
            provider=acfg.get("provider", ""),
            model=acfg.get("model", ""),
            max_reviewer_iterations=acfg.get("max_reviewer_iterations", 3),
            params=acfg.get("params", {}),
        )

    for required_agent in ("orchestrator", "writer", "reviewer1"):
        if required_agent not in agents:
            raise ConfigError(f"缺少必需的 Agent 配置: '{required_agent}'")

    if not agents["reviewer1"].enabled:
        raise ConfigError("reviewer1 必须启用（agents.reviewer1.enabled 必须为 true）")

    reviewer2_cfg = agents.get("reviewer2")
    for agent_name in ("orchestrator", "writer", "reviewer1"):
        _validate_enabled_agent(agent_name, agents[agent_name], providers)

    for reviewer_name in ("reviewer1", "reviewer2"):
        reviewer_cfg = agents.get(reviewer_name)
        if reviewer_cfg is None or not reviewer_cfg.enabled:
            continue
        reviewer_cfg.max_reviewer_iterations = _validate_positive_int(
            reviewer_cfg.max_reviewer_iterations,
            f"agents.{reviewer_name}.max_reviewer_iterations",
        )
        _validate_enabled_agent(reviewer_name, reviewer_cfg, providers)

    if reviewer2_cfg and reviewer2_cfg.enabled:
        if (
            reviewer2_cfg.provider == agents["reviewer1"].provider
            and reviewer2_cfg.model == agents["reviewer1"].model
        ):
            raise ConfigError("reviewer2 启用时，必须与 reviewer1 使用不同的 provider+model 组合")

    raw_tools = raw.get("tools", {})
    if not isinstance(raw_tools, dict):
        raw_tools = {}
    tavily_cfg = raw_tools.get("tavily", {}) if isinstance(raw_tools, dict) else {}
    ctx7_cfg = raw_tools.get("context7", {}) if isinstance(raw_tools, dict) else {}
    tools = ToolsConfig(
        tavily_enabled=tavily_cfg.get("enabled", False),
        tavily_api_key_env=tavily_cfg.get("api_key_env", "TAVILY_API_KEY"),
        tavily_max_results=tavily_cfg.get("max_results", 5),
        context7=Context7Config(
            enabled=ctx7_cfg.get("enabled", False),
            api_key_env=ctx7_cfg.get("api_key_env", "CONTEXT7_API_KEY"),
            url=ctx7_cfg.get("url", "https://mcp.context7.com/mcp"),
        ),
    )

    return AppConfig(
        max_iterations=max_iterations,
        log_level=log_level,
        file_log_level=file_log_level,
        hil_clarify=hil_clarify,
        providers=providers,
        agents=agents,
        tools=tools,
    )


def validate_env_vars(config: AppConfig) -> list[str]:
    """检查配置中引用的环境变量是否已设置。"""
    missing: list[str] = []

    used_providers = {
        agent_cfg.provider
        for agent_cfg in config.agents.values()
        if agent_cfg.enabled and agent_cfg.provider
    }
    for provider_name in used_providers:
        pcfg = config.providers[provider_name]
        if pcfg.api_key_env and not os.environ.get(pcfg.api_key_env):
            missing.append(pcfg.api_key_env)
        if pcfg.base_url_env and not os.environ.get(pcfg.base_url_env):
            missing.append(pcfg.base_url_env)

    if config.tools.tavily_enabled and not os.environ.get(config.tools.tavily_api_key_env):
        missing.append(config.tools.tavily_api_key_env)

    if config.tools.context7.enabled and not os.environ.get(config.tools.context7.api_key_env):
        missing.append(config.tools.context7.api_key_env)

    return missing
