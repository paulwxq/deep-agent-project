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
