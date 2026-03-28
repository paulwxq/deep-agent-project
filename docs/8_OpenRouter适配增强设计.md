# OpenRouter 适配增强设计

> **版本**: v1.1  
> **日期**: 2026-03-28  
> **状态**: 待审核  
> **目标**: 在**不破坏现有 provider 能力**的前提下，增强当前项目对 OpenRouter 的适配，使以下模型组合能够稳定运行当前 deepagents 工作流，并且在现有多 Agent 体系中保持工具调用、MCP/外部工具链访问、文件系统工具、subagent 调度链路可用：
>
> - `orchestrator/admin`: `anthropic/claude-sonnet-4.6`
> - `writer`: `google/gemini-3.1-pro-preview`
> - `reviewer1`: `anthropic/claude-sonnet-4.6`
> - `reviewer2`: `openai/gpt-5.3-codex`

---

## 1. 背景与结论

### 1.1 当前项目的 OpenRouter 接入现状

当前项目已经声明了 `openrouter` provider，并在 [src/model_factory.py](../src/model_factory.py) 中通过：

```python
model_name = f"openrouter:{agent_config.model}"
return init_chat_model(model_name, **kwargs)
```

来构造模型实例。

但结合代码检查与运行环境现状，这条链路目前并不能满足“稳定支持 OpenRouter 上的 Claude 4.6 / Gemini 3.1 / GPT-5.3-Codex”的目标，主要问题有：

1. **当前环境未安装 `langchain-openrouter`**  
   项目依赖中只有 `langchain-openai`、`langchain-anthropic`、`langchain-deepseek`，没有 `langchain-openrouter`。  
   对应文件：[pyproject.toml](../pyproject.toml)

   同时，根据验证结果，**不应额外安装官方 `openrouter` SDK**。  
   `langchain-openrouter==0.2.0` 自身已经包含内部 `OpenRouter` Pydantic 实现；若再安装官方 `openrouter` SDK，可能引入命名空间冲突与参数不兼容问题。

2. **`openrouter` 分支没有传递关键参数**  
   当前 `_create_openrouter(...)` 只处理了 `temperature` 和 `max_tokens`，没有透传：
   - `timeout`
   - `max_retries`
   - `reasoning`
    - `verbosity`
   - `app_title`
   - `app_url`
    - OpenRouter `openrouter_provider` 路由参数
    - `model_kwargs`
    - 自定义请求头

3. **当前兼容层只覆盖了字符串型 reasoning 回传，尚未为 OpenRouter 做“父类复用 + 历史回传”闭环**  
   项目已有 [src/reasoning_compat.py](../src/reasoning_compat.py)，但它当前主要处理：
   - `reasoning_content`
   - `reasoning`
   - `thought`

   没有完整处理 OpenRouter 官方文档重点要求保留的 `reasoning_details` 在多轮工具链中的回传闭环。

4. **GPT-5.3-Codex / GPT-5.4 的 `phase` 需要 Responses API 才能完整支持**  
   OpenRouter 的 GPT-5.4 迁移文档明确指出：`phase` 是 GPT-5.3 Codex / GPT-5.4 / GPT-5.4 Pro 在多轮 agentic workflow 中的重要元数据，而 **Chat Completions API 不支持 `phase`**，完整支持需要 **Responses API**。

### 1.2 本次设计的核心结论

本次设计不直接改动当前 `dashscope`、`anthropic_compatible`、`openai_compatible`、`deepseek` 的实现，而是：

1. **保留现有 provider 路由结构**
2. **仅增强 `openrouter` 分支**
3. **为 OpenRouter 单独引入 `langchain-openrouter` 依赖**
4. **新增基于 `ChatOpenRouter` 的 OpenRouter 专用兼容模型包装层**
5. **优先保证 Chat Completions 模式下的稳定 tool-calling**
6. **将 GPT-5.3-Codex / GPT-5.4 的 Responses API + `phase` 支持保留为后续扩展**

结论上，本次改造的目标不是“一步到位支持 OpenRouter 所有高级能力”，而是：

- 当前实现：**让目标四模型在当前 deepagents 架构中稳定跑通**
- 后续扩展：**在不影响当前稳定性的前提下，再补 Responses API / `phase` / 更完整 reasoning 语义**

---

## 2. 设计目标

### 2.1 本次必须达成

1. 当前项目使用 OpenRouter 时，不影响其他 provider 的既有行为
2. 目标四模型可以在当前 deepagents + LangGraph + 文件工具链下稳定运行
3. OpenRouter 模型在**工具调用场景**下具有更好的兼容性
4. OpenRouter 模型在当前项目的外部能力链路中保持可用，包括：
   - deepagents 内建文件工具：`ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`
   - 任务规划与子代理工具：`write_todos`、`task`
   - HIL 工具：`ask_user`、`confirm_continue`
   - MCP/外部工具链：Context7 MCP、Tavily web search
5. OpenRouter 适配需要兼容当前项目的多 Agent 编排方式：
   - orchestrator 调度 writer / reviewer1 / reviewer2
   - reviewer 先写 verdict，再输出审阅文本
   - writer 在初稿与修订模式下均可正常工作
6. OpenRouter 配置可以显式控制：
   - 是否启用 reasoning
   - 是否启用 Responses API
   - 是否启用 OpenRouter provider 路由偏好
7. 默认配置下应优先选择“稳定运行”而不是“开启所有高级特性”

### 2.2 明确不在本次范围

1. 不重写 deepagents 的主 Agent 执行框架
2. 不替换现有 minimax / bigmodel / deepseek / moonshot 接入逻辑
3. 不在本次强制启用 reasoning / thinking
4. 不在本次强制将全链路切换到 Responses API
5. 不修改业务提示词逻辑，只做 provider 适配增强

### 2.3 本次需求的验收口径

本次文档对应的代码改造在验收时，至少应满足以下口径：

1. 用 OpenRouter 配置替换四个 Agent 的模型后，系统能够成功启动并完成一轮完整流程
2. Writer、reviewer1、reviewer2 在执行任务时，能够正常调用文件工具和 Todo 工具
3. 启用 Context7 MCP 时，writer / reviewer 能正常调用 MCP 工具
4. 启用 Tavily 时，writer / reviewer 能正常调用 web search 工具
5. orchestrator 与 reviewer2 的链路中，不因 OpenRouter 适配而破坏已有的状态推进与 verdict 文件写入
6. 现有 minimax / bigmodel / deepseek / moonshot 配置不需要同步修改，且原有测试应继续通过

---

## 3. 官方依据

以下结论以 OpenRouter 官方文档为主。

### 3.1 OpenRouter 官方 LangChain 集成建议

OpenRouter 官方 LangChain 页面说明，OpenRouter 可通过 LangChain 使用，官方建议使用 `ChatOpenRouter` 集成包：

- OpenRouter LangChain 页面：  
  [https://openrouter.ai/docs/guides/community/langchain](https://openrouter.ai/docs/guides/community/langchain)

文档中明确提到：

- OpenRouter 与 LangChain 的官方建议集成形态是 `ChatOpenRouter`
- 支持流式、工具调用、结构化输出、reasoning、provider routing 等能力
- 安装方式是单独安装 `langchain-openrouter`

LangChain 官方 `ChatOpenRouter` 集成页也明确给出了同样的接法与安装方式：

- LangChain ChatOpenRouter 集成页：  
  [https://docs.langchain.com/oss/python/integrations/chat/openrouter](https://docs.langchain.com/oss/python/integrations/chat/openrouter)

### 3.2 OpenRouter 工具调用规范

OpenRouter 工具调用文档说明：

- `tools` 使用 OpenAI 兼容形状
- `tool_choice` 支持 `auto` / `none` / 指定函数
- `parallel_tool_calls` 默认为 `true`

文档：

- API Overview：  
  [https://openrouter.ai/docs/api/reference/overview](https://openrouter.ai/docs/api/reference/overview)
- Parameters：  
  [https://openrouter.ai/docs/api/reference/parameters](https://openrouter.ai/docs/api/reference/parameters)
- Responses API Tool Calling：  
  [https://openrouter.ai/docs/api/reference/responses/tool-calling](https://openrouter.ai/docs/api/reference/responses/tool-calling)

对本项目的直接影响：

1. 当前 deepagents 的工具循环仍然可以继续基于 OpenAI 风格 `tool_calls`
2. `tool_choice` 需要避免在 Claude thinking 场景下使用强制特定工具
3. 如需降低风险，可以在 OpenRouter provider 上显式关闭 `parallel_tool_calls`

### 3.3 OpenRouter 对 reasoning 的要求

OpenRouter 在 reasoning 文档与各模型 quickstart 页面中都强调：

- reasoning 模型在多轮 tool-calling 时，需要**保留完整 `reasoning_details`**
- 不能只保留普通文本摘要

文档：

- Reasoning Tokens：  
  [https://openrouter.ai/docs/guides/best-practices/reasoning-tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- Gemini 3.1 Pro Preview API：  
  [https://openrouter.ai/google/gemini-3.1-pro-preview/api](https://openrouter.ai/google/gemini-3.1-pro-preview/api)
- Claude Sonnet 4.6 API：  
  [https://openrouter.ai/anthropic/claude-sonnet-4.6/api](https://openrouter.ai/anthropic/claude-sonnet-4.6/api)
- GPT-5.3-Codex API：  
  [https://openrouter.ai/openai/gpt-5.3-codex/api](https://openrouter.ai/openai/gpt-5.3-codex/api)

对本项目的直接影响：

1. 当前 `reasoning_compat.py` 需要升级，不能只保留字符串 reasoning
2. 在当前实现中，默认应将 reasoning 关闭
3. reasoning 能力必须做成**显式开关**，而不是默认开启
4. 根据实测，`ChatOpenRouter` 已会把结构化 `reasoning_details` 写入 `AIMessage.additional_kwargs["reasoning_details"]`
5. 因此本项目更需要补的是 **history injection / 回传逻辑**，而不是重新实现一套父类响应提取逻辑

### 3.4 Claude 4.6 的 thinking 约束

OpenRouter 的 Claude 4.6 迁移指南指出：

- Claude 4.6 默认是 **adaptive thinking**
- `verbosity` 与 `reasoning` 是两个不同维度
- 若与 tool use 组合，需要遵守 Anthropic 的 thinking/tool 约束

文档：

- Claude 4.6 Migration Guide：  
  [https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/claude-4-6](https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/claude-4-6)

对本项目的直接影响：

1. Claude 4.6 默认不应直接开启 adaptive thinking
2. 如后续需要开启，应优先使用 OpenRouter `reasoning` 参数，而不是生造 Anthropic 原生 `thinking`
3. `verbosity` 可作为单独可选参数暴露

### 3.5 GPT-5.3-Codex / GPT-5.4 的 `phase`

OpenRouter 的 GPT-5.4 迁移指南指出：

- `phase` 对 GPT-5.3-Codex / GPT-5.4 / GPT-5.4 Pro 的多轮 agentic workflow 很重要
- **Responses API 支持 `phase`**
- **Chat Completions API 不支持 `phase`**

文档：

- GPT-5.4 Migration Guide：  
  [https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/gpt-5-4](https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/gpt-5-4)
- Responses API Tool Calling：  
  [https://openrouter.ai/docs/api/reference/responses/tool-calling](https://openrouter.ai/docs/api/reference/responses/tool-calling)

对本项目的直接影响：

1. 不能声称“当前 deepagents 链路下已经完整支持 GPT-5.3-Codex 的 phase”
2. 本次需要在设计上为 Responses API 留出扩展点
3. 当前实现中，GPT-5.3-Codex 以 **Chat Completions 兼容模式**先跑通 reviewer2 场景

### 3.6 OpenRouter 的 provider routing

OpenRouter 文档说明：

- 只要请求中包含 `tools`，**Auto Exacto 默认启用**
- 它会优先选择工具调用质量更高的 provider

文档：

- Auto Exacto：  
  [https://openrouter.ai/docs/guides/routing/auto-exacto](https://openrouter.ai/docs/guides/routing/auto-exacto)
- Exacto Variant：  
  [https://openrouter.ai/docs/guides/routing/model-variants/exacto](https://openrouter.ai/docs/guides/routing/model-variants/exacto)

对本项目的直接影响：

1. 当前项目即使不额外配置，也能从 Auto Exacto 受益
2. 但为了可控性，应允许通过配置向 `ChatOpenRouter(openrouter_provider=...)` 透传 provider routing 对象
3. 因为当前实现改为基于 `ChatOpenRouter`，所以应优先使用官方参数名 `openrouter_provider`，而不是继续沿用一个语义模糊的 `provider` 通用字段

### 3.7 `ChatOpenRouter` 的实测行为结论

基于项目外部验证脚本与 `langchain-openrouter==0.2.0` 的实测结果，本次实现额外采用以下事实前提：

1. `reasoning` 与 `openrouter_provider` 已是 `ChatOpenRouter` 的原生建模字段
2. `parallel_tool_calls` 不适合作为当前构造函数主传参方式，应优先在 `bind_tools(..., parallel_tool_calls=...)` 传递
3. `ChatOpenRouter` 已自动把结构化 `reasoning_details` 写入 `AIMessage.additional_kwargs["reasoning_details"]`
4. `phase` 仅存在于 Responses API；在当前 Chat Completions 路径下，原始响应中默认不会出现该字段
5. `langchain-openrouter==0.2.0` 与额外安装的官方 `openrouter` SDK 存在冲突风险，因此当前推荐仅保留 `langchain-openrouter`

---

## 4. 当前实现存在的问题

### 4.1 `openrouter` provider 依赖链不完整

当前 `_create_openrouter(...)` 依赖：

```python
from langchain.chat_models import init_chat_model
return init_chat_model(f"openrouter:{agent_config.model}", **kwargs)
```

问题在于：

1. 当前实现没有使用 OpenRouter 官方推荐的 `ChatOpenRouter` 集成
2. 本地未安装 `langchain-openrouter`
3. `init_chat_model("openrouter:...")` 过于黑盒，不利于在本项目中精确接管 `reasoning_details`、日志、参数归一化与 non-streaming 约束

### 4.2 OpenRouter 参数映射缺失

当前 `_create_openrouter(...)` 只处理：

- `temperature`
- `max_tokens`

缺少：

- `timeout`
- `max_retries`
- `reasoning`
- `verbosity`
 - `model_kwargs`
- `openrouter_provider`
- `parallel_tool_calls`
- `headers`
- `use_responses_api`

这会直接导致：

1. 配置文件无法完整表达 OpenRouter 官方参数
2. 迁移到 OpenRouter 后，模型行为不透明

### 4.2.1 当前实现存在不必要的全局环境副作用

当前 `src/model_factory.py` 的 OpenRouter 分支中存在：

```python
os.environ["OPENROUTER_API_KEY"] = api_key
```

这属于应当删除的副作用代码，原因如下：

1. 它会修改当前 Python 进程中的全局环境变量状态
2. 后续任何读取 `OPENROUTER_API_KEY` 的代码都会受到影响
3. 它与当前项目中其他 provider 的实现风格不一致
4. 模型构造函数不应承担“回写全局环境变量”的职责

本项目其他 provider 的一致做法是：

1. 在 `create_model(...)` 中统一读取 `.env` 对应的环境变量
2. 将读取到的 `api_key` 显式传给模型构造函数
3. 不在具体 provider 创建函数内部修改 `os.environ`

因此，本次 OpenRouter 新实现必须显式修复这一点：

1. 删除 `os.environ["OPENROUTER_API_KEY"] = api_key`
2. 保持 `api_key` 仅通过构造参数传递
3. 即使 `.env` 中已经存在 `OPENROUTER_API_KEY`，运行时也不再做二次写回

### 4.3 reasoning 兼容层不符合 OpenRouter 当前推荐

当前 [src/reasoning_compat.py](../src/reasoning_compat.py) 的设计更接近：

- DeepSeek / GLM / Kimi 一类字符串 reasoning 回传兼容

而不是：

- OpenRouter 的 `reasoning_details` 完整保留

所以如果在 OpenRouter 上开启 reasoning，当前链路有较高概率在工具循环中出现：

1. reasoning 元数据丢失
2. 第二次请求无法延续 reasoning 状态
3. 工具循环退化或报错

### 4.4 GPT-5.3-Codex 的 `phase` 暂未被当前项目承接

这是能力边界问题，不是单纯 bug：

1. 当前项目主链路是 `BaseChatModel` + deepagents 标准工具循环
2. 当前日志与补丁中没有 `phase` 的读取、存储、回传逻辑
3. 若直接以 “完整 GPT-5.3-Codex agent 模式” 为目标，会把本次改造范围放大到 Responses API 适配

因此本次必须明确区分：

- **稳定适配**
- **完整发挥 GPT-5.3-Codex / GPT-5.4 的 Responses API 能力**

### 4.5 需求里“工具调用 / MCP”必须被视为一等目标

本项目不是简单的“文本问答”应用，而是一个带有多层工具调用能力的 deepagents 系统。  
因此 OpenRouter 适配的真实目标不是“模型能返回文本”，而是：

1. 模型能在 subagent 内稳定进行工具调用
2. 模型能读取与写入工作目录中的关键文件
3. 模型能继续使用 Context7 MCP 与 Tavily 等外部工具
4. 模型在工具循环中不会因为 reasoning / thinking 元数据问题导致消息历史损坏

这也是为什么本次设计优先强调：

- 工具调用兼容
- 历史消息完整性
- reasoning 默认关闭
- Responses API 作为后续扩展能力

---

## 5. 改造原则

### 5.1 最小影响面

本次改造必须遵守：

1. 仅增强 `openrouter` 分支
2. 不修改现有 minimax / bigmodel / deepseek / moonshot 的构造逻辑
3. 不修改现有 agent prompt / middleware 业务行为

### 5.2 先稳定、后增强

本次优先级排序：

1. 工具调用稳定
2. 参数表达完整
3. reasoning 可控开关
4. Responses API 预留扩展
5. `phase` 完整支持放到后续扩展

### 5.3 配置显式化

对 OpenRouter 相关能力，全部通过显式参数控制，不走隐式推断：

- 是否启用 reasoning
- 是否启用 Responses API
- 是否透传 provider routing
- 是否关闭 parallel tool calls

---

## 6. 方案概述

### 6.1 总体方案

新增一个 **OpenRouter 专用模型包装层**，基于 `langchain-openrouter` 的 `ChatOpenRouter` 集成，并在其外层补充本项目需要的兼容与约束逻辑，形成专门用于 OpenRouter 的安全接入分支。

本次方案的当前实现目标：

1. 支持目标四模型在当前 deepagents 工作流下稳定运行
2. 默认使用 Chat Completions 兼容模式
3. 默认关闭 reasoning
4. 支持 OpenRouter 关键参数透传
5. 支持 OpenRouter `reasoning_details` 的 non-streaming 提取、存储与回传

### 6.2 为什么当前实现不直接切 Responses API

原因不是 OpenRouter 不支持，而是当前项目结构尚未为 Responses API 做专门适配：

1. deepagents 当前主链路仍主要面向标准 `AIMessage.tool_calls`
2. 现有 `PatchToolCallsMiddleware`、summarization、日志中间件都更接近 Chat Completions 语义
3. 一步切 Responses API，会扩大验证面，增加对其他 provider 的连带风险

因此本次设计结论：

- **先在 OpenRouter 上稳定跑 Chat Completions 风格工具链**
- **在代码结构上预留 Responses API 开关与扩展点**

---

## 7. 当前详细设计

### 7.1 新增 OpenRouter 专用包装类

新增文件建议：

- `src/openrouter_compat.py`

新增类建议：

- `ReasoningCompatibleChatOpenRouter`

职责：

1. 基于 `ChatOpenRouter` 构造 OpenRouter 请求
2. 统一设置 `base_url=https://openrouter.ai/api/v1`
3. 透传 OpenRouter 参数
4. 补齐 `reasoning_details` 的读取与回传
5. 为未来的 `phase` 支持预留字段

设计上应当遵守“**OpenRouter 独立实现、非 OpenRouter 保持原状**”的原则：

1. OpenRouter 走独立的 structured reasoning 代码分支
2. 现有 minimax / bigmodel / deepseek / moonshot / dashscope 继续走原有字符串 reasoning 或非 reasoning 路径
3. 不要求 OpenRouter 去兼容或复用当前 `_ReasoningPassthroughMixin` 的字符串注入模型
4. 仅可复用与 reasoning 数据结构无关的外围能力，例如：
   - tool history 清洗思路
   - provider metadata 标记方式
   - payload hook 的组织方式

### 7.2 `model_factory.py` 中的 OpenRouter 路由改造

当前：

- `_create_openrouter(...)` 直接走 `init_chat_model("openrouter:...")`

当前函数签名为：

```python
def _create_openrouter(
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
```

这个签名存在一个明确问题：

1. **拿不到 `provider_config`**
2. 因而无法读取：
   - `provider_config.base_url`
   - `provider_config.base_url_env`
   - 后续如需扩展的 OpenRouter provider 级配置

因此，本次代码改造必须把 `_create_openrouter(...)` 的签名调整为与其他 provider 创建函数一致的形态。

改造后：

- `_create_openrouter(...)` 改为实例化 `ReasoningCompatibleChatOpenRouter`

建议改为：

```python
def _create_openrouter(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
```

同时，`create_model(...)` 中的 `case "openrouter"` 分支也需要同步调整为：

```python
case "openrouter":
    return _create_openrouter(provider_config, agent_config, api_key, params)
```

这样才能让 OpenRouter 分支与现有：

- `_create_dashscope(...)`
- `_create_anthropic_compatible(...)`
- `_create_openai_compatible(...)`
- `_create_deepseek(...)`

保持一致的 provider 配置注入方式。

建议支持的参数：

| 参数 | 来源 | 说明 |
|------|------|------|
| `model` | `agent_config.model` | 使用完整 OpenRouter 模型名，如 `anthropic/claude-sonnet-4.6` |
| `api_key` | `OPENROUTER_API_KEY` | 必填 |
| `base_url` | provider config 或默认值 | 默认 `https://openrouter.ai/api/v1` |
| `temperature` | `params.temperature` | 可选 |
| `max_tokens` | `params.max_tokens` | 可选 |
| `max_retries` | `params.max_retries` | 可选 |
| `timeout` | `params.timeout` | 可选 |
| `reasoning` | `params.reasoning` | 可选，默认不启用 |
| `verbosity` | `params.verbosity` | 可选；当前并入 `model_kwargs` |
| `app_title` | `params.app_title` | 可选；映射到 `ChatOpenRouter(app_title=...)` |
| `app_url` | `params.app_url` | 可选；映射到 `ChatOpenRouter(app_url=...)` |
| `extra_body` | `params.extra_body` | 可选；仅作为配置层扩展字段，最终并入 `model_kwargs` |
| `openrouter_provider` | `params.openrouter_provider` | 可选，映射到 `ChatOpenRouter(openrouter_provider=...)` |
| `parallel_tool_calls` | `params.parallel_tool_calls` | 可选；优先在 `bind_tools(..., parallel_tool_calls=...)` 传递，必要时回退到 `model_kwargs` |
| `use_responses_api` | `params.use_responses_api` | 保留字段；当前实现显式读取，若为 `true` 则直接报错 |
| `output_version` | `params.output_version` | 保留字段；仅作为未来 Responses API 扩展预留 |

其中 `base_url` 的解析规则应明确为：

1. 若 `provider_config.base_url_env` 已配置且对应环境变量存在，则优先使用环境变量值
2. 否则若 `provider_config.base_url` 已配置，则使用该固定值
3. 若上述两者都未配置，则回退为 OpenRouter 默认值：
   `https://openrouter.ai/api/v1`

也就是说，`base_url` 不是仅由 `_create_openrouter(...)` 内部写死，而是一个**provider 级可配置项**，这也是本次必须修改函数签名的直接原因。

### 7.3 OpenRouter 参数映射策略

当前参数映射规则：

1. `reasoning`
   - 仅当显式传入时才发送
   - 优先作为 `ChatOpenRouter(reasoning=...)` 的显式参数传入
   - 默认不设置

2. `verbosity`
   - 作为当前 `ChatOpenRouter` 未显式建模的 OpenRouter 参数处理
   - 通过 `model_kwargs` 透传到请求层

3. `app_title` / `app_url`
   - 应直接映射到 `ChatOpenRouter(app_title=..., app_url=...)`
   - 不再使用旧 SDK 风格的 `x_title` / `http_referer`
   - 在代码实现中，禁止把 `x_title` 或 `http_referer` 放入 `model_kwargs`

4. `openrouter_provider`
   - 允许在配置中透传 OpenRouter provider preferences
   - 映射到 `ChatOpenRouter(openrouter_provider=...)`

5. `parallel_tool_calls`
   - 不应作为当前 `ChatOpenRouter` 构造函数的默认显式参数使用
   - 优先在 `bind_tools(..., parallel_tool_calls=...)` 环节传递
   - 仅当工具绑定链路无法覆盖时，才回退到 `model_kwargs`
   - 默认保持 OpenRouter 默认值
   - 对 Claude 4.6 / Gemini 3.1 可选设为 `false` 以降低复杂工具链风险

6. `extra_body`
   - 不作为 `ChatOpenRouter` 的原生构造参数假设
   - 若配置层保留 `extra_body`，实现时应把其视为项目侧扩展字段容器，并在进入模型前合并到 `model_kwargs`

### 7.4 reasoning 兼容增强

对 [src/reasoning_compat.py](../src/reasoning_compat.py) 做增强，但不改变现有其他 provider 的默认行为。

这里必须特别强调：

1. OpenRouter 的 `reasoning_details` 是 `list[dict]` 结构
2. 现有 `_ReasoningPassthroughMixin` 的核心假设是 reasoning 为字符串
3. 因此 **OpenRouter 不得通过设置不同的 `reasoning_field_name` 来复用现有字符串 mixin**
4. `ReasoningCompatibleChatOpenRouter` 必须拥有独立的提取与注入实现

也就是说，OpenRouter 这里不是“扩展现有 mixin”，而是“新增一条结构化 reasoning 专用分支”。

建议改造点：

1. `extract_reasoning_text(...)` 保留，继续兼容现有 DeepSeek / GLM / Moonshot
2. 新增：
   - `extract_reasoning_details(...)`
   - `inject_reasoning_details_into_payload(...)`
3. OpenRouter 模型优先回传：
   - `reasoning_details`
4. 若无 `reasoning_details`，再退化到：
   - `reasoning`
   - `reasoning_content`

实现约束需要进一步写明：

1. OpenRouter 的 `reasoning_details` 回传逻辑不依赖 `reasoning_field_name`
2. OpenRouter 的 payload 注入逻辑不能写成：

```python
payload_message[self.reasoning_field_name] = reasoning_text
```

3. `ReasoningCompatibleChatOpenRouter` 至少需要独立实现：
   - `_extract_reasoning_details_from_choice(...)`
   - `_inject_reasoning_details_into_payload(...)`
4. 若继续复用 `_ReasoningPassthroughMixin` 中的 `_inject_reasoning_into_payload(...)`，则会把结构化 `reasoning_details` 错误降级成字符串，这是禁止的
5. 实现时必须先检查 `ChatOpenRouter` 父类是否已经把原始 `reasoning_details` 写入 `AIMessage.additional_kwargs`
6. 若父类已经提供 `additional_kwargs["reasoning_details"]`，则优先复用父类结果，避免重复提取与重复注入
7. 仅当父类未保留结构化 `reasoning_details` 时，才由 `_OpenRouterReasoningDetailsMixin` 执行补提取与回填

这里再明确文件归属：

1. `extract_reasoning_details(...)` 与 `inject_reasoning_details_into_payload(...)` 定义在 [src/reasoning_compat.py](../src/reasoning_compat.py)
2. [src/openrouter_compat.py](../src/openrouter_compat.py) 中的 `ReasoningCompatibleChatOpenRouter` 负责调用这些 helper，并在 OpenRouter 独立分支中完成响应提取与请求注入

当前策略：

- **默认 reasoning 关闭**
- reasoning 支持做到“可安全开启”，但不作为默认行为

### 7.5 `phase` 的当前处理方式

本次不承诺完整 `phase` 支持，但代码结构上应满足：

1. 当前 Chat Completions 模式下，不应把 `phase` 视为可用字段，因为该字段属于 Responses API
2. 当前实现不依赖 `phase` 做业务逻辑判断
3. Responses API 开启后，再增加 `phase` 的提取、存储与回传逻辑
4. 当前代码中可以保留 `_extract_phase_from_response(...)` 之类的扩展占位，但不把其视为本次有效能力

这样做的好处是：

1. 当前就可以先让 `openai/gpt-5.3-codex` 跑通 reviewer2
2. 后续如要追求更完整的 agentic 能力，再补 `phase` 闭环

### 7.6 日志与调试增强

当前项目已经有较好的模型日志输出。针对 OpenRouter，建议新增：

1. 记录 `provider_name="openrouter"`
2. 记录 OpenRouter model slug
3. 记录是否显式配置了 `use_responses_api`
4. 若显式配置了 `use_responses_api=True`，记录“当前实现不支持 Responses API，并已拒绝该配置”
5. 若显式配置了 `use_responses_api=False`，记录“当前实现固定走 Chat Completions，不进入父类构造函数”
6. 若启用 reasoning：
   - 记录是否收到 `reasoning_details`
   - 记录是否成功回传 reasoning 元数据
7. 若未来切到 Responses API：
   - 记录 `phase` 的原始位置
   - 记录最终采用的来源字段，供后续 `phase` 闭环设计参考

---

## 8. 针对目标四模型的配置建议

### 8.1 推荐运行配置

```yaml
providers:
  openrouter:
    type: "openrouter"
    api_key_env: "OPENROUTER_API_KEY"
    base_url: "https://openrouter.ai/api/v1"

agents:
  orchestrator:
    provider: "openrouter"
    model: "anthropic/claude-sonnet-4.6"
    params:
      temperature: 0.2
      timeout: 240
      max_retries: 3

  writer:
    provider: "openrouter"
    model: "google/gemini-3.1-pro-preview"
    params:
      temperature: 0.2
      timeout: 600
      max_retries: 3

  reviewer1:
    provider: "openrouter"
    model: "anthropic/claude-sonnet-4.6"
    params:
      temperature: 0.2
      timeout: 300
      max_retries: 3

  reviewer2:
    provider: "openrouter"
    model: "openai/gpt-5.3-codex"
    params:
      temperature: 0.2
      timeout: 300
      max_retries: 3
```

如确实需要在 YAML 中保留该字段用于未来扩展，文档要求必须加注释并明确其当前无实际效果，例如：

```yaml
params:
  # 仅为未来 Responses API 扩展预留；当前实现若配置为 true 会直接报错
  use_responses_api: false
```

### 8.2 为什么这套配置先关闭 reasoning

原因很明确：

1. 你的项目之前已经出现过“thinking 开启后工具调用异常”
2. OpenRouter 官方要求 reasoning 模型在 tool-calling 中保留完整 `reasoning_details`
3. 当前项目主链路还没有为 OpenRouter 做完这层增强

因此，当前默认：

- **先保证 tool-calling 稳定**
- **不默认开启 reasoning**

### 8.3 对 `gpt-5.3-codex` 的边界说明

当前阶段，`openai/gpt-5.3-codex` 运行目标是：

- 在 reviewer2 场景中稳定完成审阅任务
- 正确使用工具
- 正常输出 verdict 与审阅结果

不把当前目标定义为：

- 充分发挥其 Responses API + `phase` 多阶段 agentic 优势

这样可以把风险控制在可验证范围内。

---

## 9. 代码改造点清单

### 9.1 新增文件

建议新增：

- `src/openrouter_compat.py`

### 9.2 修改文件

建议修改：

1. `src/model_factory.py`
   - 调整 `_create_openrouter(...)` 函数签名，增加 `provider_config: ProviderConfig`
   - 调整 `create_model(...)` 中 `case "openrouter"` 的调用方式
   - 删除 `os.environ["OPENROUTER_API_KEY"] = api_key` 这一全局副作用代码
   - 替换 `_create_openrouter(...)` 实现
   - 支持 OpenRouter 参数透传

2. `src/reasoning_compat.py`
    - 增加 OpenRouter `reasoning_details` 的历史回传兼容
    - 预留 `phase` 支持

3. `src/config_loader.py`
    - 新增 `_validate_openrouter_all_or_nothing(...)` 校验
    - 在配置加载阶段禁止 OpenRouter 与现有 provider 混用

4. `config/agents.yaml`
    - 保留现有 provider 不变
    - 可增加 OpenRouter 配置示例

5. `pyproject.toml`
    - 新增 `langchain-openrouter==0.2.0`
    - 保留现有 `langchain-openai`，继续服务非 OpenRouter provider
    - 如存在官方 `openrouter` SDK 依赖，则移除，避免与 `langchain-openrouter` 内部实现冲突

6. `.env.sample`
    - 如有需要，补充 OpenRouter 相关可选 header 环境变量说明

7. `tests/`
    - 新增 OpenRouter 适配单元测试
    - 增加 `verify_openrouter_params.py` 一类的验证脚本，用于确认 `ChatOpenRouter` 构造参数、`bind_tools` 参数与依赖版本兼容性

### 9.3 不应修改

以下内容本次不应修改：

1. `src/agent_factory.py` 的业务编排逻辑
2. Writer / Reviewer / Orchestrator prompt 文本
3. 现有 minimax / bigmodel / deepseek / moonshot 的构造逻辑

---

## 10. 测试设计

### 10.1 单元测试

需要新增以下测试：

1. `test_create_openrouter_model_basic`
   - 验证基本 OpenRouter 模型创建成功

2. `test_create_openrouter_model_maps_timeout_and_retries`
   - 验证 `timeout` / `max_retries` 被正确映射

3. `test_create_openrouter_model_maps_reasoning_and_verbosity`
    - 验证 OpenRouter 参数透传正确

4. `test_create_openrouter_model_maps_model_kwargs_extensions`
   - 验证 `verbosity` 与配置层 `extra_body` 最终被合并到 `model_kwargs`

5. `test_openrouter_bind_tools_passes_parallel_tool_calls`
   - 验证 `parallel_tool_calls` 优先在 `bind_tools(...)` 环节传递，并以请求体顶层字段发送

6. `test_reasoning_compat_preserves_reasoning_details`
    - 验证父类已保留的 `reasoning_details` 能被复用并正确回传

7. `test_use_responses_api_true_raises`
   - 验证 `use_responses_api=True` 会直接报错，而不是静默降级

8. `test_openrouter_chat_completions_has_no_phase`
   - 验证当前 Chat Completions 路径不期待 `phase` 字段

9. `test_openrouter_phase_extraction_placeholder_for_responses`
   - 验证 `phase` 提取逻辑仅作为 Responses API 扩展占位，不影响当前 Chat Completions 主路径

10. `test_other_providers_unchanged`
    - 验证 minimax / bigmodel / deepseek / moonshot 的既有构造路径未被破坏

### 10.2 集成级 smoke test

建议新增一个最小 smoke test 配置，仅验证模型对象构造与工具调用链路，不依赖真实线上 key：

1. 使用 mock transport / monkeypatch 拦截 OpenRouter 请求
2. 验证：
   - 工具调用请求体包含 `tools`
   - `parallel_tool_calls` 在工具绑定路径上正确生效，并以请求体顶层字段出现
   - assistant + tool + assistant 的消息序列保持完整
   - reasoning 关闭时不会注入额外字段
   - reasoning 开启时如有 `reasoning_details`，能够复用父类结果并保留
   - 当前 Chat Completions 响应中不期待 `phase`

### 10.3 真实 API 验证

代码合并前建议进行真实 OpenRouter smoke test，至少覆盖：

1. `anthropic/claude-sonnet-4.6`
2. `google/gemini-3.1-pro-preview`
3. `openai/gpt-5.3-codex`

验证内容：

1. 无 reasoning
2. 含工具调用
3. 至少跑一轮：
   - `read_file`
   - `write_file`
   - `edit_file`
   - `write_todos`

### 10.4 MCP 与外部工具链验证

由于本项目显式依赖 Context7 MCP 与 Tavily，本次 OpenRouter 适配测试还应补充：

1. Context7 启用时：
   - writer 至少成功调用一次 `resolve-library-id`
   - writer 或 reviewer 至少成功调用一次文档查询工具

2. Tavily 启用时：
   - writer 或 reviewer 至少成功调用一次 web search 工具

3. 验证重点：
   - OpenRouter 模型在调用 MCP / web 工具后，后续 assistant 轮次仍能继续
   - 工具结果注入消息历史后，不出现 dangling tool-call 或消息格式异常

---

## 11. 风险与回滚

### 11.1 主要风险

1. OpenRouter 上不同 provider 对工具调用的细节兼容度仍存在差异
2. `gpt-5.3-codex` 在 Chat Completions 模式下不具备完整 `phase` 优势
3. 一旦默认开启 reasoning，仍可能触发工具循环边缘问题
4. `langchain-openrouter` 与 `openrouter` SDK 版本组合可能存在兼容性问题，例如参数名从 `x_title` 到 `x_open_router_title` 的变化
5. 额外安装官方 `openrouter` SDK 可能与 `langchain-openrouter==0.2.0` 内部 `OpenRouter` 实现发生冲突

### 11.2 风险缓解

1. OpenRouter 当前默认关闭 reasoning
2. `use_responses_api=True` 时直接报错，避免静默降级；`false` 时只做记录，不传给 `ChatOpenRouter` 父类构造函数
3. 对 OpenRouter 新能力全部加测试
4. 对其他 provider 不改路由分支
5. 在安装依赖前先验证 `langchain-openrouter` 与 `openrouter` 的兼容版本组合，并将结果固定到 `pyproject.toml`
6. 当前优先策略是仅安装 `langchain-openrouter`，不额外安装官方 `openrouter` SDK

### 11.3 回滚策略

若 OpenRouter 新实现出现问题，回滚应足够简单：

1. 保留 `openrouter` 旧分支代码快照
2. 如上线后出现阻塞问题，可将 YAML 中所有启用的 OpenRouter agents 整体切回原有 provider 组合，不能与 OpenRouter 混用
3. 因为 minimax / bigmodel / deepseek / moonshot 不改，所以回滚范围局限于 OpenRouter 分支本身

---

## 12. 当前范围外的后续扩展

本节仅描述当前范围外的扩展方向，避免后续误以为本次已经完整覆盖。

### 12.1 Responses API 模式

后续应考虑在 OpenRouter provider 中增加：

- `api_mode: "chat_completions" | "responses"`

当设置为 `responses` 时：

1. 启用 `use_responses_api=True`
2. 配置 `output_version="responses/v1"`
3. 为 `phase`、`reasoning_details`、Responses 工具项做完整回传

### 12.1.1 依赖版本兼容性

在正式实现前，应先确认一组可运行的依赖组合，并写入 [pyproject.toml](../pyproject.toml)。

当前已知风险点：

1. `langchain-openrouter` 与 `openrouter` SDK 之间可能存在构造参数命名不兼容
2. 某些版本组合下会出现类似 `OpenRouter.__init__() got an unexpected keyword argument 'x_title'` 的实例化错误
3. `langchain-openrouter==0.2.0` 自带内部 `OpenRouter` 实现，若再安装官方 `openrouter` SDK，可能触发命名冲突和参数不匹配

因此当前建议是：

1. 当前优先采用 `langchain-openrouter==0.2.0`
2. 不额外安装官方 `openrouter` SDK
3. 优先采用版本 pinning，而不是运行时 monkey patch
4. 只有在无法找到稳定版本组合时，才把 monkey patch 作为兜底方案写入实现计划

### 12.2 GPT-5.4 / GPT-5.3-Codex 的 phase 闭环

后续需要实现：

1. assistant 输出项中的 `phase` 存储
2. 下一轮请求时原样回传
3. 为日志与 debug 增加 `phase` 可视化

### 12.3 推理模式灰度验证

后续若要启用：

- Claude 4.6 adaptive thinking
- Gemini 3.1 reasoning
- GPT-5.3-Codex reasoning

建议采用灰度方式：

1. 先 reviewer2
2. 再 reviewer1
3. 最后 writer

不建议一步到位全开。

---

## 13. 最终实施结论

本次 OpenRouter 改造的推荐实施方案如下：

1. **保留现有 provider 架构**
2. **仅增强 `openrouter` 分支**
3. **为 OpenRouter 单独引入 `langchain-openrouter`，并新增基于 `ChatOpenRouter` 的专用兼容包装层**
4. **当前默认使用 Chat Completions + reasoning 关闭**
5. **先确保 Claude 4.6 / Gemini 3.1 / GPT-5.3-Codex 在当前 deepagents 工作流中稳定运行**
6. **将 GPT-5.3-Codex / GPT-5.4 的 Responses API 与 `phase` 完整闭环保留为后续扩展，不纳入本次实现**

这样做的收益是：

1. 改动范围小
2. 不影响现有 minimax / bigmodel / deepseek / moonshot
3. 能尽快支撑你指定的四模型组合
4. 后续仍可继续向 OpenRouter 的高级特性演进

---

## 14. 参考资料

### OpenRouter 官方文档

- LangChain 集成：  
  [https://openrouter.ai/docs/guides/community/langchain](https://openrouter.ai/docs/guides/community/langchain)
- API 概览：  
  [https://openrouter.ai/docs/api/reference/overview](https://openrouter.ai/docs/api/reference/overview)
- Parameters：  
  [https://openrouter.ai/docs/api/reference/parameters](https://openrouter.ai/docs/api/reference/parameters)
- API Overview：  
  [https://openrouter.ai/docs/api/reference/overview](https://openrouter.ai/docs/api/reference/overview)
- Responses API Tool Calling：  
  [https://openrouter.ai/docs/api/reference/responses/tool-calling](https://openrouter.ai/docs/api/reference/responses/tool-calling)
- Reasoning Tokens：  
  [https://openrouter.ai/docs/guides/best-practices/reasoning-tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- Auto Exacto：  
  [https://openrouter.ai/docs/guides/routing/auto-exacto](https://openrouter.ai/docs/guides/routing/auto-exacto)
- Exacto Variant：  
  [https://openrouter.ai/docs/guides/routing/model-variants/exacto](https://openrouter.ai/docs/guides/routing/model-variants/exacto)
- Claude 4.6 Migration：  
  [https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/claude-4-6](https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/claude-4-6)
- GPT-5.4 Migration：  
  [https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/gpt-5-4](https://openrouter.ai/docs/guides/evaluate-and-optimize/model-migrations/gpt-5-4)

### 目标模型页面

- Claude Sonnet 4.6：  
  [https://openrouter.ai/anthropic/claude-sonnet-4.6](https://openrouter.ai/anthropic/claude-sonnet-4.6)  
  [https://openrouter.ai/anthropic/claude-sonnet-4.6/api](https://openrouter.ai/anthropic/claude-sonnet-4.6/api)
- Gemini 3.1 Pro Preview：  
  [https://openrouter.ai/google/gemini-3.1-pro-preview](https://openrouter.ai/google/gemini-3.1-pro-preview)  
  [https://openrouter.ai/google/gemini-3.1-pro-preview/api](https://openrouter.ai/google/gemini-3.1-pro-preview/api)
- GPT-5.3-Codex：  
  [https://openrouter.ai/openai/gpt-5.3-codex](https://openrouter.ai/openai/gpt-5.3-codex)  
  [https://openrouter.ai/openai/gpt-5.3-codex/api](https://openrouter.ai/openai/gpt-5.3-codex/api)

---

## 15. 补充约束：不支持 Streaming

本项目针对 OpenRouter 的适配，明确采用 **non-streaming** 策略，不实现也不支持 streaming 响应链路。

### 15.1 约束结论

1. 本项目当前 OpenRouter 适配实现不支持 streaming（此为实现层约束，非 OpenRouter 平台限制）
2. OpenRouter 当前版本若实现 `reasoning_details`，也只支持 non-streaming
3. 所有测试、日志与兼容层设计均以“完整响应对象”而非 chunk/delta 为基础

### 15.2 原因说明

1. 本项目的核心目标是多 Agent + 工具调用稳定性，而不是实时 token 级输出体验
2. streaming 只改变返回方式，不节省上下文，也不降低 token 消耗
3. streaming 会显著增加：
   - `tool_calls` chunk 拼装复杂度
   - `reasoning_details` 增量拼装复杂度
   - 异常恢复与调试复杂度

### 15.3 对实现范围的直接影响

若后续在 OpenRouter 分支中实现 `reasoning_details`，只需要处理完整响应中的：

1. `choices[].message.reasoning_details`
2. 或 Responses API 完整 output 中的 reasoning 项

不处理：

1. `delta.reasoning_details`
2. 任意 chunk 级 reasoning 拼装
3. 任意 streaming tool-call 增量状态管理

### 15.4 对代码设计的要求

1. OpenRouter 模型包装类默认关闭 streaming
2. OpenRouter 适配测试不覆盖 streaming 分支
3. 若未来有人提出 streaming 需求，应视为新的设计议题，不纳入本次方案默认范围

---

## 16. 设计修订：`reasoning_details` 纳入当前范围

根据审核意见，`reasoning_details` 直接纳入本次 OpenRouter 适配的当前设计范围。  
本修订的核心目的不是“默认开启 OpenRouter reasoning”，而是：

1. 消除“当前实现不支持 `reasoning_details` 时，OpenRouter 是否能稳定运行”的不确定性
2. 为 Claude 4.6 / Gemini 3.1 / GPT-5.3-Codex 提供完整的 non-streaming 结构化 reasoning 兼容能力
3. 在保持 OpenRouter reasoning 默认关闭的前提下，仍让代码具备保留与回传 `reasoning_details` 的能力

### 16.1 范围调整后的结论

本次设计范围现在包括：

1. OpenRouter 基础接入增强
2. OpenRouter 工具调用兼容
3. OpenRouter `reasoning_details` 的 **non-streaming 提取、存储、回传**

本次设计范围仍然不包括：

1. streaming `reasoning_details`
2. GPT-5.3-Codex / GPT-5.4 的完整 `phase` 闭环
3. 全链路默认开启 reasoning

### 16.2 为什么现在就做 `reasoning_details`

原因是：如果 OpenRouter 分支完全不支持 `reasoning_details`，那么对 reasoning-capable 模型的行为边界仍然是不清晰的，尤其是在多轮工具调用下。

具体来说：

1. OpenRouter 官方文档明确要求，在 reasoning + tools 场景中保留完整 `reasoning_details`
2. Claude、Gemini、OpenAI reasoning 模型都可能通过 OpenRouter 返回结构化 reasoning 信息
3. 即使当前配置默认关闭 reasoning，也应让 OpenRouter 分支具备“看到 structured reasoning 时不丢失、不破坏”的能力

因此，把 `reasoning_details` 放在当前范围，更符合“让 OpenRouter 适配真正可控”的目标。

### 16.3 设计原则：不复用 `reasoning_field_name`

`reasoning_details` 不能被建模成现有 `reasoning_field_name` 机制的一个字段名变体。

原因是：

1. 现有 `_ReasoningPassthroughMixin` 的核心假设是 reasoning 是字符串
2. `reasoning_details` 是结构化对象列表，不是字符串
3. 它需要独立的提取、存储、序列化与回传逻辑

因此，本次设计明确要求：

1. 保留现有字符串 reasoning 通道，继续服务于 DeepSeek / GLM / Moonshot 等现有 provider
2. 为 OpenRouter 新增一条**独立的 structured reasoning 通道**
3. 不通过给 `reasoning_field_name` 赋值 `"reasoning_details"` 的方式偷复用现有逻辑

### 16.4 建议的结构化设计

建议把当前 reasoning 兼容设计拆成两类能力：

1. **字符串 reasoning 通道**
   - 继续使用现有 `extract_reasoning_text(...)`
   - 继续面向 `reasoning_content` / `reasoning` / `thought`

2. **结构化 reasoning 通道**
   - 新增 `extract_reasoning_details(...)`
   - 新增 `inject_reasoning_details_into_payload(...)`
   - 面向 OpenRouter 的 `reasoning_details: list[dict]`

也就是说，`reasoning_details` 的实现应是“并列能力”，而不是“字段名替换”。

### 16.5 当前推荐的落地形态

对于 OpenRouter 分支，建议新增类似下面的专用能力：

1. `extract_reasoning_details(message: BaseMessage) -> list[dict]`
2. `store_reasoning_details(ai_message: AIMessage, details: list[dict])`
3. `inject_reasoning_details_into_payload(messages, payload) -> payload`

其中关键约束是：

1. 只处理 non-streaming 完整响应中的 `choices[].message.reasoning_details`
2. 原样保留对象列表，不转成纯文本摘要
3. 在下一轮 OpenRouter 请求中，将 `reasoning_details` 原样挂回 assistant message

### 16.6 与 OpenRouter reasoning 默认关闭并不冲突

“实现 `reasoning_details` 兼容”与“默认关闭 OpenRouter reasoning”并不矛盾。

推荐策略仍然是：

1. **默认配置**：OpenRouter reasoning 关闭
2. **代码能力**：具备 `reasoning_details` 的完整兼容路径

这样做的收益是：

1. 默认运行路径更稳
2. 一旦后续开启 reasoning，不需要再进行一次架构级改造
3. 即使某些模型在特定返回中附带 reasoning 结构，也不会把消息历史弄坏

### 16.7 对实现与测试的新增要求

既然 `reasoning_details` 纳入当前范围，那么测试应同步新增以下验证：

1. OpenRouter non-streaming 响应中包含 `reasoning_details` 时，能够成功提取
2. assistant message 中保存的 `reasoning_details` 在下一轮请求中被原样回传
3. `reasoning_details` 的存在不影响 `tool_calls` / `tool` message 链路
4. 现有 minimax / bigmodel / deepseek / moonshot 的字符串 reasoning 通道不受影响

### 16.8 修订后的最终边界

修订后，本次 OpenRouter 适配的边界如下：

1. 做 OpenRouter 基础接入增强
2. 做 OpenRouter 工具调用兼容
3. 做 OpenRouter `reasoning_details` 的 non-streaming 结构化兼容
4. 默认仍关闭 OpenRouter reasoning
5. 仍不实现 streaming
6. 仍不在本次完成 GPT-5.3-Codex / GPT-5.4 的完整 `phase` 闭环

---

## 17. 代码化设计细节

本节把当前设计进一步具体化到“实现接口级别”，目标是让后续代码改造不再依赖模糊理解。

### 17.1 文件改动清单

建议最终涉及以下文件：

1. 新增 [src/openrouter_compat.py](../src/openrouter_compat.py)
2. 修改 [src/model_factory.py](../src/model_factory.py)
3. 修改 [src/reasoning_compat.py](../src/reasoning_compat.py)
4. 修改 [src/config_loader.py](../src/config_loader.py)
   - 新增 `_validate_openrouter_all_or_nothing(...)`
5. 修改 [config/agents.yaml](../config/agents.yaml)
6. 修改 [pyproject.toml](../pyproject.toml)
7. 修改 [.env.sample](../.env.sample)
8. 新增或修改 `tests/` 下 OpenRouter 相关测试文件

### 17.2 `src/openrouter_compat.py` 的建议结构

建议新增以下常量、类型别名与类：

```python
from __future__ import annotations

from typing import Any

from langchain_openrouter import ChatOpenRouter

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
ReasoningDetails = list[dict[str, Any]]
```

建议新增主类：

```python
class ReasoningCompatibleChatOpenRouter(ChatOpenRouter):
    provider_name: str = "openrouter"
```

该类职责：

1. 作为 OpenRouter 的唯一模型包装入口
2. 统一接收 OpenRouter 的 provider 级配置与 agent 级参数
3. 复用父类已经提取好的 `reasoning_details`
4. 补齐 `reasoning_details` 的历史回传
5. 为未来 Responses API 场景预留 `phase` 提取扩展点
6. 明确保持 non-streaming

### 17.3 `ReasoningCompatibleChatOpenRouter` 的建议构造参数

建议构造函数最终支持以下字段：

```python
ReasoningCompatibleChatOpenRouter(
    model: str,
    api_key: str,
    base_url: str = OPENROUTER_DEFAULT_BASE_URL,
    streaming: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
    reasoning: dict[str, Any] | None = None,
    app_title: str | None = None,
    app_url: str | None = None,
    openrouter_provider: dict[str, Any] | None = None,
    parallel_tool_calls: bool | None = None,
    model_kwargs: dict[str, Any] | None = None,
    output_version: str | None = None,
    preserve_reasoning_details: bool = False,
)
```

其中：

1. `use_responses_api` 不应作为 `ReasoningCompatibleChatOpenRouter` 的父类构造参数透传
2. 若配置中出现 `use_responses_api=True`，建议在 `_create_openrouter(...)` 或配置校验阶段直接抛出明确错误，提示“当前版本尚不支持 Responses API”
3. 若配置中出现 `use_responses_api=False`，可以读取并记录，但不进入父类构造函数
4. `output_version` 同样只作为后续扩展保留字段，当前不进入父类构造函数
5. `preserve_reasoning_details` 表示是否在多轮消息中回传 `reasoning_details`
6. `app_title` / `app_url` 映射到 `ChatOpenRouter` 的官方字段，禁止退回到 `x_title` / `http_referer`
7. `openrouter_provider` 映射到 `ChatOpenRouter` 的官方 provider routing 参数
8. `parallel_tool_calls` 应优先在 `bind_tools(...)` 时传递；若工具绑定链路无法覆盖，再放入 `model_kwargs`
9. `streaming` 固定传 `False`，用于落实“本项目当前 OpenRouter 适配实现不支持 streaming”的实现约束
10. `model_kwargs` 是当前承接 `verbosity` 及其他未建模 OpenRouter 扩展参数的主通道，但不得包含 `x_title` / `http_referer`

### 17.4 `src/reasoning_compat.py` 建议新增的结构化 helper

建议保留现有字符串 helper，不删除：

```python
def extract_reasoning_text(message: BaseMessage) -> str:
    ...
```

同时新增以下结构化 helper：

```python
def extract_reasoning_details(message: BaseMessage) -> list[dict[str, Any]]:
    ...

def normalize_reasoning_details(value: Any) -> list[dict[str, Any]]:
    ...

def copy_reasoning_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ...
```

职责划分建议：

1. `extract_reasoning_details(...)`
   - 优先从 `AIMessage.additional_kwargs["reasoning_details"]` 读取父类已经保留的结构化数组
   - 仅作为兜底时，再从 `response_metadata` 或 content blocks 补取

2. `normalize_reasoning_details(...)`
   - 仅接受 `list[dict]`
   - 丢弃非 dict 项
   - 不做文本化转换

3. `copy_reasoning_details(...)`
   - 做防御性深拷贝
   - 避免原始对象在后续处理链中被原地修改

### 17.5 建议新增 codec 抽象，而不是复用 `reasoning_field_name`

当前文档已经明确，`reasoning_details` 不能继续复用字符串 field-name 机制。  
为避免实现者误入歧途，建议直接在代码层做显式拆分。

建议新增两个 codec：

```python
class StringReasoningCodec:
    field_names: tuple[str, ...] = ("reasoning_content", "reasoning", "thought")

    def extract_from_message(self, message: BaseMessage) -> str: ...
    def inject_into_payload(self, messages: Sequence[BaseMessage], payload: dict[str, Any]) -> dict[str, Any]: ...


class StructuredReasoningDetailsCodec:
    field_name: str = "reasoning_details"

    def extract_from_message(self, message: BaseMessage) -> list[dict[str, Any]]: ...
    def inject_into_payload(self, messages: Sequence[BaseMessage], payload: dict[str, Any]) -> dict[str, Any]: ...
```

当前范围内的使用建议：

1. 现有 DeepSeek / GLM / Moonshot 继续使用 `StringReasoningCodec`
2. OpenRouter 新分支使用 `StructuredReasoningDetailsCodec`
3. 两者并列存在，不互相替代

### 17.6 `src/reasoning_compat.py` 中建议新增的 mixin

建议保留现有 `_ReasoningPassthroughMixin` 给字符串 reasoning provider 使用。  
同时新增一个 OpenRouter 专用 mixin：

```python
class _OpenRouterReasoningDetailsMixin:
    preserve_reasoning_details: bool = False

    def _extract_reasoning_details_from_choice(self, choice: Any) -> list[dict[str, Any]]: ...
    def _extract_reasoning_details_from_message(self, message: Any) -> list[dict[str, Any]]: ...
    def _inject_reasoning_details_into_payload(
        self,
        messages: Sequence[BaseMessage],
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...
```

设计要求：

1. 这个 mixin 只服务 OpenRouter
2. 不处理 streaming delta
3. 只处理 non-streaming `choices[].message.reasoning_details`
4. 不把 `reasoning_details` 降级成字符串
5. 它与现有 `_ReasoningPassthroughMixin` 是**并列关系**，不是子类扩展关系
6. 在 mixin 接管前，先检查 `ChatOpenRouter` 父类结果中是否已经存在 `additional_kwargs["reasoning_details"]`
7. 若父类已保留结构化 reasoning，则 mixin 应复用父类结果，而不是重复覆盖
8. mixin 的主要职责是“回传（Injection）”而不是重新实现父类已经完成的“提取（Extraction）”
9. `_sanitize_tool_messages(...)` 不属于该 mixin 的职责范围，应由 `ReasoningCompatibleChatOpenRouter` 自身定义

### 17.7 OpenRouter 模型类的推荐继承结构

推荐继承关系：

```python
class ReasoningCompatibleChatOpenRouter(
    _OpenRouterReasoningDetailsMixin,
    ChatOpenRouter,
):
    ...
```

不建议：

```python
class ReasoningCompatibleChatOpenRouter(_ReasoningPassthroughMixin, ChatOpenRouter):
    ...
```

原因：

1. `_ReasoningPassthroughMixin` 是字符串 reasoning 设计
2. OpenRouter `reasoning_details` 是结构化数组
3. 二者共用同一个主通道会导致实现概念混乱
4. 更重要的是，这会让 OpenRouter 的独立代码分支重新与现有非 OpenRouter provider 混在一起，不符合本次“OpenRouter 单独一条线”的需求

### 17.8 OpenRouter 请求体构造建议

在 `ReasoningCompatibleChatOpenRouter` 中，建议通过 `_get_request_payload(...)` 统一处理 OpenRouter 特有逻辑。

此外，针对工具绑定，建议在包装类中显式覆盖或包装 `bind_tools(...)`，使 `parallel_tool_calls` 优先在工具绑定阶段生效。

这里需要特别说明：`_sanitize_tool_messages(...)` **不来自** `_OpenRouterReasoningDetailsMixin`。  
该方法应由 `ReasoningCompatibleChatOpenRouter` 自身定义，逻辑可参考现有 `_ReasoningPassthroughMixin._sanitize_tool_messages(...)`，但不要通过继承 `_ReasoningPassthroughMixin` 来获得它。

建议顺序：

```python
def _get_request_payload(...):
    payload = super()._get_request_payload(...)
    payload = self._inject_reasoning_details_into_payload(messages, payload)
    payload = self._sanitize_tool_messages(payload)
    payload = self._inject_openrouter_extra_options(payload)
    return payload
```

```python
def bind_tools(self, tools, **kwargs):
    if self.parallel_tool_calls is not None and "parallel_tool_calls" not in kwargs:
        kwargs["parallel_tool_calls"] = self.parallel_tool_calls
    return super().bind_tools(tools, **kwargs)
```

```python
def _sanitize_tool_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
    ...
```

其中建议新增：

```python
def _inject_openrouter_extra_options(self, payload: dict[str, Any]) -> dict[str, Any]:
    ...

def _extract_phase_from_response(self, response: dict | Any) -> str | None:
    ...
```

负责整理以下字段的最终去向：

1. `verbosity` 与其他未建模扩展字段并入 `model_kwargs`
2. `parallel_tool_calls` 优先在 `bind_tools(...)` 处理
3. 只有在 `bind_tools(...)` 无法覆盖时，才考虑把 `parallel_tool_calls` 作为兜底扩展字段处理

若底层 `ChatOpenRouter` 已通过显式参数、`model_kwargs` 或 `bind_tools(...)` 承接这些字段，则该 helper 只负责整理与归一化，避免重复注入。

### 17.9 OpenRouter 响应读取建议

在 `ReasoningCompatibleChatOpenRouter._create_chat_result(...)` 中建议追加：

```python
def _create_chat_result(self, response: dict | Any, generation_info: dict | None = None) -> ChatResult:
    result = super()._create_chat_result(response, generation_info)
    details = result.generations[0].message.additional_kwargs.get("reasoning_details")
    if not details:
        details = self._extract_reasoning_details_from_choice(...)
    if details:
        result.generations[0].message.additional_kwargs["reasoning_details"] = details
    return result
```

约束：

1. 只往 `additional_kwargs["reasoning_details"]` 中放结构化列表
2. 不做字符串化摘要
3. 如需日志展示，可额外写入 `response_metadata` 标记，但不替代原始结构
4. 优先复用 `ChatOpenRouter` 父类已保留的字段，只有在父类未保留时才做补提取
5. `_extract_phase_from_response(...)` 可以作为 Responses API 扩展点保留，但当前 Chat Completions 主路径不依赖它

### 17.10 `model_factory.py` 的推荐代码形态

建议修改导入：

```python
from src.openrouter_compat import ReasoningCompatibleChatOpenRouter
```

建议修改分发：

```python
case "openrouter":
    return _create_openrouter(provider_config, agent_config, api_key, params)
```

建议的新函数签名：

```python
def _create_openrouter(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    ...
```

建议的 base_url 解析 helper：

```python
def _resolve_base_url(
    provider_config: ProviderConfig,
    default: str,
) -> str:
    ...
```

优先级：

1. `provider_config.base_url_env`
2. `provider_config.base_url`
3. `OPENROUTER_DEFAULT_BASE_URL`

### 17.11 `_create_openrouter(...)` 的推荐参数映射

建议该函数内部显式整理如下字段：

```python
model_kwargs = dict(params.get("extra_body", {}))
if "verbosity" in params:
    model_kwargs["verbosity"] = params["verbosity"]
if "x_title" in model_kwargs or "http_referer" in model_kwargs:
    raise ValueError("Use app_title/app_url instead of x_title/http_referer.")
openrouter_provider = params.get("openrouter_provider")
parallel_tool_calls = params.get("parallel_tool_calls")
use_responses_api = params.get("use_responses_api")
```

之后统一实例化：

```python
if use_responses_api is True:
    raise NotImplementedError(
        "OpenRouter Responses API is not supported in the current implementation."
    )

return ReasoningCompatibleChatOpenRouter(
    model=agent_config.model,
    api_key=api_key,
    base_url=base_url,
    streaming=False,
    temperature=params.get("temperature"),
    max_tokens=params.get("max_tokens"),
    max_retries=params.get("max_retries"),
    timeout=params.get("timeout"),
    reasoning=params.get("reasoning"),
    app_title=params.get("app_title"),
    app_url=params.get("app_url"),
    openrouter_provider=openrouter_provider,
    parallel_tool_calls=parallel_tool_calls,
    preserve_reasoning_details=params.get("preserve_reasoning_details", False),
    model_kwargs=model_kwargs or None,
)
```

并明确：

1. 不再写 `os.environ["OPENROUTER_API_KEY"] = api_key`
2. 不依赖全局环境变量回写
3. `use_responses_api=True` 时，不做静默降级，而是直接报错
4. `use_responses_api=False` 时，可以记录日志，但不传给 `ReasoningCompatibleChatOpenRouter(...)/ChatOpenRouter(...)`
5. `parallel_tool_calls` 不应假设构造函数原生支持；实现时应优先在 `bind_tools(...)` 传递，必要时再回退到 `model_kwargs`
6. 配置层 `extra_body` 只作为项目侧扩展参数容器，进入模型前统一并入 `model_kwargs`
7. `app_title` / `app_url` 直接使用 `ChatOpenRouter` 官方命名，不允许在任何实现层继续出现 `x_title` / `http_referer`
8. `streaming` 在本次实现中固定传 `False`
9. `output_version` 若出现在 `params` 中，当前实现同样只读取并记录，不进入父类构造函数

### 17.12 OpenRouter 配置建议写法

建议在 YAML 中支持：

```yaml
providers:
  openrouter:
    type: "openrouter"
    api_key_env: "OPENROUTER_API_KEY"
    base_url: "https://openrouter.ai/api/v1"

agents:
  writer:
    provider: "openrouter"
    model: "google/gemini-3.1-pro-preview"
    params:
      temperature: 0.2
      timeout: 600
      max_retries: 3
      app_title: "Deep Agent Project"
      preserve_reasoning_details: true
      reasoning:
        effort: "medium"
```

说明：

1. `preserve_reasoning_details: true` 可以开启结构化回传能力
2. `reasoning` 是否真正发送，由业务配置决定
3. 如需控制 OpenRouter provider routing，应使用 `openrouter_provider`
4. `use_responses_api` 不建议出现在当前 YAML 样例中；若保留，仅作为未来扩展占位
5. 当前推荐默认仍然是**不配置 `reasoning`**
6. 如需传递 `verbosity` 或其他未建模 OpenRouter 扩展项，当前设计建议放在配置层 `extra_body`，实现时统一并入 `model_kwargs`
7. 如需传递应用标识，统一使用 `app_title` / `app_url`，不要使用 `x_title` / `http_referer`

### 17.13 测试文件建议

建议新增以下测试文件：

1. `tests/test_openrouter_model_factory.py`
2. `tests/test_openrouter_reasoning_details.py`

建议覆盖的测试函数：

```python
def test_create_openrouter_uses_provider_config_base_url(): ...
def test_create_openrouter_does_not_mutate_os_environ(): ...
def test_openrouter_maps_extra_body_reasoning_verbosity_provider(): ...
def test_extract_reasoning_details_from_ai_message(): ...
def test_inject_reasoning_details_into_payload(): ...
def test_openrouter_reasoning_details_preserved_with_tool_history(): ...
def test_non_openrouter_providers_do_not_use_structured_reasoning_codec(): ...
```

### 17.14 与 deepagents middleware 的边界

为了降低侵入性，本次设计建议：

1. 不修改 deepagents 自带的 `PatchToolCallsMiddleware`
2. 不修改 deepagents 自带的 summarization 中间件行为
3. OpenRouter `reasoning_details` 兼容优先在模型层闭环

需要明确的工程约束是：

1. `reasoning_details` 仅作为 assistant message 的附加元数据保留
2. 不让 deepagents 中间件理解或操作其内部结构
3. 若后续发现 summarization 会破坏这部分元数据，再作为单独议题处理

### 17.15 当前推荐实施顺序

建议按以下顺序实现，而不是并行混改：

1. 改 `model_factory.py`
   - 修复签名
   - 去掉环境变量副作用
   - 接入新 OpenRouter 模型类

2. 加 `src/openrouter_compat.py`
   - 先完成基础模型构造
   - 再补 payload 注入
   - 再补响应读取

3. 改 `src/reasoning_compat.py`
   - 新增 structured reasoning helper / codec / mixin
   - 保持旧字符串通道不动

4. 加测试
   - 先单元测试
   - 再 mock 请求 smoke test
   - 最后真实 API smoke test

---

## 18. 补充约束：OpenRouter 不允许与现有 Provider 混用

根据当前需求，OpenRouter 在本项目中的定位不是“再新增一个可自由混搭的 provider”，而是一种**统一运行模式**。

### 18.1 业务约束

只要任一启用中的 agent 选择了：

```yaml
provider: "openrouter"
```

则所有启用中的 agent 都必须同时选择：

```yaml
provider: "openrouter"
```

允许：

1. 4 个 agent 使用不同的 OpenRouter 模型 slug
2. 4 个 agent 共用同一个 `OPENROUTER_API_KEY`
3. 4 个 agent 通过同一套 OpenRouter 代码分支运行

不允许：

1. orchestrator 用 `openrouter`，writer 用 `minimax`
2. writer 用 `openrouter`，reviewer1 用 `bigmodel`
3. reviewer2 用 `openrouter`，其余 agent 用 `deepseek`

### 18.2 为什么必须做全量切换约束

原因如下：

1. 当前需求本身就是“切到 OpenRouter 方案”，而不是“混搭 provider”
2. OpenRouter 分支将引入独立的：
   - payload 组织方式
   - `reasoning_details` 保留与回传逻辑
   - OpenRouter 参数映射逻辑
3. 若允许混用，会显著增加：
   - 工具调用差异分析成本
   - reasoning 语义差异
   - 调试复杂度

因此，从设计上应把 OpenRouter 视为一套独立运行模式，而不是一个可任意拼接的 provider。

### 18.3 与“不要影响现有非 OpenRouter 代码”的关系

这条约束**不会影响现有非 OpenRouter 模式**，因为它只在以下条件下触发：

1. 至少一个启用中的 agent 使用了 `provider: openrouter`

若全部启用中的 agent 都不是 `openrouter`，则：

1. 当前 minimax / bigmodel / deepseek / moonshot / dashscope 等配置继续保持原样
2. 不新增任何额外限制
3. 现有非 OpenRouter 运行模式应继续正常工作

### 18.4 `config_loader.py` 的推荐校验设计

建议在 [src/config_loader.py](../src/config_loader.py) 中新增专用 helper：

```python
def _validate_openrouter_all_or_nothing(
    agents: dict[str, AgentModelConfig],
) -> None:
    enabled_agents = {
        name: cfg
        for name, cfg in agents.items()
        if cfg.enabled
    }

    openrouter_agents = {
        name
        for name, cfg in enabled_agents.items()
        if cfg.provider == "openrouter"
    }

    if openrouter_agents and len(openrouter_agents) != len(enabled_agents):
        raise ConfigError(
            "检测到 OpenRouter 与其他 provider 混用。当前项目要求："
            "只要任一启用中的 Agent 使用 openrouter，则所有启用中的 Agent 都必须使用 openrouter。"
        )
```

建议调用时机：

1. 在所有必需 agent 存在性校验之后
2. 在 `enabled` 状态已经解析完成之后
3. 在 reviewer2 可选启用逻辑已经生效之后

### 18.5 推荐的配置示例应体现全量切换

OpenRouter 配置示例不应只写单个 agent，而应明确展示 4 个 agent 全部走 OpenRouter：

```yaml
providers:
  openrouter:
    type: "openrouter"
    api_key_env: "OPENROUTER_API_KEY"
    base_url: "https://openrouter.ai/api/v1"

agents:
  orchestrator:
    provider: "openrouter"
    model: "anthropic/claude-sonnet-4.6"

  writer:
    provider: "openrouter"
    model: "google/gemini-3.1-pro-preview"

  reviewer1:
    provider: "openrouter"
    model: "anthropic/claude-sonnet-4.6"

  reviewer2:
    provider: "openrouter"
    model: "openai/gpt-5.3-codex"
```

### 18.6 需要新增的测试点

建议新增至少两个测试：

```python
def test_openrouter_all_or_nothing_validation() -> None: ...
def test_non_openrouter_configs_are_not_affected_by_all_or_nothing_rule() -> None: ...
```

验证目标：

1. 只要有一个 agent 使用 openrouter，而其他 agent 没有全部跟随，则配置加载直接失败
2. 当所有 agent 都不是 openrouter 时，现有配置行为完全不变
