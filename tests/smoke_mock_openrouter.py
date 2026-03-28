
import json
from typing import Any, Sequence, Optional
from unittest.mock import MagicMock, patch
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

# 模拟即将实现的组件逻辑（原型）
from langchain_openrouter import ChatOpenRouter

class ReasoningCompatibleChatOpenRouterPrototype(ChatOpenRouter):
    """用于测试的设计原型"""
    parallel_tool_calls: Optional[bool] = Field(default=None)
    preserve_reasoning_details: bool = Field(default=False)

    def bind_tools(self, tools, **kwargs):
        # 设计点：优先在绑定环节传 parallel_tool_calls
        if self.parallel_tool_calls is not None and "parallel_tool_calls" not in kwargs:
            kwargs["parallel_tool_calls"] = self.parallel_tool_calls
        return super().bind_tools(tools, **kwargs)

    def _get_request_payload(self, messages: Sequence[BaseMessage], **kwargs: Any) -> dict:
        payload = super()._get_request_payload(messages, **kwargs)
        # 模拟设计中的 reasoning 回传逻辑
        if self.preserve_reasoning_details:
            # 找到 payload 中的 assistant 消息并注入
            # 注意：LangChain 内部会把 BaseMessage 转为 dict
            for i, msg in enumerate(messages):
                if isinstance(msg, AIMessage) and "reasoning_details" in msg.additional_kwargs:
                    if i < len(payload["messages"]):
                        payload["messages"][i]["reasoning_details"] = msg.additional_kwargs["reasoning_details"]
        return payload

def run_mock_smoke_test():
    print("=== [Mock Smoke Test] 开始验证 ===")
    
    # 1. 初始化原型
    # 注意：ChatOpenRouter 是 Pydantic 模型，直接传参
    llm = ReasoningCompatibleChatOpenRouterPrototype(
        model_name="anthropic/claude-3.7-sonnet",
        openrouter_api_key="sk-test",
        parallel_tool_calls=False,
        preserve_reasoning_details=True,
        app_title="MockTestApp",
        streaming=False # 强制设为 False
    )

    @tool
    def search_sas_code(query: str):
        """Search SAS code."""
        return "found lineage info"

    llm_with_tools = llm.bind_tools([search_sas_code])

    # 2. 准备带推理细节的历史消息 (模拟多轮对话)
    history = [
        HumanMessage(content="分析血缘"),
        AIMessage(
            content="我需要调用搜索工具。",
            additional_kwargs={
                "reasoning_details": [{"type": "text", "text": "思考中..."}]
            }
        ),
        ToolMessage(content="搜索结果: abc", tool_call_id="call_1")
    ]

    # 3. 拦截请求并检查
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "分析结果完毕。"
    mock_choice.message.tool_calls = None
    mock_response.choices = [mock_choice]
    mock_response.usage.total_tokens = 50
    mock_client.chat.send.return_value = mock_response
    
    llm.client = mock_client

    print("正在发送多轮对话请求...")
    try:
        llm_with_tools.invoke(history)
    except Exception:
        pass

    # 4. 深度检查 Payload
    if mock_client.chat.send.called:
        _, call_kwargs = mock_client.chat.send.call_args
        print("\n[Payload 检查结果]")
        
        # 验证 parallel_tool_calls
        ptc = call_kwargs.get("parallel_tool_calls")
        print(f"1. parallel_tool_calls: {ptc} ({'✅ 正确' if ptc is False else '❌ 错误'})")
        
        # 验证 reasoning_details 是否注入到消息历史
        msgs = call_kwargs.get("messages", [])
        # 检查 payload 里的第二条消息（AIMessage）是否带有推理
        has_reasoning = any("reasoning_details" in m for m in msgs)
        print(f"2. 历史消息中包含 reasoning_details: {has_reasoning} ({'✅ 正确' if has_reasoning else '❌ 错误'})")
        if has_reasoning:
            for m in msgs:
                if "reasoning_details" in m:
                    print(f"   内容样例: {m['reasoning_details']}")

    print("\n=== Mock Smoke Test 完成 ===")

if __name__ == "__main__":
    import openrouter
    old_init = openrouter.OpenRouter.__init__
    def new_init(self, *args, **kwargs):
        kwargs.pop('x_title', None)
        return old_init(self, *args, **kwargs)
    openrouter.OpenRouter.__init__ = new_init
    
    run_mock_smoke_test()
