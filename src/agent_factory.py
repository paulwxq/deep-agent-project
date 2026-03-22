"""Agent 工厂模块。

根据配置创建完整的 Orchestrator Agent，包含 Writer/Reviewer 子代理定义、
工具集成和日志中间件。
"""

from __future__ import annotations

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from src.config_loader import AppConfig
from src.middleware.logging_middleware import LoggingMiddleware
from src.model_factory import create_model
from src.prompts.orchestrator_prompt import build_orchestrator_prompt
from src.prompts.reviewer_prompt import build_reviewer_prompt
from src.prompts.writer_prompt import build_writer_prompt


def create_orchestrator_agent(
    config: AppConfig,
    requirement_filename: str = "requirement.txt",
) -> tuple[CompiledStateGraph, LoggingMiddleware]:
    """根据配置创建完整的 Orchestrator Agent。

    Returns:
        (agent, orch_middleware) — agent 图实例与 Orchestrator 的日志中间件。
        调用方可通过 orch_middleware.task_counts 获取子代理委派统计。
    """
    # 1. 通过模型工厂创建各 Agent 的模型实例
    orchestrator_model = create_model(
        config.providers[config.agents["orchestrator"].provider],
        config.agents["orchestrator"],
    )
    writer_model = create_model(
        config.providers[config.agents["writer"].provider],
        config.agents["writer"],
    )
    reviewer_model = create_model(
        config.providers[config.agents["reviewer"].provider],
        config.agents["reviewer"],
    )

    # 2. 构建可选工具列表
    tools: list = []
    if config.tools.tavily_enabled:
        from src.tools.web_search import create_web_search_tool

        tools.append(create_web_search_tool(
            max_results=config.tools.tavily_max_results,
            api_key_env=config.tools.tavily_api_key_env,
        ))

    req_path = f"/input/{requirement_filename}"

    # 3. 定义子代理
    writer_subagent = {
        "name": "writer",
        "description": (
            "根据业务需求撰写可落地的技术设计文档。"
            f"需求文件在 {req_path}，同目录下其他文件为参考文件。"
            "草稿保存到 /drafts/design.md。接受反馈后修订文档。"
        ),
        "system_prompt": build_writer_prompt(requirement_filename),
        "tools": tools,
        "model": writer_model,
        "skills": ["/skills/tech-doc-writing/"],
        "middleware": [LoggingMiddleware(agent_name="writer")],
    }

    reviewer_subagent = {
        "name": "reviewer",
        "description": (
            f"基于 {req_path} 中的业务需求审核 /drafts/design.md 中的技术设计文档，"
            "从需求覆盖性、可落地性、无歧义性、完整性、合理性评估，"
            "返回 ACCEPT 或 REVISE 结论及详细反馈。"
        ),
        "system_prompt": build_reviewer_prompt(requirement_filename),
        "tools": tools,
        "model": reviewer_model,
        "skills": ["/skills/tech-doc-review/"],
        "middleware": [LoggingMiddleware(agent_name="reviewer")],
    }

    # 4. 组装 Orchestrator
    orch_middleware = LoggingMiddleware(agent_name="orchestrator")
    agent = create_deep_agent(
        model=orchestrator_model,
        tools=[],
        system_prompt=build_orchestrator_prompt(config.max_iterations, requirement_filename),
        subagents=[writer_subagent, reviewer_subagent],
        middleware=[orch_middleware],
        backend=FilesystemBackend(root_dir=".", virtual_mode=True),
        name="orchestrator",
        checkpointer=MemorySaver(),
    )

    return agent, orch_middleware
