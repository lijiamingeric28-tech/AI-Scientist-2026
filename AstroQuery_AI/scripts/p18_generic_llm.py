"""P18 对照组 4：通用检索（裸 qwen3.7-plus 直接回答，无系统提示/无工具/无上下文工程）

一次 API 调用，响应存 output/p18_ablation/generic_llm_response.txt（含 token 用量）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

from astroquery_ai.config import get_settings


def main() -> None:
    s = get_settings()
    client = OpenAI(base_url=s.dashscope_base_url, api_key=s.dashscope_api_key)
    model = os.environ.get("P18_GENERIC_MODEL", s.dashscope_vlm_model)  # 默认 qwen3.7-plus
    question = "昴星团(M45)的年龄、距离和金属丰度"

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
    )
    text = resp.choices[0].message.content
    usage = resp.usage
    out = os.path.join("output", "p18_ablation", "generic_llm_response.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "question": question, "model": model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }, ensure_ascii=False, indent=2))
        f.write("\n\n--- 完整回答 ---\n\n")
        f.write(text + "\n")

    print("== 通用 LLM 回答 ==")
    print(text)
    print("\n[P18] saved ->", out, "(tokens:", getattr(usage, "total_tokens", "?"), ")")


if __name__ == "__main__":
    main()
