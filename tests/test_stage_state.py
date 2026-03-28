"""StageStateMiddleware 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.middleware.stage_state import StageStateMiddleware


def _state_path(tmp_path: Path) -> Path:
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    path = drafts / "review-state.json"
    path.write_text(
        json.dumps(
            {
                "current_stage": "reviewer1",
                "reviewer1_round": 0,
                "reviewer2_round": 0,
                "reviewer2_enabled": True,
                "awaiting_confirm_for": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _middleware(tmp_path: Path) -> StageStateMiddleware:
    return StageStateMiddleware(str(_state_path(tmp_path)), reviewer1_max=3, reviewer2_max=2)


def _request(tool_name: str, **args) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": tool_name, "args": args})


def _write_verdict(tmp_path: Path, name: str, payload: dict) -> None:
    filename = "review-verdict-stage2.json" if name == "reviewer2" else "review-verdict.json"
    (tmp_path / "drafts" / filename).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "drafts" / "review-state.json").read_text(encoding="utf-8"))


def test_reviewer1_accept_advances_to_reviewer2(tmp_path: Path):
    mw = _middleware(tmp_path)
    _write_verdict(tmp_path, "reviewer1", {"verdict": "ACCEPT", "summary": "通过"})

    result = mw.wrap_tool_call(
        _request("task", subagent_type="reviewer1", description="review"),
        lambda request: "VERDICT: ACCEPT",
    )

    assert result == "VERDICT: ACCEPT"
    state = _read_state(tmp_path)
    assert state["reviewer1_round"] == 1
    assert state["current_stage"] == "reviewer2"


def test_reviewer1_accept_sets_done_when_reviewer2_disabled(tmp_path: Path):
    mw = _middleware(tmp_path)
    state = _read_state(tmp_path)
    state["reviewer2_enabled"] = False
    (tmp_path / "drafts" / "review-state.json").write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_verdict(tmp_path, "reviewer1", {"verdict": "ACCEPT", "summary": "通过"})

    result = mw.wrap_tool_call(
        _request("task", subagent_type="reviewer1", description="review"),
        lambda request: "VERDICT: ACCEPT",
    )

    assert result == "VERDICT: ACCEPT"
    state = _read_state(tmp_path)
    assert state["reviewer1_round"] == 1
    assert state["current_stage"] == "done"


def test_dispatching_reviewer2_before_stage_raises(tmp_path: Path):
    mw = _middleware(tmp_path)
    with pytest.raises(RuntimeError, match="尚未推进到 reviewer2"):
        mw.wrap_tool_call(
            _request("task", subagent_type="reviewer2", description="review"),
            lambda request: "noop",
        )


def test_stage_limit_returns_control_message_and_sets_awaiting(tmp_path: Path):
    mw = _middleware(tmp_path)
    state = _read_state(tmp_path)
    state["reviewer1_round"] = 3
    (tmp_path / "drafts" / "review-state.json").write_text(json.dumps(state), encoding="utf-8")
    _write_verdict(tmp_path, "reviewer1", {"verdict": "REVISE", "summary": "缺少错误处理"})

    result = mw.wrap_tool_call(
        _request("task", subagent_type="reviewer1", description="review"),
        lambda request: "should not run",
    )

    assert result.startswith("[STAGE_LIMIT_REACHED]")
    state = _read_state(tmp_path)
    assert state["awaiting_confirm_for"] == "reviewer1"


def test_confirm_continue_yes_resets_current_stage_round(tmp_path: Path):
    mw = _middleware(tmp_path)
    state = _read_state(tmp_path)
    state["awaiting_confirm_for"] = "reviewer2"
    state["current_stage"] = "reviewer2"
    state["reviewer2_round"] = 2
    (tmp_path / "drafts" / "review-state.json").write_text(json.dumps(state), encoding="utf-8")

    mw.wrap_tool_call(
        _request("confirm_continue", status="continue?"),
        lambda request: "USER_DECISION: YES\n继续",
    )

    state = _read_state(tmp_path)
    assert state["reviewer2_round"] == 0
    assert state["awaiting_confirm_for"] is None
    assert state["current_stage"] == "reviewer2"


def test_verdict_parse_error_returns_control_message_without_stage_advance(tmp_path: Path):
    mw = _middleware(tmp_path)
    (tmp_path / "drafts" / "review-verdict.json").write_text("{broken", encoding="utf-8")

    result = mw.wrap_tool_call(
        _request("task", subagent_type="reviewer1", description="review"),
        lambda request: "VERDICT: REVISE",
    )

    assert result.startswith("[VERDICT_PARSE_ERROR]")
    state = _read_state(tmp_path)
    assert state["reviewer1_round"] == 1
    assert state["current_stage"] == "reviewer1"
