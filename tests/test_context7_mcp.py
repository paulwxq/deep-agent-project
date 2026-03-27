"""tests/test_context7_mcp.py

Unit tests for src/tools/context7_mcp.py — load_context7_tools()

Covers:
  - Returns [] when CONTEXT7_API_KEY env var is not set
  - Returns [] when langchain_mcp_adapters is not installed (ImportError)
  - Returns [] when MCP connection fails (exception handling)
  - Returns tool list when connection succeeds
  - Passes correct transport config to MultiServerMCPClient
  - Logs appropriate messages for each scenario
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine in a fresh event loop (for sync test functions)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test: missing API key
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_returns_empty_list_when_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)

        from src.tools.context7_mcp import load_context7_tools
        result = _run(load_context7_tools())

        assert result == []

    def test_logs_warning_when_env_var_not_set(self, monkeypatch, caplog):
        monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)

        with caplog.at_level(logging.WARNING, logger="deep_agent_project"):
            from src.tools.context7_mcp import load_context7_tools
            _run(load_context7_tools())

        assert any("CONTEXT7_API_KEY" in r.message for r in caplog.records)

    def test_returns_empty_list_for_custom_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("MY_CTX7_KEY", raising=False)

        from src.tools.context7_mcp import load_context7_tools
        result = _run(load_context7_tools(api_key_env="MY_CTX7_KEY"))

        assert result == []


# ---------------------------------------------------------------------------
# Test: ImportError (package not installed)
# ---------------------------------------------------------------------------

class TestImportError:
    def test_returns_empty_list_when_package_missing(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        import sys
        # Simulate langchain_mcp_adapters not being installed
        fake_modules = dict(sys.modules)
        fake_modules["langchain_mcp_adapters"] = None
        fake_modules["langchain_mcp_adapters.client"] = None

        with patch.dict(sys.modules, {"langchain_mcp_adapters.client": None}):
            # Patch the import inside the function body
            with patch("builtins.__import__", side_effect=_make_importer_with_error()):
                from src.tools import context7_mcp
                import importlib
                importlib.reload(context7_mcp)
                # Use a direct approach: patch at module load time
        # Reset and test with ImportError patching
        _test_import_error_returns_empty(monkeypatch)

    def test_logs_warning_when_package_missing(self, monkeypatch, caplog):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        with caplog.at_level(logging.WARNING, logger="deep_agent_project"):
            with _patch_mcp_import_error():
                from src.tools.context7_mcp import load_context7_tools
                _run(load_context7_tools())

        assert any("langchain-mcp-adapters" in r.message for r in caplog.records)


def _make_importer_with_error():
    """Not used directly; see _patch_mcp_import_error below."""
    pass


def _patch_mcp_import_error():
    """Context manager that makes `from langchain_mcp_adapters.client import ...` raise ImportError."""
    import sys
    original = sys.modules.get("langchain_mcp_adapters.client")

    class _RaisingModule:
        """Placeholder that raises ImportError on attribute access."""
        def __getattr__(self, name):
            raise ImportError("No module named 'langchain_mcp_adapters'")

    return patch.dict(sys.modules, {"langchain_mcp_adapters.client": _RaisingModule()})  # type: ignore[arg-type]


def _test_import_error_returns_empty(monkeypatch):
    """Isolated helper used by test methods that can't easily do async inside patch."""
    with _patch_mcp_import_error():
        from src.tools.context7_mcp import load_context7_tools
        result = _run(load_context7_tools())
    assert result == []


# ---------------------------------------------------------------------------
# Test: connection failure
# ---------------------------------------------------------------------------

class TestConnectionFailure:
    def test_returns_empty_list_when_get_tools_raises(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(side_effect=Exception("Connection refused"))

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
            from src.tools.context7_mcp import load_context7_tools
            result = _run(load_context7_tools())

        assert result == []

    def test_logs_warning_when_connection_fails(self, monkeypatch, caplog):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(side_effect=Exception("timeout"))

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with caplog.at_level(logging.WARNING, logger="deep_agent_project"):
            with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
                from src.tools.context7_mcp import load_context7_tools
                _run(load_context7_tools())

        assert any("加载失败" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Test: successful load
# ---------------------------------------------------------------------------

class TestSuccessfulLoad:
    def _make_mock_tools(self, names: list[str]) -> list:
        tools = []
        for name in names:
            t = MagicMock()
            t.name = name
            tools.append(t)
        return tools

    def test_returns_tool_list_on_success(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        mock_tools = self._make_mock_tools(["resolve-library-id", "query-docs"])
        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=mock_tools)

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
            from src.tools.context7_mcp import load_context7_tools
            result = _run(load_context7_tools())

        assert len(result) == 2
        assert result[0].name == "resolve-library-id"
        assert result[1].name == "query-docs"

    def test_passes_api_key_in_headers(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-my-secret")

        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=[])

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
            from src.tools.context7_mcp import load_context7_tools
            _run(load_context7_tools())

        call_kwargs = mock_mcp_module.MultiServerMCPClient.call_args
        config_arg = call_kwargs[0][0]  # first positional arg
        assert config_arg["context7"]["headers"]["CONTEXT7_API_KEY"] == "ctx7-my-secret"

    def test_passes_custom_url(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")
        custom_url = "https://custom.mcp.example.com/mcp"

        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=[])

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
            from src.tools.context7_mcp import load_context7_tools
            _run(load_context7_tools(url=custom_url))

        call_kwargs = mock_mcp_module.MultiServerMCPClient.call_args
        config_arg = call_kwargs[0][0]
        assert config_arg["context7"]["url"] == custom_url

    def test_uses_http_transport(self, monkeypatch):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=[])

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
            from src.tools.context7_mcp import load_context7_tools
            _run(load_context7_tools())

        call_kwargs = mock_mcp_module.MultiServerMCPClient.call_args
        config_arg = call_kwargs[0][0]
        assert config_arg["context7"]["transport"] == "http"

    def test_logs_info_with_tool_count(self, monkeypatch, caplog):
        monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7-test-key")

        mock_tools = self._make_mock_tools(["resolve-library-id", "query-docs"])
        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=mock_tools)

        mock_mcp_module = MagicMock()
        mock_mcp_module.MultiServerMCPClient.return_value = mock_client

        with caplog.at_level(logging.INFO, logger="deep_agent_project"):
            with patch.dict("sys.modules", {"langchain_mcp_adapters.client": mock_mcp_module}):
                from src.tools.context7_mcp import load_context7_tools
                _run(load_context7_tools())

        assert any("2" in r.message for r in caplog.records)
