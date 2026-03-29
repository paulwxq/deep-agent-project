"""OpenRouter 专用模型包装层。

基于 langchain-openrouter 的 ChatOpenRouter，补充本项目需要的
兼容约束与结构化 reasoning_details 支持。

关键约束：
- streaming 固定 False（实现层约束，非 OpenRouter 平台限制）
- 不继承 _ReasoningPassthroughMixin（字符串 reasoning 通道）
- 结构化 reasoning_details 通道由 _OpenRouterReasoningDetailsMixin 提供
- Responses API 暂不支持（use_responses_api=True 时直接报错）
"""

import logging
from collections.abc import Sequence
from typing import Any

import openrouter
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_openrouter import ChatOpenRouter
from pydantic import Field

# ============================================================
# 兼容性补丁 (Monkeypatch)
# 解决 langchain-openrouter 0.2.0 错误传递 x_title
# 而最新 openrouter SDK 0.8.0 期望 x_open_router_title 的问题。
# ============================================================
_old_openrouter_init = openrouter.OpenRouter.__init__


def _patched_openrouter_init(self, *args, **kwargs):
    if "x_title" in kwargs and "x_open_router_title" not in kwargs:
        kwargs["x_open_router_title"] = kwargs.pop("x_title")
    return _old_openrouter_init(self, *args, **kwargs)


openrouter.OpenRouter.__init__ = _patched_openrouter_init
# ============================================================

from src.reasoning_compat import (
    _OpenRouterReasoningDetailsMixin,
    sanitize_tool_messages_payload,
)

logger = logging.getLogger("deep_agent_project")

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
ReasoningDetails = list[dict[str, Any]]


class ReasoningCompatibleChatOpenRouter(_OpenRouterReasoningDetailsMixin, ChatOpenRouter):
    """OpenRouter 的唯一模型包装入口。

    职责：
    1. 统一接收 OpenRouter provider 级配置与 agent 级参数
    2. 固定使用 non-streaming（streaming=False）
    3. 优先复用父类已提取的 reasoning_details，补齐历史回传
    4. 支持 parallel_tool_calls 在 bind_tools 阶段生效
    5. 为未来 Responses API 场景预留 _extract_phase_from_response 扩展点
    """

    provider_name: str = Field(default="openrouter")
    parallel_tool_calls: bool | None = Field(default=None)
    streaming: bool = Field(default=False)

    def bind_tools(self, tools, **kwargs):
        """在工具绑定阶段优先传递 parallel_tool_calls。"""
        if self.parallel_tool_calls is not None and "parallel_tool_calls" not in kwargs:
            kwargs["parallel_tool_calls"] = self.parallel_tool_calls
        return super().bind_tools(tools, **kwargs)

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload = self._inject_reasoning_details_into_payload(messages, payload)
        payload = sanitize_tool_messages_payload(payload, "openrouter")
        payload = self._inject_openrouter_extra_options(payload)
        return payload

    def _create_chat_result(
        self,
        response: dict | Any,
    ) -> ChatResult:
        result = super()._create_chat_result(response)

        if not result.generations:
            return result

        first_message = result.generations[0].message
        if not isinstance(first_message, AIMessage):
            return result

        # 优先复用父类已保留的 reasoning_details，仅在父类未提取时补取
        details = first_message.additional_kwargs.get("reasoning_details")
        if not details:
            choices = getattr(response, "choices", None)
            if choices:
                details = self._extract_reasoning_details_from_choice(choices[0])

        if details:
            first_message.additional_kwargs["reasoning_details"] = details
            model_id = getattr(self, "model", "") or getattr(self, "model_name", "")
            logger.debug(
                "OpenRouter reasoning_details 已提取: model=%s, items=%d",
                model_id,
                len(details),
                extra={"agent_name": "system"},
            )

        return result

    def _inject_openrouter_extra_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        """整理 OpenRouter 扩展字段的最终归一化（当前为占位，model_kwargs 已由父类处理）。"""
        return payload

    def _extract_phase_from_response(self, response: dict | Any) -> str | None:
        """从 Responses API 响应中提取 phase。

        当前为扩展占位，Chat Completions 主路径不使用此字段。
        待后续启用 Responses API 时再实现完整逻辑。
        """
        return None
