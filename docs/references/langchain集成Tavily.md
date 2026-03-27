# LangChain 集成 Tavily 核心指南

在 `deepagents` SDK 环境中，Tavily 是最常推荐的外部能力扩展，负责 **“互联网搜索”**。

## 1. Tavily：互联网搜索专家

Tavily 是专为 AI 设计的搜索引擎，它会过滤掉广告和无关干扰，直接返回包含内容摘要的结构化数据。

### 1.1 核心价值
1. **自动摘要**：搜索结果自带内容片段，减少模型因阅读长网页而消耗的 Token。
2. **相关性过滤**：搜索结果经过 AI 优化，更贴合大模型理解需求。
3. **原生集成**：`deepagents` SDK 虽然未硬编码该工具，但其函数签名与 LangChain 完全兼容。

### 1.2 集成步骤

**第一步：安装依赖**
```bash
uv add tavily-python
```

**第二步：环境配置**
```bash
# .env 文件
TAVILY_API_KEY="tvly-your-api-key"
```

**第三步：创建搜索工具 (推荐封装方式)**
```python
import os
from tavily import TavilyClient

def create_web_search_tool(max_results: int = 5):
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise KeyError("未设置 TAVILY_API_KEY 环境变量")
    
    client = TavilyClient(api_key=api_key)

    def internet_search(query: str) -> str:
        """Search the internet for current technical information, documentation, or code examples."""
        results = client.search(query, max_results=max_results)
        return str(results)
    
    return internet_search
```

## 2. 在 `create_deep_agent` 中挂载

```python
from deepagents import create_deep_agent

search_tool = create_web_search_tool()

agent = create_deep_agent(
    model=model,
    tools=[search_tool], # 在此处注册
    system_prompt="You are a research assistant. Use the internet_search tool to gather information."
)
```

## 3. 故障排除

1. **Proxy 代理问题**：如果在内网环境运行，请确保设置了 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量，否则无法访问 Tavily 的 API。
2. **API 限制**：Tavily 免费版有每月搜索次数限制。建议在 `internet_search` 工具中加入 `try-except` 捕获异常。
3. **Token 消耗**：Tavily 返回的是摘要，通常不会导致 Context Window 溢出，但如果 `max_results` 设置过大，仍需注意单次响应的长度。
