"""config_loader 单元测试。

覆盖范围：
  - load_config() 加载实际 config/agents.yaml 成功
  - AppConfig 已无 output_dir 字段（验证字段删除）
  - Agent 引用不存在的 Provider → ConfigError
  - Provider 缺少 type 字段 → ConfigError
  - 配置文件不存在 → FileNotFoundError
  - 顶层不是字典 → ConfigError
  - validate_env_vars() 全部变量已设置 → []
  - validate_env_vars() 缺少变量 → [var_name]
  - validate_env_vars() Tavily 启用但 key 缺失 → 包含该 key
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config_loader import (
    AppConfig,
    AgentModelConfig,
    ConfigError,
    ProviderConfig,
    ToolsConfig,
    load_config,
    validate_env_vars,
)


# ---------------------------------------------------------------------------
# 辅助：从字符串写 YAML 到 tmp_path
# ---------------------------------------------------------------------------

def write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "agents.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# load_config — 正常路径：加载实际配置文件
# ---------------------------------------------------------------------------

class TestLoadConfigHappyPath:
    def test_loads_actual_agents_yaml(self, project_root: Path):
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))

        assert isinstance(cfg, AppConfig)
        assert cfg.max_iterations == 3
        assert cfg.log_level == "INFO"
        # 三个 Agent 都存在
        assert "orchestrator" in cfg.agents
        assert "writer" in cfg.agents
        assert "reviewer" in cfg.agents
        # 四个 Provider 都存在
        assert "dashscope" in cfg.providers
        assert "minimax" in cfg.providers
        assert "bigmodel" in cfg.providers
        assert "openrouter" in cfg.providers

    def test_appconfig_has_no_output_dir(self, project_root: Path):
        """验证 output_dir 字段已从 AppConfig 彻底删除。"""
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))
        assert not hasattr(cfg, "output_dir"), (
            "output_dir 字段应已从 AppConfig 删除，但仍然存在"
        )

    def test_agents_yaml_has_no_output_dir_key(self, project_root: Path):
        """验证 config/agents.yaml 的 global 节点不含 output_dir 键。"""
        import yaml
        raw = yaml.safe_load(
            (project_root / "config" / "agents.yaml").read_text(encoding="utf-8")
        )
        assert "output_dir" not in raw.get("global", {}), (
            "agents.yaml 的 global 节点不应含 output_dir"
        )

    def test_agent_provider_references_are_valid(self, project_root: Path):
        """所有 Agent 的 provider 引用必须在 providers 中已定义。"""
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))
        for agent_name, agent_cfg in cfg.agents.items():
            assert agent_cfg.provider in cfg.providers, (
                f"Agent '{agent_name}' 的 provider '{agent_cfg.provider}' "
                f"未在 providers 中定义"
            )

    def test_writer_provider_is_minimax(self, project_root: Path):
        """验证 writer 的 provider 是 minimax（而非旧的 anthropic_compatible）。"""
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))
        assert cfg.agents["writer"].provider == "minimax"

    def test_reviewer_provider_is_bigmodel(self, project_root: Path):
        """验证 reviewer 的 provider 是 bigmodel（而非旧的 openai_compatible）。"""
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))
        assert cfg.agents["reviewer"].provider == "bigmodel"

    def test_tools_config_loaded(self, project_root: Path):
        config_path = project_root / "config" / "agents.yaml"
        cfg = load_config(str(config_path))
        assert isinstance(cfg.tools, ToolsConfig)
        assert cfg.tools.tavily_enabled is False


# ---------------------------------------------------------------------------
# load_config — 错误路径
# ---------------------------------------------------------------------------

class TestLoadConfigErrors:
    def test_file_not_found_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_non_dict_yaml_raises_config_error(self, tmp_path: Path):
        path = write_yaml(tmp_path, "- item1\n- item2\n")
        with pytest.raises(ConfigError, match="期望顶层为字典"):
            load_config(path)

    def test_agent_references_undefined_provider_raises(self, tmp_path: Path):
        yaml_content = """\
            global:
              max_iterations: 3
              log_level: INFO
            providers:
              dashscope:
                type: dashscope
                api_key_env: DASHSCOPE_API_KEY
            agents:
              orchestrator:
                provider: nonexistent_provider
                model: qwen3-max
        """
        path = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="未在 providers 中定义"):
            load_config(path)

    def test_provider_missing_type_raises(self, tmp_path: Path):
        yaml_content = """\
            global:
              max_iterations: 3
              log_level: INFO
            providers:
              myprovider:
                api_key_env: SOME_KEY
            agents:
              orchestrator:
                provider: myprovider
                model: some-model
        """
        path = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="缺少 'type' 字段"):
            load_config(path)

    def test_global_section_optional(self, tmp_path: Path):
        """global 节点缺失时应使用默认值，不应报错。"""
        yaml_content = """\
            providers:
              dashscope:
                type: dashscope
                api_key_env: DASHSCOPE_API_KEY
            agents:
              orchestrator:
                provider: dashscope
                model: qwen3-max
        """
        path = write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert cfg.max_iterations == 3     # 默认值
        assert cfg.log_level == "DEBUG"    # 默认值


# ---------------------------------------------------------------------------
# validate_env_vars
# ---------------------------------------------------------------------------

def _make_config(providers: dict, agents: dict, tavily_enabled: bool = False) -> AppConfig:
    """构造最小化 AppConfig，用于隔离测试 validate_env_vars。"""
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        providers={
            k: ProviderConfig(**v) for k, v in providers.items()
        },
        agents={
            k: AgentModelConfig(**v) for k, v in agents.items()
        },
        tools=ToolsConfig(
            tavily_enabled=tavily_enabled,
            tavily_api_key_env="TAVILY_API_KEY",
        ),
    )


class TestValidateEnvVars:
    def test_all_vars_set_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test")
        cfg = _make_config(
            providers={"myprovider": {"type": "openai_compatible", "api_key_env": "MY_API_KEY"}},
            agents={"writer": {"provider": "myprovider", "model": "gpt-4"}},
        )
        assert validate_env_vars(cfg) == []

    def test_missing_api_key_returned(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        cfg = _make_config(
            providers={"myprovider": {"type": "openai_compatible", "api_key_env": "MISSING_KEY"}},
            agents={"writer": {"provider": "myprovider", "model": "gpt-4"}},
        )
        missing = validate_env_vars(cfg)
        assert "MISSING_KEY" in missing

    def test_missing_base_url_env_returned(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test")
        monkeypatch.delenv("MY_BASE_URL", raising=False)
        cfg = _make_config(
            providers={
                "dashscope": {
                    "type": "dashscope",
                    "api_key_env": "MY_API_KEY",
                    "base_url_env": "MY_BASE_URL",
                }
            },
            agents={"orchestrator": {"provider": "dashscope", "model": "qwen3-max"}},
        )
        missing = validate_env_vars(cfg)
        assert "MY_BASE_URL" in missing

    def test_tavily_key_missing_when_enabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        cfg = _make_config(
            providers={"myprovider": {"type": "openai_compatible", "api_key_env": "MY_API_KEY"}},
            agents={"writer": {"provider": "myprovider", "model": "gpt-4"}},
            tavily_enabled=True,
        )
        missing = validate_env_vars(cfg)
        assert "TAVILY_API_KEY" in missing

    def test_tavily_key_not_checked_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        cfg = _make_config(
            providers={"myprovider": {"type": "openai_compatible", "api_key_env": "MY_API_KEY"}},
            agents={"writer": {"provider": "myprovider", "model": "gpt-4"}},
            tavily_enabled=False,   # 未启用
        )
        missing = validate_env_vars(cfg)
        assert "TAVILY_API_KEY" not in missing

    def test_unused_provider_not_checked(self, monkeypatch: pytest.MonkeyPatch):
        """只检查 agents 实际引用的 provider，未引用的 provider 的 key 不影响结果。"""
        monkeypatch.setenv("USED_KEY", "sk-test")
        monkeypatch.delenv("UNUSED_KEY", raising=False)
        cfg = _make_config(
            providers={
                "used": {"type": "openai_compatible", "api_key_env": "USED_KEY"},
                "unused": {"type": "openai_compatible", "api_key_env": "UNUSED_KEY"},
            },
            agents={"writer": {"provider": "used", "model": "gpt-4"}},
        )
        missing = validate_env_vars(cfg)
        assert "UNUSED_KEY" not in missing
        assert missing == []
