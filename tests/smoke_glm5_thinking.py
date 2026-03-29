import os
import sys
from pathlib import Path

# 将 src 目录添加到路径
sys.path.append(str(Path(__file__).parent.parent))

import logging
from src.config_loader import load_config
from src.model_factory import create_model
from langchain_core.messages import HumanMessage, AIMessage

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_glm5")

def test_glm5_thinking():
    """测试 GLM-5 开启 Thinking 模式下的表现。"""
    try:
        config = load_config()
        # 获取 bigmodel provider 配置 (GLM-5)
        provider_cfg = config.providers.get("bigmodel")
        if not provider_cfg:
            print("错误: 未找到 bigmodel provider 配置")
            return

        # 手构造一个开启 thinking 和高温度的 Agent 配置
        from src.config_loader import AgentModelConfig
        agent_cfg = AgentModelConfig(
            provider="bigmodel",
            model="glm-5",
            params={
                "thinking": {"type": "enabled", "budget_tokens": 4096},
                "temperature": 1.0,
                "timeout": 600
            }
        )

        print(f"\n[1] 正在创建 GLM-5 模型实例 (model={agent_cfg.model})...")
        model = create_model(provider_cfg, agent_cfg)

        import time
        max_retries = 3
        for retry in range(max_retries):
            try:
                print(f"\n[2] 发送复杂逻辑问题以触发 Thinking (尝试 {retry+1}/{max_retries})...")
                question = "请分析：在 SAS 中使用 PROC SQL 进行大表连接时，如果两张表都没有索引，为什么哈希连接（Hash Join）通常比合并连接（Merge Join）快？请先深入思考再回答。"
                messages = [HumanMessage(content=question)]
                
                response = model.invoke(messages)
                break 
            except Exception as e:
                if "429" in str(e) and retry < max_retries - 1:
                    print(f"⚠️ 触发 429 频率限制，等待 10 秒后重试...")
                    time.sleep(10)
                    continue
                raise e

        print("\n[3] 检查响应结果:")
        # 检查是否有推理内容
        reasoning = getattr(response, "reasoning_content", None)
        # 兼容性检查：有些模型可能放在 additional_kwargs
        if not reasoning:
            reasoning = response.additional_kwargs.get("reasoning_content")

        if reasoning:
            print(f"✅ 成功捕获推理内容 (长度: {len(reasoning)}):")
            print("-" * 40)
            print(reasoning[:300] + "...")
            print("-" * 40)
        else:
            print("❌ 未捕获到推理内容。请检查 API 密钥或模型是否支持。")

        print(f"\n最终回答内容 (长度: {len(response.content)}):")
        print(response.content[:200] + "...")

        # 测试多轮对话中的推理回传
        if reasoning:
            print("\n[4] 测试多轮对话回传 (验证 preserve_reasoning)...")
            # 模拟手动构造带有推理内容的 AIMessage
            ai_msg = AIMessage(content=response.content, additional_kwargs={"reasoning_content": reasoning})
            messages.append(ai_msg)
            messages.append(HumanMessage(content="那如果其中一张表非常大，超出了内存限制，哈希连接还会快吗？"))
            
            response2 = model.invoke(messages)
            print("✅ 第二轮对话响应成功。")
            print(f"第二轮回答: {response2.content[:100]}...")

    except Exception as e:
        print(f"❌ 测试过程中发生异常: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if not os.environ.get("ZHIPUAI_API_KEY"):
        print("跳过测试：未设置 ZHIPUAI_API_KEY 环境变量。")
    else:
        test_glm5_thinking()
