
import os
from dotenv import load_dotenv
from langchain_openrouter import ChatOpenRouter
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

# 加载环境变量
load_dotenv()

# 版本兼容补丁
import openrouter
old_init = openrouter.OpenRouter.__init__
def new_init(self, *args, **kwargs):
    kwargs.pop('x_title', None)
    return old_init(self, *args, **kwargs)
openrouter.OpenRouter.__init__ = new_init

@tool
def get_file_count(directory: str):
    """Count files in a directory."""
    if directory == "/input":
        return 5
    return 0

def run_real_smoke_test():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "YOUR_OPENROUTER_API_KEY":
        print("❌ 错误: 未找到有效的 OPENROUTER_API_KEY，跳过真实测试。")
        return

    models = [
        "anthropic/claude-3.7-sonnet", # 映射到 4.6 设计
        "google/gemini-2.0-pro-exp-02-05", # 映射到 3.1 设计
        "openai/gpt-4o-2024-08-06" # 映射到 5.3 设计
    ]

    print(f"=== [Real API Smoke Test] 开始验证 (Key 后四位: {api_key[-4:]}) ===")

    for model_id in models:
        print(f"\n--- 测试模型: {model_id} ---")
        try:
            llm = ChatOpenRouter(
                model_name=model_id,
                openrouter_api_key=api_key,
                temperature=0.1,
                max_tokens=500
            )
            llm_with_tools = llm.bind_tools([get_file_count])
            
            # 第一轮：触发工具调用
            print(f"[{model_id}] 正在发送工具调用请求...")
            res1 = llm_with_tools.invoke([HumanMessage(content="请帮我统计一下 /input 目录下有多少个文件？")])
            
            if res1.tool_calls:
                print(f"✅ {model_id} 成功发起工具调用: {res1.tool_calls[0]['name']}")
                
                # 第二轮：发送工具结果
                from langchain_core.messages import ToolMessage
                tool_msg = ToolMessage(
                    content="5", 
                    tool_call_id=res1.tool_calls[0]['id']
                )
                print(f"[{model_id}] 正在发送工具结果以获取最终答案...")
                res2 = llm_with_tools.invoke([
                    HumanMessage(content="请帮我统计一下 /input 目录下有多少个文件？"),
                    res1,
                    tool_msg
                ])
                print(f"✅ {model_id} 最终回答: {res2.content[:100]}...")
            else:
                print(f"⚠️ {model_id} 未发起工具调用，内容: {res1.content[:100]}...")

        except Exception as e:
            print(f"❌ {model_id} 测试失败: {e}")

    print("\n=== Real API Smoke Test 完成 ===")

if __name__ == "__main__":
    run_real_smoke_test()
