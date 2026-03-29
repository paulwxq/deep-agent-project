
import os
import pytest
from unittest.mock import MagicMock, patch
from src.config_loader import ProviderConfig, AgentModelConfig
from src.model_factory import create_model, _create_openrouter
from src.openrouter_compat import ReasoningCompatibleChatOpenRouter

def test_create_openrouter_model_basic():
    """验证基本 OpenRouter 模型创建成功。"""
    pcfg = ProviderConfig(
        type="openrouter",
        api_key_env="TEST_OPENROUTER_KEY",
        base_url="https://openrouter.ai/api/v1"
    )
    acfg = AgentModelConfig(
        provider="openrouter",
        model="anthropic/claude-3.7-sonnet",
        params={"temperature": 0.5}
    )
    
    with patch.dict(os.environ, {"TEST_OPENROUTER_KEY": "sk-test"}):
        model = create_model(pcfg, acfg)
        assert isinstance(model, ReasoningCompatibleChatOpenRouter)
        assert model.model_name == "anthropic/claude-3.7-sonnet"
        assert model.temperature == 0.5

def test_create_openrouter_does_not_mutate_os_environ():
    """验证不再写全局环境变量 OPENROUTER_API_KEY。"""
    pcfg = ProviderConfig(
        type="openrouter",
        api_key_env="CUSTOM_KEY_ENV",
    )
    acfg = AgentModelConfig(model="test", params={})
    
    # 确保初始状态没有这个环境变量
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
        
    with patch.dict(os.environ, {"CUSTOM_KEY_ENV": "sk-secret"}):
        _create_openrouter(pcfg, acfg, "sk-secret", {})
        # 验证全局环境变量未被污染
        assert "OPENROUTER_API_KEY" not in os.environ

def test_openrouter_maps_model_kwargs_and_validation():
    """验证 verbosity 进入 model_kwargs，且禁止旧参数。"""
    pcfg = ProviderConfig(type="openrouter", api_key_env="K")
    acfg = AgentModelConfig(model="m")
    params = {
        "verbosity": "high",
        "extra_body": {"top_k": 50}
    }
    
    model = _create_openrouter(pcfg, acfg, "sk", params)
    assert model.model_kwargs["verbosity"] == "high"
    assert model.model_kwargs["top_k"] == 50

    # 验证禁止旧参数
    with pytest.raises(ValueError, match="app_title / app_url"):
        _create_openrouter(pcfg, acfg, "sk", {"extra_body": {"x_title": "bad"}})

def test_use_responses_api_error():
    """验证开启 Responses API 会报错。"""
    pcfg = ProviderConfig(type="openrouter", api_key_env="K")
    acfg = AgentModelConfig(model="m")
    
    with pytest.raises(NotImplementedError):
        _create_openrouter(pcfg, acfg, "sk", {"use_responses_api": True})
