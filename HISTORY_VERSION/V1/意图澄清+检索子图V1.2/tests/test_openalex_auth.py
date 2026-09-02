"""
OpenAlex API 最小测试脚本

用于验证API密钥和认证方式是否正确
"""

import requests
import json

print("="*80)
print("OpenAlex API 认证测试")
print("="*80)

API_KEY = "ZLwbEQ2B1nOALHLdeukZGr"
EMAIL = "lijiamingeric28@gmail.com"
BASE_URL = "https://api.openalex.org/works"

# 测试1: 只使用邮箱
print("\n[测试 1] 只使用邮箱（mailto参数）")
print("-"*80)
try:
    response = requests.get(
        BASE_URL,
        params={
            "search": "graphene",
            "mailto": EMAIL,
            "per_page": 5
        },
        timeout=30
    )
    print(f"状态码: {response.status_code}")
    print(f"URL: {response.url}")
    if response.status_code == 200:
        data = response.json()
        print(f"结果数: {data.get('meta', {}).get('count', 0)}")
        print("[OK] 成功")
    else:
        print(f"[FAIL] 失败")
        print(f"响应: {response.text[:200]}")
except Exception as e:
    print(f"[ERROR] 错误: {e}")

# 测试2: 使用api_key参数
print("\n[测试 2] 使用api_key参数")
print("-"*80)
try:
    response = requests.get(
        BASE_URL,
        params={
            "search": "graphene",
            "api_key": API_KEY,
            "mailto": EMAIL,
            "per_page": 5
        },
        timeout=30
    )
    print(f"状态码: {response.status_code}")
    print(f"URL: {response.url}")
    if response.status_code == 200:
        data = response.json()
        print(f"结果数: {data.get('meta', {}).get('count', 0)}")
        print("[OK] 成功")
    else:
        print(f"[FAIL] 失败")
        print(f"响应: {response.text[:200]}")
except Exception as e:
    print(f"[ERROR] 错误: {e}")

# 测试3: 使用Bearer token
print("\n[测试 3] 使用Bearer token（请求头）")
print("-"*80)
try:
    response = requests.get(
        BASE_URL,
        params={
            "search": "graphene",
            "mailto": EMAIL,
            "per_page": 5
        },
        headers={
            "Authorization": f"Bearer {API_KEY}"
        },
        timeout=30
    )
    print(f"状态码: {response.status_code}")
    print(f"URL: {response.url}")
    if response.status_code == 200:
        data = response.json()
        print(f"结果数: {data.get('meta', {}).get('count', 0)}")
        print("[OK] 成功")
    else:
        print(f"[FAIL] 失败")
        print(f"响应: {response.text[:200]}")
except Exception as e:
    print(f"[ERROR] 错误: {e}")

# 测试4: 查看具体返回结果
print("\n[测试 4] 查看返回数据结构")
print("-"*80)
try:
    response = requests.get(
        BASE_URL,
        params={
            "search": "graphene mechanical properties",
            "mailto": EMAIL,
            "per_page": 3
        },
        timeout=30
    )
    if response.status_code == 200:
        data = response.json()
        print(f"总结果数: {data.get('meta', {}).get('count', 0)}")
        print(f"返回结果数: {len(data.get('results', []))}")

        if data.get('results'):
            print("\n前3篇论文:")
            for idx, work in enumerate(data['results'][:3], 1):
                print(f"\n  [{idx}] {work.get('title', 'N/A')}")
                print(f"      ID: {work.get('id', 'N/A')}")
                print(f"      引用数: {work.get('cited_by_count', 0)}")
                print(f"      年份: {work.get('publication_year', 'N/A')}")

        print("\n[OK] 可以正常搜索论文")
    else:
        print(f"[FAIL] 失败 (状态码: {response.status_code})")
except Exception as e:
    print(f"[ERROR] 错误: {e}")

print("\n" + "="*80)
print("测试完成")
print("="*80)
