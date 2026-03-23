# deep-agent-project

一个基于 `deepagents` SDK 的多智能体技术文档生成项目。它接收放在 `input/` 目录下的需求文件和参考资料，由 `Orchestrator` 编排 `Writer` 与 `Reviewer` 两个子代理迭代协作，最终在 `output/` 目录输出可落地的 Markdown 技术设计文档。

当前仓库里的示例数据以 SAS 数据血缘分析需求为主，但代码本身并不绑定具体业务领域。只要把需求文档和相关参考文件放进 `input/`，它就可以作为通用的“需求 -> 技术设计文档”生产框架使用。

## 项目用途

这个项目主要解决两类问题：

1. 把自然语言需求和项目参考资料整理成结构化、可执行的技术设计文档。
2. 用 Writer/Reviewer 的分工模式，把“先写初稿，再做质量审核，再按反馈修订”的流程固化下来。

它适合以下场景：

- 为新模块、数据处理任务、分析应用生成概要设计或详细设计文档
- 读取 `input/` 中的代码、配置、数据定义、示例文件作为设计依据
- 在需求不清晰时，通过 Human-in-the-Loop 机制向用户追问关键问题
- 在达到最大迭代轮次后，让用户决定继续修订还是接受当前版本

## 核心流程

1. `main.py` 从 `input/` 读取用户指定的需求文件。
2. 程序按 `config/agents.yaml` 加载模型提供商、Agent 参数和工具开关。
3. `Orchestrator` 创建并调度两个子代理：
   - `Writer`：阅读需求和参考文件，写入 `/drafts/design.md`
   - `Reviewer`：审核文档并输出 `ACCEPT` / `REVISE`
4. 如果审核未通过，`Orchestrator` 把反馈重新交给 `Writer` 修订。
5. 结束后，程序把最终草稿复制到 `output/`，文件名可由用户指定，也可由 Agent 自动建议。

## 技术栈

### Agent 与工作流

- `deepagents`：多 Agent 编排核心 SDK
- `langgraph`：中断恢复、状态图、`MemorySaver` checkpointer
- `langchain`：模型抽象、middleware、工具接入
- `FilesystemBackend`：让 Agent 通过共享文件系统协作，围绕 `input/`、`drafts/`、`output/` 工作

### 模型接入

项目通过 `src/model_factory.py` 做了一层 Provider 抽象，当前支持：

- DashScope / Qwen
- Anthropic 兼容接口
- OpenAI 兼容接口
- OpenRouter

默认配置位于 `config/agents.yaml`：

- `orchestrator`：`qwen3-max`
- `writer`：`MiniMax-M2.7`
- `reviewer`：`glm-5`

### 工程与基础设施

- Python `3.12`
- `uv`：依赖管理与运行
- `PyYAML`：YAML 配置加载
- `python-dotenv`：环境变量加载
- `tavily-python`：可选 Web 搜索工具
- `logging` + `RotatingFileHandler`：控制台与文件双通道日志
- `pytest`：单元测试

## 项目特点

- 多 Agent 分工明确：编排、写作、审核职责分离
- 输入文件驱动：需求文件之外，Agent 会按需读取 `input/` 下的参考代码和资料
- 支持 HIL：通过 `ask_user` 和 `confirm_continue` 两个工具处理需求澄清与超限确认
- 可配置 Provider：模型供应商、模型名、温度、超时等都在 YAML 中配置
- 输出链路清晰：工作草稿写入 `drafts/`，正式结果复制到 `output/`
- 有测试覆盖：已为配置加载、文件名清洗、HIL 流程、`drafts` 备份等核心逻辑编写测试

## 目录结构

```text
deep-agent-project/
├── main.py                # CLI 入口
├── pyproject.toml         # 项目依赖与元数据
├── config/
│   └── agents.yaml        # Agent、Provider、工具配置
├── src/
│   ├── agent_factory.py   # 创建 Orchestrator 与子代理
│   ├── model_factory.py   # 按 Provider 类型创建模型
│   ├── config_loader.py   # 配置加载与校验
│   ├── logger.py          # 日志初始化
│   ├── middleware/        # 自定义日志中间件
│   ├── prompts/           # Orchestrator / Writer / Reviewer 提示词
│   └── tools/             # HIL 与 Web 搜索工具
├── input/                 # 用户输入目录
├── drafts/                # Agent 工作区
├── output/                # 最终文档输出目录
├── tests/                 # pytest 测试
├── docs/                  # 设计文档与运行指南
└── skills/                # 写作/审核技能
```

## 快速开始

### 1. 安装依赖

```bash
# Windows
set UV_PROJECT_ENVIRONMENT=.venv-win
uv sync

# WSL / Linux
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync
```

如需运行测试：

```bash
uv sync --group dev
```

### 2. 配置环境变量

```bash
cp .env.sample .env
```

根据 `config/agents.yaml` 中实际启用的 Provider，填写对应的 API Key。默认配置下至少需要：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_API_BASE`
- `MINIMAX_API_KEY`
- `ZHIPUAI_API_KEY`

如果启用 Tavily 搜索，还需要：

- `TAVILY_API_KEY`

### 3. 准备输入文件

把需求文件和相关参考文件放到 `input/` 下。当前仓库已经提供了一组 SAS 数据血缘分析相关样例，可直接参考。

### 4. 运行项目

```bash
uv run python main.py -f 需求文件.md
```

常用参数：

- `-f, --file`：需求文件名，固定从 `input/` 读取
- `-o, --output`：输出文件名，固定写入 `output/`
- `-m, --max-iterations`：最大迭代轮次
- `-l, --log-level`：控制台日志级别
- `-i, --interactive`：强制开启交互模式，覆盖配置文件中的 HIL 开关

说明：当前仓库默认配置 `config/agents.yaml` 已开启 `hil_clarify` 和 `hil_confirm`，因此即使不传 `-i`，默认也会进入交互式需求澄清与超限确认流程。

示例：

```bash
uv run python main.py -f sas代码的数据血缘分析需求.md -o SAS数据血缘分析设计.md -i
```

## 输出结果

运行完成后，你会看到以下产物：

- `drafts/design.md`：Agent 工作中的设计草稿
- `drafts/review-verdict.json`：Reviewer 结构化审核结论
- `drafts/output-filename.txt`：Orchestrator 建议的输出文件名
- `output/*.md`：最终交付文档
- `logs/agent.log`：完整执行日志

每次运行前，程序会先把现有 `drafts/` 内容备份到 `drafts/_backups/`，避免直接覆盖上一次工作区。

## 进一步阅读

- `docs/10_运行指南.md`：更完整的运行说明和参数说明
- `docs/2_概要设计文档.md`：项目整体设计
- `input/sas代码的数据血缘分析需求.md`：当前示例需求
