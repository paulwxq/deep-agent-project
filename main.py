"""Writer-Reviewer Agent 系统入口。

解析命令行参数，加载配置，初始化 Agent 并运行。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.rich_console import (
    console,
    print_ask_user,
    print_confirm_continue,
    print_final_summary,
    print_startup,
    print_system,
)

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def _stamp_filename(filename: str) -> str:
    """在文件名 stem 后插入北京时间戳，格式：name_yyyyMMdd-HHmmss.md"""
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    p = Path(filename)
    return f"{p.stem}_{ts}{p.suffix}"


def sanitize_filename(raw: str, default: str = "design.md") -> str:
    """清洗文件名，确保在所有平台上安全可用。

    处理规则：strip -> 只取第一行 -> basename -> 过滤非法字符 ->
    去除首尾点和空格 -> Windows 保留名兜底 -> 大小写不敏感补 .md 后缀。
    任何环节得到空名均回退为 *default*。
    """
    lines = raw.strip().splitlines()
    name = lines[0].strip() if lines else ""
    name = Path(name).name
    name = _ILLEGAL_CHARS.sub("_", name)
    name = name.strip(". ")
    if not name:
        return default
    stem = Path(name).stem
    if stem.upper() in _WINDOWS_RESERVED:
        return default
    if not name.lower().endswith(".md"):
        name += ".md"
    return name


def _setup_console_readline() -> None:
    """尽量启用 readline 行编辑能力，改善退格/左右移动的交互体验。"""
    try:
        import readline
    except ImportError:
        return

    for command in (
        "set editing-mode emacs",
        "set bell-style none",
        "set enable-bracketed-paste off",
    ):
        try:
            readline.parse_and_bind(command)
        except Exception:
            # 不同平台/实现对命令支持不完全一致，失败时静默降级。
            continue


def _normalize_console_input(raw: str) -> str:
    """清洗控制台输入中的转义序列、退格残留和不可见控制字符。"""
    raw = _ANSI_ESCAPE.sub("", raw)

    chars: list[str] = []
    for ch in raw:
        if ch in {"\b", "\x7f"}:
            if chars:
                chars.pop()
            continue
        if ch == "\r":
            continue
        if ch == "\t":
            chars.append(ch)
            continue
        if unicodedata.category(ch).startswith("C"):
            continue
        chars.append(ch)
    return "".join(chars)


def _read_console_input(prompt: str = "", logger=None) -> str:
    """读取并清洗一行控制台输入，尽量兼容终端退格和乱码残留。"""
    raw = input(prompt)
    cleaned = _normalize_console_input(raw)
    if logger is not None and cleaned != raw:
        logger.warning("检测到终端控制字符或退格残留，已自动清洗本次输入")
    return cleaned


def _backup_drafts_contents(drafts_dir: Path, logger=None) -> Path | None:
    """备份 drafts 工作区内容到 ./drafts/_backups/drafts_YYYYMMDD_HHMMSS。

    只备份 drafts 根目录下除 `_backups` 之外的内容，历史备份目录不会被再次清理或打包。
    返回本次创建的备份目录；若无需备份则返回 None。
    """
    drafts_dir.mkdir(parents=True, exist_ok=True)
    backups_root = drafts_dir / "_backups"
    backups_root.mkdir(parents=True, exist_ok=True)

    items_to_backup = [p for p in drafts_dir.iterdir() if p.name != "_backups"]
    if not items_to_backup:
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backups_root / f"drafts_{ts}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = backups_root / f"drafts_{ts}_{suffix}"
        suffix += 1
    backup_dir.mkdir(parents=True, exist_ok=False)

    for item in items_to_backup:
        shutil.move(str(item), str(backup_dir / item.name))

    print_system(f"drafts 工作区已备份到 ./{backup_dir.as_posix()}")
    return backup_dir


def _run_with_hil(agent, initial_messages: list, thread_config: dict) -> dict:
    """执行 Agent，处理 ask_user（需求澄清）和 confirm_continue（超限确认）两类中断。

    使用 agent.stream() 流式运行；遇到 __interrupt__ 事件时：
    - "questions" key → 需求澄清：逐条收集 A1/A2/A3 或降级为自由文本
    - "status" key   → 超限确认：收集 yes/no 决策
    - 其他           → 安全兜底，以空字符串恢复

    正常结束后通过 agent.get_state() 获取最终状态，与 invoke() 返回结构兼容。
    """
    import logging as _logging
    import re as _re

    from langgraph.types import Command

    _Q_PATTERN = _re.compile(r'^Q(\d+)[:.：、]\s*(.+)$')
    _EXIT_CMDS = {"quit", "exit"}
    _log = _logging.getLogger("deep_agent_project")

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

                    print_ask_user(questions)

                    if protocol_valid:
                        console.print("  [dim]（请逐条回答，每条输入完成后按回车；输入 quit 终止）[/dim]")
                        answers = []
                        for num, _ in q_matches:
                            print(f"A{num}：", end="", flush=True)
                            ans = _read_console_input(logger=_log).strip()
                            if ans.lower() in _EXIT_CMDS:
                                _log.info("用户主动退出，程序终止")
                                raise SystemExit(0)
                            while not ans:
                                ans = _read_console_input(logger=_log).strip()
                                if ans.lower() in _EXIT_CMDS:
                                    _log.info("用户主动退出，程序终止")
                                    raise SystemExit(0)
                            answers.append(f"A{num}：{ans}")
                        user_answer = "\n".join(answers)
                    else:
                        if len(q_matches) > 3:
                            _log.warning("问题数量超过上限 3 个，降级为自由文本回答")
                        elif actual_nums != expected_nums:
                            _log.warning(
                                "问题编号不连续或不从 1 开始（实际: %s），降级为自由文本回答",
                                actual_nums,
                            )
                        else:
                            # len == 0（无 Qn: 行）或 len == 1（单问题）：同样不符合协议
                            _log.warning(
                                "问题文本中仅发现 %d 条 Qn: 格式行（需 2-3 条），降级为自由文本回答",
                                len(q_matches),
                            )
                        lines: list[str] = []
                        while True:
                            line = _read_console_input(logger=_log)
                            if line.lower() in _EXIT_CMDS:
                                _log.info("用户主动退出，程序终止")
                                raise SystemExit(0)
                            if line == "" and lines:
                                break
                            if line:
                                lines.append(line)
                        user_answer = "\n".join(lines)

                    payload = Command(resume=user_answer)

                # ── 第二类：超限确认 ─────────────────────────────────────────
                elif "status" in interrupt_value:
                    status = interrupt_value.get("status", "迭代已达上限")
                    print_confirm_continue(status)
                    _YES_INPUTS = {"yes", "y", "继续", "是"}
                    _NO_INPUTS = {"no", "n", "否"}
                    while True:
                        choice = _read_console_input(logger=_log).strip().lower()
                        if choice in _EXIT_CMDS:
                            _log.info("用户主动退出，程序终止")
                            raise SystemExit(0)
                        if choice in _YES_INPUTS or choice in _NO_INPUTS:
                            break
                        print("请输入 yes 或 no（输入 quit 退出）：", end="", flush=True)
                    user_answer = "yes" if choice in _YES_INPUTS else "no"
                    if user_answer == "yes":
                        print_system("用户授权继续，再给约一轮完整配额")
                    else:
                        print_system("用户选择结束迭代，以当前版本作为最终输出")
                    payload = Command(resume=user_answer)

                # ── 未知中断类型：安全兜底 ───────────────────────────────────
                else:
                    _log.warning("收到未知类型的 HIL 中断，自动以空字符串恢复")
                    payload = Command(resume="")

                break  # 退出本轮 stream，用新 payload 重新进入 while
        finally:
            gen.close()

        if not interrupted:
            result = agent.get_state(config=thread_config).values
            break

    return result


async def _run_with_hil_async(agent, initial_messages: list, thread_config: dict) -> dict:
    """_run_with_hil 的异步版本，使用 agent.astream() 替代 agent.stream()。

    与同步版本逻辑完全相同，但：
    - async def + async for（供 asyncio.run 事件循环调度）
    - 兼容 MCP 异步工具（同步 stream() 在同一事件循环内调用会死锁）
    """
    import logging as _logging
    import re as _re

    from langgraph.types import Command

    _Q_PATTERN = _re.compile(r'^Q(\d+)[:.：、]\s*(.+)$')
    _EXIT_CMDS = {"quit", "exit"}
    _log = _logging.getLogger("deep_agent_project")

    payload = {"messages": initial_messages}
    result = None

    while True:
        interrupted = False
        gen = agent.astream(payload, config=thread_config)
        try:
            async for event in gen:
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

                    print_ask_user(questions)

                    if protocol_valid:
                        console.print("  [dim]（请逐条回答，每条输入完成后按回车；输入 quit 终止）[/dim]")
                        answers = []
                        for num, _ in q_matches:
                            print(f"A{num}：", end="", flush=True)
                            ans = _read_console_input(logger=_log).strip()
                            if ans.lower() in _EXIT_CMDS:
                                _log.info("用户主动退出，程序终止")
                                raise SystemExit(0)
                            while not ans:
                                ans = _read_console_input(logger=_log).strip()
                                if ans.lower() in _EXIT_CMDS:
                                    _log.info("用户主动退出，程序终止")
                                    raise SystemExit(0)
                            answers.append(f"A{num}：{ans}")
                        user_answer = "\n".join(answers)
                    else:
                        if len(q_matches) > 3:
                            _log.warning("问题数量超过上限 3 个，降级为自由文本回答")
                        elif actual_nums != expected_nums:
                            _log.warning(
                                "问题编号不连续或不从 1 开始（实际: %s），降级为自由文本回答",
                                actual_nums,
                            )
                        else:
                            _log.warning(
                                "问题文本中仅发现 %d 条 Qn: 格式行（需 2-3 条），降级为自由文本回答",
                                len(q_matches),
                            )
                        lines: list[str] = []
                        while True:
                            line = _read_console_input(logger=_log)
                            if line.lower() in _EXIT_CMDS:
                                _log.info("用户主动退出，程序终止")
                                raise SystemExit(0)
                            if line == "" and lines:
                                break
                            if line:
                                lines.append(line)
                        user_answer = "\n".join(lines)

                    payload = Command(resume=user_answer)

                # ── 第二类：超限确认 ─────────────────────────────────────────
                elif "status" in interrupt_value:
                    status = interrupt_value.get("status", "迭代已达上限")
                    print_confirm_continue(status)
                    _YES_INPUTS = {"yes", "y", "继续", "是"}
                    _NO_INPUTS = {"no", "n", "否"}
                    while True:
                        choice = _read_console_input(logger=_log).strip().lower()
                        if choice in _EXIT_CMDS:
                            _log.info("用户主动退出，程序终止")
                            raise SystemExit(0)
                        if choice in _YES_INPUTS or choice in _NO_INPUTS:
                            break
                        print("请输入 yes 或 no（输入 quit 退出）：", end="", flush=True)
                    user_answer = "yes" if choice in _YES_INPUTS else "no"
                    if user_answer == "yes":
                        print_system("用户授权继续，再给约一轮完整配额")
                    else:
                        print_system("用户选择结束迭代，以当前版本作为最终输出")
                    payload = Command(resume=user_answer)

                # ── 未知中断类型：安全兜底 ───────────────────────────────────
                else:
                    _log.warning("收到未知类型的 HIL 中断，自动以空字符串恢复")
                    payload = Command(resume="")

                break  # 退出本轮 astream，用新 payload 重新进入 while
        finally:
            await gen.aclose()

        if not interrupted:
            result = agent.get_state(config=thread_config).values
            break

    return result


async def _async_main(
    config,
    requirement_filename: str,
    output_filename_from_arg: str | None,
    logger,
) -> None:
    """Agent 执行的异步主体。

    异步加载 MCP 工具、创建 Agent、运行并输出结果。
    从 main() 通过 asyncio.run() 调用。
    """
    # 9a. 加载 Context7 MCP 工具（若已启用）
    context7_tools: list = []
    if config.tools.context7.enabled:
        from src.tools.context7_mcp import load_context7_tools
        context7_tools = await load_context7_tools(
            api_key_env=config.tools.context7.api_key_env,
            url=config.tools.context7.url,
        )

    # 9b. 创建并运行 Agent
    from src.agent_factory import create_orchestrator_agent

    agent, orch_middleware = create_orchestrator_agent(
        config, requirement_filename, context7_tools=context7_tools
    )
    print_system("Agent 创建完成，开始执行…")

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

    interactive = True
    if interactive:
        result = await _run_with_hil_async(agent, initial_messages, thread_config)
    else:
        result = await agent.ainvoke({"messages": initial_messages}, config=thread_config)

    # 10. 确定输出文件名（三级降级：-o > drafts/output-filename.txt > design.md）
    if output_filename_from_arg:
        output_filename = sanitize_filename(output_filename_from_arg)
        if output_filename != output_filename_from_arg:
            logger.warning("输出文件名已清洗: %s -> %s", output_filename_from_arg, output_filename)
    else:
        suggested_path = Path("drafts/output-filename.txt")
        if suggested_path.exists():
            raw_suggested = suggested_path.read_text(encoding="utf-8")
            output_filename = sanitize_filename(raw_suggested)
            if output_filename != raw_suggested.strip():
                logger.warning("LLM 建议的文件名已清洗: %s -> %s", repr(raw_suggested.strip()), output_filename)
        else:
            output_filename = "design.md"

    output_filename = _stamp_filename(output_filename)

    # 11. 复制最终产物到 ./output/
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    drafts_path = Path("drafts/design.md")

    if drafts_path.exists():
        final_output_path = output_dir / output_filename
        shutil.copy2(drafts_path, final_output_path)
    else:
        logger.error("Agent 运行完成但未找到 drafts/design.md，请检查 Writer 是否正常执行")

    # 12. Agent 的迭代摘要（从后向前找第一条有实质文本的 AIMessage）
    final_message = ""
    if result and result.get("messages"):
        for msg in reversed(result["messages"]):
            if getattr(msg, "type", "") == "ai":
                content = msg.content if hasattr(msg, "content") else ""
                if isinstance(content, str) and content.strip():
                    final_message = content
                    break
    if not final_message:
        logger.warning("未找到 Orchestrator 的文本摘要（最后一条消息可能是工具回执）")

    # 13. 最终摘要（rich 表格 + 面板）
    print_final_summary(output_filename, orch_middleware.task_counts, final_message)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Writer-Reviewer Agent System (deepagents SDK)",
    )
    parser.add_argument("-f", "--file", type=str, required=True,
                        help="需求文件名（位于 ./input/ 目录下）")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="输出文件名（写入 ./output/，不传则由 LLM 生成）")
    parser.add_argument("-c", "--config", default="config/agents.yaml",
                        help="Config file path")
    parser.add_argument("-m", "--max-iterations", type=int, default=None,
                        help="Max iteration rounds")
    parser.add_argument("-l", "--log-level", default=None,
                        help="Log level (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="开启交互模式：当前双阶段审核架构固定为交互式；该参数仅保留兼容语义")
    args = parser.parse_args()

    # 1. 解析 -f/-o，收集延迟告警（此时 logger 尚未初始化）
    deferred_warnings: list[str] = []

    config_path = Path(args.config).resolve()

    requirement_filename = Path(args.file).name
    if requirement_filename != args.file:
        deferred_warnings.append(
            f"--file 只接受文件名，已忽略路径部分: {args.file} -> {requirement_filename}"
        )

    output_filename_from_arg: str | None = None
    if args.output:
        raw_output = Path(args.output).name
        if raw_output != args.output:
            deferred_warnings.append(
                f"--output 只接受文件名，已忽略路径部分: {args.output} -> {raw_output}"
            )
        output_filename_from_arg = raw_output

    # 2. 切换 cwd 为项目根目录（FilesystemBackend(root_dir=".") 依赖此前提）
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)

    # 3. 加载 .env 文件
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 4. 提前初始化日志（使用默认级别），确保配置加载阶段的错误能以统一格式输出
    from src.logger import setup_logger

    _setup_console_readline()
    logger = setup_logger("WARNING", "DEBUG")

    # 5. 加载配置（延迟导入，确保 .env 已加载）
    from src.config_loader import ConfigError, load_config, validate_env_vars

    try:
        config = load_config(str(config_path))
    except FileNotFoundError as exc:
        logger.error("配置文件不存在: %s", exc)
        sys.exit(1)
    except ConfigError as exc:
        logger.error("配置文件错误: %s", exc)
        sys.exit(1)

    if args.max_iterations is not None:
        config.max_iterations = args.max_iterations
    if args.log_level:
        config.log_level = args.log_level
    if args.interactive:
        config.hil_clarify = True

    # 用配置中的最终级别重新设置文件 handler 级别；控制台固定 WARNING，由 rich 接管显示
    logger = setup_logger("WARNING", config.file_log_level)

    for msg in deferred_warnings:
        logger.warning(msg)

    # 6. 校验环境变量
    missing = validate_env_vars(config)
    if missing:
        logger.error("以下环境变量未设置: %s", ", ".join(missing))
        logger.error("请复制 .env.sample 为 .env 并填入实际的 API Key")
        sys.exit(1)

    # 7. 验证需求文件存在且为普通文件（固定从 ./input/ 读取，不做任何猜测）
    file_path = Path("input") / requirement_filename
    if not file_path.exists():
        logger.error("需求文件不存在: ./input/%s", requirement_filename)
        sys.exit(1)
    if not file_path.is_file():
        logger.error("./input/%s 存在但不是文件（可能是目录），-f 只接受文件名", requirement_filename)
        sys.exit(1)

    print_startup(requirement_filename)

    # 8. 清理上一次运行的残留状态：
    #    将 drafts 工作区内容备份到 ./drafts/_backups/，但保留 _backups 历史内容
    drafts_dir = Path("drafts")
    _backup_drafts_contents(drafts_dir)

    # 9-13. 异步执行 Agent（MCP 工具加载 + 运行 + 输出）
    try:
        asyncio.run(_async_main(config, requirement_filename, output_filename_from_arg, logger))
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except SystemExit:
        raise
    except Exception:
        logger.exception("Agent 执行失败，请检查上方 traceback 以及 provider 超时/参数配置")
        sys.exit(1)


if __name__ == "__main__":
    main()
