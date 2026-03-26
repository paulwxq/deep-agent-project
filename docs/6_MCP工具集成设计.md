# 6. MCP 工具集成设计

## 1. 背景与目标

### 1.1 当前状态

当前系统通过 `src/tools/web_search.py` 封装了 Tavily HTTP API，以 LangChain `BaseTool` 的形式挂载给 Writer 和 Reviewer。但该方案存在以下局限：

- 只支持 Tavily 一种工具，扩展新工具需要逐个手写封装
- 未利用 MCP（Model Context Protocol）生态，错过 Context7、Memory、Filesystem 等大量现成服务
- 工具配置分散，缺乏统一的"启用/禁用/分配目标 Agent"管理方式

### 1.2 目标

设计一套通用的 MCP 工具集成机制，以 **Context7**（文档查询）和 **Tavily MCP**（网络搜索）为参考实现，满足：

1. 在 `agents.yaml` 中声明任意 MCP Server，无需修改 Python 代码即可启停
2. 支持按 Agent 分配工具（Writer / Reviewer 各自只拿自己需要的；Orchestrator v1 不挂载领域工具）
3. 与现有同步代码架构兼容，最小化改造范围
4. 为 prompt 提供对应的工具使用指引

---

## 2. 技术选型

### 2.1 接入路径

`deepagents.create_deep_agent` 的 `tools` 参数接受 `Sequence[BaseTool | Callable | dict]`。因此，只要能把 MCP 工具包装成 `BaseTool`，就可以无缝挂载。

官方推荐路径：**`langchain-mcp-adapters`** 库提供 `load_mcp_tools(session)` 方法，将 MCP Server 暴露的工具转换为 LangChain `BaseTool` 列表。

```
MCP Server (stdio/SSE)
  ↓ mcp.ClientSession
  ↓ langchain_mcp_adapters.load_mcp_tools()
  → List[BaseTool]
  → create_deep_agent(tools=[...])
```

### 2.2 新增依赖

```toml
# pyproject.toml
dependencies = [
    ...
    "mcp>=1.0",
    "langchain-mcp-adapters>=0.1",
]
```

### 2.3 MCP 传输方式

| 传输类型 | 适用场景 | 示例 |
|---------|---------|------|
| `stdio` | 本地进程（npx/uvx 启动） | Context7、Tavily MCP |
| `sse` | 远程 HTTP 服务 | 自建 MCP Server |

本设计以 `stdio` 为主，`sse` 作为扩展。

### 2.4 异步生命周期问题

MCP Session 是异步 context manager，必须在整个 Agent 运行期间保持连接：

```python
# 伪代码
async with stdio_client(...) as (read, write):
    async with ClientSession(read, write) as session:
        tools = await load_mcp_tools(session)
        # ← Agent 必须在此 with 块内运行，否则 session 关闭，工具失效
        result = await agent.ainvoke(...)
```

**⚠️ 关键约束**：`langchain-mcp-adapters` 加载的 MCP 工具是异步协程（`CoroutineTool`）。LangGraph 在执行同步 `agent.invoke()` / `agent.stream()` 时，遇到 async 工具需要调用 `asyncio.run()` 或 `loop.run_until_complete()`——但我们已经在 `asyncio.run(_async_main(...))` 内部，再次进入会引发 `"This event loop is already running"` 错误，导致工具调用阻塞或死锁。

**结论**：必须使用全链路异步调用：
- 非交互路径：`await agent.ainvoke(...)`
- 交互路径（HIL）：`async def _run_with_hil_async(...)` + `agent.astream(...)`
- `create_orchestrator_agent()` 本身不需要改为 async（它只是构建图，不执行）

---

## 3. 配置设计

### 3.1 `config/agents.yaml` 新增 `mcp_servers` 节

```yaml
tools:
  # 原有 Tavily HTTP 配置保留（与 Tavily MCP 二选一，不要同时启用）
  tavily:
    enabled: false
    api_key_env: "TAVILY_API_KEY"
    max_results: 5

  # MCP Server 配置列表
  mcp_servers:

    context7:
      enabled: true
      transport: "stdio"          # stdio | sse
      command: "npx"
      args: ["-y", "@upstash/context7-mcp"]
      env: {}                     # 额外注入子进程的环境变量
      assign_to: ["writer", "reviewer"]  # Writer/Reviewer 信息对等，各自独立查询
      prompt_hint: "查询第三方库的最新 API 文档：先调用 resolve-library-id 获取库 ID，再调用 get-library-docs 拉取文档"

    tavily_mcp:
      enabled: false
      transport: "stdio"
      command: "npx"
      args: ["-y", "tavily-mcp"]
      env:
        TAVILY_API_KEY: "${TAVILY_API_KEY}"   # 支持 ${VAR} 占位符展开
      assign_to: ["writer", "reviewer"]
      prompt_hint: "网络搜索：用于查找行业资料、技术规范或验证技术引用，直接传入查询关键词"

    # 扩展示例：SSE 类型
    # my_remote_mcp:
    #   enabled: false
    #   transport: "sse"
    #   url: "http://localhost:8000/sse"
    #   assign_to: ["writer"]
    #   prompt_hint: "..."
```

### 3.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否启用该 Server |
| `transport` | str | `stdio` 或 `sse` |
| `command` | str | stdio 模式：启动命令（如 `npx`、`uvx`） |
| `args` | list[str] | stdio 模式：命令参数 |
| `env` | dict | 额外注入子进程的环境变量，支持 `${VAR}` 引用系统环境变量 |
| `url` | str | sse 模式：Server 地址 |
| `assign_to` | list[str] | 工具挂载到哪些 Agent：`writer`、`reviewer`（v1 不支持 `orchestrator`，填写后会在加载时忽略并输出 warning） |
| `prompt_hint` | str | 该工具的使用说明，运行时成功加载后自动注入对应 Agent 的 prompt；留空则只写工具名 |

---

## 4. 代码改造方案

### 4.1 文件改动一览

| 文件 | 操作 | 说明 |
|------|------|------|
| `pyproject.toml` | 修改 | 新增 `mcp`、`langchain-mcp-adapters` 依赖 |
| `config/agents.yaml` | 修改 | 新增 `tools.mcp_servers` 配置节 |
| `src/config_loader.py` | 修改 | 新增 `McpServerConfig`、更新 `ToolsConfig` 和 `load_config` |
| `src/tools/mcp_loader.py` | **新建** | 异步 MCP 工具加载器（context manager） |
| `src/agent_factory.py` | 修改 | 接受 `mcp_tools_by_agent` 参数，按 Agent 分配 MCP 工具 |
| `main.py` | 修改 | 用 `asyncio.run()` 包裹，管理 MCP session 生命周期 |
| `src/prompts/writer_prompt.py` | 修改 | 新增 Context7 使用指引 |
| `src/prompts/reviewer_prompt.py` | 修改 | 新增 Context7 使用指引 |

### 4.2 `src/config_loader.py`

新增 `McpServerConfig` dataclass，更新 `ToolsConfig`：

```python
@dataclass
class McpServerConfig:
    """单个 MCP Server 的配置。"""
    name: str
    transport: str          # "stdio" | "sse"
    enabled: bool = False
    # stdio 参数
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # sse 参数
    url: str = ""
    # 工具分配
    assign_to: list[str] = field(default_factory=lambda: ["writer", "reviewer"])
    # prompt 注入：成功加载后注入 Agent 系统提示词；空字符串表示只列工具名，不附加说明
    prompt_hint: str = ""


@dataclass
class ToolsConfig:
    """工具配置。"""
    tavily_enabled: bool = False
    tavily_api_key_env: str = "TAVILY_API_KEY"
    tavily_max_results: int = 5
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
```

`load_config` 中解析 `mcp_servers`：

```python
# --- tools.mcp_servers ---
mcp_servers: list[McpServerConfig] = []
for server_name, scfg in raw_tools.get("mcp_servers", {}).items():
    if not isinstance(scfg, dict):
        continue
    # 展开 env 中的 ${VAR} 占位符
    raw_env = scfg.get("env", {})
    resolved_env = {
        k: os.path.expandvars(v) for k, v in raw_env.items()
    }
    mcp_servers.append(McpServerConfig(
        name=server_name,
        transport=scfg.get("transport", "stdio"),
        enabled=scfg.get("enabled", False),
        command=scfg.get("command", ""),
        args=scfg.get("args", []),
        env=resolved_env,
        url=scfg.get("url", ""),
        assign_to=scfg.get("assign_to", ["writer", "reviewer"]),
        prompt_hint=scfg.get("prompt_hint", ""),
    ))
```

`load_config` 解析完 `mcp_servers` 后，调用 `_validate_mcp_servers` 对 **enabled=true 的 Server** 做启动前校验，失败立即抛 `ValueError`（不等到 session 初始化阶段）：

```python
def _validate_mcp_servers(servers: list[McpServerConfig]) -> None:
    """对 enabled=true 的 MCP Server 做 fail-fast 校验。

    校验项：
    1. transport 必须是 stdio 或 sse
    2. stdio → command 不能为空
       sse   → url 不能为空
    3. assign_to 只允许 writer / reviewer（v1 约束）
    4. env 展开后不得含未解析占位符（${VAR} 原样保留说明环境变量缺失）
    """
    _VALID_TRANSPORTS = {"stdio", "sse"}
    _VALID_TARGETS = {"writer", "reviewer"}

    for server in servers:
        if not server.enabled:
            continue

        if server.transport not in _VALID_TRANSPORTS:
            raise ValueError(
                f"MCP Server [{server.name}]: transport 必须是 stdio 或 sse，"
                f"当前值: {server.transport!r}"
            )

        if server.transport == "stdio" and not server.command:
            raise ValueError(
                f"MCP Server [{server.name}]: transport=stdio 时 command 不能为空"
            )

        if server.transport == "sse" and not server.url:
            raise ValueError(
                f"MCP Server [{server.name}]: transport=sse 时 url 不能为空"
            )

        invalid_targets = set(server.assign_to) - _VALID_TARGETS
        if invalid_targets:
            raise ValueError(
                f"MCP Server [{server.name}]: assign_to 包含不支持的目标 {sorted(invalid_targets)}，"
                f"v1 仅支持 writer / reviewer"
            )

        # 检测未展开的 ${VAR} 占位符（expandvars 对未设置变量保留原样）
        for env_key, env_val in server.env.items():
            if "${" in env_val:
                raise ValueError(
                    f"MCP Server [{server.name}]: env.{env_key} 含未解析的占位符 {env_val!r}，"
                    f"请确认对应环境变量已设置"
                )
```

> **设计说明**：`_validate_mcp_servers` 只校验 **结构完整性** 和 **可检测缺失**，不做网络连通性校验（那属于运行期）。`mcp_loader.py` 中保留对启动异常的 `try/except warning`，但上述几类明确的配置错误不再降级为 warning——它们是用户配置错误，应快速失败给出清晰提示。

### 4.3 `src/tools/mcp_loader.py`（新建）

```python
"""MCP 工具加载器。

提供异步 context manager load_mcp_tools_by_agent()：
- 依次启动 agents.yaml 中 enabled=true 的 MCP Server
- 将每个 Server 的工具和配置按 assign_to 分配给对应 Agent
- 退出时自动关闭所有 Server 连接

返回 McpLoadResult，区分"工具列表"和"成功加载的 Server 配置"，
确保 prompt 只根据实际就绪的能力生成工具说明，避免 tool-not-found 风险。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, AsyncExitStack
from dataclasses import dataclass, field
from typing import AsyncIterator

from langchain_core.tools import BaseTool

from src.config_loader import McpServerConfig

_log = logging.getLogger("deep_agent_project")


@dataclass
class McpLoadResult:
    """MCP 加载结果，同时携带工具实例和成功加载的 Server 配置。

    tools_by_agent:   {agent_name: [BaseTool, ...]}  — 直接传给 create_deep_agent
    servers_by_agent: {agent_name: [McpServerConfig, ...]}  — 只含成功加载的 Server，
                      用于 prompt builder 动态生成工具说明段落
    """
    tools_by_agent: dict[str, list[BaseTool]] = field(default_factory=dict)
    servers_by_agent: dict[str, list[McpServerConfig]] = field(default_factory=dict)


@asynccontextmanager
async def load_mcp_tools_by_agent(
    servers: list[McpServerConfig],
) -> AsyncIterator[McpLoadResult]:
    """启动所有 enabled MCP Server，yield McpLoadResult。

    单个 Server 启动失败只记录 warning，不中断整体流程；
    失败的 Server 不会出现在 servers_by_agent 中，因此不会被写进 prompt。

    工具名冲突策略（v1）：
    - 按 agent 维度检测重名，先加载（YAML 顺序靠前）的工具优先保留
    - 后注册的同名工具被跳过，并输出 warning 注明冲突的 server 名和工具名
    - 冲突的 server 若还有其他非冲突工具，则仍会出现在 servers_by_agent（prompt hint 照常注入）
    - 根本解决：在 agents.yaml 中为不同 server 配置不重叠的 assign_to，或禁用其中一个

    Usage:
        async with load_mcp_tools_by_agent(config.tools.mcp_servers) as mcp_result:
            agent = create_orchestrator_agent(config, ..., mcp_result=mcp_result)
            agent.invoke(...)
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from langchain_mcp_adapters.tools import load_mcp_tools

    result = McpLoadResult()
    enabled = [s for s in servers if s.enabled]

    async with AsyncExitStack() as stack:
        for server in enabled:
            try:
                if server.transport == "stdio":
                    env = {**os.environ, **server.env}
                    params = StdioServerParameters(
                        command=server.command,
                        args=server.args,
                        env=env,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                elif server.transport == "sse":
                    read, write = await stack.enter_async_context(sse_client(server.url))
                else:
                    raise ValueError(f"不支持的 MCP transport: {server.transport}")

                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools: list[BaseTool] = await load_mcp_tools(session)

                # assign_to 合法性已在 config_loader._validate_mcp_servers 校验，此处无需重复检查
                for agent_name in server.assign_to:
                    # 工具名冲突检测：按 agent 维度去重，先注册者优先
                    existing_names = {t.name for t in result.tools_by_agent.get(agent_name, [])}
                    safe_tools, skipped = [], []
                    for tool in tools:
                        if tool.name in existing_names:
                            skipped.append(tool.name)
                        else:
                            safe_tools.append(tool)
                            existing_names.add(tool.name)
                    if skipped:
                        _log.warning(
                            "MCP Server [%s] 工具名与已有工具冲突，已跳过（agent=%s, 冲突工具=%s）"
                            "请检查是否有多个 Server 暴露了同名工具，或调整 assign_to 避免共用同一 Agent。",
                            server.name, agent_name, skipped,
                        )

                    result.tools_by_agent.setdefault(agent_name, []).extend(safe_tools)
                    if safe_tools:  # 至少有一个工具成功加载才记入 servers_by_agent
                        result.servers_by_agent.setdefault(agent_name, []).append(server)

                _log.info(
                    "MCP Server [%s] 加载成功，工具数: %d，分配目标: %s",
                    server.name, len(tools), server.assign_to,
                    extra={"agent_name": "system"},
                )

            except Exception as exc:
                # 失败的 Server 不进入 result，prompt 不会提及它
                _log.warning(
                    "MCP Server [%s] 启动失败，跳过: %s", server.name, exc,
                    extra={"agent_name": "system"},
                )

        yield result
```

### 4.4 `src/agent_factory.py`

`create_orchestrator_agent` 新增可选参数 `mcp_result`：

```python
from src.tools.mcp_loader import McpLoadResult   # ← 新增

def create_orchestrator_agent(
    config: AppConfig,
    requirement_filename: str = "requirement.txt",
    mcp_result: McpLoadResult | None = None,   # ← 新增
) -> tuple[CompiledStateGraph, LoggingMiddleware]:
    ...
    mcp_result = mcp_result or McpLoadResult()

    # 构建各 Agent 工具列表时合并 MCP 工具
    writer_tools = list(tools)
    writer_tools.extend(mcp_result.tools_by_agent.get("writer", []))
    if config.hil_clarify:
        writer_tools.append(ask_user)

    reviewer_tools = list(tools)
    reviewer_tools.extend(mcp_result.tools_by_agent.get("reviewer", []))

    orch_tools = hil_tools   # v1: Orchestrator 不挂载 MCP 工具

    # 构建 MCP 工具指引（只含已成功加载的 Server）
    writer_mcp_hint = _build_mcp_section(mcp_result.servers_by_agent.get("writer", []))
    reviewer_mcp_hint = _build_mcp_section(mcp_result.servers_by_agent.get("reviewer", []))

    writer_prompt = build_writer_prompt(config, requirement_filename, mcp_hint=writer_mcp_hint)
    reviewer_prompt = build_reviewer_prompt(mcp_hint=reviewer_mcp_hint)
    ...

    reviewer_subagent = {
        ...
        "tools": reviewer_tools,   # 原来是 tools，现在是 reviewer_tools
        ...
    }
```

### 4.5 `main.py`

将核心执行逻辑抽为 `async def _async_main()`，`main()` 用 `asyncio.run()` 调用。

**⚠️ 重要**：由于 MCP 工具是异步协程，必须全链路使用 async 调用（见 2.4 节）。

```python
import asyncio

async def _async_main(args, config, requirement_filename, output_filename_from_arg) -> None:
    from src.tools.mcp_loader import load_mcp_tools_by_agent, McpLoadResult

    enabled_servers = [s for s in config.tools.mcp_servers if s.enabled]

    async with load_mcp_tools_by_agent(enabled_servers) as mcp_result:
        agent, orch_middleware = create_orchestrator_agent(
            config, requirement_filename, mcp_result=mcp_result
        )
        # ⚠️ 必须使用 ainvoke / astream，不能用同步 invoke / stream
        if config.hil_clarify or config.hil_confirm:
            result = await _run_with_hil_async(agent, initial_messages, thread_config)
        else:
            result = await agent.ainvoke(
                {"messages": initial_messages}, config=thread_config
            )
        # ... 后处理（复制文件、print_final_summary 等）


async def _run_with_hil_async(agent, initial_messages, thread_config) -> dict:
    """HIL 交互路径的异步版本，替换原同步 _run_with_hil()。

    原 _run_with_hil() 使用 agent.stream()（同步生成器）；
    在 asyncio.run() 内部调用 MCP async 工具时会引发事件循环冲突。
    改为 agent.astream() 异步生成器，MCP 工具调用可正确 await。
    """
    messages = initial_messages
    while True:
        async for chunk in agent.astream(
            {"messages": messages}, config=thread_config, stream_mode="updates"
        ):
            # 与原 _run_with_hil 相同的 interrupt / confirm 逻辑，改为 await input
            ...
        break  # 占位，实际逻辑同原函数


def main() -> None:
    # 前段（argparse、日志初始化、配置加载、文件校验、drafts 备份）保持同步
    ...
    # 核心执行部分改为 async
    asyncio.run(_async_main(args, config, requirement_filename, output_filename_from_arg))
```

> **注意**：`_run_with_hil_async` 中使用 `input()` 等同步 I/O 仍然安全（Python 的 `input()` 不阻塞事件循环，因为它在 asyncio 看来是一次 OS syscall）。如果未来改用 `aioconsole` 等异步 I/O，则改用 `await ainput()`。

---

## 5. Prompt 改造

### 5.1 Context7 使用规则（Writer）

`build_writer_prompt` 新增参数 `mcp_hint: str = ""`，由 `agent_factory.py` 调用 `_build_mcp_section(servers)` 动态生成并传入。只有实际加载成功的 MCP Server 才会出现在 hint 中（见 4.4 节）。

`_build_mcp_section` 将每个 `McpServerConfig.prompt_hint` 拼接为字符串，格式示例：

```python
def _build_mcp_section(servers: list[McpServerConfig]) -> str:
    if not servers:
        return ""
    parts = [s.prompt_hint for s in servers if s.prompt_hint]
    if not parts:
        return ""
    return "\n\n---\n## 可用外部工具\n\n" + "\n\n".join(parts)
```

当 context7 与 Tavily 均成功加载时，`mcp_hint` 注入以下内容（来自 `agents.yaml` 的 `prompt_hint` 字段）：

```
## 可用外部工具

**context7（技术文档查询）**
遇到以下情况时，可调用 context7 工具查询最新技术文档：
- 需要确认某个库/框架的 API 签名、参数名或版本差异
- 需求涉及第三方服务的集成规范（如云厂商 API、标准协议）
- 对某技术选型存在版本约束疑问

查询规则：
- 先用 resolve-library-id 获取库 ID，再用 get-library-docs 拉取文档
- 每次文档查询限于直接影响设计决策的内容，不要泛读
- 查询结果作为设计参考，不直接复制到文档；引用时注明来源
- 如果 context7 查询失败，退回到基于已有知识设计，不阻塞写作

**Tavily（网络搜索）**
- 用于查询行业资料、官方博客、最新动态
- 优先搜索官方文档和 changelog，不依赖二手摘要
- 搜索结果用于辅助判断，不直接大段引用
```

若某个 Server 加载失败，其 `prompt_hint` 不会出现；若所有 MCP Server 均未加载，`mcp_hint` 为空字符串，prompt 末尾不追加任何内容。

### 5.2 Context7 与 Tavily 使用规则（Reviewer）

`build_reviewer_prompt` 同样新增 `mcp_hint: str = ""` 参数，由 `_build_mcp_section(mcp_result.servers_by_agent.get("reviewer", []))` 生成。

当 context7 与 Tavily 均成功加载时，Reviewer 的 `mcp_hint` 注入：

```
## 可用外部工具

**context7 / Tavily（独立核实工具）**
Reviewer 与 Writer 拥有相同的查询工具，以保证信息对等——你可以独立查阅 Writer
所参考的技术文档或网络资料，而不必依赖 Writer 的转述。

可主动查询的场景：
- 设计文档引用了具体的库版本或 API 名称，需要独立核实其准确性
- Writer 描述的技术方案涉及某个你不确定的行业规范或协议细节
- 对 Writer 的技术选型存疑，希望查询当前社区主流实践

查询规则：
- context7：先用 resolve-library-id 获取库 ID，再用 get-library-docs 拉取文档
- Tavily：直接搜索技术关键词，优先看官方文档和 changelog
- 查询结果只用于形成审核判断，不要在反馈中大段引用原文
- 不要用"网上有更好的方案"否定 Writer 的合理选型，除非 Writer 引用的 API 已被废弃
- 工具调用失败时，在审核意见中注明"未验证"，不影响 VERDICT 判断
```

同 5.1 节：只有实际加载成功的 Server 才出现；若全部失败，`mcp_hint` 为空，prompt 不追加额外内容。

---

## 6. 工具分配策略建议

### 6.1 Context7 与 Tavily：Writer/Reviewer 信息对等

Context7 和 Tavily 均同时分配给 Writer 和 Reviewer，原因是**信息对等原则**：

- **Writer** 用 Context7 查文档辅助设计，用 Tavily 搜行业资料；
- **Reviewer** 同样拥有这两个工具，可以独立查询同一份资料来验证 Writer 的技术决策，而不是只能被动接受 Writer 提供的信息。

如果 Reviewer 没有查询工具，它只能根据自身训练知识审核，无法与 Writer 在同等信息基础上对话，容易出现"审核者知识滞后"或"无法验证 Writer 查到的最新 API"的问题。

### 6.2 分配总表

> v1 范围：`assign_to` 仅支持 `writer` / `reviewer`。`orchestrator` 暂不开放——Orchestrator 只负责任务调度，不需要领域查询工具，且缺乏对应的 prompt 约束和测试策略。如需在未来版本支持，需补充使用场景、prompt 规则和集成测试后再开放。

| MCP Server | Writer | Reviewer | 说明 |
|-----------|:------:|:--------:|------|
| Context7 | ✅ | ✅ | 信息对等：Writer 查文档写设计，Reviewer 独立查同一文档做验证 |
| Tavily MCP | ✅ | ✅ | 信息对等：搜索能力对称，Reviewer 可复核 Writer 引用的网络资料 |
| 自定义记忆/知识库 MCP | ✅ | ✅ | 若涉及项目内部知识库，同样保持对等 |
| 数据库/查询类 MCP | ✅ | ❌ | 数据读取属于写作阶段行为，Reviewer 不直接操作数据源 |

**原则**：
- v1 中 `assign_to: ["orchestrator"]` 为无效配置，加载时输出 warning 并跳过
- 凡是涉及"查资料、查文档、查事实"的工具，Writer 和 Reviewer 保持对等配置
- 凡是涉及"操作数据、写入文件"的工具，仅 Writer 使用

---

## 7. Tavily MCP vs Tavily HTTP 的取舍

现有 `src/tools/web_search.py` 使用 Tavily HTTP API，与 `tavily-mcp` 功能基本重叠。

| 维度 | Tavily HTTP (`web_search.py`) | Tavily MCP |
|------|-------------------------------|-----------|
| 启动依赖 | 无额外依赖 | 需要 Node.js + npx |
| 配置复杂度 | 简单（API Key 即可） | 略复杂（MCP 进程管理） |
| 工具能力 | 单一搜索接口 | 可能提供更多工具变体 |
| 统一管理 | 独立于 MCP 体系 | 与其他 MCP 工具统一管理 |

**建议**：两者不要同时启用。如果已引入 MCP 框架，优先使用 Tavily MCP，并在 `agents.yaml` 中将 `tools.tavily.enabled` 设为 `false`。

---

## 8. 实施顺序

1. **依赖安装**：`uv add mcp langchain-mcp-adapters`
2. **配置层**：`config_loader.py` 新增 `McpServerConfig`（含 `prompt_hint` 字段），`agents.yaml` 添加 `mcp_servers` 节
3. **加载器**：新建 `src/tools/mcp_loader.py`，返回 `McpLoadResult`（含 `tools_by_agent` + `servers_by_agent`）；先写单元测试（mock session）验证分配逻辑
4. **Prompt 层**：`writer_prompt.py` 和 `reviewer_prompt.py` 各增 `mcp_hint: str = ""` 参数；新建 `_build_mcp_section(servers)` 辅助函数
5. **Agent 工厂**：`create_orchestrator_agent` 加 `mcp_result: McpLoadResult | None = None` 参数，通过 `mcp_result.tools_by_agent` 注入工具，通过 `_build_mcp_section` 生成 prompt hint
6. **main.py 异步重构**：
   - 核心执行逻辑提取为 `async def _async_main(...)`
   - 非 HIL 路径改为 `await agent.ainvoke(...)`
   - HIL 路径新建 `async def _run_with_hil_async(...)` + `agent.astream(...)`
   - `main()` 调用 `asyncio.run(_async_main(...))`
7. **集成测试**：本地启动 `npx -y @upstash/context7-mcp` 验证工具加载；在实际 Agent 运行中确认 `agent.ainvoke()` 正确调用 MCP 工具，无事件循环错误

---

## 9. 风险与注意事项

| 风险 | 应对 |
|------|------|
| **同步 invoke + async MCP 工具死锁** | 全链路使用 `agent.ainvoke()` / `agent.astream()`，在 `asyncio.run()` 内禁止调用同步 `agent.invoke()` / `agent.stream()`；HIL 路径改为 `_run_with_hil_async()` |
| **同 agent 工具名冲突** | `mcp_loader.py` 按 agent 维度检测重名，先加载者优先，后注册者跳过并 warning；根本解决：配置层确保同一 agent 下各 server 无同名工具 |
| **配置错误推迟到运行期** | `load_config` 末尾调用 `_validate_mcp_servers`，对 enabled server 做 fail-fast 校验：transport 合法性、stdio/sse 必填字段、assign_to 合法目标、`${VAR}` 占位符是否已解析 |
| Node.js / npx 未安装 | Server 启动失败时 `mcp_loader.py` 捕获异常并 warning，不中断整体运行 |
| MCP Server 启动慢 | `AsyncExitStack` 串行启动，多个 Server 时总延迟叠加；如需优化可改为并发启动 |
| context7 查询超时 | Prompt 中要求工具失败时退回本地知识，不阻塞写作 |
| Tavily MCP 与 Tavily HTTP 重复 | 配置层约定：`mcp_servers.tavily_mcp.enabled=true` 时必须同时 `tavily.enabled=false`；可在 `load_config` 中加校验规则 |
| 工具列表过长影响模型 | 控制每个 Agent 挂载的 MCP Server 数量；`assign_to` 字段精细化分配 |
