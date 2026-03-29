
import os
import json
import requests
from dotenv import load_dotenv

def test_raw_http():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # 即使不传 X-Title，OpenRouter 也应该能跑通，只是没有署名
    }

    # 测试模型列表
    models = ["anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat"]

    print(f"--- 原始 HTTP 请求测试 (Key 后四位: {api_key[-4:]}) ---")
    
    for model in models:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10
        }
        
        print(f"\n[探测模型: {model}]")
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
            print(f"HTTP 状态码: {response.status_code}")
            if response.status_code == 200:
                print(f"✅ 成功! 响应: {response.json()['choices'][0]['message']['content']}")
            else:
                print(f"❌ 失败! 错误体: {response.text}")
        except Exception as e:
            print(f"💥 网络请求崩溃: {e}")

if __name__ == "__main__":
    test_raw_http()
