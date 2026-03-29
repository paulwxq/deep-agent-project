
import json
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from src.openrouter_compat import ReasoningCompatibleChatOpenRouter
from langchain_core.tools import tool

def test_openrouter_full_cycle_mock():
    """模拟 OpenRouter 从工具调用到最终回答的完整周期。"""
    llm = ReasoningCompatibleChatOpenRouter(
        model_name="anthropic/claude-3.7-sonnet",
        openrouter_api_key="sk-test",
        parallel_tool_calls=False,
        preserve_reasoning_details=True
    )

    @tool
    def get_weather(location: str):
        """test tool"""
        return "sunny"

    llm_with_tools = llm.bind_tools([get_weather])

    # 1. 模拟第一次请求：模型决定调用工具
    mock_response_1 = {
        "id": "gen-1",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I will check the weather.",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"location": "Shanghai"}'}
                }],
                "reasoning_details": [{"type": "text", "text": "I should call weather tool."}]
            }
        }],
        "usage": {"total_tokens": 10}
    }

    # 2. 模拟第二次请求：回传工具结果和推理详情
    mock_response_2 = {
        "id": "gen-2",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "The weather is sunny.",
            }
        }],
        "usage": {"total_tokens": 20}
    }

    # 使用 patch 拦截底层 API 调用
    with patch("openrouter.OpenRouter") as mock_sdk_class:
        mock_client = mock_sdk_class.return_value
        
        # 构造模拟的 SDK 响应对象
        mock_res_1 = MagicMock()
        mock_res_1.model_dump.return_value = mock_response_1
        
        mock_res_2 = MagicMock()
        mock_res_2.model_dump.return_value = mock_response_2

        # 第一次调用返回 mock_res_1
        # 第二次调用返回 mock_res_2
        mock_client.chat.send.side_effect = [mock_res_1, mock_res_2]
        
        # 重新挂载模拟的 client
        llm.client = mock_client

        # 执行第一轮
        messages = [HumanMessage(content="weather?")]
        res1 = llm_with_tools.invoke(messages)
        
        assert len(res1.tool_calls) == 1
        assert res1.additional_kwargs["reasoning_details"][0]["text"] == "I should call weather tool."

        # 执行第二轮（手动拼装历史）
        tool_msg = ToolMessage(content="sunny", tool_call_id="call_1")
        messages.extend([res1, tool_msg])
        
        res2 = llm_with_tools.invoke(messages)
        
        # 核心验证：检查第二次请求的 payload 是否包含第一次的 reasoning_details
        if mock_client.chat.send.called:
            # 获取第二次调用的参数 (索引为 1)
            _, second_call_kwargs = mock_client.chat.send.call_args
            msgs_in_payload = second_call_kwargs["messages"]
            
            # 找到 payload 中的 assistant 消息
            assistant_msg = next(m for m in msgs_in_payload if m.get("role") == "assistant")
            assert "reasoning_details" in assistant_msg
            assert assistant_msg["reasoning_details"][0]["text"] == "I should call weather tool."
            print("--- Full Cycle Mock SUCCESS: Reasoning details preserved ---")

if __name__ == "__main__":
    test_openrouter_full_cycle_mock()
