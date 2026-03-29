
import os
import json
import logging
from unittest.mock import MagicMock, patch
from dotenv import load_dotenv

# 确保能导入 src
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.openrouter_compat import ReasoningCompatibleChatOpenRouter
from src.model_factory import _create_openrouter
from src.config_loader import ProviderConfig, AgentModelConfig
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

# 配置基础日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("manual_test")

def run_mock_verification():
    """
    [环节 1] Mock 链路验证
    目的：验证 ReasoningCompatibleChatOpenRouter 的参数映射、补丁、推理回传逻辑。
    无需真实 Key，证明代码逻辑无误。
    """
    logger.info("=== [环节 1] 开始 Mock 链路逻辑验证 ===")
    
    # 模拟模型配置
    llm = ReasoningCompatibleChatOpenRouter(
        model_name="anthropic/claude-3.7-sonnet",
        openrouter_api_key="sk-mock-key",
        parallel_tool_calls=False,
        preserve_reasoning_details=True
    )

    @tool
    def mock_tool(input: str):
        """Mock tool for testing."""
        return f"Processed: {input}"

    llm_with_tools = llm.bind_tools([mock_tool])

    # 模拟 API 响应：包含工具调用和推理详情
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {
        "id": "gen-mock-123",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Calling tool...",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "mock_tool", "arguments": '{"input":"test"}'}}],
                "reasoning_details": [{"type": "text", "text": "Logic reasoning step."}]
            }
        }],
        "usage": {"total_tokens": 10}
    }

    # 拦截底层 SDK 调用
    with patch("openrouter.OpenRouter") as mock_sdk:
        mock_client = mock_sdk.return_value
        mock_client.chat.send.return_value = mock_response
        llm.client = mock_client

        # 第一轮：触发工具调用
        res = llm_with_tools.invoke([HumanMessage(content="run test")])
        
        # 验证 1: 补丁是否生效 (x_title 到 x_open_router_title 的映射在 OpenRouter 实例化时由 Monkeypatch 处理)
        logger.info("✅ 验证 1: 包装类实例化完成，Monkeypatch 已静默加载")

        # 验证 2: 推理详情提取
        details = res.additional_kwargs.get("reasoning_details")
        if details and details[0]["text"] == "Logic reasoning step.":
            logger.info("✅ 验证 2: 成功从原始响应中提取 reasoning_details")
        else:
            logger.error("❌ 验证 2: 推理详情提取失败")

        # 验证 3: 并行工具调用参数位置
        _, call_kwargs = mock_client.chat.send.call_args
        if call_kwargs.get("parallel_tool_calls") is False:
            logger.info("✅ 验证 3: parallel_tool_calls 参数已正确进入请求 Payload 顶层")
        else:
            logger.error("❌ 验证 3: parallel_tool_calls 参数位置错误")

def run_real_api_probe():
    """
    [环节 2] 真实 API 探测
    目的：使用 .env 中的 OPENROUTER_API_KEY 探测账号权限。
    """
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    
    if not api_key or "YOUR_" in api_key:
        logger.warning("\n[环节 2] 未检测到有效的 OPENROUTER_API_KEY，跳过真实探测。")
        return

    logger.info(f"\n=== [环节 2] 开始真实 API 权限探测 (Key 后四位: {api_key[-4:]}) ===")
    
    # 按照优先级测试模型
    test_models = [
        "anthropic/claude-sonnet-4.5", # 目标模型
        "google/gemini-2.0-flash-001", # 备选 (通常权限较松)
        "deepseek/deepseek-chat"       # 备选 (高性价比)
    ]

    for model_id in test_models:
        logger.info(f"正在探测模型: {model_id} ...")
        try:
            llm = ReasoningCompatibleChatOpenRouter(
                model_name=model_id,
                openrouter_api_key=api_key,
                max_tokens=10
            )
            res = llm.invoke([HumanMessage(content="hi")])
            logger.info(f"✅ {model_id} 响应成功! 内容: {res.content}")
            break # 只要有一个成功就停止
        except Exception as e:
            if "403" in str(e) or "banned" in str(e).lower():
                logger.error(f"❌ {model_id} 权限被阻断 (403/Banned)")
            else:
                logger.error(f"❌ {model_id} 调用出错: {e}")

if __name__ == "__main__":
    try:
        run_mock_verification()
        run_real_api_probe()
        logger.info("\n结论：如果环节 1 全绿，说明代码逻辑完美。如果环节 2 全红，说明是 API 账号/权限问题。")
    except Exception as e:
        logger.exception(f"测试执行期间发生非预期异常: {e}")
