"""config_loader 单元测试。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config_loader import (
    AppConfig,
    AgentModelConfig,
    ConfigError,
    Context7Config,
    ProviderConfig,
    ToolsConfig,
    load_config,
    validate_env_vars,
)


def write_yaml(tmp_path: Path, content: str) -> str:
    path = tmp_path / "agents.yaml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(path)


class TestLoadConfigHappyPath:
    def test_loads_actual_agents_yaml(self, project_root: Path):
        cfg = load_config(str(project_root / "config" / "agents.yaml"))
        assert isinstance(cfg, AppConfig)
        assert cfg.hil_clarify is True
        assert "reviewer1" in cfg.agents
        assert "reviewer2" in cfg.agents
        assert not hasattr(cfg, "hil_confirm")
        assert cfg.agents["reviewer1"].provider == "bigmodel"
        assert cfg.agents["reviewer2"].provider == "minimax"
        assert cfg.agents["reviewer2"].model == "minimax-2.5"
        assert cfg.agents["reviewer2"].enabled is False

    def test_context7_config_loaded(self, project_root: Path):
        cfg = load_config(str(project_root / "config" / "agents.yaml"))
        assert isinstance(cfg.tools.context7, Context7Config)
        assert cfg.tools.context7.api_key_env == "CONTEXT7_API_KEY"


class TestLoadConfigErrors:
    def test_old_reviewer_key_raises(self, tmp_path: Path):
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: true
            providers:
              p:
                type: dashscope
                api_key_env: KEY
            agents:
              orchestrator:
                provider: p
                model: m1
              writer:
                provider: p
                model: m2
              reviewer:
                provider: p
                model: m3
            """,
        )
        with pytest.raises(ConfigError, match="agents.reviewer"):
            load_config(path)

    def test_reviewer1_must_be_enabled(self, tmp_path: Path):
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: true
            providers:
              p:
                type: dashscope
                api_key_env: KEY
            agents:
              orchestrator:
                provider: p
                model: m1
              writer:
                provider: p
                model: m2
              reviewer1:
                enabled: false
                provider: p
                model: m3
            """,
        )
        with pytest.raises(ConfigError, match="reviewer1 必须启用"):
            load_config(path)

    def test_reviewer2_enabled_requires_different_model(self, tmp_path: Path):
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: true
            providers:
              p:
                type: dashscope
                api_key_env: KEY
            agents:
              orchestrator:
                provider: p
                model: m1
              writer:
                provider: p
                model: m2
              reviewer1:
                enabled: true
                provider: p
                model: m3
              reviewer2:
                enabled: true
                provider: p
                model: m3
            """,
        )
        with pytest.raises(ConfigError, match="不同的 provider\\+model"):
            load_config(path)

    @pytest.mark.parametrize("field,value", [("hil_clarify", '"false"'), ("hil_clarify", "0")])
    def test_hil_clarify_must_be_bool(self, tmp_path: Path, field: str, value: str):
        path = write_yaml(
            tmp_path,
            f"""
            global:
              {field}: {value}
            providers:
              p:
                type: dashscope
                api_key_env: KEY
            agents:
              orchestrator:
                provider: p
                model: m1
              writer:
                provider: p
                model: m2
              reviewer1:
                enabled: true
                provider: p
                model: m3
            """,
        )
        with pytest.raises(ConfigError, match="必须为布尔值"):
            load_config(path)


def _make_config(
    providers: dict,
    agents: dict,
    tavily_enabled: bool = False,
    context7_enabled: bool = False,
) -> AppConfig:
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        file_log_level="DEBUG",
        hil_clarify=False,
        providers={k: ProviderConfig(**v) for k, v in providers.items()},
        agents={k: AgentModelConfig(**v) for k, v in agents.items()},
        tools=ToolsConfig(
            tavily_enabled=tavily_enabled,
            tavily_api_key_env="TAVILY_API_KEY",
            context7=Context7Config(enabled=context7_enabled),
        ),
    )


class TestValidateEnvVars:
    def test_all_vars_set_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test")
        cfg = _make_config(
            providers={"p": {"type": "openai_compatible", "api_key_env": "MY_API_KEY"}},
            agents={"writer": {"provider": "p", "model": "gpt-4"}},
        )
        assert validate_env_vars(cfg) == []

    def test_disabled_reviewer2_provider_env_is_skipped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("USED_KEY", "ok")
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        cfg = _make_config(
            providers={
                "used": {"type": "deepseek", "api_key_env": "USED_KEY"},
                "minimax": {"type": "anthropic_compatible", "api_key_env": "MINIMAX_API_KEY"},
            },
            agents={
                "orchestrator": {"provider": "used", "model": "m1"},
                "writer": {"provider": "used", "model": "m2"},
                "reviewer1": {"provider": "used", "model": "m3"},
                "reviewer2": {"enabled": False, "provider": "minimax", "model": "minimax-2.5"},
            },
        )
        assert "MINIMAX_API_KEY" not in validate_env_vars(cfg)

    def test_enabled_reviewer2_provider_env_is_checked(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("USED_KEY", "ok")
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        cfg = _make_config(
            providers={
                "used": {"type": "deepseek", "api_key_env": "USED_KEY"},
                "minimax": {"type": "anthropic_compatible", "api_key_env": "MINIMAX_API_KEY"},
            },
            agents={
                "orchestrator": {"provider": "used", "model": "m1"},
                "writer": {"provider": "used", "model": "m2"},
                "reviewer1": {"provider": "used", "model": "m3"},
                "reviewer2": {"enabled": True, "provider": "minimax", "model": "minimax-2.5"},
            },
        )
        assert "MINIMAX_API_KEY" in validate_env_vars(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter 参数早期校验
# ─────────────────────────────────────────────────────────────────────────────

def _openrouter_yaml(tmp_path: Path, agent_params: str = "") -> str:
    """生成只含 OpenRouter 四模型的最小合法 YAML，可在 agent params 处插入额外字段。"""
    return write_yaml(
        tmp_path,
        f"""
        global:
          hil_clarify: false
        providers:
          openrouter:
            type: openrouter
            api_key_env: OPENROUTER_API_KEY
        agents:
          orchestrator:
            provider: openrouter
            model: anthropic/claude-sonnet-4.6
            params:
              temperature: 0.2
              {agent_params}
          writer:
            provider: openrouter
            model: google/gemini-3.1-pro-preview
            params:
              temperature: 0.2
          reviewer1:
            enabled: true
            provider: openrouter
            model: anthropic/claude-sonnet-4.6
            params:
              temperature: 0.2
          reviewer2:
            enabled: true
            provider: openrouter
            model: openai/gpt-5.3-codex
            params:
              temperature: 0.2
        """,
    )


class TestOpenRouterAgentParamValidation:
    def test_use_responses_api_true_raises_config_error(self, tmp_path: Path):
        path = _openrouter_yaml(tmp_path, "use_responses_api: true")
        with pytest.raises(ConfigError, match="use_responses_api"):
            load_config(path)

    def test_use_responses_api_false_does_not_raise(self, tmp_path: Path):
        path = _openrouter_yaml(tmp_path, "use_responses_api: false")
        cfg = load_config(path)
        assert cfg.agents["orchestrator"].params["use_responses_api"] is False

    def test_use_responses_api_absent_does_not_raise(self, tmp_path: Path):
        path = _openrouter_yaml(tmp_path)
        cfg = load_config(path)
        assert "use_responses_api" not in cfg.agents["orchestrator"].params

    def test_x_title_in_extra_body_raises_config_error(self, tmp_path: Path):
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: false
            providers:
              openrouter:
                type: openrouter
                api_key_env: OPENROUTER_API_KEY
            agents:
              orchestrator:
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params:
                  extra_body:
                    x_title: "My App"
              writer:
                provider: openrouter
                model: google/gemini-3.1-pro-preview
                params: {}
              reviewer1:
                enabled: true
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params: {}
            """,
        )
        with pytest.raises(ConfigError, match="x_title"):
            load_config(path)

    def test_http_referer_in_extra_body_raises_config_error(self, tmp_path: Path):
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: false
            providers:
              openrouter:
                type: openrouter
                api_key_env: OPENROUTER_API_KEY
            agents:
              orchestrator:
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params:
                  extra_body:
                    http_referer: "https://example.com"
              writer:
                provider: openrouter
                model: google/gemini-3.1-pro-preview
                params: {}
              reviewer1:
                enabled: true
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params: {}
            """,
        )
        with pytest.raises(ConfigError, match="http_referer"):
            load_config(path)

    def test_disabled_openrouter_agent_use_responses_api_true_not_checked(self, tmp_path: Path):
        """禁用中的 agent 不参与校验。"""
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: false
            providers:
              openrouter:
                type: openrouter
                api_key_env: OPENROUTER_API_KEY
            agents:
              orchestrator:
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params: {}
              writer:
                provider: openrouter
                model: google/gemini-3.1-pro-preview
                params: {}
              reviewer1:
                enabled: true
                provider: openrouter
                model: anthropic/claude-sonnet-4.6
                params: {}
              reviewer2:
                enabled: false
                provider: openrouter
                model: openai/gpt-5.3-codex
                params:
                  use_responses_api: true
            """,
        )
        cfg = load_config(path)
        assert cfg.agents["reviewer2"].enabled is False

    def test_non_openrouter_agent_use_responses_api_true_not_checked(self, tmp_path: Path):
        """非 OpenRouter agent 不参与 OpenRouter 参数校验。"""
        path = write_yaml(
            tmp_path,
            """
            global:
              hil_clarify: false
            providers:
              deepseek:
                type: deepseek
                api_key_env: DEEPSEEK_API_KEY
            agents:
              orchestrator:
                provider: deepseek
                model: deepseek-chat
                params:
                  use_responses_api: true
              writer:
                provider: deepseek
                model: deepseek-chat
                params: {}
              reviewer1:
                enabled: true
                provider: deepseek
                model: deepseek-chat
                params: {}
            """,
        )
        cfg = load_config(path)
        assert cfg.agents["orchestrator"].params["use_responses_api"] is True

    def test_error_message_includes_agent_name(self, tmp_path: Path):
        """报错信息应包含出问题的 agent 名称，便于定位。"""
        path = _openrouter_yaml(tmp_path, "use_responses_api: true")
        with pytest.raises(ConfigError, match="orchestrator"):
            load_config(path)
