
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.reasoning_compat import (
    extract_reasoning_details,
    StructuredReasoningDetailsCodec,
    _OpenRouterReasoningDetailsMixin
)
from src.openrouter_compat import ReasoningCompatibleChatOpenRouter

def test_extract_reasoning_details_logic():
    """验证从 AIMessage 中提取结构化推理。"""
    details = [{"type": "text", "text": "thinking..."}]
    msg = AIMessage(content="hello", additional_kwargs={"reasoning_details": details})
    
    extracted = extract_reasoning_details(msg)
    assert extracted == details
    assert extracted is not msg.additional_kwargs["reasoning_details"]  # 深度拷贝验证由 Codec 负责

def test_structured_codec_injection():
    """验证 Codec 将推理细节注入到请求 Payload。"""
    codec = StructuredReasoningDetailsCodec()
    details = [{"type": "text", "text": "thought"}]
    messages = [
        AIMessage(content="res", additional_kwargs={"reasoning_details": details})
    ]
    payload = {"messages": [{"role": "assistant", "content": "res"}]}
    
    updated_payload = codec.inject_into_payload(messages, payload)
    assert updated_payload["messages"][0]["reasoning_details"] == details
    # 验证防御性拷贝
    assert updated_payload["messages"][0]["reasoning_details"] is not details

def test_mixin_extraction_from_raw_choice():
    """验证 Mixin 能从原始 API Choice 中补取推理（兜底逻辑）。"""
    mixin = _OpenRouterReasoningDetailsMixin()
    mock_choice = type('obj', (object,), {
        'message': type('obj', (object,), {
            'reasoning_details': [{"t": "1"}]
        })
    })
    
    extracted = mixin._extract_reasoning_details_from_choice(mock_choice)
    assert extracted == [{"t": "1"}]

def test_openrouter_all_or_nothing_validation():
    """验证 OpenRouter 全量切换校验（在 config_loader 中）。"""
    from src.config_loader import AgentModelConfig, _validate_openrouter_all_or_nothing, ConfigError
    
    agents = {
        "orchestrator": AgentModelConfig(enabled=True, provider="openrouter"),
        "writer": AgentModelConfig(enabled=True, provider="deepseek") # 混合使用
    }
    
    with pytest.raises(ConfigError, match="检测到 OpenRouter 与其他 provider 混用"):
        _validate_openrouter_all_or_nothing(agents)
        
    # 全量 openrouter 应该通过
    agents["writer"].provider = "openrouter"
    _validate_openrouter_all_or_nothing(agents)
