"""双阶段审核流程状态中间件。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger("deep_agent_project")


class StageStateMiddleware(AgentMiddleware):
    """Orchestrator 专属中间件：维护双阶段 reviewer 的流程状态。"""

    def __init__(self, state_path: str, reviewer1_max: int, reviewer2_max: int):
        self._state_path = Path(state_path)
        self._reviewer1_max = reviewer1_max
        self._reviewer2_max = reviewer2_max

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name, target, tool_call_id = self._extract_tool_info(request)

        if tool_name in ("write_file", "edit_file"):
            tool_call = request.tool_call if hasattr(request, "tool_call") else {}
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            path = str(args.get("path") or args.get("file_path") or "")
            if "review-state.json" in path:
                logger.warning(
                    "StageState: 拦截了对 review-state.json 的直接写入尝试（工具=%s, path=%s）",
                    tool_name, path, extra={"agent_name": "system"},
                )
                return (
                    "[SYSTEM_ERROR] review-state.json 由 StageStateMiddleware 自动维护，"
                    "禁止直接写入。请勿重试，系统状态已由中间件正确更新。"
                )

        if tool_name == "task" and target in ("reviewer1", "reviewer2"):
            intercept_msg = self._check_before_dispatch(target)
            if intercept_msg is not None:
                # 包装成 Command 对象返回，防止 SDK 内部对 task 工具结果类型校验失败
                return Command(
                    update={
                        "messages": [ToolMessage(content=intercept_msg, tool_call_id=tool_call_id)]
                    }
                )

        result = handler(request)

        if tool_name == "task" and target in ("reviewer1", "reviewer2"):
            error_msg = self._update_after_reviewer(target)
            if error_msg:
                # 同样包装成 Command，替换原有的子代理返回结果
                return Command(
                    update={
                        "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
                    }
                )
            return result

        if tool_name == "confirm_continue":
            self._update_after_hil(result)
        return result

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name, target, tool_call_id = self._extract_tool_info(request)

        if tool_name in ("write_file", "edit_file"):
            tool_call = request.tool_call if hasattr(request, "tool_call") else {}
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            path = str(args.get("path") or args.get("file_path") or "")
            if "review-state.json" in path:
                logger.warning(
                    "StageState: 拦截了对 review-state.json 的直接写入尝试（工具=%s, path=%s）",
                    tool_name, path, extra={"agent_name": "system"},
                )
                return (
                    "[SYSTEM_ERROR] review-state.json 由 StageStateMiddleware 自动维护，"
                    "禁止直接写入。请勿重试，系统状态已由中间件正确更新。"
                )

        if tool_name == "task" and target in ("reviewer1", "reviewer2"):
            intercept_msg = self._check_before_dispatch(target)
            if intercept_msg is not None:
                return Command(
                    update={
                        "messages": [ToolMessage(content=intercept_msg, tool_call_id=tool_call_id)]
                    }
                )

        result = await handler(request)

        if tool_name == "task" and target in ("reviewer1", "reviewer2"):
            error_msg = self._update_after_reviewer(target)
            if error_msg:
                return Command(
                    update={
                        "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
                    }
                )
            return result

        if tool_name == "confirm_continue":
            self._update_after_hil(result)
        return result

    def _extract_tool_info(self, request: Any) -> tuple[str, str, str]:
        tool_call = request.tool_call if hasattr(request, "tool_call") else {}
        if not isinstance(tool_call, dict):
            return "", "", ""
        tool_name = tool_call.get("name", "")
        tool_call_id = tool_call.get("id", "")
        args = tool_call.get("args", {}) or {}
        target = args.get("subagent_type", "")
        return tool_name, target, tool_call_id

    def _default_state(self) -> dict[str, Any]:
        return {
            "current_stage": "reviewer1",
            "reviewer1_round": 0,
            "reviewer2_round": 0,
            "reviewer2_enabled": False,
            "awaiting_confirm_for": None,
        }

    def _read_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return self._default_state()
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "review-state.json 读取失败，回退到默认状态",
                extra={"agent_name": "system"},
            )
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        state = self._default_state()
        state.update(data)
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _verdict_path(self, target: str) -> Path:
        if target == "reviewer2":
            return self._state_path.parent / "review-verdict-stage2.json"
        return self._state_path.parent / "review-verdict.json"

    def _read_verdict_payload(self, target: str) -> tuple[str, str, str | None]:
        path = self._verdict_path(target)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            reason = f"{target} verdict 文件不存在: {path.as_posix()}"
            logger.warning(reason, extra={"agent_name": "system"})
            return "REVISE", "", reason
        except OSError as exc:
            reason = f"{target} verdict 文件读取失败: {exc}"
            logger.warning(reason, extra={"agent_name": "system"})
            return "REVISE", "", reason
        except json.JSONDecodeError as exc:
            reason = f"{target} verdict JSON 解析失败: {exc}"
            logger.warning(reason, extra={"agent_name": "system"})
            return "REVISE", "", reason

        if not isinstance(data, dict):
            reason = f"{target} verdict 文件格式错误：顶层不是 JSON 对象"
            logger.warning(reason, extra={"agent_name": "system"})
            return "REVISE", "", reason

        verdict = str(data.get("verdict", "")).strip().upper()
        summary = str(data.get("summary", "")).strip()
        if verdict not in {"ACCEPT", "REVISE"}:
            reason = f"{target} verdict 字段缺失或非法: {verdict!r}"
            logger.warning(reason, extra={"agent_name": "system"})
            return "REVISE", summary, reason

        return verdict, summary, None

    def _check_before_dispatch(self, target: str) -> str | None:
        state = self._read_state()
        current = state["current_stage"]
        awaiting = state.get("awaiting_confirm_for")

        if current == "done":
            raise RuntimeError("StageState: 任务已结束（current_stage=done），不允许再委派 reviewer")

        if target == "reviewer1" and current == "reviewer2":
            raise RuntimeError("StageState: 禁止回退——current_stage 已为 reviewer2")

        if target == "reviewer2" and current != "reviewer2":
            raise RuntimeError("StageState: 非法切换——current_stage 尚未推进到 reviewer2")

        max_val = self._reviewer1_max if target == "reviewer1" else self._reviewer2_max
        round_val = state.get(f"{target}_round", 0)
        if max_val > 0 and round_val >= max_val:
            if awaiting is None:
                state["awaiting_confirm_for"] = target
                self._write_state(state)
            _, summary, _ = self._read_verdict_payload(target)
            summary_text = f"核心问题：{summary}" if summary else "核心问题：请查看 reviewer 最近一轮详细反馈。"
            return (
                f"[STAGE_LIMIT_REACHED] {target} 已完成 {round_val} 轮审核，达到上限（{max_val} 轮）。"
                f"{summary_text} 请调用 confirm_continue 决定是否继续。"
            )

        return None

    def _update_after_reviewer(self, target: str) -> str | None:
        state = self._read_state()
        verdict, _summary, error_reason = self._read_verdict_payload(target)
        round_key = f"{target}_round"
        state[round_key] = state.get(round_key, 0) + 1

        if error_reason is None and verdict == "ACCEPT":
            if target == "reviewer1" and state.get("reviewer2_enabled"):
                state["current_stage"] = "reviewer2"
            else:
                state["current_stage"] = "done"

        self._write_state(state)

        if error_reason is not None:
            return (
                f"[VERDICT_PARSE_ERROR] {target} 的 verdict 文件读取或解析异常，"
                f"本轮已按系统级强制 REVISE 处理。原因：{error_reason}"
            )
        return None

    def _update_after_hil(self, result: Any) -> None:
        state = self._read_state()
        awaiting = state.get("awaiting_confirm_for")
        result_str = str(result)

        if awaiting not in ("reviewer1", "reviewer2"):
            if "USER_DECISION: NO" in result_str:
                state["current_stage"] = "done"
                self._write_state(state)
            return

        if "USER_DECISION: YES" in result_str:
            state[f"{awaiting}_round"] = 0
            state["awaiting_confirm_for"] = None
        else:
            state["current_stage"] = "done"
            state["awaiting_confirm_for"] = None

        self._write_state(state)
