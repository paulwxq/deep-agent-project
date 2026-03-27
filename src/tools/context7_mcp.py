"""Context7 MCP 工具加载模块。

通过 langchain-mcp-adapters 连接 Context7 远程 MCP 服务器，
将其工具转换为 LangChain BaseTool 列表，供 Agent 直接使用。

延迟导入 MultiServerMCPClient，在未安装 langchain-mcp-adapters 时
仅跳过加载而不引发 ImportError。
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("deep_agent_project")


async def load_context7_tools(
    api_key_env: str = "CONTEXT7_API_KEY",
    url: str = "https://mcp.context7.com/mcp",
) -> list:
    """连接 Context7 远程 MCP 服务器并返回工具列表。

    若 API Key 未设置或连接失败，则记录警告并返回空列表（不抛出异常）。

    Args:
        api_key_env: 存放 Context7 API Key 的环境变量名。
        url: Context7 MCP 服务器地址。

    Returns:
        LangChain BaseTool 列表；加载失败时返回空列表。
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        _log.warning(
            "langchain-mcp-adapters 未安装，跳过 Context7 MCP 加载。"
            "如需启用，请运行：uv add langchain-mcp-adapters mcp"
        )
        return []

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        _log.warning(
            "Context7 MCP: 环境变量 %s 未设置，跳过加载", api_key_env
        )
        return []

    _log.debug("Context7 MCP: 正在连接 %s", url)
    try:
        client = MultiServerMCPClient({
            "context7": {
                "transport": "http",
                "url": url,
                "headers": {"CONTEXT7_API_KEY": api_key},
            }
        })
        tools = await client.get_tools()
        _log.info(
            "Context7 MCP: 已加载 %d 个工具 → %s",
            len(tools),
            [t.name for t in tools],
        )
        return tools
    except Exception as exc:
        _log.warning("Context7 MCP 加载失败（跳过）: %s", exc, extra={"agent_name": "system"})
        # 打印子异常链，定位根因
        cause = getattr(exc, "__context__", None) or getattr(exc, "__cause__", None)
        if cause is not None:
            _log.warning("Context7 MCP 根因: %s: %s", type(cause).__name__, cause, extra={"agent_name": "system"})
            # ExceptionGroup / TaskGroup 可能包含多个子异常
            sub_exceptions = getattr(cause, "exceptions", None)
            if sub_exceptions:
                for i, sub in enumerate(sub_exceptions, 1):
                    _log.warning(
                        "Context7 MCP 子异常 [%d/%d]: %s: %s",
                        i, len(sub_exceptions),
                        type(sub).__name__, sub,
                        extra={"agent_name": "system"},
                    )
        _log.warning(
            "Context7 MCP: 已降级运行（Writer/Reviewer 本次无 Context7 工具）",
            extra={"agent_name": "system"},
        )
        return []
