"""Tavily Web 搜索工具封装。

当 config/agents.yaml 中 tools.tavily.enabled 为 true 时使用。
同时配置给 Writer（研究型搜索）和 Reviewer（验证型搜索），
用途差异通过各自的系统提示词约束。
"""

from __future__ import annotations

import json
import os
from typing import Literal


def create_web_search_tool(
    max_results: int = 5,
    api_key_env: str = "TAVILY_API_KEY",
):
    """创建 Tavily 网络搜索工具函数。

    Args:
        max_results: 每次搜索返回的最大结果数。
        api_key_env: API Key 所在的环境变量名，与 config/agents.yaml 中
                     tools.tavily.api_key_env 保持一致。

    Returns:
        可直接作为 LangChain tool 使用的函数。

    Raises:
        KeyError: 指定的环境变量未设置。
    """
    from tavily import TavilyClient

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise KeyError(f"环境变量 '{api_key_env}' 未设置，请在 .env 文件中配置")

    client = TavilyClient(api_key=api_key)

    def internet_search(
        query: str,
        num_results: int = max_results,
        topic: Literal["general", "news", "finance"] = "general",
    ) -> str:
        """搜索互联网获取最新信息。用于查找技术文档、最佳实践、API 参考等。

        Args:
            query: 搜索查询字符串
            num_results: 返回结果数量，默认 5
            topic: 搜索主题类型
        """
        results = client.search(query, max_results=num_results, topic=topic)
        return json.dumps(results, ensure_ascii=False)

    return internet_search
