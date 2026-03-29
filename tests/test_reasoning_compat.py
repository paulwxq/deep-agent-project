"""reasoning_compat 单元测试。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.middleware.logging_middleware import LoggingMiddleware
from src.reasoning_compat import (
    ReasoningCompatibleChatDeepSeek,
    ReasoningCompatibleChatOpenAI,
    extract_reasoning_text,
    sanitize_tool_messages_payload,
)


def _clear_proxy_env(monkeypatch) -> None:
    for key in ["ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        monkeypatch.delenv(key, raising=False)


def test_extract_reasoning_text_prefers_additional_kwargs():
    message = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "step-1\nstep-2"},
    )

    assert extract_reasoning_text(message) == "step-1\nstep-2"


def test_extract_reasoning_text_reads_thinking_blocks():
    message = AIMessage(
        content=[
            {"type": "thinking", "thinking": "first"},
            {"type": "thinking", "thinking": "second"},
            {"type": "text", "text": "visible"},
        ],
        response_metadata={"model_provider": "anthropic"},
    )

    assert extract_reasoning_text(message) == "first\nsecond"


def test_reasoning_chatopenai_reinserts_reasoning_content_into_payload(monkeypatch):
    _clear_proxy_env(monkeypatch)
    model = ReasoningCompatibleChatOpenAI(
        model="glm-5",
        api_key="sk-test",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        preserve_reasoning=True,
        provider_name="bigmodel",
    )
    messages = [
        ("human", "请读取文件"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "先分析，再调用 read_file"},
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "/tmp/test.md"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="文件内容", tool_call_id="call_1"),
    ]

    payload = model._get_request_payload(messages)

    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["reasoning_content"] == "先分析，再调用 read_file"
    assert payload["messages"][1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert payload["messages"][2]["role"] == "tool"


def test_reasoning_chatdeepseek_reinserts_reasoning_content_into_payload(monkeypatch):
    _clear_proxy_env(monkeypatch)
    model = ReasoningCompatibleChatDeepSeek(
        model="deepseek-reasoner",
        api_key="sk-test",
        preserve_reasoning=True,
        provider_name="deepseek",
    )
    messages = [
        ("human", "检查文件"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "先确定需要调用工具"},
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": "/tmp/a.md"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="ok", tool_call_id="call_1"),
    ]

    payload = model._get_request_payload(messages)

    assert payload["messages"][1]["reasoning_content"] == "先确定需要调用工具"


def test_reasoning_chatopenai_extracts_reasoning_from_provider_response(monkeypatch):
    _clear_proxy_env(monkeypatch)
    model = ReasoningCompatibleChatOpenAI(
        model="kimi-k2.5",
        api_key="sk-test",
        base_url="https://api.moonshot.cn/v1",
        provider_name="moonshot",
    )
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    reasoning_content="推理片段",
                    model_extra={},
                )
            )
        ]
    )
    base_result = ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    with patch(
        "langchain_openai.chat_models.base.ChatOpenAI._create_chat_result",
        return_value=base_result,
    ):
        result = model._create_chat_result(fake_response)

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning_content"] == "推理片段"
    assert message.response_metadata["model_provider"] == "moonshot"


def test_reasoning_chatopenai_drops_incomplete_tool_call_history(monkeypatch):
    _clear_proxy_env(monkeypatch)
    model = ReasoningCompatibleChatOpenAI(
        model="glm-5",
        api_key="sk-test",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        provider_name="bigmodel",
    )

    payload = {
        "messages": [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "write_file:15",
                        "type": "function",
                        "function": {"name": "write_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "继续处理"},
        ]
    }

    sanitized = model._sanitize_tool_messages(payload)

    assert sanitized["messages"] == [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "继续处理"},
    ]


def test_reasoning_chatopenai_keeps_complete_tool_call_history(monkeypatch):
    _clear_proxy_env(monkeypatch)
    model = ReasoningCompatibleChatOpenAI(
        model="glm-5",
        api_key="sk-test",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        provider_name="bigmodel",
    )

    payload = {
        "messages": [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "write_file:15",
                        "type": "function",
                        "function": {"name": "write_file", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "write_file:15",
                "content": "ok",
            },
            {"role": "assistant", "content": "继续处理"},
        ]
    }

    sanitized = model._sanitize_tool_messages(payload)

    assert sanitized["messages"] == payload["messages"]


class TestSanitizeToolMessagesPayload:
    """直接测试 sanitize_tool_messages_payload 独立 helper。"""

    def _incomplete_payload(self) -> dict:
        return {
            "messages": [
                {"role": "user", "content": "start"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
                    ],
                },
                {"role": "assistant", "content": "继续"},
            ]
        }

    def _complete_payload(self) -> dict:
        return {
            "messages": [
                {"role": "user", "content": "start"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "file content"},
                {"role": "assistant", "content": "done"},
            ]
        }

    def test_drops_incomplete_tool_call(self):
        payload = self._incomplete_payload()
        result = sanitize_tool_messages_payload(payload, provider="test-provider")
        roles = [m["role"] for m in result["messages"]]
        assert roles == ["user", "assistant"]
        assert result["messages"][1]["content"] == "继续"

    def test_keeps_complete_tool_call(self):
        payload = self._complete_payload()
        result = sanitize_tool_messages_payload(payload, provider="test-provider")
        assert result["messages"] == self._complete_payload()["messages"]

    def test_drops_orphan_tool_message(self):
        payload = {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "tool", "tool_call_id": "orphan_id", "content": "result"},
                {"role": "assistant", "content": "reply"},
            ]
        }
        result = sanitize_tool_messages_payload(payload, provider="test-provider")
        roles = [m["role"] for m in result["messages"]]
        assert roles == ["user", "assistant"]

    def test_no_op_when_messages_key_absent(self):
        payload = {"model": "gpt-4"}
        result = sanitize_tool_messages_payload(payload, provider="test-provider")
        assert result == {"model": "gpt-4"}

    def test_default_provider_unknown(self):
        payload = self._incomplete_payload()
        # 不传 provider 时不应抛错
        result = sanitize_tool_messages_payload(payload)
        assert len(result["messages"]) == 2

    def test_openrouter_mixin_calls_helper_with_openrouter_provider(self, monkeypatch):
        """ReasoningCompatibleChatOpenRouter._sanitize_tool_messages 传入 provider='openrouter'。"""
        from unittest.mock import patch as _patch
        from src.openrouter_compat import ReasoningCompatibleChatOpenRouter

        called_with: list = []

        def fake_sanitize(payload, provider="unknown"):
            called_with.append(provider)
            return payload

        payload = self._complete_payload()
        with _patch("src.openrouter_compat.sanitize_tool_messages_payload", side_effect=fake_sanitize):
            monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
            model = ReasoningCompatibleChatOpenRouter.__new__(ReasoningCompatibleChatOpenRouter)
            model._sanitize_tool_messages(payload)

        assert called_with == ["openrouter"]

    def test_reasoning_passthrough_mixin_calls_helper_with_provider_name(self, monkeypatch):
        """_ReasoningPassthroughMixin._sanitize_tool_messages 传入 self.provider_name。"""
        from unittest.mock import patch as _patch

        called_with: list = []

        def fake_sanitize(payload, provider="unknown"):
            called_with.append(provider)
            return payload

        model = ReasoningCompatibleChatOpenAI(
            model="glm-5",
            api_key="sk-test",
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            provider_name="bigmodel",
        )
        payload = self._complete_payload()
        with _patch("src.reasoning_compat.sanitize_tool_messages_payload", side_effect=fake_sanitize):
            model._sanitize_tool_messages(payload)

        assert called_with == ["bigmodel"]


def test_logging_middleware_logs_reasoning_blocks(caplog):
    middleware = LoggingMiddleware(agent_name="writer")
    message = AIMessage(
        content=[{"type": "thinking", "thinking": "分析路径"}],
        response_metadata={"model_provider": "anthropic"},
    )

    with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
        middleware._log_model_output(message)

    assert "💭 推理过程: 分析路径" in caplog.text
