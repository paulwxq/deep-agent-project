"""Rich 终端输出工具。

提供共享的 Console 实例和格式化帮助函数，替代 logging.info 的终端可见输出。
文件日志（RotatingFileHandler）保持不变，本模块只负责终端呈现。
"""

from __future__ import annotations

from datetime import datetime

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(highlight=False)

# 面板内容超过此长度时截断并提示
_MAX_PANEL = 1500

# 记录系统启动时间，用于计算最终耗时
_start_time: datetime | None = None


def _ts() -> str:
    """当前时间字符串，格式 HH:MM:SS，用于嵌入面板标题。"""
    return datetime.now().strftime("%H:%M:%S")


def _truncate(text: str, max_len: int = _MAX_PANEL) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n[dim]… 共 {len(text)} 字符，已截断[/dim]"


# ── Agent 通信面板 ─────────────────────────────────────────────────────────────

def print_task_delegation(source: str, target: str, count: int, message: str) -> None:
    """📤 Orchestrator 委派任务给子代理 — 蓝色面板。"""
    title = f"[bold]📤 {source} → {target}[/bold]  第{count}次  [dim]{_ts()}[/dim]"
    console.print(Panel(_truncate(message), title=title, border_style="blue"))


def print_task_result(source: str, target: str, message: str) -> None:
    """📥 子代理返回结果给 Orchestrator — 绿色面板（非 Reviewer）。"""
    title = f"[bold]📥 {source} → {target}[/bold]  [dim]{_ts()}[/dim]"
    console.print(Panel(_truncate(message), title=title, border_style="green"))


def print_reviewer_feedback(message: str) -> None:
    """🔍 Reviewer 审核结论 — 绿色(ACCEPT) / 黄色(REVISE)。"""
    first_line = message.strip().splitlines()[0].upper() if message.strip() else ""
    if "ACCEPT" in first_line:
        style, icon = "bright_green", "✅"
    elif "REVISE" in first_line:
        style, icon = "yellow", "🔄"
    else:
        style, icon = "cyan", "🔍"
    console.print(Panel(
        _truncate(message),
        title=f"[bold]{icon} Reviewer 反馈[/bold]  [dim]{_ts()}[/dim]",
        border_style=style,
    ))


# ── HIL 交互面板 ──────────────────────────────────────────────────────────────

def print_ask_user(questions: str) -> None:
    """💬 需求澄清：Writer 发起的 HIL 问题 — 醒目紫色面板。"""
    console.print(Panel(
        questions,
        title=f"[bold]💬 需要您的回答[/bold]  [dim]{_ts()}[/dim]",
        border_style="bright_magenta",
    ))


def print_confirm_continue(status: str) -> None:
    """⏸ 超限确认：迭代达到上限时的 HIL 提示 — 黄色面板。"""
    content = f"{status}\n\n请输入 [bold]yes[/bold] 继续 / [bold]no[/bold] 结束 / [bold]quit[/bold] 退出"
    console.print(Panel(
        content,
        title=f"[bold]⏸ 迭代轮次已达上限[/bold]  [dim]{_ts()}[/dim]",
        border_style="yellow",
    ))


# ── 系统级输出 ─────────────────────────────────────────────────────────────────

def print_system(message: str) -> None:
    """普通系统信息，灰色细字。"""
    console.print(f"  [dim]{message}[/dim]")


def print_startup(requirement_filename: str) -> None:
    """启动标题行 + 需求文件提示；记录启动时间。"""
    global _start_time
    _start_time = datetime.now()
    console.rule(f"[bold blue]Writer-Reviewer Agent 系统[/bold blue]  [dim]{_start_time.strftime('%H:%M:%S')}[/dim]")
    console.print(f"  需求文件: [cyan]{requirement_filename}[/cyan]\n")


def print_final_summary(
    output_filename: str,
    task_counts: dict,
    final_message: str,
) -> None:
    """任务完成：输出文件名 + 委派统计表格 + 迭代摘要面板。"""
    now = datetime.now()
    elapsed_str = ""
    if _start_time is not None:
        elapsed = int((now - _start_time).total_seconds())
        m, s = divmod(elapsed, 60)
        elapsed_str = f"  [dim]{now.strftime('%H:%M:%S')}  用时 {m}m {s:02d}s[/dim]"

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("key", style="dim")
    table.add_column("value")

    total = sum(task_counts.values())
    parts = [f"{k}×{v}" for k, v in sorted(task_counts.items())]
    table.add_row("输出文件", f"[cyan]./output/{output_filename}[/cyan]")
    table.add_row("子代理委派", f"共 {total} 次  ({', '.join(parts)})")

    console.print()
    console.print(Panel(
        table,
        title=f"[bold bright_green]✅ 文档生成完成[/bold bright_green]{elapsed_str}",
        border_style="bright_green",
    ))

    if final_message:
        console.print(Panel(
            _truncate(final_message, 2000),
            title="[bold]📋 迭代摘要[/bold]",
            border_style="dim",
        ))
