"""LoggingMiddleware 单元测试。

覆盖范围：
  - _file_tool_called 标志的初始状态与置位逻辑
  - ⚠️ 警告的触发条件：仅对 writer 且从未调用过 write_file/edit_file 时报警
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.middleware.logging_middleware import LoggingMiddleware


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_ai_message(content: str = "done", tool_calls: list | None = None) -> AIMessage:
    """构造 AIMessage，可选是否带 tool_calls。"""
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _make_tool_request(tool_name: str, args: dict | None = None) -> SimpleNamespace:
    """构造模拟的 tool request，格式与 wrap_tool_call 期待的相同。"""
    return SimpleNamespace(tool_call={"name": tool_name, "args": args or {}})


def _make_model_response(msg: AIMessage) -> SimpleNamespace:
    """构造模拟的 model response，格式与 wrap_model_call 期待的相同。"""
    return SimpleNamespace(result=msg)


def _noop_handler(request):
    """什么都不做的 handler，供 wrap_tool_call 调用。"""
    return "ok"


def _model_handler(response):
    """直接返回预设 response 的 handler，供 wrap_model_call 调用。"""
    return response


# ---------------------------------------------------------------------------
# TestFileToolTracking — 标志追踪机制
# ---------------------------------------------------------------------------

class TestFileToolTracking:
    def test_initial_state_false(self):
        mw = LoggingMiddleware(agent_name="writer")
        assert mw._file_tool_called is False

    def test_write_file_sets_flag(self):
        mw = LoggingMiddleware(agent_name="writer")
        req = _make_tool_request("write_file", {"path": "/drafts/design.md"})
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is True

    def test_edit_file_sets_flag(self):
        mw = LoggingMiddleware(agent_name="writer")
        req = _make_tool_request("edit_file", {"path": "/drafts/design.md"})
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is True

    def test_read_file_does_not_set_flag(self):
        mw = LoggingMiddleware(agent_name="writer")
        req = _make_tool_request("read_file", {"path": "/input/req.md"})
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is False

    def test_write_todos_does_not_set_flag(self):
        mw = LoggingMiddleware(agent_name="writer")
        req = _make_tool_request("write_todos", {"todos": []})
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is False

    def test_task_tool_does_not_set_flag(self):
        """task 工具走独立分支，不应触发 _file_tool_called。"""
        mw = LoggingMiddleware(agent_name="orchestrator")
        req = _make_tool_request("task", {"subagent_type": "writer", "description": "write"})
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is False

    def test_flag_persists_across_model_calls(self):
        """flag 置位后，后续 wrap_model_call 不应重置它。"""
        mw = LoggingMiddleware(agent_name="writer")
        # 先置位
        req = _make_tool_request("write_file")
        mw.wrap_tool_call(req, _noop_handler)
        assert mw._file_tool_called is True
        # 再触发模型调用（返回文字，无 tool_calls）
        msg = _make_ai_message("任务完成")
        response = _make_model_response(msg)
        mw.wrap_model_call(response, lambda r: r)
        # flag 应仍为 True
        assert mw._file_tool_called is True


# ---------------------------------------------------------------------------
# TestWarningCondition — ⚠️ 警告触发条件
# ---------------------------------------------------------------------------

class TestWarningCondition:
    """通过 caplog 验证警告是否出现在 DEBUG 日志中。"""

    def _run_model_call(self, mw: LoggingMiddleware, msg: AIMessage) -> None:
        response = _make_model_response(msg)
        mw.wrap_model_call(response, lambda r: r)

    def test_warns_writer_no_file_written(self, caplog):
        """Writer 未调用任何文件工具 → 应出现 ⚠️ 警告。"""
        mw = LoggingMiddleware(agent_name="writer")
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("现在开始撰写文档"))
        assert "⚠️" in caplog.text

    def test_no_warn_writer_after_write_file(self, caplog):
        """Writer 已调用 write_file → 不应出现 ⚠️ 警告。"""
        mw = LoggingMiddleware(agent_name="writer")
        mw.wrap_tool_call(_make_tool_request("write_file"), _noop_handler)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("文档已写入"))
        assert "⚠️" not in caplog.text

    def test_no_warn_writer_after_edit_file(self, caplog):
        """Writer 已调用 edit_file → 不应出现 ⚠️ 警告。"""
        mw = LoggingMiddleware(agent_name="writer")
        mw.wrap_tool_call(_make_tool_request("edit_file"), _noop_handler)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("修订完成"))
        assert "⚠️" not in caplog.text

    def test_no_warn_reviewer_text_only(self, caplog):
        """Reviewer 返回文字结论 → 不应出现 ⚠️ 警告。"""
        mw = LoggingMiddleware(agent_name="reviewer")
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("VERDICT: REVISE"))
        assert "⚠️" not in caplog.text

    def test_no_warn_orchestrator_text_only(self, caplog):
        """Orchestrator 返回最终摘要 → 不应出现 ⚠️ 警告。"""
        mw = LoggingMiddleware(agent_name="orchestrator")
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("已完成 3 轮迭代"))
        assert "⚠️" not in caplog.text

    def test_no_warn_writer_with_tool_calls(self, caplog):
        """Writer 的消息带 tool_calls → 走 tool_calls 分支，不触发 elif 警告。"""
        mw = LoggingMiddleware(agent_name="writer")
        tool_call = {"name": "write_file", "args": {}, "id": "t1", "type": "tool_call"}
        msg = _make_ai_message("", tool_calls=[tool_call])
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, msg)
        assert "⚠️" not in caplog.text

    def test_warning_message_content(self, caplog):
        """验证警告文字内容符合预期（含 write_file/edit_file 关键词）。"""
        mw = LoggingMiddleware(agent_name="writer")
        with caplog.at_level(logging.DEBUG, logger="deep_agent_project"):
            self._run_model_call(mw, _make_ai_message("只说话不写文件"))
        assert "write_file" in caplog.text or "edit_file" in caplog.text
