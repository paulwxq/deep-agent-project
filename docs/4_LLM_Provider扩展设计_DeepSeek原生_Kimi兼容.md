# LLM Provider 扩展设计：DeepSeek 原生接入 + Kimi OpenAI 兼容接入

> **版本**: v1.0  
> **日期**: 2026-03-24  
> **状态**: 待审核  
> **目标**: 在当前 deep-agent-project 中新增 DeepSeek 与 Kimi 的模型接入能力，其中：
>
> - **DeepSeek**：新增 LangChain 原生 provider 接入
> - **Kimi**：使用 OpenAI 兼容模式接入

---

## 1. 背景与结论

### 1.1 当前项目的模型接入方式

当前项目并不是“直接通过 LangChain Agent 来生成整个 Agent 系统”，而是采用三层结构：

1. **Agent 编排层**：`deepagents.create_deep_agent(...)`
2. **状态管理层**：LangGraph
3. **模型接入层**：LangChain `BaseChatModel`

对应代码位置：

- 编排入口：[agent_factory.py](src/agent_factory.py)
- 模型工厂：[model_factory.py](src/model_factory.py)

因此，本次“新增 LLM provider”的核心改造点，不在 Orchestrator / Writer / Reviewer 的业务逻辑，而在：

- provider 配置
- 模型工厂路由
- 环境变量
- 单元测试

### 1.2 当前已支持的 provider

当前 `src/model_factory.py` 已支持以下 provider 类型：

- `dashscope`
- `anthropic_compatible`
- `openai_compatible`
- `openrouter`

对应路由代码见 [model_factory.py](src/model_factory.py#L35)。

### 1.3 本次接入策略

本次接入采用以下策略：

1. **DeepSeek**
   - 新增独立 provider type：`deepseek`
   - 使用 LangChain 原生集成包 `langchain-deepseek`
   - 对应模型类：`ChatDeepSeek`

2. **Kimi**
   - 不新增独立 provider type
   - 继续复用现有 `openai_compatible`
   - 使用 `langchain-openai` 的 `ChatOpenAI(base_url=..., api_key=...)`

### 1.4 为什么 DeepSeek 不走兼容模式

在 LangChain 已存在原生集成的前提下，DeepSeek 继续走 OpenAI 兼容模式并非最佳选择，原因如下：

1. 原生 provider 语义更清晰，配置与日志中可以明确区分 “DeepSeek” 与 “任意 OpenAI 兼容厂商”
2. LangChain 官方明确提供了 `ChatDeepSeek` 与独立 provider 包 `langchain-deepseek`
3. 官方 provider 往往能更好地跟进该厂商的特性、返回字段和后续能力扩展
4. 当前项目已经采用“能原生则原生、不能原生则兼容”的思路：
   - DashScope 走原生 `ChatQwen`
   - OpenRouter 走专门接入
   - DeepSeek 采用原生 provider 更一致

### 1.5 为什么 Kimi 仍采用兼容模式

尽管 LangChain 社区中存在 Moonshot 相关集成页面，但本项目本次仍建议 Kimi 使用 OpenAI 兼容模式，原因如下：

1. **Kimi 官方文档明确支持 OpenAI 兼容模式**
2. 当前项目已经有成熟稳定的 `openai_compatible` 接入链路
3. 对 Kimi 而言，兼容模式接入改动最小、依赖最少、与当前代码最一致
4. 本次目标是尽快稳定接入 Kimi 2.5，而不是同时引入新的 Moonshot 专用集成分支

结论：

- **DeepSeek：新增原生 provider**
- **Kimi：复用现有 OpenAI 兼容 provider**

---

## 2. 官方依据

### 2.1 DeepSeek

- LangChain 官方 DeepSeek Provider 页面：  
  [DeepSeek integrations](https://docs.langchain.com/oss/python/integrations/providers/deepseek)
- LangChain 官方 `ChatDeepSeek` 页面：  
  [ChatDeepSeek integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek)
- DeepSeek 官方文档：  
  [DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/)

从上述资料可确认：

- LangChain 对 DeepSeek 有**原生 provider**
- 需要安装依赖：`langchain-deepseek`

### 2.2 Kimi

- Moonshot 官方快速开始：  
  [Kimi K2.5 Quickstart](https://platform.moonshot.cn/docs/guide/kimi-k2-5-quickstart)
- Moonshot 官方博客 Quick Start：  
  [Moonshot Quick Start Guide](https://platform.moonshot.cn/blog/posts/kimi-api-quick-start-guide)

从官方资料可确认：

- Kimi 官方支持 **OpenAI 兼容模式**
- 推荐接入地址为 `https://api.moonshot.cn/v1`

---

## 3. 需求说明

### 3.1 新增能力

本次需要新增以下能力：

1. 配置层可声明 DeepSeek provider
2. 模型工厂可创建 `ChatDeepSeek`
3. 配置层可声明 Kimi provider
4. Kimi 使用现有 `openai_compatible` 路由
5. `.env.sample` 提供新环境变量示例
6. 单元测试覆盖新 provider 的配置加载与模型工厂行为

### 3.2 不在本次范围内

以下内容本次不改：

- Orchestrator / Writer / Reviewer 提示词
- HIL 工具逻辑
- 业务流程编排逻辑
- 文档生成逻辑

---

## 4. 依赖改动

### 4.1 新增依赖

需要新增以下依赖：

```text
langchain-deepseek>=1.0.1
```

### 4.2 安装方式

建议使用项目现有的 `uv` 工作流：

```bash
uv add "langchain-deepseek>=1.0.1"
```

### 4.3 是否需要新增 Kimi 依赖

**不需要。**

原因：

- Kimi 复用现有 `openai_compatible`
- 当前项目已经依赖 `langchain-openai`

对应现有依赖见 [pyproject.toml](pyproject.toml#L7)。

### 4.4 `pyproject.toml` 需要修改的内容

在 dependencies 中新增：

```toml
"langchain-deepseek>=1.0.1",
```

修改后示意：

```toml
dependencies = [
    "deepagents>=0.4.11",
    "langchain>=1.2.0",
    "langgraph>=1.1.3",
    "langchain-qwq>=0.3.4",
    "langchain-openai>=1.0.0",
    "langchain-anthropic>=0.3.0",
    "langchain-deepseek>=1.0.1",
    "pyyaml>=6.0",
    "tavily-python>=0.5.0",
    "python-dotenv>=1.0.0",
]
```

> **注意**: 根据当前已发布的 `langchain-deepseek 1.0.1` PyPI 元数据，其依赖约束为 `langchain-openai>=1.0.0,<2.0.0`。因此本文建议同时将项目中的 `langchain-openai` 下限收紧为 `>=1.0.0`，避免文档示例与真实依赖关系不一致。

---

## 5. 配置文件改动

### 5.1 `config/agents.yaml` 的 provider 新增项

建议新增两个 provider：

```yaml
providers:
  deepseek:
    type: "deepseek"
    api_key_env: "DEEPSEEK_API_KEY"

  moonshot:
    type: "openai_compatible"
    base_url: "https://api.moonshot.cn/v1"
    api_key_env: "MOONSHOT_API_KEY"
```

说明：

- `deepseek` 使用新的原生 provider type
- `moonshot` 不新增新 type，直接复用 `openai_compatible`

### 5.2 Agent 使用方式示例

例如：

```yaml
agents:
  orchestrator:
    provider: "deepseek"
    model: "deepseek-chat"
    params:
      temperature: 0.3
      max_tokens: 8192
      max_retries: 6
      timeout: 120

  writer:
    provider: "moonshot"
    model: "kimi-k2.5"
    params:
      temperature: 0.6
      max_tokens: 16384
      max_retries: 6
      timeout: 180
```

说明：

- DeepSeek 常用模型名可使用 `deepseek-chat` 或 `deepseek-reasoner`
- 但若使用 `deepseek-reasoner`，落地前需先验证 `langchain-deepseek` / `ChatDeepSeek` 在当前项目中的工具调用兼容性
- Kimi 模型名应以 Moonshot 官方当前正式模型 ID 为准，以上仅作结构示例

### 5.3 `.env.sample` 需要新增的环境变量

建议新增：

```env
# DeepSeek —— 原生 LangChain provider
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# Moonshot / Kimi —— OpenAI 兼容模式
MOONSHOT_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

同时建议补充说明：

```env
# DeepSeek —— LangChain 原生集成（langchain-deepseek）
# 获取地址：https://platform.deepseek.com/

# Moonshot / Kimi —— OpenAI API 兼容模式
# 获取地址：https://platform.moonshot.cn/
# Base URL: https://api.moonshot.cn/v1
```

---

## 6. 代码改动设计

### 6.1 `src/model_factory.py`

这是本次最核心的代码改动点。

#### 需要修改的内容

1. 在 `create_model()` 中新增 `case "deepseek"`
2. 新增 `_create_deepseek(...)` 方法
3. Kimi 不新增分支，继续走 `_create_openai_compatible(...)`

#### 建议改法

```python
match provider_config.type:
    case "dashscope":
        return _create_dashscope(provider_config, agent_config, api_key, params)
    case "anthropic_compatible":
        return _create_anthropic_compatible(provider_config, agent_config, api_key, params)
    case "openai_compatible":
        return _create_openai_compatible(provider_config, agent_config, api_key, params)
    case "deepseek":
        return _create_deepseek(provider_config, agent_config, api_key, params)
    case "openrouter":
        return _create_openrouter(agent_config, api_key, params)
```

新增方法示意：

```python
def _create_deepseek(
    provider_config: ProviderConfig,
    agent_config: AgentModelConfig,
    api_key: str,
    params: dict,
) -> BaseChatModel:
    from langchain_deepseek import ChatDeepSeek

    kwargs: dict = {
        "model": agent_config.model,
        "api_key": api_key,
    }
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "max_retries" in params:
        kwargs["max_retries"] = params["max_retries"]
    if "timeout" in params:
        # 注意：ChatDeepSeek 采用 LangChain 最新标准参数名 "timeout"
        # 区别于部分旧版插件（如 ChatQwen）使用的 "request_timeout"
        kwargs["timeout"] = params["timeout"]

    return ChatDeepSeek(**kwargs)
```

#### 设计说明

- DeepSeek 原生 provider 不需要走 `ChatOpenAI`
- Kimi 不需要单独加 `_create_kimi()`，因为已有 `_create_openai_compatible()` 足够使用

### 6.2 `src/config_loader.py`

#### 需要修改的内容

1. 更新 `ProviderConfig.type` 注释，加入 `deepseek`
2. `load_config()` 本身不需要额外分支，因为 provider 是通用字典加载
3. 如果有 provider type 白名单校验，需加入 `deepseek`

#### 建议修改点

当前注释：

```python
type: str  # "dashscope" | "anthropic_compatible" | "openai_compatible" | "openrouter"
```

建议改为：

```python
type: str  # "dashscope" | "anthropic_compatible" | "openai_compatible" | "deepseek" | "openrouter"
```

#### 是否需要改 `validate_env_vars()`

**通常不需要。**

因为 `validate_env_vars()` 是基于 `api_key_env` 通用检查的，[config_loader.py](src/config_loader.py#L153)。

只要：

- `deepseek.api_key_env = "DEEPSEEK_API_KEY"`
- `moonshot.api_key_env = "MOONSHOT_API_KEY"`

它就会自动工作。

### 6.3 `src/agent_factory.py`

**原则上不需要改逻辑。**

原因：

- `agent_factory.py` 只是按 `config.agents["xxx"].provider` 找 provider 配置，然后统一调用 `create_model(...)`
- 只要 `model_factory.py` 能识别新的 provider type，`agent_factory.py` 无需感知 DeepSeek 或 Kimi

因此：

- **不需要新增 DeepSeek / Kimi 特殊逻辑**
- 只需在配置中把 agent 绑定到相应 provider

### 6.4 `main.py`

**不需要改。**

原因：

- `main.py` 不关心底层供应商
- 它只负责读取配置、校验环境变量、创建 agent、运行流程

---

## 7. 推荐实施方案

### 7.1 方案选择

本次推荐方案如下：

1. **DeepSeek**
   - 新增原生 provider type：`deepseek`
   - 新增依赖：`langchain-deepseek`

2. **Kimi**
   - 继续使用 `openai_compatible`
   - 不新增依赖

### 7.2 推荐原因

这种方案兼顾了：

- **语义清晰**：DeepSeek 明确是原生 provider
- **改动最小**：Kimi 不额外引入新分支
- **依赖可控**：只新增一个必要依赖
- **架构一致**：遵循“原生优先，兼容兜底”

---

## 8. 单元测试设计

### 8.1 建议新增测试文件

建议新增：

```text
tests/test_model_factory.py
```

原因：

- 当前测试集中已有 `config_loader` 与运行流程测试
- 但缺少对 `model_factory.py` 路由行为的直接测试

### 8.2 `test_config_loader.py` 需要增加的测试

建议新增以下用例：

1. 能正确加载 `deepseek` provider
2. 能正确加载 `moonshot` provider
3. `DEEPSEEK_API_KEY` 缺失时，`validate_env_vars()` 能返回该变量名
4. `MOONSHOT_API_KEY` 缺失时，`validate_env_vars()` 能返回该变量名

### 8.3 `test_model_factory.py` 建议覆盖的用例

#### DeepSeek 原生 provider

1. `provider.type="deepseek"` 时调用 `langchain_deepseek.ChatDeepSeek`
2. `model` / `temperature` / `max_tokens` / `timeout` / `max_retries` 参数能正确透传
3. API Key 缺失时抛出 `KeyError`

#### Kimi OpenAI 兼容 provider

4. `provider.type="openai_compatible"` 且 `base_url="https://api.moonshot.cn/v1"` 时调用 `langchain_openai.ChatOpenAI`
5. `base_url`、`model` 与 params 能正确透传

#### 通用错误路径

6. 未知 `provider.type` 时抛出 `ValueError`

### 8.4 测试实现方式建议

建议使用 `unittest.mock.patch` mock 以下类：

- `langchain_deepseek.ChatDeepSeek`
- `langchain_openai.ChatOpenAI`
- `langchain_anthropic.ChatAnthropic`
- `langchain_qwq.ChatQwen`

这样测试只验证：

- 路由是否正确
- 参数是否正确

而不依赖真实外部 API。

### 8.5 示例测试点

```python
def test_create_model_uses_chatdeepseek_for_deepseek_provider(...):
    ...

def test_create_model_uses_chatopenai_for_moonshot_openai_compatible(...):
    ...

def test_validate_env_vars_includes_deepseek_key_when_missing(...):
    ...
```

---

## 9. 实施清单

### 9.1 必改文件

| 文件 | 改动 |
|------|------|
| [pyproject.toml](pyproject.toml) | 新增 `langchain-deepseek` |
| [config/agents.yaml](config/agents.yaml) | 新增 `deepseek` / `moonshot` provider 配置 |
| [src/model_factory.py](src/model_factory.py) | 新增 `deepseek` 路由与 `_create_deepseek()` |
| [src/config_loader.py](src/config_loader.py) | 更新 provider type 注释 |
| [tests/test_config_loader.py](tests/test_config_loader.py) | 增加 provider 与 env 校验测试 |
| `tests/test_model_factory.py` | 新增模型工厂路由测试 |
| [.env.sample](.env.sample) | 增加 `DEEPSEEK_API_KEY` / `MOONSHOT_API_KEY` 示例 |

### 9.2 可选改动

| 文件 | 改动 |
|------|------|
| [README.md](README.md) | 补充新 provider 使用说明 |
| [10_运行指南.md](docs/10_运行指南.md) | 补充安装与环境变量步骤 |

---

## 10. 风险与注意事项

### 10.1 DeepSeek 原生 provider 与兼容模式的差异

如果未来团队同时保留：

- `deepseek` 原生 provider
- `openai_compatible + DeepSeek base_url`

则会产生两种接法并存的问题，增加认知成本。

建议约定：

- **DeepSeek 一律使用原生 provider**
- **Kimi 一律使用 OpenAI 兼容 provider**

### 10.2 Kimi 模型名需要以官方正式 ID 为准

本设计文档只定义“接入方式”，不对 Kimi 2.5 的具体模型 ID 做硬编码假设。落地时应以 Moonshot 官方文档最新正式模型名为准。

### 10.3 `deepseek-reasoner` 的能力边界

截至 **2026-03-24**，关于 `deepseek-reasoner` 是否可用于本项目的判断，需要区分 **DeepSeek 官方 API 能力** 与 **LangChain 集成层能力**，两者目前并不完全一致。

#### DeepSeek 官方 API 侧

DeepSeek 于 **2025-12-01** 发布 DeepSeek-V3.2 后，已明确支持：

- `deepseek-chat`：对应 **非思考模式**
- `deepseek-reasoner`：对应 **思考模式**
- 思考模式下支持工具调用（tool calling）

但官方同时强调：在思考模式的工具调用过程中，调用方必须正确回传 `reasoning_content`，否则 API 会返回 `400`。

#### LangChain `ChatDeepSeek` 侧

截至本文编写日期，LangChain 官方 `ChatDeepSeek` 文档仍标注：

- `deepseek-chat`：支持 tool calling / structured output
- `deepseek-reasoner`：**不支持** tool calling / structured output

这说明当前存在一个实现层面的不确定性：

- **DeepSeek 官方 API 已支持**
- **但 LangChain 集成文档尚未完全反映这一变化**

#### 本项目的设计约束

由于当前项目通过 `langchain-deepseek` 接入 DeepSeek，而不是直接裸调 DeepSeek API，因此本项目是否能安全使用 `deepseek-reasoner`，不能只依据官方 API 新闻页判断，还必须验证 LangChain 集成层是否已经正确处理以下行为：

1. `ChatDeepSeek(model="deepseek-reasoner")` 是否能在 `deepagents + LangGraph` 链路中正常发起工具调用
2. 多轮工具调用过程中，是否会正确保留并回传 `reasoning_content`
3. 与当前 Orchestrator / Writer / Reviewer 的工具注入方式是否兼容

**设计建议**：

- 在完成专项集成测试前，默认仍建议优先使用 `deepseek-chat`
- 若团队要启用 `deepseek-reasoner`，应先补充一条端到端或 smoke test，覆盖至少一次真实工具调用回路
- 文档中不再把 `deepseek-reasoner` 视为“已与 `deepseek-chat` 等价可用”的默认选项

来源：  
[DeepSeek 官方更新 - DeepSeek-V3.2（2025-12-01）](https://api-docs.deepseek.com/zh-cn/news/news251201)  
[DeepSeek 官方文档 - 思考模式与工具调用](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode)  
[DeepSeek 官方更新日志](https://api-docs.deepseek.com/zh-cn/updates)  
[LangChain 官方文档 - ChatDeepSeek](https://docs.langchain.com/oss/python/integrations/chat/deepseek)

---

## 11. 结论

本次接入建议如下：

1. **DeepSeek**
   - 新增原生 provider `deepseek`
   - 新增依赖 `langchain-deepseek`
   - 在 `model_factory.py` 中显式创建 `ChatDeepSeek`

2. **Kimi**
   - 使用 `openai_compatible`
   - 不新增依赖
   - 在 `config/agents.yaml` 中通过 `base_url=https://api.moonshot.cn/v1` 接入

3. **测试**
   - 新增 `model_factory` 单测
   - 扩展 `config_loader` 与环境变量测试

这是一种“**DeepSeek 原生优先、Kimi 兼容复用**”的折中方案，既保持架构清晰，也控制实现复杂度。
