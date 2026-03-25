"""_run_with_hil() 测试套件。

- TestQProtocolParsing   — 正则解析 / 协议校验（纯函数，快速）
- TestYesNoNormalization — yes/no 别名集合校验（纯函数，快速）
- TestRunWithHilFunction — 真正驱动 _run_with_hil() 的中断恢复集成测试
- TestExecutionRouting   — 路由分支（interactive flag → _run_with_hil vs invoke）
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# 协议解析辅助函数（与 _run_with_hil 中使用的逻辑完全一致）
# ─────────────────────────────────────────────────────────────────────────────

Q_PATTERN = re.compile(r'^Q(\d+)[:.：、]\s*(.+)$')


def parse_questions(questions: str) -> tuple[list[tuple[int, str]], bool]:
    """
    Returns:
        (q_matches, protocol_valid)
        q_matches: list of (question_num, question_line)
        protocol_valid: True if 2-3 questions, consecutive from 1
    """
    q_matches = [
        (int(m.group(1)), line.strip())
        for line in questions.splitlines()
        if (m := Q_PATTERN.match(line.strip()))
    ]
    actual_nums = [num for num, _ in q_matches]
    expected_nums = list(range(1, len(q_matches) + 1))
    protocol_valid = (
        2 <= len(q_matches) <= 3
        and actual_nums == expected_nums
    )
    return q_matches, protocol_valid


# ─────────────────────────────────────────────────────────────────────────────
# 问答协议解析测试
# ─────────────────────────────────────────────────────────────────────────────

class TestQProtocolParsing:
    def test_q_pattern_valid_two_questions(self):
        questions = "Q1: 问题一\nQ2: 问题二"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 2
        assert protocol_valid is True
        assert q_matches[0][0] == 1
        assert q_matches[1][0] == 2

    def test_q_pattern_valid_three_questions(self):
        questions = "Q1: 问题一\nQ2: 问题二\nQ3: 问题三"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 3
        assert protocol_valid is True

    def test_q_pattern_ignores_non_q_lines(self):
        questions = "说明文字\nQ1: 问题\n请回答"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 1
        assert protocol_valid is False  # single question → falls back

    def test_q_pattern_invalid_falls_back_no_q_lines(self):
        """无 Qn: 行 → protocol_valid=False，且 actual_nums==expected_nums（均为 []）。
        这意味着 main.py 里 elif actual_nums != expected_nums 不会命中，
        必须由 else 分支发出 WARNING。"""
        questions = "没有任何问题格式的文本"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 0
        assert protocol_valid is False
        actual_nums = [n for n, _ in q_matches]
        expected_nums = list(range(1, len(q_matches) + 1))
        assert actual_nums == expected_nums  # [] == [] → elif 不会触发，需走 else

    def test_q_pattern_single_question_falls_back(self):
        """只有 1 条合法 Q1: 行 → protocol_valid=False，且 actual_nums==expected_nums（均为 [1]）。
        这意味着 main.py 里 elif actual_nums != expected_nums 不会命中，
        必须由 else 分支发出 WARNING。"""
        questions = "Q1: 这是唯一一个问题"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 1
        assert protocol_valid is False
        actual_nums = [n for n, _ in q_matches]
        expected_nums = list(range(1, len(q_matches) + 1))
        assert actual_nums == expected_nums  # [1] == [1] → elif 不会触发，需走 else

    def test_q_numbering_gap_falls_back(self):
        """Q1 Q3 跳号 → protocol_valid=False"""
        questions = "Q1: 第一个问题\nQ3: 第三个问题"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 2
        actual_nums = [n for n, _ in q_matches]
        assert actual_nums == [1, 3]
        assert protocol_valid is False

    def test_q_numbering_exceeds_limit_falls_back(self):
        """4 个或以上合法 Qn: 行 → protocol_valid=False"""
        questions = "Q1: a\nQ2: b\nQ3: c\nQ4: d"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 4
        assert protocol_valid is False

    def test_q_numbering_not_start_from_one_falls_back(self):
        """Q2 Q3 不从 1 开始 → protocol_valid=False"""
        questions = "Q2: 第二个\nQ3: 第三个"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 2
        actual_nums = [n for n, _ in q_matches]
        assert actual_nums == [2, 3]
        assert protocol_valid is False

    def test_q_pattern_fullwidth_colon_separator(self):
        """全角冒号分隔符也应被识别"""
        questions = "Q1：问题一\nQ2：问题二"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 2
        assert protocol_valid is True

    def test_q_pattern_dot_separator(self):
        """句点分隔符也应被识别"""
        questions = "Q1. 问题一\nQ2. 问题二"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 2
        assert protocol_valid is True


# ─────────────────────────────────────────────────────────────────────────────
# yes/no 归一化测试（confirm_continue 路径）
# ─────────────────────────────────────────────────────────────────────────────

YES_SET = {"yes", "y", "继续", "是"}
NO_SET = {"no", "n", "否"}
VALID_INPUTS = YES_SET | NO_SET


def normalize_decision(raw: str) -> str:
    """Mirrors the normalization logic in _run_with_hil confirm_continue branch.

    Only call with inputs already validated to be in VALID_INPUTS;
    unrecognized inputs cause re-prompt in the real loop and never reach here.
    """
    choice = raw.strip().lower()
    return "yes" if choice in YES_SET else "no"


class TestConsoleInputNormalization:
    def test_strips_ansi_escape_sequences(self):
        from main import _normalize_console_input

        raw = "abc\x1b[D\x1b[Cdef"
        assert _normalize_console_input(raw) == "abcdef"

    def test_applies_backspace_and_delete(self):
        from main import _normalize_console_input

        raw = "abcz\b\x7fde"
        assert _normalize_console_input(raw) == "abde"

    def test_run_with_hil_uses_cleaned_answer(self):
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"questions": "Q1: 问题一\nQ2: 问题二"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"), patch(
            "builtins.input",
            side_effect=["答复\x1b[D\x1b[C", "第二个\b案"],
        ):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert "A1：答复" in second_payload.resume
        assert "A2：第二案" in second_payload.resume


class TestYesNoNormalization:
    def test_yes_variants_accepted(self):
        for variant in ("yes", "y", "继续", "是", "YES", "Y"):
            assert normalize_decision(variant) == "yes", f"Failed for: {variant!r}"

    def test_no_variants_produce_no(self):
        # "结束" is NOT a valid input in the new code — removed from this list
        for variant in ("no", "n", "否", "NO"):
            assert normalize_decision(variant) == "no", f"Failed for: {variant!r}"

    def test_typo_not_in_valid_inputs(self):
        """Typos like 'yse' must not be in VALID_INPUTS (loop re-prompts instead)."""
        for typo in ("yse", "eys", "noo", "结束", "cancel", "ok"):
            assert typo not in VALID_INPUTS, f"{typo!r} should not be a valid input"


# ─────────────────────────────────────────────────────────────────────────────
# _run_with_hil() 集成测试：用 mock agent 真正驱动中断恢复流程
# ─────────────────────────────────────────────────────────────────────────────

def _make_interrupt_event(value: dict) -> dict:
    """构造携带 __interrupt__ 的 stream 事件。"""
    intr = MagicMock()
    intr.value = value
    return {"__interrupt__": [intr]}


def _build_agent(stream_sequences: list, final_state: dict | None = None):
    """构造带预设 stream 返回值的 mock agent。

    stream_sequences: 每次调用 agent.stream() 依次返回的事件列表。
    final_state: agent.get_state().values 的返回值（正常结束时读取）。
    """
    agent = MagicMock()

    def make_gen(events):
        yield from events

    agent.stream.side_effect = [make_gen(events) for events in stream_sequences]
    if final_state is not None:
        state = MagicMock()
        state.values = final_state
        agent.get_state.return_value = state
    return agent


class TestRunWithHilFunction:
    """直接调用 _run_with_hil()，驱动中断 → 输入 → 恢复的完整流程。"""

    def test_no_interrupt_returns_state_values(self):
        """流正常结束（无中断）→ 返回 agent.get_state().values。"""
        from main import _run_with_hil
        final = {"messages": ["done"]}
        agent = _build_agent([[{"key": "val"}]], final_state=final)
        with patch("builtins.print"):
            result = _run_with_hil(agent, [], {})
        assert result is final
        agent.get_state.assert_called_once()

    def test_ask_user_valid_q1q2_resumes_with_structured_answer(self):
        """ask_user 中断 + 合法 Q1/Q2 → 结构化 A1/A2 写入 Command.resume。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"questions": "Q1: 问题一\nQ2: 问题二"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"), patch("builtins.input", side_effect=["答案一", "答案二"]):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert "A1" in second_payload.resume
        assert "答案一" in second_payload.resume
        assert "A2" in second_payload.resume
        assert "答案二" in second_payload.resume

    def test_ask_user_no_q_lines_resumes_with_free_text(self):
        """ask_user 中断 + 无 Qn: 行 → 降级自由文本，空行终止收集。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"questions": "请说明背景"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"), patch("builtins.input", side_effect=["第一行", "第二行", ""]):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert "第一行" in second_payload.resume
        assert "第二行" in second_payload.resume

    def test_confirm_continue_yes_resumes_with_yes(self):
        """confirm_continue 中断 + 用户输入 'yes' → Command(resume='yes')。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"status": "已完成 3 轮，Reviewer 返回 REVISE"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"), patch("builtins.input", return_value="yes"):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert second_payload.resume == "yes"

    def test_confirm_continue_typo_reprompts_then_accepts(self):
        """confirm_continue 中断 + 拼写错误 'yse' → 重新提示；第二次 'yes' 被接受。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"status": "已完成 3 轮"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        # 第一次 typo，第二次正确
        with patch("builtins.print"), patch("builtins.input", side_effect=["yse", "yes"]):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert second_payload.resume == "yes"

    def test_confirm_continue_no_resumes_with_no(self):
        """confirm_continue 中断 + 用户输入 'no' → Command(resume='no')。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"status": "已完成 3 轮"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"), patch("builtins.input", return_value="no"):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert second_payload.resume == "no"

    def test_unknown_interrupt_resumes_with_empty_string(self):
        """未知中断类型 → 安全兜底，Command(resume='')。"""
        from langgraph.types import Command
        from main import _run_with_hil

        interrupt_event = _make_interrupt_event({"unknown_key": "unexpected"})
        agent = _build_agent([[interrupt_event], [{"done": True}]], final_state={"messages": []})

        with patch("builtins.print"):
            _run_with_hil(agent, [], {})

        second_payload = agent.stream.call_args_list[1][0][0]
        assert isinstance(second_payload, Command)
        assert second_payload.resume == ""


# ─────────────────────────────────────────────────────────────────────────────
# 执行路由测试：通过真实调用 main() 验证 HIL 标志选择正确的执行路径
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionRouting:
    """真实调用 main()，通过参数/配置触发路由分支，验证 _run_with_hil vs agent.invoke。

    策略：
    - monkeypatch.chdir(tmp_path) + patch("main.os.chdir") no-op
      → 所有相对路径（input/、drafts/、output/）落到 tmp_path
    - 延迟 import（src.logger / src.config_loader / src.agent_factory）在原始模块上 patch
    - 模块级 import（os.chdir / load_dotenv / shutil）在 main.* 上 patch
    """

    @staticmethod
    def _make_config(hil_clarify: bool, hil_confirm: bool):
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        p = ProviderConfig(type="dashscope", api_key_env="K")
        a = AgentModelConfig(provider="p", model="m")
        return AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=hil_clarify, hil_confirm=hil_confirm,
            providers={"p": p},
            agents={"orchestrator": a, "writer": a, "reviewer": a},
            tools=ToolsConfig(),
        )

    def _call_main(self, tmp_path, monkeypatch, cfg, extra_argv=None):
        """在 tmp_path 中调用真实 main()，返回 (mock_hil, mock_agent)。"""
        import sys
        import main as main_module

        # 最小文件结构：需求文件
        (tmp_path / "input").mkdir()
        (tmp_path / "input" / "req.txt").write_text("需求", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["main.py", "-f", "req.txt"] + (extra_argv or []))

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"messages": []}
        mock_middleware = MagicMock()
        mock_middleware.task_counts = {}
        mock_hil = MagicMock(return_value={"messages": []})

        with (
            patch("src.logger.setup_logger", return_value=MagicMock()),
            patch("src.config_loader.load_config", return_value=cfg),
            patch("src.config_loader.validate_env_vars", return_value=[]),
            patch("src.agent_factory.create_orchestrator_agent",
                  return_value=(mock_agent, mock_middleware)),
            patch.object(main_module, "_run_with_hil", mock_hil),
            patch("main.os.chdir"),      # 阻止 main() 切换到 project_root
            patch("main.load_dotenv"),
            patch("main.shutil"),
        ):
            main_module.main()

        return mock_hil, mock_agent

    def test_run_with_hil_importable_from_main(self):
        """_run_with_hil 是 main 模块级函数，可直接导入。"""
        from main import _run_with_hil
        assert callable(_run_with_hil)

    def test_interactive_flag_routes_to_run_with_hil(self, tmp_path, monkeypatch):
        """-i 标志 → main() 将两个 HIL flag 置 True → 调用 _run_with_hil，不调用 invoke。"""
        # config 默认关闭，-i 会在运行时覆盖
        cfg = self._make_config(hil_clarify=False, hil_confirm=False)
        mock_hil, mock_agent = self._call_main(tmp_path, monkeypatch, cfg, extra_argv=["-i"])
        mock_hil.assert_called_once()
        mock_agent.invoke.assert_not_called()

    def test_yaml_hil_clarify_routes_to_run_with_hil(self, tmp_path, monkeypatch):
        """YAML 设置 hil_clarify=True（不加 -i）→ main() 同样路由到 _run_with_hil。"""
        cfg = self._make_config(hil_clarify=True, hil_confirm=False)
        mock_hil, mock_agent = self._call_main(tmp_path, monkeypatch, cfg)
        mock_hil.assert_called_once()
        mock_agent.invoke.assert_not_called()

    def test_non_interactive_routes_to_invoke(self, tmp_path, monkeypatch):
        """两个 HIL flag 均 False，不加 -i → main() 调用 agent.invoke，不调用 _run_with_hil。"""
        cfg = self._make_config(hil_clarify=False, hil_confirm=False)
        mock_hil, mock_agent = self._call_main(tmp_path, monkeypatch, cfg)
        mock_hil.assert_not_called()
        mock_agent.invoke.assert_called_once()

    def test_main_logs_exception_and_exits_when_agent_execution_fails(self, tmp_path, monkeypatch):
        import sys
        import main as main_module

        (tmp_path / "input").mkdir()
        (tmp_path / "input" / "req.txt").write_text("需求", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["main.py", "-f", "req.txt"])

        cfg = self._make_config(hil_clarify=False, hil_confirm=False)
        mock_logger = MagicMock()
        mock_agent = MagicMock()
        mock_agent.invoke.side_effect = RuntimeError("request timeout")
        mock_middleware = MagicMock()
        mock_middleware.task_counts = {}

        with (
            patch("src.logger.setup_logger", return_value=mock_logger),
            patch("src.config_loader.load_config", return_value=cfg),
            patch("src.config_loader.validate_env_vars", return_value=[]),
            patch("src.agent_factory.create_orchestrator_agent",
                  return_value=(mock_agent, mock_middleware)),
            patch("main.os.chdir"),
            patch("main.load_dotenv"),
            patch("main.shutil"),
            patch.object(main_module, "_run_with_hil", MagicMock()),
        ):
            with patch("sys.exit", side_effect=SystemExit(1)) as mock_exit:
                try:
                    main_module.main()
                except SystemExit:
                    pass

        mock_logger.exception.assert_called_once()
        mock_exit.assert_called_once_with(1)
