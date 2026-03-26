"""自定义日志中间件。

继承 AgentMiddleware，通过 wrap_model_call 和 wrap_tool_call 两个
环绕式钩子记录模型输出、工具调用和 Agent 间通信。

每个 Agent（Orchestrator / Writer / Reviewer）都需要独立挂载本中间件实例。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage

from src.reasoning_compat import extract_reasoning_text

logger = logging.getLogger("deep_agent_project")

MAX_CONTENT_PREVIEW = 800
MAX_TASK_MESSAGE_LOG = 2000
MAX_TASK_RESULT_LOG = 2000
MAX_TOOL_RESULT_LOG = 500


class LoggingMiddleware(AgentMiddleware):
    """记录 Agent 的模型输出、工具调用和子代理通信。

    使用 SDK 的两个环绕式钩子：
    - wrap_model_call：在 handler 调用后记录模型的可见输出
    - wrap_tool_call：在 handler 调用前后记录工具执行（task 委派的对话内容）
    """

    def __init__(self, agent_name: str = "unknown"):
        self._agent_name = agent_name
        self.task_counts: dict[str, int] = {}
        self._file_tool_called: bool = False  # write_file/edit_file 是否已被调用过

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        """环绕式钩子：执行模型调用，并在调用后记录可见输出。"""
        response = handler(request)

        if hasattr(response, "result") and response.result:
            msgs = response.result if isinstance(response.result, list) else [response.result]
            for msg in msgs:
                if isinstance(msg, AIMessage):
                    self._log_model_output(msg)

        return response

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """环绕式钩子：执行工具调用，前后分别记录。

        对 task 工具特殊处理：记录完整的委派内容和子代理返回结果。
        """
        tool_call = request.tool_call if hasattr(request, "tool_call") else {}
        tool_name = tool_call.get("name", "unknown") if isinstance(tool_call, dict) else "unknown"

        if tool_name != "task":
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            if tool_name in ("write_file", "edit_file"):
                self._file_tool_called = True
            _log_tool_args(tool_name, args, self._agent_name)
            result = handler(request)
            _log_tool_result(tool_name, result, self._agent_name)
            return result

        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
        target = args.get("subagent_type", "unknown")
        task_message = args.get("description", "")

        self.task_counts[target] = self.task_counts.get(target, 0) + 1

        logger.info(
            "📤 [%s → %s] 委派任务 (第%d次)",
            self._agent_name,
            target,
            self.task_counts[target],
            extra={"agent_name": self._agent_name},
        )
        if task_message:
            logger.info(
                "📤 [%s → %s] 任务内容: %s",
                self._agent_name,
                target,
                task_message[:MAX_TASK_MESSAGE_LOG],
                extra={"agent_name": self._agent_name},
            )

        result = handler(request)

        result_text = _extract_task_result_text(result)

        logger.info(
            "📥 [%s → %s] 返回结果: %s",
            target,
            self._agent_name,
            result_text[:MAX_TASK_RESULT_LOG],
            extra={"agent_name": self._agent_name},
        )
        if target == "reviewer":
            # Reviewer 反馈是用户最关注的信息，单独打 INFO，确保控制台可见。
            logger.info(
                "🔍 Reviewer 反馈: %s",
                result_text[:MAX_TASK_RESULT_LOG],
                extra={"agent_name": self._agent_name},
            )
        if len(result_text) > MAX_TASK_RESULT_LOG:
            if target == "reviewer":
                logger.info(
                    "🔍 Reviewer 反馈（完整，%d字符）: %s",
                    len(result_text),
                    result_text,
                    extra={"agent_name": self._agent_name},
                )
            else:
                logger.debug(
                    "📥 [%s → %s] 返回结果（完整，%d字符）: %s",
                    target,
                    self._agent_name,
                    len(result_text),
                    result_text,
                    extra={"agent_name": self._agent_name},
                )

        return result

    def _log_model_output(self, msg: AIMessage) -> None:
        """记录 AIMessage 的可见输出和思维链（如果模型提供）。"""
        # A. 可见输出文本
        if msg.content:
            content = str(msg.content)
            if len(content) <= MAX_CONTENT_PREVIEW:
                logger.debug(
                    "📝 模型输出: %s",
                    content,
                    extra={"agent_name": self._agent_name},
                )
            else:
                logger.debug(
                    "📝 模型输出（前%d字符）: %s",
                    MAX_CONTENT_PREVIEW,
                    content[:MAX_CONTENT_PREVIEW],
                    extra={"agent_name": self._agent_name},
                )
                logger.debug(
                    "📝 模型输出（完整，%d字符）: %s",
                    len(content),
                    content,
                    extra={"agent_name": self._agent_name},
                )

        # B. 思维链 / 推理过程（Qwen-Max 等模型在 additional_kwargs 中返回）
        reasoning = extract_reasoning_text(msg)
        if reasoning:
            reasoning = str(reasoning)
            if len(reasoning) <= MAX_CONTENT_PREVIEW:
                logger.debug(
                    "💭 推理过程: %s",
                    reasoning,
                    extra={"agent_name": self._agent_name},
                )
            else:
                logger.debug(
                    "💭 推理过程（前%d字符）: %s",
                    MAX_CONTENT_PREVIEW,
                    reasoning[:MAX_CONTENT_PREVIEW],
                    extra={"agent_name": self._agent_name},
                )

        # 工具调用意图
        if msg.tool_calls:
            tool_names = [
                tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                for tc in msg.tool_calls
            ]
            logger.debug(
                "🔧 工具调用意图: %s",
                ", ".join(tool_names),
                extra={"agent_name": self._agent_name},
            )
        elif msg.content and self._agent_name == "writer" and not self._file_tool_called:
            logger.debug(
                "⚠️ Writer 返回文字内容但尚未调用 write_file/edit_file，任务可能未完成",
                extra={"agent_name": self._agent_name},
            )


def _log_tool_args(tool_name: str, args: dict, agent_name: str) -> None:
    """记录工具调用的关键参数（路径、内容长度等）。"""
    path = args.get("path") or args.get("file_path") or ""
    content = args.get("content") or args.get("new_string") or ""
    pattern = args.get("pattern") or ""

    if path and content:
        logger.debug(
            "工具执行: %s | path=%s content_len=%d",
            tool_name, path, len(content),
            extra={"agent_name": agent_name},
        )
    elif path and pattern:
        logger.debug(
            "工具执行: %s | path=%s pattern=%s",
            tool_name, path, pattern[:100],
            extra={"agent_name": agent_name},
        )
    elif path:
        logger.debug(
            "工具执行: %s | path=%s",
            tool_name, path,
            extra={"agent_name": agent_name},
        )
    else:
        logger.debug(
            "工具执行: %s | args=%s",
            tool_name, str(args)[:200],
            extra={"agent_name": agent_name},
        )


def _log_tool_result(tool_name: str, result: Any, agent_name: str) -> None:
    """记录工具执行结果（首 MAX_TOOL_RESULT_LOG 字符）。"""
    result_str = result if isinstance(result, str) else str(result)
    if result_str:
        logger.debug(
            "工具结果: %s | %s",
            tool_name, result_str[:MAX_TOOL_RESULT_LOG],
            extra={"agent_name": agent_name},
        )


def _extract_task_result_text(result: Any) -> str:
    """从 task 工具返回值中提取可读的对话文本。

    deepagents 的 task 返回 Command(update={"messages": [ToolMessage(...)]})，
    真实内容在 ToolMessage.content 里。逐层剥开取出文本，避免日志中出现
    Command(update=...) 这种内部对象字符串。
    """
    if hasattr(result, "content") and isinstance(result.content, str):
        return result.content

    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages", [])
        parts = []
        for msg in messages:
            if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
                parts.append(msg.content)
        if parts:
            return " | ".join(parts)

    return str(result)
