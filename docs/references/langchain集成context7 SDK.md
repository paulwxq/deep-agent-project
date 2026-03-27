我们来逐一解答你的问题。你指出的非常正确，`deepagents` SDK 是底层提供 `create_deep_agent()` 等核心能力的框架（Agent Harness），而很多应用是基于这个 SDK 构建的。下面我们将严格围绕在代码中使用 `create_deep_agent()` 接入 Context7 展开讨论。

### 1. 关于 MCP 模式是否需要本地安装 Node.js 与 CLI？

**不需要**。这是 MCP（模型上下文协议）架构的一个巨大优势。

MCP 支持两种传输（Transport）模式：
*   **stdio 模式（本地）：** 这种模式确实需要在本地运行子进程，也就是你提到的需要本地安装 Node/npm 以及执行 `npx -y @upstash/context7-mcp` [1]。
*   **HTTP 模式（远程）：** Context7 提供了一个托管的远程 MCP 服务器端点 (`https://mcp.context7.com/mcp`)。你可以直接通过 HTTP 请求与它通信，**完全不需要在本地安装 Node.js 或任何 Context7 的 CLI 工具** [2, 1]。

**为什么 MCP（特别是 HTTP 模式）比 `CLI + Skills` 更简单且更优？**
1.  **零环境依赖**：使用远程 HTTP MCP 时，你的运行环境只需纯 Python，无需配置 Node.js、环境变量或全局 npm 包。
2.  **原生函数调用 (Function Calling)**：在 `CLI + Skills` 模式下，模型需要自己拼接类似 `ctx7 docs /vercel/next.js` 这样的终端字符串并在沙盒中执行，这极易产生格式错误。而 MCP 模式会将 Context7 的能力直接转化为大模型原生的结构化 JSON 工具 [3]。
3.  **返回数据结构化**：CLI 模式返回的是终端的纯文本输出，可能掺杂警告或乱码，污染上下文；MCP 则返回严格的结构化文档数据，大幅降低 Token 消耗并提升模型的解析成功率。

### 2. 在 `create_deep_agent()` 代码中配置 Context7 MCP 的具体步骤

在 LangChain 和 `deepagents` SDK 环境中，你可以通过官方的 `langchain-mcp-adapters` 包来加载远程 MCP 工具，并将它们无缝传递给 `create_deep_agent()`。

**第一步：安装依赖**
你只需要安装基础的 LangChain MCP 适配器，无需安装任何 Context7 特定的依赖。

如果你使用 `uv` 管理项目（推荐）：
```bash
uv add langchain-mcp-adapters deepagents mcp
```

如果你使用 `pip`：
```bash
pip install langchain-mcp-adapters deepagents mcp
```

> **注意：** `mcp` 包是 `langchain-mcp-adapters` 的核心传输依赖，显式安装可确保 `sse` (HTTP) 传输层及其相关异步组件完全可用。

**第二步：环境配置**
前往 Context7 官网获取一个 API Key。在你的运行环境中设置该环境变量（例如写入 `.env` 文件或在终端中 export）：
```bash
# .env 文件
CONTEXT7_API_KEY="your-api-key"
OPENAI_API_KEY="your-llm-api-key"
```

### 3. 连接验证脚本 (Troubleshooting)

在启动完整的 Agent 循环之前，你可以运行以下脚本来验证是否能正确连通 Context7 远程服务器并获取工具列表。这对于排查代理 (Proxy) 或网络权限问题非常有用：

```python
import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient

async def check_mcp_connection():
    try:
        # 1. 配置连接 (注意：headers 键名为 CONTEXT7_API_KEY)
        client = MultiServerMCPClient({
            "context7": {
                "transport": "http", 
                "url": "https://mcp.context7.com/mcp",
                "headers": {
                    "CONTEXT7_API_KEY": os.getenv("CONTEXT7_API_KEY", "")
                }
            }
        })
        
        # 2. 尝试获取工具
        print("Connecting to Context7 MCP...")
        tools = await client.get_tools()
        
        print(f"Success! Found {len(tools)} tools:")
        for tool in tools:
            print(f" - {tool.name}: {tool.description[:60]}...")
            
    except Exception as e:
        print(f"Connection failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(check_mcp_connection())
```

### 4. 工具使用最佳实践

Context7 的工具具有先后依赖关系，在 System Prompt 中加入以下指令可以大幅提升模型查阅文档的准确性：

1.  **分步查询策略**：引导模型首先使用 `resolve-library-id` 确定目标库的准确 ID（例如输入 `next.js` 得到 `/vercel/next.js`），随后再调用 `query-docs` 获取具体内容。
2.  **版本显式化**：如果用户提到特定版本（如 Next.js 15），引导模型在 `query-docs` 的 query 中包含版本关键词。
3.  **结合 planning 工具**：在 `deepagents` 的 `write_todos` 步骤中，应明确包含一项“使用 Context7 检索最新 API 规范”的任务，以确保检索动作发生在撰写代码之前。

### 5. 标准代码模板

你可以通过以下代码标准地初始化 `MultiServerMCPClient`，拉取工具，并传给 Deep Agent：

```python
import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

async def main():
    # 1. 配置并连接 Context7 的远程 HTTP MCP 服务器 (完全跳过本地 CLI)
    client = MultiServerMCPClient({
        "context7": {
            "transport": "http",
            "url": "https://mcp.context7.com/mcp",
            "headers": {
                "CONTEXT7_API_KEY": os.getenv("CONTEXT7_API_KEY")
            }
        }
    })

    # 2. 动态拉取 Context7 的原生工具
    mcp_tools = await client.get_tools()

    # 3. 初始化你的大语言模型
    model = init_chat_model("openai:gpt-4o")

    # 4. 创建 Deep Agent 并挂载 MCP 工具
    agent = create_deep_agent(
        model=model,
        tools=mcp_tools,
        system_prompt="You are an expert software engineer. Always use the Context7 tool to look up the latest library documentation before writing code."
    )

    # 5. 运行 Agent
    async for chunk in agent.astream({"messages": [{"role": "user", "content": "How does the new Next.js 15 after() function work?"}]}):
        if "messages" in chunk:
            print(chunk["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())
```

通过这种方式，你的代码与 Context7 的集成只停留在网络协议层 [2, 1]。Deep Agent 会根据用户的提问，自主规划并在需要时调用这些工具去拉取最新的代码示例，彻底免去了配置和维护本地执行沙盒与命令行工具的复杂性。
