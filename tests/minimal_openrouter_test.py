
import os
from dotenv import load_dotenv
from langchain_openrouter import ChatOpenRouter
from langchain_core.messages import HumanMessage

# 应用补丁以防万一
import openrouter
_old_init = openrouter.OpenRouter.__init__
def _new_init(self, *args, **kwargs):
    if "x_title" in kwargs and "x_open_router_title" not in kwargs:
        kwargs["x_open_router_title"] = kwargs.pop("x_title")
    return _old_init(self, *args, **kwargs)
openrouter.OpenRouter.__init__ = _new_init

def test_minimal():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    
    # 尝试 OpenAI 顶级模型
    model_id = "openai/gpt-5.2"
    
    print(f"--- 正在使用模型 {model_id} 进行探测 ---")
    try:
        llm = ChatOpenRouter(
            model_name=model_id,
            openrouter_api_key=api_key,
            max_tokens=20,
            # 方案 1：避开审查严苛的 Anthropic 官方节点
            openrouter_provider={
                "order": ["Vertex AI", "AWS Bedrock", "Azure"],
                "allow_fallbacks": True
            }
        )
        res = llm.invoke([HumanMessage(content="Hi")])
        print(f"✅ 验证成功! 响应: {res.content}")
    except Exception as e:
        print(f"❌ 验证失败: {e}")

if __name__ == "__main__":
    test_minimal()
