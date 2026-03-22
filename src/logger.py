"""日志模块配置。

提供 RotatingFileHandler + StreamHandler 双输出，
支持 DEBUG/INFO 级别区分和按大小自动滚动。
格式中包含 agent_name 字段，用于区分 Orchestrator/Writer/Reviewer 的日志来源。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "agent.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(agent_name)-12s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _AgentNameFilter(logging.Filter):
    """为没有 agent_name 的日志记录填充默认值。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "agent_name"):
            record.agent_name = "system"
        return True


def setup_logger(log_level: str = "DEBUG") -> logging.Logger:
    """初始化并返回项目根 Logger。

    - 文件日志：始终 DEBUG 级别，保留完整调试线索（Agent 间对话、模型输出等）
    - 控制台日志：由 log_level 参数控制（--log-level INFO 可减少控制台噪音）
    - agent_name：来自 LoggingMiddleware 的 extra 字段，未提供时显示 "system"
    - 多次调用时 handler 不重复创建，但控制台级别会随 log_level 参数更新
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    console_level = getattr(logging, log_level.upper(), logging.DEBUG)

    logger = logging.getLogger("deep_agent_project")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        # handler 已存在：只更新控制台级别，避免重复添加 handler
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, RotatingFileHandler
            ):
                handler.setLevel(console_level)
        return logger

    logger.addFilter(_AgentNameFilter())

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
