# HIL (Human-in-the-Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two HIL modes to the Writer-Reviewer agent system: `hil_clarify` (requirement Q&A via `ask_user`) and `hil_confirm` (iteration-limit confirmation via `confirm_continue`).

**Architecture:** Both HIL types use LangGraph's `interrupt()` inside tool bodies; the Orchestrator calls the tools which pause execution until `Command(resume=user_answer)` resumes them. `main.py` drives the stream loop with `_run_with_hil()`, detecting `__interrupt__` events and collecting terminal input.

**Tech Stack:** LangGraph (`interrupt`, `Command`), `langchain_core.tools` (`@tool`), `langgraph.checkpoint.memory.MemorySaver`, pytest + `unittest.mock`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/tools/hil.py` | Create | `ask_user` and `confirm_continue` tool definitions using `interrupt()` |
| `src/agent_factory.py` | Modify | Conditional HIL tool injection + conditional `checkpointer` |
| `src/prompts/orchestrator_prompt.py` | Modify | Add grep requirement to step 0; update step 5 for `confirm_continue` |
| `src/prompts/writer_prompt.py` | Modify | Add `qa-supplement.md` check with authority rule |
| `src/prompts/reviewer_prompt.py` | Modify | Add `qa-supplement.md` check with authority rule |
| `main.py` | Modify | Add `-i` flag; add `_run_with_hil()`; update execution path |
| `tests/test_agent_factory_hil.py` | Create | 6 tests: tool injection + checkpointer presence |
| `tests/test_run_with_hil.py` | Create | Protocol parsing, routing, resume path, qa-supplement tests |

---

## Task 1: Create `src/tools/hil.py`

**Files:**
- Create: `src/tools/hil.py`

- [ ] **Step 1: Create the file**

```python
"""HIL (Human-in-the-Loop) 工具定义。

ask_user: 需求澄清 — Orchestrator 发现关键歧义时调用，暂停等待用户回答。
confirm_continue: 超限确认 — 迭代达到上限时调用，询问用户是否继续。

两个工具均使用 LangGraph interrupt() 机制，而非 interrupt_on：
- interrupt() 在工具内部调用，通过 Command(resume=任意值) 恢复
- interrupt() 的返回值即用户输入，工具可基于此构造返回值交还给 Agent
"""

from __future__ import annotations

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_user(questions: str) -> str:
    """当需求存在关键歧义、需要用户补充说明时调用。

    questions: 问题列表，必须按 'Q1: 问题一\\nQ2: 问题二' 格式编写（分隔符使用英文冒号），
    最多 3 个问题。调用后程序暂停，等待用户在终端输入回答。
    """
    user_answer = interrupt({"questions": questions})
    return (
        f"需求澄清完成。\n\n"
        f"【问题】\n{questions}\n\n"
        f"【用户回答】\n{user_answer}"
    )


@tool
def confirm_continue(status: str) -> str:
    """当 Writer-Reviewer 迭代达到最大轮次时调用，询问用户是否继续。

    status: 当前迭代情况的简要说明，例如"已完成 3 轮迭代，Reviewer 仍返回 REVISE"。
    用户回答 yes 则继续迭代，回答 no 则以当前版本作为最终输出。
    """
    decision = interrupt({"status": status})
    normalized = str(decision).strip().lower()
    if normalized in ("yes", "y", "继续", "是"):
        return (
            "用户选择继续迭代。请从第 1 轮重新开始计数（进入续跑阶段），"
            "再给约一轮完整配额，Reviewer 提前 ACCEPT 则提前退出。"
        )
    return "用户选择结束迭代，以当前版本作为最终输出，请进入步骤 6。"
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run python -c "from src.tools.hil import ask_user, confirm_continue; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/tools/hil.py
git commit -m "feat: add ask_user and confirm_continue HIL tools"
```

---

## Task 2: Tests for `agent_factory` HIL behavior

**Files:**
- Create: `tests/test_agent_factory_hil.py`

- [ ] **Step 1: Write the test file**

```python
"""HIL 工具注入与 checkpointer 条件挂载测试。

验证 create_orchestrator_agent() 根据 hil_clarify / hil_confirm 标志，
独立注入 ask_user / confirm_continue 工具，并按需挂载 checkpointer。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config_loader import AgentModelConfig, AppConfig, ProviderConfig, ToolsConfig
from src.tools.hil import ask_user, confirm_continue


def _make_config(hil_clarify: bool, hil_confirm: bool) -> AppConfig:
    provider = ProviderConfig(type="dashscope", api_key_env="DASHSCOPE_API_KEY")
    agent_cfg = AgentModelConfig(provider="dashscope", model="qwen3-max")
    return AppConfig(
        max_iterations=3,
        log_level="INFO",
        file_log_level="DEBUG",
        hil_clarify=hil_clarify,
        hil_confirm=hil_confirm,
        providers={"dashscope": provider},
        agents={
            "orchestrator": agent_cfg,
            "writer": agent_cfg,
            "reviewer": agent_cfg,
        },
        tools=ToolsConfig(),
    )


@pytest.fixture()
def mock_create_deep_agent():
    """Patch create_deep_agent and all model/middleware dependencies."""
    with (
        patch("src.agent_factory.create_deep_agent") as mock_cda,
        patch("src.agent_factory.create_model") as mock_model,
        patch("src.agent_factory.LoggingMiddleware"),
        patch("src.agent_factory.FilesystemBackend"),
        patch("src.agent_factory.MemorySaver"),
    ):
        mock_model.return_value = MagicMock()
        mock_cda.return_value = (MagicMock(), MagicMock())
        yield mock_cda


class TestHilToolInjection:
    def test_only_ask_user_injected_when_clarify_only(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert any(t.name == "ask_user" for t in tools)
        assert not any(t.name == "confirm_continue" for t in tools)

    def test_only_confirm_continue_injected_when_confirm_only(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=True)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert any(t.name == "confirm_continue" for t in tools)
        assert not any(t.name == "ask_user" for t in tools)

    def test_both_tools_injected_when_both_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=True, hil_confirm=True)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        tool_names = {t.name for t in tools}
        assert "ask_user" in tool_names
        assert "confirm_continue" in tool_names

    def test_no_hil_tools_when_both_disabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        tools = call_kwargs["tools"]
        assert tools == []


class TestCheckpointerCondition:
    def test_checkpointer_present_when_any_hil_enabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        for clarify, confirm in [(True, False), (False, True), (True, True)]:
            mock_create_deep_agent.reset_mock()
            cfg = _make_config(hil_clarify=clarify, hil_confirm=confirm)
            create_orchestrator_agent(cfg)
            call_kwargs = mock_create_deep_agent.call_args.kwargs
            assert "checkpointer" in call_kwargs, (
                f"checkpointer missing for hil_clarify={clarify}, hil_confirm={confirm}"
            )

    def test_no_checkpointer_when_both_disabled(self, mock_create_deep_agent):
        from src.agent_factory import create_orchestrator_agent
        cfg = _make_config(hil_clarify=False, hil_confirm=False)
        create_orchestrator_agent(cfg)
        call_kwargs = mock_create_deep_agent.call_args.kwargs
        assert "checkpointer" not in call_kwargs
```

- [ ] **Step 2: Run tests to verify they fail (agent_factory not yet updated)**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/test_agent_factory_hil.py -v 2>&1 | tail -20
```

Expected: Tests fail because `create_orchestrator_agent` currently passes `tools=[]` and always passes `checkpointer`.

- [ ] **Step 3: Commit test file**

```bash
git add tests/test_agent_factory_hil.py
git commit -m "test: add HIL tool injection and checkpointer tests (failing)"
```

---

## Task 3: Update `src/agent_factory.py`

**Files:**
- Modify: `src/agent_factory.py`

- [ ] **Step 1: Read the current file**

Read `src/agent_factory.py` (already done — see session context).

- [ ] **Step 2: Apply changes**

Replace the orchestrator creation section. The key changes:
1. Import `ask_user`, `confirm_continue` from `src.tools.hil`
2. Build `hil_tools` list based on `config.hil_clarify` / `config.hil_confirm`
3. Pass `tools=hil_tools` instead of `tools=[]`
4. Pass `checkpointer=MemorySaver()` only when `interactive=True`
5. Pass `hil_clarify` and `hil_confirm` to `build_orchestrator_prompt()`

The updated `create_orchestrator_agent` function body (replace lines 46–99):

```python
    # 2. 构建可选工具列表（Tavily）
    tools: list = []
    if config.tools.tavily_enabled:
        from src.tools.web_search import create_web_search_tool
        tools.append(create_web_search_tool(
            max_results=config.tools.tavily_max_results,
            api_key_env=config.tools.tavily_api_key_env,
        ))

    req_path = f"/input/{requirement_filename}"

    # 3. 构建 HIL 工具列表（每个工具独立按对应开关注入）
    from src.tools.hil import ask_user, confirm_continue as confirm_continue_tool

    hil_tools: list = []
    if config.hil_clarify:
        hil_tools.append(ask_user)
    if config.hil_confirm:
        hil_tools.append(confirm_continue_tool)
    interactive = bool(hil_tools)

    # 4. 定义子代理
    writer_subagent = {
        "name": "writer",
        "description": (
            "根据业务需求撰写可落地的技术设计文档。"
            f"需求文件在 {req_path}，同目录下其他文件为参考文件。"
            "草稿保存到 /drafts/design.md。接受反馈后修订文档。"
        ),
        "system_prompt": build_writer_prompt(requirement_filename),
        "tools": tools,
        "model": writer_model,
        "skills": ["/skills/tech-doc-writing/"],
        "middleware": [LoggingMiddleware(agent_name="writer")],
    }

    reviewer_subagent = {
        "name": "reviewer",
        "description": (
            f"基于 {req_path} 中的业务需求审核 /drafts/design.md 中的技术设计文档，"
            "从需求覆盖性、可落地性、无歧义性、完整性、合理性评估，"
            "返回 ACCEPT 或 REVISE 结论及详细反馈。"
        ),
        "system_prompt": build_reviewer_prompt(requirement_filename),
        "tools": tools,
        "model": reviewer_model,
        "skills": ["/skills/tech-doc-review/"],
        "middleware": [LoggingMiddleware(agent_name="reviewer")],
    }

    # 5. 组装 Orchestrator
    orch_middleware = LoggingMiddleware(agent_name="orchestrator")
    checkpointer_kwargs = {"checkpointer": MemorySaver()} if interactive else {}
    agent = create_deep_agent(
        model=orchestrator_model,
        tools=hil_tools,
        system_prompt=build_orchestrator_prompt(
            config.max_iterations,
            requirement_filename,
            hil_clarify=config.hil_clarify,
            hil_confirm=config.hil_confirm,
        ),
        subagents=[writer_subagent, reviewer_subagent],
        middleware=[orch_middleware],
        backend=FilesystemBackend(root_dir=".", virtual_mode=True),
        name="orchestrator",
        **checkpointer_kwargs,
    )

    return agent, orch_middleware
```

- [ ] **Step 3: Run the tests**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/test_agent_factory_hil.py -v 2>&1 | tail -20
```

Expected: All 6 tests pass.

- [ ] **Step 4: Run existing tests to check no regressions**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/test_config_loader.py -v 2>&1 | tail -20
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_factory.py
git commit -m "feat: conditionally inject HIL tools and checkpointer in agent_factory"
```

---

## Task 4: Update `src/prompts/orchestrator_prompt.py`

**Files:**
- Modify: `src/prompts/orchestrator_prompt.py`

The file already has `hil_clarify_section` and `step5_confirm` logic. Two targeted changes:

1. **Step 0 grep requirement**: In `hil_clarify_section`, add the mandatory grep instruction before conflict assertion.
2. **Step 5 update**: Replace the `hil_confirm` branch text to use "confirm_continue 工具" wording and correct semantics.

- [ ] **Step 1: Read the current file** (already read — see session context lines 1-77)

- [ ] **Step 2: Update `hil_clarify_section`**

The current section (lines 16-35) says:
```
0. 在委派 Writer 之前，先用 read_file 读取 {req_path} 和 /input/ 下的参考文件（ls 浏览，按需阅读）。
   完成阅读后，判断是否存在以下任一情况...
```

Replace with (adding the grep requirement):
```
0. 在委派 Writer 之前，先用 read_file 读取 {req_path} 和 /input/ 下的参考文件（ls 浏览，按需阅读）。
   在判断是否存在冲突之前，必须对需求中提及的关键字段名、表名、逻辑名称在 /input/ 文件中
   进行至少一次 grep 检索验证，不得仅凭阅读印象断言"无冲突"。
   完成检索后，判断是否存在以下任一情况，若存在则必须调用 ask_user 工具提问：
```

Also update the `step5_confirm` branch (lines 38-42). Replace:
```python
    f"5. 达到最大轮次（{max_iterations} 轮）时，调用 confirm_continue 工具，"
    f"告知用户当前迭代情况（已完成轮数、Reviewer 最后一轮的主要问题），询问是否继续迭代一轮。"
    f"用户回答 yes 则重置计数继续；回答 no 则直接进入步骤 6"
```
With:
```python
    f"5. 达到最大轮次（{max_iterations} 轮）时：\n"
    f"   - 如果工具列表中存在 confirm_continue，使用该工具告知用户当前迭代情况\n"
    f"     （例如：\"已完成 {max_iterations} 轮迭代，Reviewer 最后一轮返回 REVISE，\n"
    f"     主要问题：XXX。是否重置计数、再给约一轮完整配额继续迭代？\"）\n"
    f"     - 用户回答 yes：尽量从第 1 轮重新开始计数，再给约一轮完整配额，Reviewer 提前 ACCEPT 则提前退出\n"
    f"     - 用户回答 no：直接进入步骤 6（输出文件名）和步骤 7（返回摘要）\n"
    f"   - 如果工具列表中不存在 confirm_continue（非交互模式），输出当前版本 + 最后一轮审核意见后退出"
```

- [ ] **Step 3: Verify it imports cleanly**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run python -c "from src.prompts.orchestrator_prompt import build_orchestrator_prompt; print(build_orchestrator_prompt(3, 'req.txt', hil_clarify=True, hil_confirm=True)[:200])"
```

Expected: Prints the first 200 chars of the prompt without errors, containing "grep".

- [ ] **Step 4: Commit**

```bash
git add src/prompts/orchestrator_prompt.py
git commit -m "feat: add grep requirement to orchestrator step 0, update step 5 confirm_continue"
```

---

## Task 5: Update writer and reviewer prompts

**Files:**
- Modify: `src/prompts/writer_prompt.py`
- Modify: `src/prompts/reviewer_prompt.py`

Both need one new bullet added to their preparation checklist.

### Writer prompt

- [ ] **Step 1: Add `qa-supplement.md` check to writer prompt**

In `build_writer_prompt`, insert after the existing step 3 (or before step 4) in the "输入目录勘查" section. Add as a new numbered step (shift existing steps down):

```
4. 检查 /drafts/qa-supplement.md 是否存在；若存在，必须读取——
   其内容为用户对需求的最新澄清，权威性高于原始需求文件；
   若两者存在冲突，必须以 qa-supplement.md 为准，不得沿用原始需求中的矛盾描述。
```

Then renumber the remaining steps (old 4 → 5, old 5 → 6).

### Reviewer prompt

- [ ] **Step 2: Add `qa-supplement.md` check to reviewer prompt**

In `build_reviewer_prompt`, in the "审核前准备" section, insert after existing step 1 (read req_path). Add as new step 2:

```
2. 检查 /drafts/qa-supplement.md 是否存在；若存在，必须读取——
   其内容为用户对需求的最新澄清，权威性高于原始需求文件；
   若两者存在冲突，必须以 qa-supplement.md 为准，不得沿用原始需求中的矛盾描述。
```

Then renumber the remaining steps (old 2 → 3, old 3 → 4, etc.), and update the `write_todos` task list at the bottom similarly.

- [ ] **Step 3: Verify both import cleanly**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run python -c "
from src.prompts.writer_prompt import build_writer_prompt
from src.prompts.reviewer_prompt import build_reviewer_prompt
w = build_writer_prompt()
r = build_reviewer_prompt()
assert 'qa-supplement.md' in w, 'Missing in writer'
assert 'qa-supplement.md' in r, 'Missing in reviewer'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/prompts/writer_prompt.py src/prompts/reviewer_prompt.py
git commit -m "feat: add qa-supplement.md authority check to writer and reviewer prompts"
```

---

## Task 6: Write tests for `_run_with_hil` and execution routing

**Files:**
- Create: `tests/test_run_with_hil.py`

These tests focus on the Q&A protocol parsing logic (pure function logic extractable from `_run_with_hil`) and the routing decision (`_run_with_hil` vs `agent.invoke`). We test the protocol parsing as a standalone regex + validation function, and the routing by patching `_run_with_hil`.

- [ ] **Step 1: Write the test file**

```python
"""_run_with_hil() 执行路由与问答协议解析测试。

协议解析测试：直接测试正则和校验逻辑（从 main.py 提取为可测试单元）。
执行路由测试：通过 monkeypatch 验证 interactive 标志选择正确执行路径。
"""

from __future__ import annotations

import re
import pytest


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


def normalize_decision(raw: str) -> str:
    """Mirrors the normalization logic in _run_with_hil confirm_continue branch."""
    choice = raw.strip().lower()
    return "yes" if choice in YES_SET else "no"


class TestYesNoNormalization:
    def test_yes_variants_accepted(self):
        for variant in ("yes", "y", "继续", "是", "YES", "Y"):
            assert normalize_decision(variant) == "yes", f"Failed for: {variant!r}"

    def test_no_variants_produce_no(self):
        for variant in ("no", "n", "结束", "否", "NO"):
            assert normalize_decision(variant) == "no", f"Failed for: {variant!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 执行路由测试（interactive 标志选择执行路径）
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionRouting:
    def test_hil_flag_true_means_interactive(self):
        """hil_clarify=True → interactive=True"""
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        cfg = AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=True, hil_confirm=False,
            providers={"p": ProviderConfig(type="dashscope", api_key_env="K")},
            agents={"orchestrator": AgentModelConfig(provider="p", model="m"),
                    "writer": AgentModelConfig(provider="p", model="m"),
                    "reviewer": AgentModelConfig(provider="p", model="m")},
            tools=ToolsConfig(),
        )
        assert cfg.hil_clarify or cfg.hil_confirm  # interactive should be True

    def test_both_flags_false_means_non_interactive(self):
        """両 flag False → interactive=False"""
        from src.config_loader import AppConfig, AgentModelConfig, ProviderConfig, ToolsConfig
        cfg = AppConfig(
            max_iterations=3, log_level="INFO", file_log_level="DEBUG",
            hil_clarify=False, hil_confirm=False,
            providers={"p": ProviderConfig(type="dashscope", api_key_env="K")},
            agents={"orchestrator": AgentModelConfig(provider="p", model="m"),
                    "writer": AgentModelConfig(provider="p", model="m"),
                    "reviewer": AgentModelConfig(provider="p", model="m")},
            tools=ToolsConfig(),
        )
        assert not (cfg.hil_clarify or cfg.hil_confirm)
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/test_run_with_hil.py -v 2>&1 | tail -30
```

Expected: All tests pass (these test pure logic, not LangGraph behavior).

- [ ] **Step 3: Commit**

```bash
git add tests/test_run_with_hil.py
git commit -m "test: add protocol parsing and routing tests for _run_with_hil"
```

---

## Task 7: Update `main.py`

**Files:**
- Modify: `main.py`

Three changes:
1. Add `-i / --interactive` CLI flag
2. Apply flag to config after loading
3. Add `_run_with_hil()` function and update execution path

- [ ] **Step 1: Read the current main.py** (already read — see session context)

- [ ] **Step 2: Add `-i` flag**

After the existing `-l / --log-level` argument (line 62), add:

```python
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="开启交互模式：等效于同时将 hil_clarify 和 hil_confirm 设为 True，优先级高于配置文件")
```

- [ ] **Step 3: Apply `-i` flag to config (after config is loaded)**

After `config.log_level = args.log_level` (around line 114), add:

```python
    if args.interactive:
        config.hil_clarify = True
        config.hil_confirm = True
```

- [ ] **Step 4: Add `_run_with_hil()` function**

Add this function before `main()` (around line 49, after `sanitize_filename`):

```python
def _run_with_hil(agent, initial_messages: list, thread_config: dict) -> dict:
    """执行 Agent，处理 ask_user（需求澄清）和 confirm_continue（超限确认）两类中断。

    使用 agent.stream() 流式运行；遇到 __interrupt__ 事件时：
    - "questions" key → 需求澄清：逐条收集 A1/A2/A3 或降级为自由文本
    - "status" key   → 超限确认：收集 yes/no 决策
    - 其他           → 安全兜底，以空字符串恢复

    正常结束后通过 agent.get_state() 获取最终状态，与 invoke() 返回结构兼容。
    """
    import re as _re
    from langgraph.types import Command

    from src.logger import setup_logger as _setup_logger

    logger = _setup_logger.__globals__.get("_logger") or __import__("logging").getLogger("system")

    _Q_PATTERN = _re.compile(r'^Q(\d+)[:.：、]\s*(.+)$')
    _EXIT_CMDS = {"quit", "exit"}

    payload = {"messages": initial_messages}
    result = None

    while True:
        interrupted = False
        gen = agent.stream(payload, config=thread_config)
        try:
            for event in gen:
                interrupts = event.get("__interrupt__")
                if not interrupts:
                    continue

                interrupted = True
                interrupt_value = interrupts[0].value

                # ── 第一类：需求澄清 ─────────────────────────────────────────
                if "questions" in interrupt_value:
                    questions = interrupt_value.get("questions", "（Agent 未提供具体问题）")

                    q_matches = [
                        (int(m.group(1)), line.strip())
                        for line in questions.splitlines()
                        if (m := _Q_PATTERN.match(line.strip()))
                    ]
                    actual_nums = [num for num, _ in q_matches]
                    expected_nums = list(range(1, len(q_matches) + 1))
                    protocol_valid = (
                        2 <= len(q_matches) <= 3
                        and actual_nums == expected_nums
                    )

                    import logging as _logging
                    _log = _logging.getLogger("system")
                    _log.info("Agent 有需求澄清问题，请逐条回答（输入 quit 可终止程序）：")
                    print(f"\n{'─' * 60}")
                    print(questions)
                    print('─' * 60)

                    if protocol_valid:
                        print("（请逐条回答，每条输入完成后按回车；输入 quit 终止）")
                        answers = []
                        for num, _ in q_matches:
                            print(f"A{num}：", end="", flush=True)
                            ans = input().strip()
                            if ans.lower() in _EXIT_CMDS:
                                _log.info("用户主动退出，程序终止")
                                raise SystemExit(0)
                            while not ans:
                                ans = input().strip()
                                if ans.lower() in _EXIT_CMDS:
                                    _log.info("用户主动退出，程序终止")
                                    raise SystemExit(0)
                            answers.append(f"A{num}：{ans}")
                        user_answer = "\n".join(answers)
                    else:
                        if len(q_matches) > 3:
                            import logging as _l; _l.getLogger("system").warning(
                                "问题数量超过上限 3 个，降级为自由文本回答")
                        elif actual_nums != expected_nums:
                            import logging as _l; _l.getLogger("system").warning(
                                "问题编号不连续或不从 1 开始（实际: %s），降级为自由文本回答",
                                actual_nums)
                        lines: list[str] = []
                        while True:
                            line = input()
                            if line.lower() in _EXIT_CMDS:
                                import logging as _l; _l.getLogger("system").info(
                                    "用户主动退出，程序终止")
                                raise SystemExit(0)
                            if line == "" and lines:
                                break
                            if line:
                                lines.append(line)
                        user_answer = "\n".join(lines)

                    payload = Command(resume=user_answer)

                # ── 第二类：超限确认 ─────────────────────────────────────────
                elif "status" in interrupt_value:
                    import logging as _log_m
                    _log = _log_m.getLogger("system")
                    status = interrupt_value.get("status", "迭代已达上限")
                    _log.info("迭代轮次已达上限，等待用户决策：")
                    print(f"\n{'─' * 60}")
                    print(f"[迭代超限] {status}")
                    print("是否重置计数、再给约一轮完整配额继续迭代？[yes/no/quit]")
                    print('─' * 60)
                    while True:
                        choice = input().strip().lower()
                        if choice in _EXIT_CMDS:
                            _log.info("用户主动退出，程序终止")
                            raise SystemExit(0)
                        if choice:
                            break
                        print("请输入 yes 或 no：", end="", flush=True)
                    user_answer = "yes" if choice in ("yes", "y", "继续", "是") else "no"
                    if user_answer == "yes":
                        _log.info("[HIL] 用户授权继续，尽量重置计数，再给约一轮完整配额")
                    else:
                        _log.info("[HIL] 用户选择结束迭代，以当前版本作为最终输出")
                    payload = Command(resume=user_answer)

                # ── 未知中断类型：安全兜底 ───────────────────────────────────
                else:
                    import logging as _l
                    _l.getLogger("system").warning("收到未知类型的 HIL 中断，自动以空字符串恢复")
                    payload = Command(resume="")

                break  # 退出本轮 stream，用新 payload 重新进入 while
        finally:
            gen.close()

        if not interrupted:
            result = agent.get_state(config=thread_config).values
            break

    return result
```

- [ ] **Step 5: Update the execution path in `main()` (step 9)**

Replace the existing `agent.invoke(...)` block (lines 156-170) with:

```python
    # 9. 创建并运行 Agent
    from src.agent_factory import create_orchestrator_agent

    agent, orch_middleware = create_orchestrator_agent(config, requirement_filename)
    logger.info("Agent 创建完成，开始执行...")

    initial_messages = [
        {
            "role": "user",
            "content": (
                f"请根据需求编写技术设计文档。"
                f"需求文件在 /input/{requirement_filename}，"
                f"同目录下的其他文件为参考文件，请按需阅读。"
            ),
        }
    ]
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    interactive = config.hil_clarify or config.hil_confirm
    if interactive:
        result = _run_with_hil(agent, initial_messages, thread_config)
    else:
        result = agent.invoke({"messages": initial_messages}, config=thread_config)
```

- [ ] **Step 6: Verify main.py imports and parses args without error**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run python main.py --help 2>&1 | grep -E "interactive|hil"
```

Expected: Shows `-i/--interactive` in help text.

- [ ] **Step 7: Run all tests**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/ -v 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat: add -i flag, _run_with_hil(), and HIL execution path to main.py"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run pytest tests/ -v 2>&1
```

Expected: All tests pass, no failures.

- [ ] **Step 2: Verify imports for all modified modules**

```bash
cd /mnt/c/Projects/cursor_2026/deep-agent-project && uv run python -c "
from src.tools.hil import ask_user, confirm_continue
from src.prompts.orchestrator_prompt import build_orchestrator_prompt
from src.prompts.writer_prompt import build_writer_prompt
from src.prompts.reviewer_prompt import build_reviewer_prompt
w = build_writer_prompt()
r = build_reviewer_prompt()
assert 'qa-supplement.md' in w
assert 'qa-supplement.md' in r
op_hil = build_orchestrator_prompt(3, 'req.txt', hil_clarify=True, hil_confirm=True)
assert 'grep' in op_hil
assert 'confirm_continue' in op_hil
print('All checks passed')
"
```

Expected: `All checks passed`

- [ ] **Step 3: Commit summary**

```bash
git add -A
git status
```

Verify no unintended files changed.

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/tools/hil.py` | **New** — `ask_user` + `confirm_continue` using `interrupt()` |
| `src/agent_factory.py` | Conditional HIL tool injection; conditional `checkpointer` |
| `src/prompts/orchestrator_prompt.py` | Grep requirement in step 0; updated step 5 |
| `src/prompts/writer_prompt.py` | `qa-supplement.md` authority check |
| `src/prompts/reviewer_prompt.py` | `qa-supplement.md` authority check |
| `main.py` | `-i` flag; `_run_with_hil()`; conditional execution path |
| `tests/test_agent_factory_hil.py` | **New** — 6 tests for tool injection + checkpointer |
| `tests/test_run_with_hil.py` | **New** — protocol parsing + routing tests |
