# Deep Agents SDK：架构、API 与多 Agent 设计模式

**`deepagents` SDK 是 LangChain 官方的"Agent 框架"——一个基于 LangChain 和 LangGraph 构建的、开箱即用的自主框架，内置了规划（Planning）、文件系统访问、子代理委派和自动上下文管理。** 该项目于 2025 年 7 月由 Harrison Chase 发布，其架构灵感来源于 Claude Code。目前已积累约 **~16,000 GitHub Stars**，开发活跃（最新版本：v0.4.12，2026 年 3 月 20 日发布）。SDK 返回一个编译后的 LangGraph `StateGraph`，完全兼容流式输出、持久化、Studio 可视化调试以及所有 LangGraph 特性，同时将提示词、工具和上下文工程的复杂接线抽象封装。

该框架基于三层技术栈：**LangGraph**（状态机运行时与持久化）、**LangChain**（模型、工具和代理框架）、以及 **Deep Agents**（提供最佳实践默认配置的上层封装）。对于构建 writer-reviewer 系统，SDK 提供两条清晰路径：由编排器（Orchestrator）通过提示词驱动的反馈循环，或使用自定义 LangGraph 工作流通过显式条件边实现精确的迭代控制。

---

## 核心架构：受 Claude Code 启发的四大支柱

`create_deep_agent()` 函数定义在 `libs/deepagents/deepagents/graph.py` 中，是 SDK 的唯一入口。它组装中间件流水线、连接工具，并委托 LangChain 的 `create_agent()` 执行，最终返回一个**编译后的 LangGraph `CompiledStateGraph`**。四大架构支柱使该 Agent 能够胜任长周期任务：

**规划（Planning）** 使用 `write_todos` 工具（一种借鉴自 Claude Code 的 `TodoWrite` 的"空操作"上下文工程技术），强制 LLM 创建和更新结构化任务列表，使 Agent 在数十次工具调用中始终保持任务方向。**文件系统访问** 提供虚拟文件系统，支持可插拔后端——临时内存（`StateBackend`）、真实磁盘（`FilesystemBackend`）、持久存储（`StoreBackend`）或沙箱环境（Modal、Daytona、Deno、Runloop）。`CompositeBackend` 可以将不同路径路由到不同的后端。**子代理委派** 使用 `task` 工具生成拥有独立上下文窗口的子 Agent，防止上下文膨胀。**上下文管理** 包括：对话接近 **~170k tokens** 时自动摘要压缩、大型工具结果在 **80k 字符** 时被清退、以及在上下文容量达到 85% 时卸载工具输入。

强制中间件栈按固定顺序执行：

1. `TodoListMiddleware` — 规划和进度追踪
2. `MemoryMiddleware` — 加载 AGENTS.md 记忆文件
3. `SkillsMiddleware` — 渐进式技能加载（从 SKILL.md 文件）
4. `FilesystemMiddleware` — 所有文件操作（ls、read、write、edit、glob、grep、execute）
5. `SubAgentMiddleware` — 通过 `task` 工具生成子代理
6. `SummarizationMiddleware` — 自动上下文压缩
7. `AnthropicPromptCachingMiddleware` — Token 成本优化
8. `PatchToolCallsMiddleware` — 修复中断的工具调用

用户提供的自定义中间件会追加到这些默认中间件之后。每个中间件实现 `AgentMiddleware` 协议，包含四个钩子：`before_agent`、`wrap_model_call`、`before_tool_call` 和 `after_tool_call`。

---

## `create_deep_agent()` 完整 API

完整的函数签名（v0.4.12）暴露了所有可定制的参数：

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="claude-sonnet-4-6",                    # str ("provider:model") 或 BaseChatModel 实例
    tools=[my_search_tool, my_analysis_tool],      # 自定义工具（函数、@tool装饰器、BaseTool）
    system_prompt="You are a research coordinator", # 会被追加到 BASE_AGENT_PROMPT 前面
    subagents=[writer_spec, reviewer_spec],        # SubAgent 字典列表或 CompiledSubAgent 列表
    middleware=[CustomMiddleware()],                # 额外中间件（追加到默认中间件之后）
    skills=["/path/to/skills/"],                   # 包含 SKILL.md 文件的技能目录
    memory=["/path/to/AGENTS.md"],                 # 加载到系统提示词中的记忆文件
    backend=FilesystemBackend(root_dir="./workspace"), # 可插拔的文件系统后端
    checkpointer=MemorySaver(),                    # 持久化和人机协作（HITL）所需
    store=InMemoryStore(),                         # 通过 LangGraph Store 实现长期记忆
    interrupt_on={"write_file": True},             # 按工具设置人机协作断点
    response_format=None,                          # 结构化输出 schema
    context_schema=None,                           # 自定义状态扩展类型
    name="my-agent",                               # 用于追踪和流式输出标识
    cache=None,                                    # LangGraph 缓存
    debug=False,                                   # 调试模式
)
```

返回的 `CompiledStateGraph` 支持 `agent.invoke()`、`agent.stream()`、`agent.ainvoke()`、`agent.astream()`，以及 `.with_config({"recursion_limit": 1000})`。**默认模型**为 `claude-sonnet-4-5-20250929`（通过 `ChatAnthropic`）。模型选择通过 LangChain 的 `init_chat_model()` 实现供应商无关，接受 `"provider:model"` 格式的字符串，例如 `"openai:gpt-5.2"`、`"google_genai:gemini-2.5-flash"`、`"openrouter:qwen/qwen3.5-397b"` 或 `"ollama:llama3"`。

**10 个内置工具**无需配置即可使用：`write_todos`、`read_todos`、`ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`、`execute`（仅沙箱环境）和 `task`（子代理委派）。

---

## 子代理架构与通信模型

子代理是实现**上下文隔离**的一等原语——每个子代理在自己的上下文窗口中运行，仅接收任务描述作为输入，仅返回最终综合答案。中间过程的工具调用和思维链对父代理不可见。通信模式**严格为父→子单向**：子代理不能回调父代理，不能调用兄弟代理，也不能生成自己的子代理（`SubAgentMiddleware` 会从子代理的中间件栈中排除，以防止递归嵌套）。

两种配置方式。**字典式（Dictionary-based）** 子代理最为简单：

```python
writer_subagent = {
    "name": "writer",                    # 必需：唯一标识符
    "description": "根据研究资料和反馈撰写高质量内容",  # 必需
    "system_prompt": "你是一位经验丰富的技术文档撰写者...",  # 必需：不从父代理继承
    "tools": [web_search],               # 必需：不从父代理继承
    "model": "openai:gpt-5.2",          # 可选：省略则继承父代理模型
}
```

关键继承规则：`model` 和 `interrupt_on` 在省略时继承自父代理；`system_prompt`、`tools`、`middleware` 和 `skills` **不继承**，必须显式指定。每个 Deep Agent 自动包含一个**内置的 `general-purpose` 子代理**，其配置与主代理相同，可用于无需专门化的上下文隔离。

**`CompiledSubAgent`** 可以将任何预构建的 LangGraph 图包装为子代理：

```python
from deepagents import CompiledSubAgent

custom_workflow = my_langgraph_graph.compile()
custom_subagent = CompiledSubAgent(
    name="data-pipeline",
    description="运行多步骤数据分析工作流",
    runnable=custom_workflow  # 必须包含 "messages" 状态键
)
```

`subagent_model` 参数（v0.4.11 新增）为所有子代理提供默认模型覆盖，无需逐个指定。这在主代理使用前沿模型而子代理使用低成本模型时非常有用。

---

## 构建 Writer-Reviewer 反馈循环

由于 deepagents 采用层级委派模型（非对等通信），实现 writer-reviewer 循环需要以下两种方式之一。

### 方案 A：编排器管理的循环

依赖父代理的提示词驱动迭代。实现更简单，但确定性较低——由 LLM 决定何时停止：

```python
writer_subagent = {
    "name": "writer",
    "description": "撰写和修订内容。将草稿保存到 /drafts/current.md",
    "system_prompt": """你是一位经验丰富的技术文档撰写者。如果收到反馈意见，
    请据此修订你的草稿。将输出写入 /drafts/current.md。""",
    "tools": [],
}

reviewer_subagent = {
    "name": "reviewer",
    "description": "审核草稿。给出 ACCEPT 或 REVISE 结论及反馈意见。",
    "system_prompt": """阅读 /drafts/current.md 的草稿。从准确性、清晰度和完整性评估。
    返回 ACCEPT 或 REVISE 结论及具体反馈意见。
    不要直接修改草稿。""",
    "tools": [],
}

orchestrator = create_deep_agent(
    model="claude-sonnet-4-6",
    system_prompt="""你负责协调一个写作工作流：
    1. 将主题和所有之前的反馈委派给 'writer'
    2. 委派给 'reviewer' 评估草稿
    3. 如果 reviewer 判定为 REVISE，通过新任务将反馈发回 writer
    4. 最多 3 轮修订。当 reviewer 判定为 ACCEPT 时停止。
    5. 返回最终的草稿内容。""",
    subagents=[writer_subagent, reviewer_subagent],
    backend=StateBackend(),  # 用于草稿交换的共享文件系统
)
```

**共享文件系统**（`/drafts/current.md`）作为轮次间的状态交换介质——writer 写入，reviewer 读取。轮次控制来自提示词指令（"最多 3 轮"）。

### 方案 B：LangGraph 自定义工作流

提供确定性的循环控制，使用显式条件边：

```python
from langgraph.graph import StateGraph, START, END
from deepagents import create_deep_agent, CompiledSubAgent

class ReviewState(TypedDict):
    messages: list
    draft: str
    feedback: str
    iteration: int
    verdict: str

def writer_node(state):
    # LLM 根据 state["feedback"] 撰写或修订
    return {"draft": new_draft, "iteration": state["iteration"] + 1}

def reviewer_node(state):
    # LLM 评估 state["draft"]
    return {"feedback": review_text, "verdict": "ACCEPT" or "REVISE"}

def should_continue(state):
    if state["verdict"] == "ACCEPT" or state["iteration"] >= 3:
        return "end"
    return "writer"

workflow = StateGraph(ReviewState)
workflow.add_node("writer", writer_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_edge(START, "writer")
workflow.add_edge("writer", "reviewer")
workflow.add_conditional_edges("reviewer", should_continue, 
                               {"writer": "writer", "end": END})

# 将自定义工作流作为子代理嵌入 Deep Agent
review_cycle = CompiledSubAgent(
    name="writer-reviewer",
    description="通过迭代审核循环撰写内容",
    runnable=workflow.compile()
)
agent = create_deep_agent(model="claude-sonnet-4-6", subagents=[review_cycle])
```

方案 B 对最大迭代次数、路由逻辑和状态结构提供**精确控制**，同时仍能享受 Deep Agent 的规划、文件系统和上下文管理能力。

---

## 技能（Skills）、工具集成与 LLM 配置

**技能（Skills）** 遵循 `agentskills.io` 规范。每个技能是一个包含 YAML 前置内容（frontmatter）的 `SKILL.md` 文件，存储在 `.deepagents/skills/` 目录下：

```yaml
---
name: review-document
description: 审核文档的质量与合规性
version: 1.0.0
tags: [review, quality]
---
# 文档审核流程
审核文档时，请按照以下步骤操作...
```

SDK 使用**渐进式披露**机制：启动时仅加载 YAML 前置内容到系统提示词中。当 Agent 判断某个技能相关时，才按需加载完整内容，从而最大限度地减少 Token 消耗。

**外部工具**可以作为普通 Python 函数、`@tool` 装饰器函数或 `BaseTool` 实例集成。Tavily 网络搜索是典型示例：

```python
from tavily import TavilyClient
tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

def internet_search(query: str, max_results: int = 5):
    """执行网络搜索。"""
    return tavily.search(query, max_results=max_results)

agent = create_deep_agent(tools=[internet_search])
```

MCP（模型上下文协议）工具通过 `langchain-mcp-adapters` 支持，可与任何兼容 MCP 的工具服务器集成。

**LLM 配置**完全与供应商无关。`model` 参数接受 `"provider:model"` 格式字符串（通过 `init_chat_model()` 解析）或预构建的 `BaseChatModel` 实例。支持的供应商包括 Anthropic、OpenAI、Google（Gemini）、Azure OpenAI、AWS Bedrock、**OpenRouter**、Groq、Fireworks、Baseten、NVIDIA、Ollama、LiteLLM、HuggingFace 以及任何 LangChain 兼容的供应商。JS 版 SDK 文档明确列出了对 **Qwen 3.5**、**GLM-5**、**MiniMax M2.5** 和 **Kimi K2.5** 的支持。SDK 本身没有基于 YAML 的 Agent 配置——Agent 创建通过 Python 代码完成。但 **content-builder-agent 示例** 展示了从 `subagents.yaml` 文件加载子代理定义的模式，这是一种社区认可的 YAML 驱动配置方案。

---

## CLI 与 SDK 的区别

| 维度 | SDK（`pip install deepagents`） | CLI（`pip install deepagents-cli`） |
|------|------|-----|
| 接口 | Python 编程 API | 交互式终端 TUI（基于 Textual） |
| 主要用途 | 构建自定义 Agent 应用 | 终端编码代理（类似 Claude Code） |
| 可定制性 | 完全控制所有参数 | 通过命令行标志、AGENTS.md、技能配置 |
| 模型选择 | 代码中的 `model` 参数 | `/model` 命令、`--model` 标志、根据 API Key 自动检测 |
| 执行模式 | `invoke()`、`stream()`、异步 | 交互式、非交互式（`-n`）、无头模式、ACP 服务器（`--acp`） |
| 持久化 | 通过 checkpointer/store 手动配置 | 内置对话恢复、`/threads` 命令 |
| 附加功能 | 仅核心功能 | 网络搜索、远程沙箱、持久化记忆、LangSmith 追踪 |

CLI 构建在 SDK 之上——其 `create_cli_agent()` 函数调用 `create_deep_agent()` 并附加 CLI 特有的默认配置和中间件。

---

## LangGraph 深度集成

deepagents 与 LangGraph 的关系不是表面性的——**每个 Deep Agent 本质上就是一个 LangGraph 图**。`create_deep_agent()` 函数内部调用 `langchain.agents.create_agent()`，构建一个包含两个节点（`call_model` 和 `tool_executor`）的 `StateGraph`，通过条件边实现 ReAct 循环。这意味着：

- **检查点（Checkpointing）** 原生支持——传入 `MemorySaver()` 或 `PostgresSaver()` 即可启用对话持久化和时间旅行调试
- **流式输出** 支持多种模式：`stream_mode="values"` 返回完整状态，`stream_mode="updates"` 返回增量，以及 LLM 输出的 Token 级流式
- **LangGraph Studio** 可以可视化和调试任何 Deep Agent
- **人机协作（HITL）** 使用 LangGraph 的中断机制，在指定工具调用处暂停执行，等待人工审批后恢复
- **长期记忆** 利用 LangGraph 的 `InMemoryStore` 或 `PostgresStore`，通过 `CompositeBackend` 将 `/memories/` 路径路由到持久存储

`CompiledSubAgent` 抽象允许将**任何 LangGraph 图**嵌入为子代理，实现复杂组合：一个 Deep Agent 可以委派给自定义多步工作流、检索增强生成（RAG）管道，甚至另一个 Deep Agent。

---

## 仓库中的实用示例

仓库包含四个可运行的示例。**deep_research** 示例与 writer-reviewer 模式最相关——它实现了一个 5 步研究工作流，最多 3 个并发子代理和最多 3 轮迭代，简单查询委派给 1 个子代理，比较类查询每个元素 1 个子代理，多面向主题每个方面 1 个子代理。**content-builder-agent** 示例展示了 YAML 驱动的子代理加载、通过 AGENTS.md 记忆文件定义品牌语调、基于技能的内容生成（博客文章、社交媒体），以及使用 `FilesystemBackend` 进行真实磁盘操作。

生态系统更为广泛：**deep-agents-from-scratch** 提供 5 个渐进式教学 Notebook 讲解底层概念，**deepagentsjs** 是 TypeScript 移植版，**deep-agents-ui** 提供自定义 React 前端。第三方集成包括 **Langfuse**（可观测性）、**CopilotKit + AG-UI**（前端绑定）、**NVIDIA AI-Q Blueprint**（企业研究）和 **Harbor**（评估编排）。

---

## 总结

Deep Agents 在低层级的 LangGraph 图构建和完全不透明的 Agent 平台之间提供了务实的中间方案。其**中间件架构**是核心扩展机制——每项能力（规划、文件系统、子代理、摘要压缩）都是可插拔的中间件，自定义中间件可以注入工具、修改提示词或拦截 Agent 生命周期中的任何事件。

对于生产级 writer-reviewer 系统，**推荐的架构**是：简单场景使用编排器管理的委派（依赖提示词指令和共享文件系统状态），需要确定性迭代控制、显式状态管理和精确约束修订轮次的场景使用**包装 LangGraph 工作流的 CompiledSubAgent**。SDK 的**供应商无关模型配置**意味着系统中的不同 Agent 可以使用针对其角色优化的不同 LLM——编排器使用前沿模型、写作使用创造力强的模型、审核使用精确度高的模型——全部通过简单的 `"provider:model"` 字符串配置。
