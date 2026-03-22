"""Writer-Reviewer Agent 系统入口。

解析命令行参数，加载配置，初始化 Agent 并运行。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


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
                            _log.warning("问题数量超过上限 3 个，降级为自由文本回答")
                        elif actual_nums != expected_nums:
                            _log.warning(
                                "问题编号不连续或不从 1 开始（实际: %s），降级为自由文本回答",
                                actual_nums,
                            )
                        lines: list[str] = []
                        while True:
                            line = input()
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
                    _log.info("迭代轮次已达上限，等待用户决策：")
                    print(f"\n{'─' * 60}")
                    print(f"[迭代超限] {status}")
                    print("是否重置计数、再给约一轮完整配额继续迭代？[yes/no/quit]")
                    print('─' * 60)
                    _YES_INPUTS = {"yes", "y", "继续", "是"}
                    _NO_INPUTS = {"no", "n", "否"}
                    while True:
                        choice = input().strip().lower()
                        if choice in _EXIT_CMDS:
                            _log.info("用户主动退出，程序终止")
                            raise SystemExit(0)
                        if choice in _YES_INPUTS or choice in _NO_INPUTS:
                            break
                        print("请输入 yes 或 no（输入 quit 退出）：", end="", flush=True)
                    user_answer = "yes" if choice in _YES_INPUTS else "no"
                    if user_answer == "yes":
                        _log.info("[HIL] 用户授权继续，尽量重置计数，再给约一轮完整配额")
                    else:
                        _log.info("[HIL] 用户选择结束迭代，以当前版本作为最终输出")
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
                        help="开启交互模式：等效于同时将 hil_clarify 和 hil_confirm 设为 True，优先级高于配置文件")
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

    logger = setup_logger("INFO", "DEBUG")

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
        config.hil_confirm = True

    # 用配置中的最终级别重新设置控制台和文件 handler 级别
    logger = setup_logger(config.log_level, config.file_log_level)
    logger.info("Writer-Reviewer Agent 系统启动")

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

    logger.info("需求文件: ./input/%s", requirement_filename)

    # 8. 清理上一次运行的残留状态（旧 drafts/ 按时间戳备份，方便调试对比）
    drafts_dir = Path("drafts")
    if drafts_dir.exists() and any(drafts_dir.iterdir()):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = drafts_dir.parent / f"drafts_{ts}"
        shutil.move(str(drafts_dir), str(backup))
        logger.info("已将 drafts/ 备份为 %s", backup.name)
    drafts_dir.mkdir(parents=True, exist_ok=True)

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
            logger.info("最终采用输出文件名: %s", output_filename)
        else:
            output_filename = "design.md"

    # 11. 复制最终产物到 ./output/
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    drafts_path = Path("drafts/design.md")

    if drafts_path.exists():
        final_output_path = output_dir / output_filename
        shutil.copy2(drafts_path, final_output_path)
        logger.info("最终文档已输出到 ./output/%s", output_filename)
    else:
        logger.error("Agent 运行完成但未找到 drafts/design.md，请检查 Writer 是否正常执行")

    # 12. 程序级统计（由中间件精确计数，不依赖 LLM 自述）
    counts = orch_middleware.task_counts
    total_tasks = sum(counts.values())
    if counts:
        stats_parts = [f"{k}x{v}" for k, v in sorted(counts.items())]
        logger.info("执行统计: 共 %d 次子代理委派 (%s)", total_tasks, ", ".join(stats_parts))

    # 13. Agent 的迭代摘要
    # 从后向前找第一条有实质文本内容的 AIMessage，跳过 ToolMessage（工具回执）
    final_message = ""
    if result and result.get("messages"):
        for msg in reversed(result["messages"]):
            if getattr(msg, "type", "") == "ai":
                content = msg.content if hasattr(msg, "content") else ""
                if isinstance(content, str) and content.strip():
                    final_message = content
                    break
    if final_message:
        logger.info("迭代摘要:\n%s", final_message)
    else:
        logger.warning("未找到 Orchestrator 的文本摘要（最后一条消息可能是工具回执）")


if __name__ == "__main__":
    main()
