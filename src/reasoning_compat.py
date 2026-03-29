"""推理内容兼容层。

补齐 LangChain 对第三方 OpenAI 兼容 / DeepSeek 兼容接口中
`reasoning_content` 的提取与回传能力。

适用场景：
- Moonshot Kimi K2.5 thinking + tools
- GLM-5 thinking + tools
- DeepSeek thinking + tools

这些 provider 在工具循环中要求将 assistant message 中的
`reasoning_content` 原样回传。原生 `ChatOpenAI` 不会保留这类
非 OpenAI 标准字段，因此需要在本项目侧补一层兼容。

OpenRouter 专用：
- `_OpenRouterReasoningDetailsMixin` 处理结构化 `reasoning_details: list[dict]`
- 独立于字符串 reasoning 通道，与 `_ReasoningPassthroughMixin` 并列而非继承
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any
import logging

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger("deep_agent_project")


def sanitize_tool_messages_payload(
    payload: dict[str, Any],
    provider: str = "unknown",
) -> dict[str, Any]:
    """清理 payload 中不完整的 tool-call 历史。

    某些 middleware（如 summarization）可能截断历史，导致
    assistant(tool_calls=...) 后面缺少完整的 tool messages。
    这类请求会被严格校验的服务端直接拒绝。

    供 _ReasoningPassthroughMixin 和 ReasoningCompatibleChatOpenRouter 共同调用，
    两者通过各自的 _sanitize_tool_messages 方法传入对应的 provider 名称。
    """
    payload_messages = payload.get("messages")
    if not isinstance(payload_messages, list):
        return payload

    sanitized: list[dict[str, Any]] = []
    i = 0
    while i < len(payload_messages):
        message = payload_messages[i]
        if not isinstance(message, dict):
            i += 1
            continue

        role = message.get("role")
        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            required_ids = {
                tc.get("id")
                for tc in tool_calls
                if isinstance(tc, dict) and tc.get("id")
            }
            contiguous_tool_messages: list[dict[str, Any]] = []
            j = i + 1
            while j < len(payload_messages):
                next_message = payload_messages[j]
                if not isinstance(next_message, dict) or next_message.get("role") != "tool":
                    break
                contiguous_tool_messages.append(next_message)
                j += 1

            returned_ids = {
                tm.get("tool_call_id")
                for tm in contiguous_tool_messages
                if isinstance(tm, dict) and tm.get("tool_call_id")
            }
            if required_ids and not required_ids.issubset(returned_ids):
                logger.debug(
                    "清理不完整 tool 调用历史: provider=%s, 缺失 tool_call_id=%s",
                    provider,
                    ", ".join(sorted(required_ids - returned_ids)),
                    extra={"agent_name": "system"},
                )
                i = j
                continue

            sanitized.append(message)
            sanitized.extend(contiguous_tool_messages)
            i = j
            continue

        if role == "tool":
            logger.debug(
                "清理孤立 tool message: provider=%s, tool_call_id=%s",
                provider,
                message.get("tool_call_id", ""),
                extra={"agent_name": "system"},
            )
            i += 1
            continue

        sanitized.append(message)
        i += 1

    payload["messages"] = sanitized
    return payload


def extract_reasoning_text(message: BaseMessage) -> str:
    """从 LangChain message 中尽可能提取 reasoning 文本。"""
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    for key in ("reasoning_content", "thought", "reasoning"):
        value = additional_kwargs.get(key)
        if isinstance(value, str) and value:
            return value

    blocks = []
    try:
        blocks = list(getattr(message, "content_blocks", []) or [])
    except Exception:
        blocks = []

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "reasoning":
            reasoning = block.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                parts.append(reasoning)
        elif block.get("type") == "thinking":
            thinking = block.get("thinking") or block.get("text")
            if isinstance(thinking, str) and thinking:
                parts.append(thinking)

    return "\n".join(parts)


class _ReasoningPassthroughMixin:
    """为第三方 provider 增加 reasoning 提取与回传。"""

    preserve_reasoning: bool = Field(default=False)
    provider_name: str | None = Field(default=None)
    reasoning_field_name: str = Field(default="reasoning_content")

    def _set_provider_metadata(self, message: AIMessage | AIMessageChunk) -> None:
        if not self.provider_name:
            return
        message.response_metadata = {
            **(message.response_metadata or {}),
            "model_provider": self.provider_name,
        }

    def _extract_reasoning_from_choice(self, choice: Any) -> str:
        message = getattr(choice, "message", None)
        if message is None:
            return ""

        value = getattr(message, self.reasoning_field_name, None)
        if isinstance(value, str) and value:
            return value

        model_extra = getattr(message, "model_extra", None)
        if isinstance(model_extra, dict):
            for key in (self.reasoning_field_name, "reasoning"):
                extra_value = model_extra.get(key)
                if isinstance(extra_value, str) and extra_value:
                    return extra_value

        return ""

    def _extract_reasoning_from_delta(self, chunk: dict[str, Any]) -> str:
        choices = chunk.get("choices")
        if not choices:
            return ""
        top = choices[0]
        delta = top.get("delta", {})
        if not isinstance(delta, dict):
            return ""

        value = delta.get(self.reasoning_field_name) or delta.get("reasoning")
        return value if isinstance(value, str) else ""

    def _inject_reasoning_into_payload(
        self,
        messages: Sequence[BaseMessage],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.preserve_reasoning or "messages" not in payload:
            return payload

        payload_messages = payload.get("messages", [])
        for original_message, payload_message in zip(messages, payload_messages):
            if not isinstance(original_message, AIMessage):
                continue
            if not isinstance(payload_message, dict) or payload_message.get("role") != "assistant":
                continue

            reasoning = extract_reasoning_text(original_message)
            if reasoning:
                payload_message[self.reasoning_field_name] = reasoning

        return payload

    def _sanitize_tool_messages(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """清理 OpenAI 兼容接口中的不完整 tool-call 历史。

        某些 middleware（如 summarization）可能截断历史，导致：
        assistant(tool_calls=...) 后面缺少完整的 tool messages。
        这类请求会被 Moonshot / Zhipu / DeepSeek 等严格校验的服务端直接拒绝。
        """
        return sanitize_tool_messages_payload(payload, self.provider_name or "unknown")

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload = self._inject_reasoning_into_payload(messages, payload)
        return self._sanitize_tool_messages(payload)

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)

        for generation in result.generations:
            if isinstance(generation.message, AIMessage):
                self._set_provider_metadata(generation.message)

        choices = getattr(response, "choices", None)
        if choices and result.generations:
            reasoning = self._extract_reasoning_from_choice(choices[0])
            if reasoning and isinstance(result.generations[0].message, AIMessage):
                result.generations[0].message.additional_kwargs[
                    self.reasoning_field_name
                ] = reasoning

        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if not generation_chunk or not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk

        self._set_provider_metadata(generation_chunk.message)
        reasoning = self._extract_reasoning_from_delta(chunk)
        if reasoning:
            generation_chunk.message.additional_kwargs[self.reasoning_field_name] = reasoning

        return generation_chunk


class ReasoningCompatibleChatOpenAI(_ReasoningPassthroughMixin, ChatOpenAI):
    """支持第三方 reasoning_content 的 ChatOpenAI 包装器。"""


class ReasoningCompatibleChatDeepSeek(_ReasoningPassthroughMixin, ChatDeepSeek):
    """支持 DeepSeek reasoning_content 回传的 ChatDeepSeek 包装器。"""


# ============================================================
# 结构化 reasoning_details 通道（OpenRouter 专用）
# 与字符串 reasoning 通道并列，不互相替代。
# ============================================================


def extract_reasoning_details(message: BaseMessage) -> list[dict[str, Any]]:
    """从 LangChain message 中提取结构化 reasoning_details。

    优先读取 additional_kwargs["reasoning_details"]（父类已保留的字段）。
    """
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    return normalize_reasoning_details(additional_kwargs.get("reasoning_details"))


def normalize_reasoning_details(value: Any) -> list[dict[str, Any]]:
    """规范化 reasoning_details：只接受 list[dict]，丢弃非 dict 项。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def copy_reasoning_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """防御性深拷贝 reasoning_details，避免原始对象在后续处理链中被修改。"""
    return copy.deepcopy(details)


class StringReasoningCodec:
    """字符串 reasoning 通道 codec。

    服务于 DeepSeek / GLM / Moonshot 等基于字符串 reasoning_content 的 provider。
    """

    field_names: tuple[str, ...] = ("reasoning_content", "reasoning", "thought")

    def extract_from_message(self, message: BaseMessage) -> str:
        return extract_reasoning_text(message)

    def inject_into_payload(
        self,
        messages: Sequence[BaseMessage],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "messages" not in payload:
            return payload
        payload_messages = payload.get("messages", [])
        primary_field = self.field_names[0]
        for original_message, payload_message in zip(messages, payload_messages):
            if not isinstance(original_message, AIMessage):
                continue
            if not isinstance(payload_message, dict) or payload_message.get("role") != "assistant":
                continue
            reasoning = extract_reasoning_text(original_message)
            if reasoning:
                payload_message[primary_field] = reasoning
        return payload


class StructuredReasoningDetailsCodec:
    """结构化 reasoning_details 通道 codec。

    服务于 OpenRouter 的 reasoning_details: list[dict] 结构。
    不降级成字符串，不与 StringReasoningCodec 互相替代。
    """

    field_name: str = "reasoning_details"

    def extract_from_message(self, message: BaseMessage) -> list[dict[str, Any]]:
        return extract_reasoning_details(message)

    def inject_into_payload(
        self,
        messages: Sequence[BaseMessage],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "messages" not in payload:
            return payload
        payload_messages = payload.get("messages", [])
        for original_message, payload_message in zip(messages, payload_messages):
            if not isinstance(original_message, AIMessage):
                continue
            if not isinstance(payload_message, dict) or payload_message.get("role") != "assistant":
                continue
            details = extract_reasoning_details(original_message)
            if details:
                payload_message[self.field_name] = copy_reasoning_details(details)
        return payload


class _OpenRouterReasoningDetailsMixin(BaseModel):
    """OpenRouter 专用结构化 reasoning_details 提取与回传 mixin。

    与 `_ReasoningPassthroughMixin` 并列关系，不是子类扩展。
    只处理 non-streaming 完整响应中的 choices[].message.reasoning_details。
    不把 reasoning_details 降级成字符串。
    """

    preserve_reasoning_details: bool = False

    def _extract_reasoning_details_from_choice(self, choice: Any) -> list[dict[str, Any]]:
        """从 raw response choice 中提取 reasoning_details。

        优先检查父类是否已处理（additional_kwargs），此方法作为兜底补取。
        """
        message = getattr(choice, "message", None)
        if message is None:
            return []
        # 先尝试 model_extra（OpenAI SDK 把非标准字段放这里）
        model_extra = getattr(message, "model_extra", None)
        if isinstance(model_extra, dict):
            details = normalize_reasoning_details(model_extra.get("reasoning_details"))
            if details:
                return details
        # 再尝试直接属性
        return normalize_reasoning_details(getattr(message, "reasoning_details", None))

    def _extract_reasoning_details_from_message(self, message: Any) -> list[dict[str, Any]]:
        """从 LangChain message 中提取 reasoning_details。"""
        if isinstance(message, BaseMessage):
            return extract_reasoning_details(message)
        return []

    def _inject_reasoning_details_into_payload(
        self,
        messages: Sequence[BaseMessage],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """将历史 assistant message 中的 reasoning_details 注入到请求 payload。

        仅当 preserve_reasoning_details=True 时生效。
        """
        if not self.preserve_reasoning_details or "messages" not in payload:
            return payload
        codec = StructuredReasoningDetailsCodec()
        return codec.inject_into_payload(messages, payload)
