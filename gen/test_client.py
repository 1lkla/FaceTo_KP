#!/usr/bin/env python3
"""读 .env 发一条最小请求，验证 GLM 端点连通性，打印回复和 usage。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glm_client import GLMClient


async def main():
    client = GLMClient()
    print(f"protocol={client.protocol} model={client.model} base_url={client.base_url}")
    text, usage = await client.chat(
        [{"role": "user", "content": "用一句话回答：什么是 SQL 注入？"}],
        max_tokens=2048,
    )
    print(f"模型回复: {text}")
    print(f"usage: {usage}")


if __name__ == "__main__":
    asyncio.run(main())
