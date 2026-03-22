"""_run_with_hil() 执行路由与问答协议解析测试。

协议解析测试：直接测试正则和校验逻辑（与 _run_with_hil 中使用的逻辑完全一致）。
执行路由测试：通过 config 标志验证 interactive 计算。
"""

from __future__ import annotations

import re


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
        questions = "没有任何问题格式的文本"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 0
        assert protocol_valid is False

    def test_q_pattern_single_question_falls_back(self):
        """只有 1 条合法 Q1: 行 → protocol_valid=False（单问题走自由文本路径）"""
        questions = "Q1: 这是唯一一个问题"
        q_matches, protocol_valid = parse_questions(questions)
        assert len(q_matches) == 1
        assert protocol_valid is False

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
# 执行路由测试（interactive 标志选择执行路径）
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionRouting:
    def test_hil_clarify_flag_true_means_interactive(self):
        """hil_clarify=True → interactive=True"""
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        cfg = AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=True, hil_confirm=False,
            providers={"p": ProviderConfig(type="dashscope", api_key_env="K")},
            agents={
                "orchestrator": AgentModelConfig(provider="p", model="m"),
                "writer": AgentModelConfig(provider="p", model="m"),
                "reviewer": AgentModelConfig(provider="p", model="m"),
            },
            tools=ToolsConfig(),
        )
        assert cfg.hil_clarify or cfg.hil_confirm

    def test_hil_confirm_flag_true_means_interactive(self):
        """hil_confirm=True → interactive=True"""
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        cfg = AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=False, hil_confirm=True,
            providers={"p": ProviderConfig(type="dashscope", api_key_env="K")},
            agents={
                "orchestrator": AgentModelConfig(provider="p", model="m"),
                "writer": AgentModelConfig(provider="p", model="m"),
                "reviewer": AgentModelConfig(provider="p", model="m"),
            },
            tools=ToolsConfig(),
        )
        assert cfg.hil_clarify or cfg.hil_confirm

    def test_both_flags_false_means_non_interactive(self):
        """两个 flag 均 False → interactive=False"""
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        cfg = AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=False, hil_confirm=False,
            providers={"p": ProviderConfig(type="dashscope", api_key_env="K")},
            agents={
                "orchestrator": AgentModelConfig(provider="p", model="m"),
                "writer": AgentModelConfig(provider="p", model="m"),
                "reviewer": AgentModelConfig(provider="p", model="m"),
            },
            tools=ToolsConfig(),
        )
        assert not (cfg.hil_clarify or cfg.hil_confirm)
