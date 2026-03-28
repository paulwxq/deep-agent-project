"""Agent 工厂模块。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from src.config_loader import AppConfig
from src.middleware.logging_middleware import LoggingMiddleware
from src.middleware.stage_state import StageStateMiddleware
from src.model_factory import create_model
from src.prompts.orchestrator_prompt import build_orchestrator_prompt
from src.prompts.reviewer_prompt import build_reviewer_prompt
from src.prompts.writer_prompt import build_writer_prompt
from src.tools.hil import ask_user, confirm_continue as confirm_continue_tool

logger = logging.getLogger("deep_agent_project")


def _log_skills_config(agent_name: str, skill_dirs: list[str]) -> None:
    for skill_dir in skill_dirs:
        actual_path = Path(skill_dir.lstrip("/"))
        if not actual_path.exists():
            logger.warning(
                "技能目录不存在 [%s]: %s（该 Agent 将无技能可用）",
                agent_name,
                skill_dir,
                extra={"agent_name": "system"},
            )
            continue
        skill_names = sorted(
            d.name for d in actual_path.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        )
        if skill_names:
            logger.debug(
                "技能配置 [%s]: 目录=%s → 发现技能 %s",
                agent_name,
                skill_dir,
                skill_names,
                extra={"agent_name": "system"},
            )


def _log_agent_model_config(config: AppConfig, agent_name: str) -> None:
    agent_cfg = config.agents[agent_name]
    provider_cfg = config.providers[agent_cfg.provider]
    params_text = json.dumps(agent_cfg.params, ensure_ascii=False, sort_keys=True)
    logger.debug(
        "LLM 配置 [%s]: provider=%s, type=%s, model=%s, params=%s",
        agent_name,
        agent_cfg.provider,
        provider_cfg.type,
        agent_cfg.model,
        params_text,
        extra={"agent_name": "system"},
    )


def _ensure_review_state(state_path: Path, reviewer2_enabled: bool) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        return
    state_path.write_text(
        json.dumps(
            {
                "current_stage": "reviewer1",
                "reviewer1_round": 0,
                "reviewer2_round": 0,
                "reviewer2_enabled": reviewer2_enabled,
                "awaiting_confirm_for": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def create_orchestrator_agent(
    config: AppConfig,
    requirement_filename: str = "requirement.txt",
    context7_tools: list | None = None,
) -> tuple[CompiledStateGraph, LoggingMiddleware]:
    """根据配置创建完整的 Orchestrator Agent。"""
    reviewer2_enabled = bool(config.agents.get("reviewer2") and config.agents["reviewer2"].enabled)

    for agent_name in ("orchestrator", "writer", "reviewer1"):
        _log_agent_model_config(config, agent_name)
    if reviewer2_enabled:
        _log_agent_model_config(config, "reviewer2")

    orchestrator_model = create_model(
        config.providers[config.agents["orchestrator"].provider],
        config.agents["orchestrator"],
    )
    writer_model = create_model(
        config.providers[config.agents["writer"].provider],
        config.agents["writer"],
    )
    reviewer1_model = create_model(
        config.providers[config.agents["reviewer1"].provider],
        config.agents["reviewer1"],
    )
    reviewer2_model = None
    if reviewer2_enabled:
        reviewer2_model = create_model(
            config.providers[config.agents["reviewer2"].provider],
            config.agents["reviewer2"],
        )

    context7_tools = context7_tools or []
    context7_tool_names = [t.name for t in context7_tools]

    tools: list = []
    if config.tools.tavily_enabled:
        from src.tools.web_search import create_web_search_tool

        tools.append(
            create_web_search_tool(
                max_results=config.tools.tavily_max_results,
                api_key_env=config.tools.tavily_api_key_env,
            )
        )

    hil_tools: list = [confirm_continue_tool]
    interactive = True

    writer_tools = list(tools) + list(context7_tools)
    if config.hil_clarify:
        writer_tools.append(ask_user)
    reviewer_tools = list(tools) + list(context7_tools)

    req_path = f"/input/{requirement_filename}"

    writer_subagent = {
        "name": "writer",
        "description": (
            "根据业务需求撰写可落地的技术设计文档。"
            f"需求文件在 {req_path}，同目录下其他文件为参考文件。"
            "草稿保存到 /drafts/design.md。接受反馈后修订文档。"
        ),
        "system_prompt": build_writer_prompt(
            requirement_filename,
            hil_clarify=config.hil_clarify,
            context7_tool_names=context7_tool_names,
        ),
        "tools": writer_tools,
        "model": writer_model,
        "skills": ["/skills/writer/"],
        "middleware": [LoggingMiddleware(agent_name="writer")],
    }

    reviewer1_subagent = {
        "name": "reviewer1",
        "description": (
            f"基于 {req_path} 中的业务需求审核 /drafts/design.md 中的技术设计文档。"
            "你必须优先调用 write_file 将结论写入结构化文件（verdict），"
            "然后再提供详细的文本反馈。从需求覆盖性、可落地性等维度评估。"
        ),
        "system_prompt": build_reviewer_prompt(
            requirement_filename,
            context7_tool_names=context7_tool_names,
            stage=1,
        ),
        "tools": reviewer_tools,
        "model": reviewer1_model,
        "skills": ["/skills/reviewer/"],
        "middleware": [LoggingMiddleware(agent_name="reviewer1")],
    }

    subagents = [writer_subagent, reviewer1_subagent]
    _log_skills_config("writer", writer_subagent["skills"])
    _log_skills_config("reviewer1", reviewer1_subagent["skills"])

    if reviewer2_enabled and reviewer2_model is not None:
        reviewer2_subagent = {
            "name": "reviewer2",
            "description": (
                f"基于 {req_path} 中的业务需求，从独立视角终审 /drafts/design.md。"
                "你必须优先调用 write_file 将 ACCEPT 或 REVISE 结论写入结构化文件，"
                "然后再提供详细的文本反馈。不参考 reviewer1 的意见。"
            ),
            "system_prompt": build_reviewer_prompt(
                requirement_filename,
                context7_tool_names=context7_tool_names,
                stage=2,
            ),
            "tools": reviewer_tools,
            "model": reviewer2_model,
            "skills": ["/skills/reviewer/"],
            "middleware": [LoggingMiddleware(agent_name="reviewer2")],
        }
        subagents.append(reviewer2_subagent)
        _log_skills_config("reviewer2", reviewer2_subagent["skills"])

    state_path = Path("drafts") / "review-state.json"
    _ensure_review_state(state_path, reviewer2_enabled=reviewer2_enabled)
    stage_state = StageStateMiddleware(
        state_path=str(state_path),
        reviewer1_max=config.agents["reviewer1"].max_reviewer_iterations,
        reviewer2_max=config.agents["reviewer2"].max_reviewer_iterations if reviewer2_enabled else 0,
    )

    orch_middleware = LoggingMiddleware(agent_name="orchestrator")
    checkpointer_kwargs = {"checkpointer": MemorySaver()} if interactive else {}
    agent = create_deep_agent(
        model=orchestrator_model,
        tools=hil_tools,
        system_prompt=build_orchestrator_prompt(
            max_iterations=config.max_iterations,
            requirement_filename=requirement_filename,
            reviewer2_enabled=reviewer2_enabled,
            reviewer1_max=config.agents["reviewer1"].max_reviewer_iterations,
            reviewer2_max=config.agents["reviewer2"].max_reviewer_iterations if reviewer2_enabled else 0,
        ),
        subagents=subagents,
        middleware=[orch_middleware, stage_state],
        backend=FilesystemBackend(root_dir=".", virtual_mode=True),
        name="orchestrator",
        **checkpointer_kwargs,
    )

    return agent, orch_middleware
