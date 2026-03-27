"""tests/test_web_search.py

Unit tests for src/tools/web_search.py — create_web_search_tool()

Covers:
  - Missing API key → raises KeyError（启动时 fail-fast）
  - Successful creation → returns callable
  - Return format is JSON string, not Python repr（6.2 文档核心改动）
  - Chinese / Unicode characters preserved with ensure_ascii=False
  - TavilyClient called with correct query / max_results / topic args
  - num_results default comes from outer max_results
  - Custom topic passed through correctly
  - Custom api_key_env is read from the correct env var
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(monkeypatch, api_key: str = "tvly-test-key", max_results: int = 5):
    """构造一个 mock TavilyClient 并返回 (tool_fn, mock_client)。"""
    monkeypatch.setenv("TAVILY_API_KEY", api_key)

    mock_client = MagicMock()
    # 默认搜索返回值
    mock_client.search.return_value = {
        "query": "test query",
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2"},
        ],
    }

    with patch("tavily.TavilyClient", return_value=mock_client):
        from src.tools.web_search import create_web_search_tool
        tool = create_web_search_tool(max_results=max_results)

    return tool, mock_client


# ---------------------------------------------------------------------------
# Test: missing API key
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_raises_key_error_when_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        from src.tools.web_search import create_web_search_tool
        import pytest
        with pytest.raises(KeyError, match="TAVILY_API_KEY"):
            create_web_search_tool()

    def test_raises_key_error_for_custom_env_var(self, monkeypatch):
        monkeypatch.delenv("MY_TAVILY_KEY", raising=False)

        from src.tools.web_search import create_web_search_tool
        import pytest
        with pytest.raises(KeyError, match="MY_TAVILY_KEY"):
            create_web_search_tool(api_key_env="MY_TAVILY_KEY")

    def test_custom_api_key_env_is_read(self, monkeypatch):
        """自定义 api_key_env 时，工具应读取指定的环境变量而非默认 TAVILY_API_KEY。"""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("MY_TAVILY_KEY", "tvly-custom")

        mock_client = MagicMock()
        mock_client.search.return_value = {"query": "x", "results": []}

        with patch("tavily.TavilyClient", return_value=mock_client):
            from src.tools.web_search import create_web_search_tool
            tool = create_web_search_tool(api_key_env="MY_TAVILY_KEY")

        assert callable(tool)


# ---------------------------------------------------------------------------
# Test: tool creation
# ---------------------------------------------------------------------------

class TestToolCreation:
    def test_returns_callable(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        mock_client = MagicMock()
        mock_client.search.return_value = {"query": "x", "results": []}
        with patch("tavily.TavilyClient", return_value=mock_client):
            from src.tools.web_search import create_web_search_tool
            tool = create_web_search_tool()
        assert callable(tool)

    def test_tavily_client_receives_api_key(self, monkeypatch):
        """TavilyClient 应收到从环境变量读取的 API Key。"""
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret-key")
        with patch("tavily.TavilyClient") as mock_cls:
            mock_cls.return_value.search.return_value = {"query": "x", "results": []}
            from src.tools.web_search import create_web_search_tool
            create_web_search_tool()
        mock_cls.assert_called_once_with(api_key="tvly-secret-key")


# ---------------------------------------------------------------------------
# Test: return format（6.2 文档核心改动）
# ---------------------------------------------------------------------------

class TestReturnFormat:
    def test_returns_valid_json_string(self, monkeypatch):
        """internet_search 必须返回合法 JSON 字符串，而非 Python repr。"""
        tool, mock_client = _make_tool(monkeypatch)
        mock_client.search.return_value = {"query": "q", "results": [{"title": "T"}]}

        result = tool("test query")

        # 必须能被 json.loads 解析
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_result_is_not_python_repr(self, monkeypatch):
        """返回值不应包含 Python repr 的特征：单引号键名或 True/False 大写。"""
        tool, mock_client = _make_tool(monkeypatch)
        mock_client.search.return_value = {"flag": True, "results": []}

        result = tool("test")

        # JSON 使用双引号和小写 true，Python repr 使用单引号和大写 True
        assert "True" not in result   # Python repr 特征
        assert '"flag": true' in result or '"flag":true' in result  # JSON 特征

    def test_unicode_characters_not_escaped(self, monkeypatch):
        """ensure_ascii=False：中文等 Unicode 字符应直接输出，而非 \\uXXXX 转义。"""
        tool, mock_client = _make_tool(monkeypatch)
        mock_client.search.return_value = {
            "query": "测试",
            "results": [{"title": "中文标题", "content": "中文内容"}],
        }

        result = tool("测试")

        assert "中文标题" in result
        assert "\\u" not in result  # 没有 Unicode 转义序列

    def test_nested_structure_preserved(self, monkeypatch):
        """嵌套结构（results 数组）在 JSON 序列化后应保持完整。"""
        tool, mock_client = _make_tool(monkeypatch)
        mock_client.search.return_value = {
            "query": "q",
            "results": [
                {"title": "A", "url": "https://a.com", "content": "content A"},
                {"title": "B", "url": "https://b.com", "content": "content B"},
            ],
        }

        result = tool("q")
        parsed = json.loads(result)

        assert len(parsed["results"]) == 2
        assert parsed["results"][0]["title"] == "A"
        assert parsed["results"][1]["url"] == "https://b.com"


# ---------------------------------------------------------------------------
# Test: TavilyClient.search() call arguments
# ---------------------------------------------------------------------------

class TestSearchCallArgs:
    def test_query_passed_correctly(self, monkeypatch):
        tool, mock_client = _make_tool(monkeypatch)
        tool("how does langgraph work")
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[0][0] == "how does langgraph work"

    def test_default_max_results_from_factory(self, monkeypatch):
        """num_results 默认值来自工厂函数的 max_results 参数。"""
        tool, mock_client = _make_tool(monkeypatch, max_results=3)
        tool("query")
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[1]["max_results"] == 3

    def test_override_num_results_at_call_time(self, monkeypatch):
        """调用时可通过 num_results 参数覆盖默认值。"""
        tool, mock_client = _make_tool(monkeypatch, max_results=5)
        tool("query", num_results=2)
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[1]["max_results"] == 2

    def test_default_topic_is_general(self, monkeypatch):
        """topic 默认为 'general'。"""
        tool, mock_client = _make_tool(monkeypatch)
        tool("query")
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[1]["topic"] == "general"

    def test_topic_news_passed_through(self, monkeypatch):
        """指定 topic='news' 时应原样传给 TavilyClient.search()。"""
        tool, mock_client = _make_tool(monkeypatch)
        tool("latest release", topic="news")
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[1]["topic"] == "news"

    def test_topic_finance_passed_through(self, monkeypatch):
        tool, mock_client = _make_tool(monkeypatch)
        tool("stock market", topic="finance")
        call_kwargs = mock_client.search.call_args
        assert call_kwargs[1]["topic"] == "finance"
